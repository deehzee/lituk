import json
import random
from datetime import date, timedelta

import pytest

from lituk.db import init_db
from lituk.review.presenter import Prompt
from lituk.review.session import SessionConfig, SessionResult, run_session


TODAY = date(2026, 5, 9)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_fact_and_question(conn, q_text, a_text, source_test, q_num,
                               choices=None, correct_letters=None):
    if choices is None:
        choices = ["Correct", "Wrong1", "Wrong2", "Wrong3"]
    if correct_letters is None:
        correct_letters = ["A"]
    conn.execute(
        "INSERT OR IGNORE INTO facts (question_text, correct_answer_text)"
        " VALUES (?, ?)",
        (q_text, a_text),
    )
    conn.commit()
    fid = conn.execute(
        "SELECT id FROM facts WHERE question_text=? AND correct_answer_text=?",
        (q_text, a_text),
    ).fetchone()["id"]
    conn.execute(
        "INSERT OR IGNORE INTO questions"
        " (source_test, q_number, question_text, choices, correct_letters,"
        "  is_true_false, is_multi, fact_id)"
        " VALUES (?, ?, ?, ?, ?, 0, 0, ?)",
        (source_test, q_num, q_text, json.dumps(choices),
         json.dumps(correct_letters), fid),
    )
    conn.commit()
    return fid


def _seed_due_card(conn, fact_id, due_date=None):
    if due_date is None:
        due_date = TODAY - timedelta(days=1)
    conn.execute(
        "INSERT OR REPLACE INTO card_state"
        " (fact_id, ease_factor, interval_days, repetitions, due_date, lapses)"
        " VALUES (?, 2.5, 1, 1, ?, 0)",
        (fact_id, due_date.isoformat()),
    )
    conn.commit()


class StubUI:
    """Always answers correctly (index 0 in prompt.correct_indices) and grades Good."""

    def __init__(self, always_correct=True, grade=4):
        self.always_correct = always_correct
        self.grade = grade
        self.prompts_shown: list[Prompt] = []
        self.feedbacks: list[tuple[Prompt, bool]] = []

    def show_prompt(self, prompt: Prompt) -> list[int]:
        self.prompts_shown.append(prompt)
        if self.always_correct:
            return list(prompt.correct_indices)
        wrong = [i for i in range(len(prompt.choices))
                 if i not in prompt.correct_indices]
        return wrong[:1] if wrong else list(prompt.correct_indices)

    def show_feedback(self, prompt: Prompt, correct: bool) -> int:
        self.feedbacks.append((prompt, correct))
        if not correct:
            return 0
        return self.grade

    def show_summary(self, result: SessionResult) -> None:
        pass


@pytest.fixture
def conn(tmp_path):
    c = init_db(str(tmp_path / "test.db"))
    yield c
    c.close()


# ---------------------------------------------------------------------------
# 1-card session — verify state written
# ---------------------------------------------------------------------------

def test_one_card_session_writes_card_state(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    ui = StubUI()
    result = run_session(conn, TODAY, random.Random(0), SessionConfig(size=1), ui)
    assert result.total == 1
    assert result.correct == 1
    row = conn.execute(
        "SELECT * FROM card_state WHERE fact_id=?", (fid,)
    ).fetchone()
    assert row is not None
    assert row["repetitions"] == 1


def test_one_card_session_writes_review_row(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    run_session(conn, TODAY, random.Random(0), SessionConfig(size=1), StubUI())
    count = conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE fact_id=?", (fid,)
    ).fetchone()[0]
    assert count == 1


def test_one_card_session_updates_pool_state(conn):
    _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    run_session(conn, TODAY, random.Random(0), SessionConfig(size=1), StubUI())
    new_row = conn.execute(
        "SELECT alpha, beta FROM pool_state WHERE pool='new'"
    ).fetchone()
    # one correct answer on the new arm → alpha should have increased
    assert new_row["alpha"] > 1.0


# ---------------------------------------------------------------------------
# Lapsed-in-session reinforcement
# ---------------------------------------------------------------------------

def test_lapsed_card_reappears_in_session(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    # Answer wrong on first showing, then correct
    call_count = [0]
    original_show = None

    class ToggleUI(StubUI):
        def show_prompt(self, prompt):
            self.prompts_shown.append(prompt)
            call_count[0] += 1
            if call_count[0] == 1:
                # Wrong first time
                wrong = [i for i in range(len(prompt.choices))
                         if i not in prompt.correct_indices]
                return wrong[:1] if wrong else prompt.correct_indices
            return list(prompt.correct_indices)

    ui = ToggleUI(always_correct=False)
    result = run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=3), ui
    )
    # fact_id must appear at least twice in prompts (once wrong, once right)
    shown_facts = [p.fact_id for p in ui.prompts_shown]
    assert shown_facts.count(fid) >= 2


def test_lapsed_card_counted_toward_session_size(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)

    call_count = [0]

    class AlwaysWrongUI(StubUI):
        def show_prompt(self, prompt):
            self.prompts_shown.append(prompt)
            call_count[0] += 1
            wrong = [i for i in range(len(prompt.choices))
                     if i not in prompt.correct_indices]
            return wrong[:1] if wrong else prompt.correct_indices

    ui = AlwaysWrongUI(always_correct=False)
    result = run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=2), ui
    )
    # Session should end after 2 slots regardless of lapsed state
    assert result.total == 2


# ---------------------------------------------------------------------------
# Pool fallbacks
# ---------------------------------------------------------------------------

def test_empty_new_pool_falls_back_to_due(conn):
    # Insert 3 due cards, no new cards
    for i in range(3):
        fid = _insert_fact_and_question(conn, f"Q{i}?", "Correct", 1, i + 1)
        _seed_due_card(conn, fid)
    ui = StubUI()
    result = run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=3, new_cap=5), ui
    )
    assert result.total == 3


def test_empty_due_pool_falls_back_to_new(conn):
    # Insert 3 new cards, no due cards
    for i in range(3):
        _insert_fact_and_question(conn, f"Q{i}?", "Correct", 1, i + 1)
    ui = StubUI()
    result = run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=3, new_cap=5), ui
    )
    assert result.total == 3


# ---------------------------------------------------------------------------
# new_cap
# ---------------------------------------------------------------------------

def test_new_cap_limits_new_cards(conn):
    # 10 new facts, new_cap=3
    for i in range(10):
        _insert_fact_and_question(conn, f"Q{i}?", "Correct", 1, i + 1)
    # Also add some due cards so session can fill remaining slots
    for i in range(10, 20):
        fid = _insert_fact_and_question(conn, f"Q{i}?", "Correct", 2, i - 9)
        _seed_due_card(conn, fid)

    shown_pools: list[str] = []

    class TrackingUI(StubUI):
        pass

    ui = StubUI()
    result = run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=6, new_cap=3), ui
    )
    new_count = conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE pool='new'"
    ).fetchone()[0]
    assert new_count <= 3


# ---------------------------------------------------------------------------
# All pools empty → early exit
# ---------------------------------------------------------------------------

def test_empty_pools_early_exit(conn):
    ui = StubUI()
    result = run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=10), ui
    )
    assert result.total == 0
    assert result.correct == 0


# ---------------------------------------------------------------------------
# weak_facts in result
# ---------------------------------------------------------------------------

def test_weak_facts_populated_on_lapse(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)

    class WrongUI(StubUI):
        def show_prompt(self, prompt):
            self.prompts_shown.append(prompt)
            wrong = [i for i in range(len(prompt.choices))
                     if i not in prompt.correct_indices]
            return wrong[:1] if wrong else prompt.correct_indices

    ui = WrongUI(always_correct=False)
    result = run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=1), ui
    )
    assert fid in result.weak_facts


def test_weak_facts_empty_on_all_correct(conn):
    for i in range(3):
        _insert_fact_and_question(conn, f"Q{i}?", "Correct", 1, i + 1)
    result = run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=3), StubUI()
    )
    assert result.weak_facts == []
