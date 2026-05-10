import random
import sqlite3
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from lituk.review.bandit import PoolPosterior, choose
from lituk.review.presenter import Prompt, build_prompt, grade_answer
from lituk.review.scheduler import CardState, initial_state
from lituk.review.scheduler import update as sm2_update


@dataclass(frozen=True)
class SessionConfig:
    size: int = 24


@dataclass(frozen=True)
class SessionResult:
    correct: int
    total: int
    weak_facts: list[int]


class UI(Protocol):
    def show_prompt(self, prompt: Prompt) -> list[int]: ...
    def show_feedback(self, prompt: Prompt, correct: bool) -> int: ...
    def show_summary(self, result: SessionResult) -> None: ...


def _due_pool(
    conn: sqlite3.Connection, today: date, topics: list[int] | None = None
) -> list[int]:
    topic_sql = (
        f" AND f.topic IN ({','.join('?' * len(topics))})" if topics else ""
    )
    sql = (
        "SELECT cs.fact_id FROM card_state cs"
        " JOIN facts f ON f.id = cs.fact_id"
        f" WHERE cs.due_date <= ?{topic_sql}"
        " ORDER BY cs.ease_factor ASC, cs.due_date ASC"
    )
    params: list = [today.isoformat()] + (list(topics) if topics else [])
    return [r["fact_id"] for r in conn.execute(sql, params).fetchall()]


def _new_pool(
    conn: sqlite3.Connection, topics: list[int] | None = None
) -> list[int]:
    topic_sql = (
        f" AND f.topic IN ({','.join('?' * len(topics))})" if topics else ""
    )
    sql = (
        "SELECT f.id FROM facts f"
        " LEFT JOIN card_state cs ON f.id = cs.fact_id"
        f" WHERE cs.fact_id IS NULL{topic_sql}"
    )
    params: list = list(topics) if topics else []
    return [r["id"] for r in conn.execute(sql, params).fetchall()]


def _drill_pool(
    conn: sqlite3.Connection, topics: list[int] | None = None
) -> list[int]:
    topic_sql = (
        f" AND f.topic IN ({','.join('?' * len(topics))})" if topics else ""
    )
    sql = (
        "SELECT cs.fact_id FROM card_state cs"
        " JOIN facts f ON f.id = cs.fact_id"
        f" WHERE cs.lapses > 0{topic_sql}"
        " ORDER BY cs.lapses DESC, cs.last_reviewed_at ASC"
    )
    params: list = list(topics) if topics else []
    return [r["fact_id"] for r in conn.execute(sql, params).fetchall()]


def _compute_posteriors(
    conn: sqlite3.Connection,
    today: date,
    topics: list[int] | None = None,
) -> tuple[PoolPosterior, PoolPosterior]:
    """Compute bandit posteriors fresh from DB state.

    new arm:  Beta(n_unexplored + 1, n_explored + 1)  — coverage signal
    due arm:  Beta(n_wrong + 1, n_correct + 1)        — failure-rate signal
    """
    topic_fact_sql = (
        f" WHERE topic IN ({','.join('?' * len(topics))})" if topics else ""
    )
    topic_params: list = list(topics) if topics else []

    n_total = conn.execute(
        f"SELECT COUNT(*) FROM facts{topic_fact_sql}", topic_params
    ).fetchone()[0]
    topic_cs_sql = (
        " JOIN facts f ON f.id = cs.fact_id"
        f" WHERE f.topic IN ({','.join('?' * len(topics))})" if topics else ""
    )
    n_explored = conn.execute(
        f"SELECT COUNT(*) FROM card_state cs{topic_cs_sql}", topic_params
    ).fetchone()[0]
    n_unexplored = n_total - n_explored

    cutoff = (today - timedelta(days=30)).isoformat()
    topic_rev_sql = (
        f" AND f.topic IN ({','.join('?' * len(topics))})" if topics else ""
    )
    row = conn.execute(
        "SELECT"
        " SUM(CASE WHEN r.correct=0 THEN 1 ELSE 0 END) AS wrong,"
        " SUM(CASE WHEN r.correct=1 THEN 1 ELSE 0 END) AS correct"
        " FROM reviews r JOIN facts f ON f.id = r.fact_id"
        " WHERE r.pool IN ('due','lapsed','drill')"
        f"  AND date(r.reviewed_at) >= ?{topic_rev_sql}",
        [cutoff] + topic_params,
    ).fetchone()
    n_wrong = row["wrong"] or 0
    n_correct = row["correct"] or 0

    return (
        PoolPosterior(alpha=n_unexplored + 1, beta=n_explored + 1),
        PoolPosterior(alpha=n_wrong + 1, beta=n_correct + 1),
    )


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
    session_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO reviews"
        " (fact_id, question_id, reviewed_at, grade, correct, pool,"
        "  ease_after, interval_after, session_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            fact_id,
            question_id,
            datetime.now(timezone.utc).isoformat(),
            grade,
            int(correct),
            pool,
            state.ease,
            state.interval,
            session_id,
        ),
    )
    conn.commit()


def _present_and_grade(
    conn: sqlite3.Connection,
    today: date,
    ui: UI,
    fact_id: int,
    pool_label: str,
    rng: random.Random,
    session_id: str | None = None,
) -> tuple[bool, CardState]:
    """Present one card, collect grade, persist state. Return (correct, new_state)."""
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
    _save_review(
        conn, fact_id, prompt.question_id, grade, correct,
        pool_label, new_state, session_id,
    )
    return correct, new_state


def run_session(
    conn: sqlite3.Connection,
    today: date,
    rng: random.Random,
    config: SessionConfig,
    ui: UI,
    topics: list[int] | None = None,
    session_id: str | None = None,
) -> SessionResult:
    due: list[int] = _due_pool(conn, today, topics)
    new: list[int] = _new_pool(conn, topics)
    rng.shuffle(new)
    new_post, due_post = _compute_posteriors(conn, today, topics)

    # In-memory counters for mid-session posterior updates
    n_unexplored = len(new)
    n_explored = conn.execute("SELECT COUNT(*) FROM card_state").fetchone()[0]
    cutoff = (today - timedelta(days=30)).isoformat()
    row = conn.execute(
        "SELECT"
        " SUM(CASE WHEN correct=0 THEN 1 ELSE 0 END) AS wrong,"
        " SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) AS correct"
        " FROM reviews WHERE pool IN ('due','lapsed','drill')"
        " AND date(reviewed_at) >= ?",
        (cutoff,),
    ).fetchone()
    n_wrong = row["wrong"] or 0
    n_correct = row["correct"] or 0

    lapsed: deque[int] = deque()
    correct_count = 0
    total = 0
    weak: set[int] = set()

    for _ in range(config.size):
        if lapsed:
            fact_id = lapsed.popleft()
            pool_label = "lapsed"
        else:
            due_ok = bool(due)
            new_ok = bool(new)
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
                n_unexplored -= 1
                n_explored += 1
                new_post = PoolPosterior(
                    alpha=n_unexplored + 1, beta=n_explored + 1
                )

        correct, _ = _present_and_grade(
            conn, today, ui, fact_id, pool_label, rng, session_id
        )

        if pool_label in ("due", "lapsed"):
            if correct:
                n_correct += 1
            else:
                n_wrong += 1
            due_post = PoolPosterior(alpha=n_wrong + 1, beta=n_correct + 1)

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


def run_explore_session(
    conn: sqlite3.Connection,
    today: date,
    rng: random.Random,
    config: SessionConfig,
    ui: UI,
    topics: list[int] | None = None,
    session_id: str | None = None,
) -> SessionResult:
    """Session using only unseen facts (no card_state row). No bandit; updates SM-2."""
    pool: list[int] = _new_pool(conn, topics)
    rng.shuffle(pool)

    lapsed: deque[int] = deque()
    correct_count = 0
    total = 0
    weak: set[int] = set()

    for _ in range(config.size):
        if lapsed:
            fact_id = lapsed.popleft()
            pool_label = "lapsed"
        else:
            if not pool:
                break
            fact_id = pool.pop(0)
            pool_label = "new"

        correct, _ = _present_and_grade(
            conn, today, ui, fact_id, pool_label, rng, session_id
        )

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


def run_drill_session(
    conn: sqlite3.Connection,
    today: date,
    rng: random.Random,
    config: SessionConfig,
    ui: UI,
    topics: list[int] | None = None,
    session_id: str | None = None,
) -> SessionResult:
    """Session using only facts with prior lapses. No bandit; updates SM-2."""
    pool: list[int] = _drill_pool(conn, topics)
    rng.shuffle(pool)

    lapsed: deque[int] = deque()
    correct_count = 0
    total = 0
    weak: set[int] = set()

    for _ in range(config.size):
        if lapsed:
            fact_id = lapsed.popleft()
            pool_label = "lapsed"
        else:
            if not pool:
                break
            fact_id = pool.pop(0)
            pool_label = "drill"

        correct, _ = _present_and_grade(
            conn, today, ui, fact_id, pool_label, rng, session_id
        )

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
