import random
import sqlite3
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol

from lituk.review.bandit import PoolPosterior, choose
from lituk.review.bandit import update as bandit_update
from lituk.review.presenter import Prompt, build_prompt, grade_answer
from lituk.review.scheduler import CardState, initial_state
from lituk.review.scheduler import update as sm2_update


@dataclass(frozen=True)
class SessionConfig:
    size: int = 24
    new_cap: int = 5


@dataclass(frozen=True)
class SessionResult:
    correct: int
    total: int
    weak_facts: list[int]


class UI(Protocol):
    def show_prompt(self, prompt: Prompt) -> list[int]: ...
    def show_feedback(self, prompt: Prompt, correct: bool) -> int: ...
    def show_summary(self, result: SessionResult) -> None: ...


def _due_pool(conn: sqlite3.Connection, today: date) -> list[int]:
    rows = conn.execute(
        "SELECT fact_id FROM card_state WHERE due_date <= ?"
        " ORDER BY ease_factor ASC, due_date ASC",
        (today.isoformat(),),
    ).fetchall()
    return [r["fact_id"] for r in rows]


def _new_pool(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        "SELECT f.id FROM facts f"
        " LEFT JOIN card_state cs ON f.id = cs.fact_id"
        " WHERE cs.fact_id IS NULL"
    ).fetchall()
    return [r["id"] for r in rows]


def _load_posteriors(conn: sqlite3.Connection) -> tuple[PoolPosterior, PoolPosterior]:
    rows = {
        r["pool"]: r
        for r in conn.execute(
            "SELECT pool, alpha, beta FROM pool_state"
        ).fetchall()
    }
    return (
        PoolPosterior(alpha=rows["due"]["alpha"], beta=rows["due"]["beta"]),
        PoolPosterior(alpha=rows["new"]["alpha"], beta=rows["new"]["beta"]),
    )


def _save_posteriors(
    conn: sqlite3.Connection, due: PoolPosterior, new: PoolPosterior
) -> None:
    conn.execute(
        "UPDATE pool_state SET alpha=?, beta=? WHERE pool='due'",
        (due.alpha, due.beta),
    )
    conn.execute(
        "UPDATE pool_state SET alpha=?, beta=? WHERE pool='new'",
        (new.alpha, new.beta),
    )
    conn.commit()


def _load_card_state(
    conn: sqlite3.Connection, fact_id: int, today: date
) -> CardState:
    row = conn.execute(
        "SELECT ease_factor, interval_days, repetitions, due_date, lapses"
        " FROM card_state WHERE fact_id=?",
        (fact_id,),
    ).fetchone()
    if row is None:
        return initial_state(today)
    return CardState(
        ease=row["ease_factor"],
        interval=row["interval_days"],
        repetitions=row["repetitions"],
        due_date=date.fromisoformat(row["due_date"]),
        lapses=row["lapses"],
    )


def _save_card_state(
    conn: sqlite3.Connection, fact_id: int, state: CardState
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO card_state"
        " (fact_id, ease_factor, interval_days, repetitions,"
        "  due_date, last_reviewed_at, lapses)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            fact_id,
            state.ease,
            state.interval,
            state.repetitions,
            state.due_date.isoformat(),
            datetime.now(timezone.utc).isoformat(),
            state.lapses,
        ),
    )
    conn.commit()


def _save_review(
    conn: sqlite3.Connection,
    fact_id: int,
    question_id: int,
    grade: int,
    correct: bool,
    pool: str,
    state: CardState,
) -> None:
    conn.execute(
        "INSERT INTO reviews"
        " (fact_id, question_id, reviewed_at, grade, correct, pool,"
        "  ease_after, interval_after)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            fact_id,
            question_id,
            datetime.now(timezone.utc).isoformat(),
            grade,
            int(correct),
            pool,
            state.ease,
            state.interval,
        ),
    )
    conn.commit()


def run_session(
    conn: sqlite3.Connection,
    today: date,
    rng: random.Random,
    config: SessionConfig,
    ui: UI,
) -> SessionResult:
    due: list[int] = _due_pool(conn, today)
    new: list[int] = _new_pool(conn)
    due_post, new_post = _load_posteriors(conn)

    lapsed: deque[int] = deque()
    new_drawn = 0
    correct_count = 0
    total = 0
    weak: set[int] = set()

    for _ in range(config.size):
        if lapsed:
            fact_id = lapsed.popleft()
            pool_label = "lapsed"
        else:
            due_ok = bool(due)
            new_ok = bool(new) and new_drawn < config.new_cap
            if not due_ok and not new_ok:
                break

            if due_ok and new_ok:
                arm = choose(rng, due_post, new_post)
            elif due_ok:
                arm = "due"
            else:
                arm = "new"

            if arm == "due":
                fact_id = due.pop(0)
                pool_label = "due"
            else:
                fact_id = new.pop(0)
                pool_label = "new"
                new_drawn += 1

        prompt = build_prompt(conn, fact_id, rng)
        user_indices = ui.show_prompt(prompt)
        correct = grade_answer(prompt, user_indices)

        state = _load_card_state(conn, fact_id, today)
        if correct:
            grade = ui.show_feedback(prompt, True)
        else:
            grade = 0
            ui.show_feedback(prompt, False)

        new_state = sm2_update(state, grade, today)
        _save_card_state(conn, fact_id, new_state)
        _save_review(conn, fact_id, prompt.question_id, grade, correct,
                     pool_label, new_state)

        if pool_label != "lapsed":
            if pool_label == "due":
                due_post = bandit_update(due_post, correct)
            else:
                new_post = bandit_update(new_post, correct)
            _save_posteriors(conn, due_post, new_post)

        if correct:
            correct_count += 1
        else:
            weak.add(fact_id)
            lapsed.append(fact_id)

        total += 1

    result = SessionResult(
        correct=correct_count,
        total=total,
        weak_facts=sorted(weak),
    )
    ui.show_summary(result)
    return result
