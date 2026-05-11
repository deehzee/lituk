import json
import random
from collections import deque
from datetime import date, datetime, timedelta, timezone

import pytest

from lituk.db import init_db
from lituk.review.bandit import PoolPosterior
from lituk.review.presenter import Prompt
from lituk.review.session import (
    Selection,
    SessionConfig,
    SessionResult,
    _compute_posteriors,
    _drill_reasoning,
    _select_card,
    run_drill_session,
    run_explore_session,
    run_session,
)


TODAY = date(2026, 5, 9)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_fact_and_question(conn, q_text, a_text, source_test=1, q_num=1,
                               choices=None, correct_letters=None,
                               topic=None):
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
    if topic is not None:
        conn.execute("UPDATE facts SET topic=? WHERE id=?", (topic, fid))
        conn.commit()
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


def _seed_card_state(conn, fact_id, lapses=1, last_reviewed_at=None,
                     ease=2.5, interval=1, due_date: date | None = None):
    if last_reviewed_at is None:
        last_reviewed_at = datetime(2026, 5, 4, 12, 0, 0,
                                    tzinfo=timezone.utc).isoformat()
    due_date_str = due_date.isoformat() if due_date else TODAY.isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO card_state"
        " (fact_id, ease_factor, interval_days, repetitions,"
        "  due_date, last_reviewed_at, lapses)"
        " VALUES (?, ?, ?, 1, ?, ?, ?)",
        (fact_id, ease, interval, due_date_str, last_reviewed_at, lapses),
    )
    conn.commit()


class StubUI:
    """Always answers correctly (index 0 in prompt.correct_indices) and grades Good."""

    def __init__(self, always_correct=True, grade=4):
        self.always_correct = always_correct
        self.grade = grade
        self.prompts_shown: list[Prompt] = []
        self.feedbacks: list[tuple[Prompt, bool]] = []
        self.reasonings: list[str] = []

    def show_reasoning(self, text: str) -> None:
        self.reasonings.append(text)

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
    assert len(ui.reasonings) == result.total
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


def test_one_card_session_writes_review(conn):
    _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    run_session(conn, TODAY, random.Random(0), SessionConfig(size=1), StubUI())
    count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    assert count == 1


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
    assert len(ui.reasonings) == result.total


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
    assert len(ui.reasonings) == result.total


# ---------------------------------------------------------------------------
# Pool fallbacks
# ---------------------------------------------------------------------------

def test_empty_new_pool_falls_back_to_due(conn):
    for i in range(3):
        fid = _insert_fact_and_question(conn, f"Q{i}?", "Correct", 1, i + 1)
        _seed_due_card(conn, fid)
    ui = StubUI()
    result = run_session(conn, TODAY, random.Random(0), SessionConfig(size=3), ui)
    assert result.total == 3
    assert len(ui.reasonings) == result.total


def test_empty_due_pool_falls_back_to_new(conn):
    for i in range(3):
        _insert_fact_and_question(conn, f"Q{i}?", "Correct", 1, i + 1)
    ui = StubUI()
    result = run_session(conn, TODAY, random.Random(0), SessionConfig(size=3), ui)
    assert result.total == 3
    assert len(ui.reasonings) == result.total


def test_fresh_db_all_new_fills_session(conn):
    for i in range(30):
        _insert_fact_and_question(conn, f"Q{i}?", "Correct", 1, i + 1)
    ui = StubUI()
    result = run_session(conn, TODAY, random.Random(0), SessionConfig(size=24), ui)
    assert result.total == 24
    assert len(ui.reasonings) == result.total


def test_no_new_cap_all_new_can_fill_session(conn):
    # Without new_cap, a session with only new cards fills up to size
    for i in range(30):
        _insert_fact_and_question(conn, f"Q{i}?", "Correct", 1, i + 1)
    ui = StubUI()
    result = run_session(conn, TODAY, random.Random(0), SessionConfig(size=10), ui)
    new_count = conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE pool='new'"
    ).fetchone()[0]
    assert result.total == 10
    assert new_count == 10
    assert len(ui.reasonings) == result.total


def test_bandit_choose_called_with_both_pools_non_empty(conn):
    # Mix of due and new cards forces the bandit to call choose()
    for i in range(5):
        fid = _insert_fact_and_question(conn, f"Qd{i}?", "Correct", 1, i + 1)
        _seed_due_card(conn, fid)
    for i in range(5):
        _insert_fact_and_question(conn, f"Qn{i}?", "Correct", 2, i + 1)
    ui = StubUI()
    result = run_session(conn, TODAY, random.Random(0), SessionConfig(size=6), ui)
    assert result.total == 6
    due_count = conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE pool='due'"
    ).fetchone()[0]
    new_count = conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE pool='new'"
    ).fetchone()[0]
    assert due_count + new_count == 6
    assert len(ui.reasonings) == result.total


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
    assert len(ui.reasonings) == result.total


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
    assert len(ui.reasonings) == result.total


def test_weak_facts_empty_on_all_correct(conn):
    for i in range(3):
        _insert_fact_and_question(conn, f"Q{i}?", "Correct", 1, i + 1)
    result = run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=3), StubUI()
    )
    assert result.weak_facts == []


# ---------------------------------------------------------------------------
# Topic filter
# ---------------------------------------------------------------------------

def test_topic_filter_excludes_other_chapters(conn):
    fid_ch3 = _insert_fact_and_question(conn, "Q_ch3?", "A", 1, 1, topic=3)
    fid_ch4 = _insert_fact_and_question(conn, "Q_ch4?", "A", 1, 2, topic=4)
    ui = StubUI()
    run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=[3],
    )
    shown_facts = {p.fact_id for p in ui.prompts_shown}
    assert fid_ch3 in shown_facts
    assert fid_ch4 not in shown_facts


def test_topic_filter_multi_chapter(conn):
    fid3 = _insert_fact_and_question(conn, "Q3?", "A", 1, 1, topic=3)
    fid4 = _insert_fact_and_question(conn, "Q4?", "A", 1, 2, topic=4)
    fid5 = _insert_fact_and_question(conn, "Q5?", "A", 1, 3, topic=5)
    ui = StubUI()
    run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=[3, 4],
    )
    shown_facts = {p.fact_id for p in ui.prompts_shown}
    assert fid3 in shown_facts
    assert fid4 in shown_facts
    assert fid5 not in shown_facts


def test_topic_filter_none_includes_all(conn):
    fid3 = _insert_fact_and_question(conn, "Q3?", "A", 1, 1, topic=3)
    fid_null = _insert_fact_and_question(conn, "Qnull?", "A", 1, 2, topic=None)
    ui = StubUI()
    run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=None,
    )
    shown_facts = {p.fact_id for p in ui.prompts_shown}
    assert fid3 in shown_facts
    assert fid_null in shown_facts


def test_topic_filter_excludes_null_topic_facts(conn):
    _insert_fact_and_question(conn, "Qnull?", "A", 1, 1, topic=None)
    fid3 = _insert_fact_and_question(conn, "Q3?", "A", 1, 2, topic=3)
    ui = StubUI()
    run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=[3],
    )
    shown_facts = {p.fact_id for p in ui.prompts_shown}
    assert fid3 in shown_facts
    null_fid = conn.execute(
        "SELECT id FROM facts WHERE question_text='Qnull?'"
    ).fetchone()["id"]
    assert null_fid not in shown_facts


def test_topic_filter_due_pool(conn):
    fid3 = _insert_fact_and_question(conn, "Q3?", "A", 1, 1, topic=3)
    fid4 = _insert_fact_and_question(conn, "Q4?", "A", 1, 2, topic=4)
    _seed_due_card(conn, fid3)
    _seed_due_card(conn, fid4)
    ui = StubUI()
    run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=[3],
    )
    shown_facts = {p.fact_id for p in ui.prompts_shown}
    assert fid3 in shown_facts
    assert fid4 not in shown_facts


# ---------------------------------------------------------------------------
# End-to-end smoke: tag → session with topic filter
# ---------------------------------------------------------------------------

def test_e2e_tag_then_session_with_topic_filter(conn):
    import re as _re
    import json as _json
    from unittest.mock import MagicMock
    from lituk.tag.tagger import tag_facts

    fid3 = _insert_fact_and_question(conn, "History Q?", "History A", 1, 1)
    fid5 = _insert_fact_and_question(conn, "Civics Q?", "Civics A", 1, 2)

    mapping = {fid3: 3, fid5: 5}

    def _respond(**kwargs):
        text = kwargs["messages"][0]["content"]
        ids = [int(m) for m in _re.findall(r"ID=(\d+):", text)]
        response = MagicMock()
        msg = MagicMock()
        msg.text = _json.dumps(
            [{"id": fid, "topic": mapping.get(fid, 3)} for fid in ids]
        )
        response.content = [msg]
        return response

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _respond
    tag_facts(conn, mock_client, "SUMMARIES")

    ui = StubUI()
    run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=[3],
    )

    review_fact_ids = {
        row["fact_id"]
        for row in conn.execute("SELECT fact_id FROM reviews").fetchall()
    }
    assert fid3 in review_fact_ids
    assert fid5 not in review_fact_ids


# ---------------------------------------------------------------------------
# session_id write-through
# ---------------------------------------------------------------------------

def test_session_id_written_to_reviews(conn):
    _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=1), StubUI(),
        session_id="test-uuid",
    )
    row = conn.execute("SELECT session_id FROM reviews").fetchone()
    assert row["session_id"] == "test-uuid"


def test_session_id_none_writes_null(conn):
    _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    run_session(conn, TODAY, random.Random(0), SessionConfig(size=1), StubUI())
    row = conn.execute("SELECT session_id FROM reviews").fetchone()
    assert row["session_id"] is None


# ---------------------------------------------------------------------------
# Drill session
# ---------------------------------------------------------------------------

def _seed_lapsed_card(conn, fact_id, lapses=1):
    conn.execute(
        "INSERT OR REPLACE INTO card_state"
        " (fact_id, ease_factor, interval_days, repetitions, due_date, lapses)"
        " VALUES (?, 2.0, 1, 1, ?, ?)",
        (fact_id, (TODAY - timedelta(days=1)).isoformat(), lapses),
    )
    conn.commit()


def test_drill_session_pulls_only_lapsed_facts(conn):
    fid_lapsed = _insert_fact_and_question(conn, "Q_lapsed?", "A", 1, 1)
    _insert_fact_and_question(conn, "Q_new?", "A", 1, 2)
    _seed_lapsed_card(conn, fid_lapsed, lapses=1)

    ui = StubUI()
    run_drill_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui
    )
    shown = {p.fact_id for p in ui.prompts_shown}
    assert fid_lapsed in shown


def test_drill_session_excludes_non_lapsed_facts(conn):
    _insert_fact_and_question(conn, "Q_new?", "A", 1, 1)  # no card_state
    fid_due = _insert_fact_and_question(conn, "Q_due?", "A", 1, 2)
    _seed_lapsed_card(conn, fid_due, lapses=0)  # due but no lapses

    ui = StubUI()
    result = run_drill_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui
    )
    assert result.total == 0  # drill pool is empty


def test_drill_session_writes_pool_drill(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    _seed_lapsed_card(conn, fid, lapses=2)

    run_drill_session(conn, TODAY, random.Random(0), SessionConfig(size=1), StubUI())

    row = conn.execute("SELECT pool FROM reviews").fetchone()
    assert row["pool"] == "drill"


def test_drill_session_updates_sm2(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    _seed_lapsed_card(conn, fid, lapses=1)

    run_drill_session(conn, TODAY, random.Random(0), SessionConfig(size=1), StubUI())

    row = conn.execute(
        "SELECT repetitions FROM card_state WHERE fact_id=?", (fid,)
    ).fetchone()
    assert row["repetitions"] > 0


def test_drill_session_writes_review_with_drill_pool(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    _seed_lapsed_card(conn, fid, lapses=1)
    run_drill_session(conn, TODAY, random.Random(0), SessionConfig(size=1), StubUI())
    row = conn.execute("SELECT pool FROM reviews").fetchone()
    assert row["pool"] == "drill"


def test_drill_session_id_written(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    _seed_lapsed_card(conn, fid, lapses=1)

    run_drill_session(
        conn, TODAY, random.Random(0), SessionConfig(size=1), StubUI(),
        session_id="drill-uuid",
    )
    row = conn.execute("SELECT session_id FROM reviews").fetchone()
    assert row["session_id"] == "drill-uuid"


def test_drill_session_topic_filter(conn):
    fid3 = _insert_fact_and_question(conn, "Q_ch3?", "A", 1, 1, topic=3)
    fid4 = _insert_fact_and_question(conn, "Q_ch4?", "A", 1, 2, topic=4)
    _seed_lapsed_card(conn, fid3, lapses=1)
    _seed_lapsed_card(conn, fid4, lapses=1)

    ui = StubUI()
    run_drill_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=[3],
    )
    shown = {p.fact_id for p in ui.prompts_shown}
    assert fid3 in shown
    assert fid4 not in shown


def test_drill_session_lapsed_in_session_reinforcement(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    _seed_lapsed_card(conn, fid, lapses=1)

    class WrongThenRightUI(StubUI):
        def __init__(self):
            super().__init__()
            self._call = 0

        def show_prompt(self, prompt):
            self.prompts_shown.append(prompt)
            self._call += 1
            if self._call == 1:
                wrong = [i for i in range(len(prompt.choices))
                         if i not in prompt.correct_indices]
                return wrong[:1] if wrong else list(prompt.correct_indices)
            return list(prompt.correct_indices)

    ui = WrongThenRightUI()
    run_drill_session(conn, TODAY, random.Random(0), SessionConfig(size=3), ui)
    assert ui.prompts_shown.count(ui.prompts_shown[0]) >= 1
    shown_facts = [p.fact_id for p in ui.prompts_shown]
    assert shown_facts.count(fid) >= 2


# ---------------------------------------------------------------------------
# run_explore_session
# ---------------------------------------------------------------------------

def test_explore_session_empty_pool_exits_early(conn):
    result = run_explore_session(
        conn, TODAY, random.Random(0), SessionConfig(size=24), StubUI()
    )
    assert result.total == 0


def test_explore_session_writes_card_state_and_review(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)

    run_explore_session(
        conn, TODAY, random.Random(0), SessionConfig(size=1), StubUI()
    )

    assert conn.execute(
        "SELECT COUNT(*) FROM card_state WHERE fact_id=?", (fid,)
    ).fetchone()[0] == 1
    row = conn.execute("SELECT pool FROM reviews WHERE fact_id=?", (fid,)).fetchone()
    assert row["pool"] == "new"


def test_explore_session_excludes_already_explored_facts(conn):
    fid_new = _insert_fact_and_question(conn, "Q_new?", "A", 1, 1)
    fid_seen = _insert_fact_and_question(conn, "Q_seen?", "A", 1, 2)
    _seed_due_card(conn, fid_seen)

    ui = StubUI()
    run_explore_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui
    )
    shown = {p.fact_id for p in ui.prompts_shown}
    assert fid_new in shown
    assert fid_seen not in shown


def test_explore_session_lapsed_reinforcement(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)

    class WrongThenRightUI(StubUI):
        def __init__(self):
            super().__init__()
            self._call = 0

        def show_prompt(self, prompt):
            self.prompts_shown.append(prompt)
            self._call += 1
            if self._call == 1:
                wrong = [i for i in range(len(prompt.choices))
                         if i not in prompt.correct_indices]
                return wrong[:1] if wrong else list(prompt.correct_indices)
            return list(prompt.correct_indices)

    ui = WrongThenRightUI()
    run_explore_session(conn, TODAY, random.Random(0), SessionConfig(size=3), ui)
    shown_facts = [p.fact_id for p in ui.prompts_shown]
    assert shown_facts.count(fid) >= 2


def test_explore_session_topic_filter(conn):
    fid1 = _insert_fact_and_question(conn, "Q_ch1?", "A", 1, 1, topic=1)
    fid2 = _insert_fact_and_question(conn, "Q_ch2?", "A", 1, 2, topic=2)

    ui = StubUI()
    run_explore_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui, topics=[1]
    )
    shown = {p.fact_id for p in ui.prompts_shown}
    assert fid1 in shown
    assert fid2 not in shown


def test_explore_session_updates_sm2(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)

    run_explore_session(
        conn, TODAY, random.Random(0), SessionConfig(size=1), StubUI()
    )

    row = conn.execute(
        "SELECT repetitions FROM card_state WHERE fact_id=?", (fid,)
    ).fetchone()
    assert row["repetitions"] > 0


def test_explore_session_session_id_written(conn):
    _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)

    run_explore_session(
        conn, TODAY, random.Random(0), SessionConfig(size=1), StubUI(),
        session_id="explore-uuid",
    )
    row = conn.execute("SELECT session_id FROM reviews").fetchone()
    assert row["session_id"] == "explore-uuid"


# ---------------------------------------------------------------------------
# _compute_posteriors
# ---------------------------------------------------------------------------

def _insert_review(conn, fid, qid, correct, pool, reviewed_at):
    conn.execute(
        "INSERT INTO reviews"
        " (fact_id, question_id, reviewed_at, grade, correct, pool,"
        "  ease_after, interval_after)"
        " VALUES (?, ?, ?, 4, ?, ?, 2.5, 1)",
        (fid, qid, reviewed_at, int(correct), pool),
    )
    conn.commit()


def test_compute_posteriors_all_unexplored(conn):
    _insert_fact_and_question(conn, "Q1?", "A", 1, 1)
    new_post, due_post = _compute_posteriors(conn, TODAY)
    # 1 unexplored, 0 explored → Beta(2, 1)
    assert new_post.alpha == 2
    assert new_post.beta == 1
    # no reviews → Beta(1, 1)
    assert due_post.alpha == 1
    assert due_post.beta == 1


def test_compute_posteriors_after_exploring(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    _seed_due_card(conn, fid)  # now explored
    new_post, due_post = _compute_posteriors(conn, TODAY)
    # 0 unexplored, 1 explored → Beta(1, 2)
    assert new_post.alpha == 1
    assert new_post.beta == 2


def test_compute_posteriors_due_arm_counts_failures(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    qid = conn.execute(
        "SELECT id FROM questions WHERE fact_id=?", (fid,)
    ).fetchone()["id"]
    _seed_due_card(conn, fid)
    ts = TODAY.isoformat() + "T10:00:00"
    _insert_review(conn, fid, qid, correct=False, pool="due", reviewed_at=ts)
    _insert_review(conn, fid, qid, correct=True, pool="due", reviewed_at=ts)
    _, due_post = _compute_posteriors(conn, TODAY)
    # due arm: Beta(n_wrong+1, n_correct+1) = Beta(1+1, 1+1) = Beta(2, 2)
    assert due_post.alpha == 2
    assert due_post.beta == 2


def test_compute_posteriors_excludes_old_reviews(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    qid = conn.execute(
        "SELECT id FROM questions WHERE fact_id=?", (fid,)
    ).fetchone()["id"]
    _seed_due_card(conn, fid)
    old_ts = (TODAY - timedelta(days=31)).isoformat() + "T10:00:00"
    _insert_review(conn, fid, qid, correct=False, pool="due", reviewed_at=old_ts)
    _, due_post = _compute_posteriors(conn, TODAY)
    # old review excluded → Beta(1, 1)
    assert due_post.alpha == 1
    assert due_post.beta == 1


def test_compute_posteriors_excludes_new_pool_reviews(conn):
    fid = _insert_fact_and_question(conn, "Q1?", "Correct", 1, 1)
    qid = conn.execute(
        "SELECT id FROM questions WHERE fact_id=?", (fid,)
    ).fetchone()["id"]
    ts = TODAY.isoformat() + "T10:00:00"
    _insert_review(conn, fid, qid, correct=False, pool="new", reviewed_at=ts)
    _, due_post = _compute_posteriors(conn, TODAY)
    # new-pool review excluded → Beta(1, 1)
    assert due_post.alpha == 1
    assert due_post.beta == 1


def test_compute_posteriors_topic_filter(conn):
    fid1 = _insert_fact_and_question(conn, "Q_ch1?", "A", 1, 1, topic=1)
    _insert_fact_and_question(conn, "Q_ch2?", "B", 1, 2, topic=2)
    _seed_due_card(conn, fid1)  # ch1 explored, ch2 not
    new_post, _ = _compute_posteriors(conn, TODAY, topics=[2])
    # ch2: 1 unexplored, 0 explored → Beta(2, 1)
    assert new_post.alpha == 2
    assert new_post.beta == 1


# ---------------------------------------------------------------------------
# _select_card: lapsed case
# ---------------------------------------------------------------------------

def test_select_card_lapsed_returns_lapsed_label(conn):
    fid = _insert_fact_and_question(conn, "Q?", "A")
    _seed_card_state(conn, fid, lapses=2,
                     last_reviewed_at=datetime(2026, 5, 4, 12, 0,
                     tzinfo=timezone.utc).isoformat())
    rng = random.Random(1)
    lapsed = deque([fid])
    due = []
    new = []
    due_post = PoolPosterior(alpha=1.0, beta=1.0)
    new_post = PoolPosterior(alpha=1.0, beta=1.0)
    sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
    assert sel is not None
    assert sel.pool_label == "lapsed"
    assert sel.fact_id == fid
    assert "Lapsed" in sel.reasoning
    assert "lapses=2" in sel.reasoning
    assert "last seen 5d ago" in sel.reasoning


def test_select_card_lapsed_pops_from_deque(conn):
    fid = _insert_fact_and_question(conn, "Q2?", "A2")
    _seed_card_state(conn, fid, lapses=1)
    lapsed = deque([fid])
    due = []
    new = []
    due_post = PoolPosterior(alpha=1.0, beta=1.0)
    new_post = PoolPosterior(alpha=1.0, beta=1.0)
    _select_card(random.Random(0), lapsed, due, new,
                 due_post, new_post, conn, TODAY)
    assert len(lapsed) == 0


def test_select_card_all_empty_returns_none(conn):
    lapsed = deque()
    due = []
    new = []
    due_post = PoolPosterior(alpha=1.0, beta=1.0)
    new_post = PoolPosterior(alpha=1.0, beta=1.0)
    sel = _select_card(random.Random(0), lapsed, due, new,
                       due_post, new_post, conn, TODAY)
    assert sel is None


# ---------------------------------------------------------------------------
# _select_card: MAB cases (both pools non-empty)
# ---------------------------------------------------------------------------

def test_select_card_mab_due_arm_label_and_reasoning(conn):
    fid_due = _insert_fact_and_question(conn, "QDue?", "ADue")
    fid_new = _insert_fact_and_question(conn, "QNew?", "ANew", source_test=2, q_num=2)
    _seed_card_state(conn, fid_due, lapses=0, ease=2.1,
                     due_date=(TODAY - timedelta(days=3)))
    rng = random.Random(0)
    lapsed = deque()
    due = [fid_due]
    new = [fid_new]   # both non-empty → MAB used
    due_post = PoolPosterior(alpha=100.0, beta=1.0)   # due arm almost certain
    new_post = PoolPosterior(alpha=1.0, beta=100.0)
    sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
    assert sel is not None
    assert sel.pool_label == "due"
    assert sel.fact_id == fid_due
    assert "MAB" in sel.reasoning
    assert "→ due" in sel.reasoning
    assert "ease=2.10" in sel.reasoning
    assert "overdue 3d" in sel.reasoning


def test_select_card_mab_new_arm_label_and_reasoning(conn):
    fid_due = _insert_fact_and_question(conn, "QDue2?", "ADue2")
    fid_new = _insert_fact_and_question(conn, "QNew2?", "ANew2", source_test=2, q_num=2)
    _seed_card_state(conn, fid_due, lapses=0, ease=2.5)
    rng = random.Random(0)
    lapsed = deque()
    due = [fid_due]
    new = [fid_new]   # both non-empty → MAB used
    due_post = PoolPosterior(alpha=1.0, beta=100.0)
    new_post = PoolPosterior(alpha=100.0, beta=1.0)  # new arm almost certain
    sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
    assert sel is not None
    assert sel.pool_label == "new"
    assert sel.fact_id == fid_new
    assert "MAB" in sel.reasoning
    assert "→ new" in sel.reasoning


def test_select_card_mab_new_arm_updates_new_post(conn):
    fid_due = _insert_fact_and_question(conn, "QDue3?", "ADue3")
    fid_new = _insert_fact_and_question(conn, "QNew3?", "ANew3", source_test=2, q_num=2)
    _seed_card_state(conn, fid_due, lapses=0, ease=2.5)
    rng = random.Random(0)
    lapsed = deque()
    due = [fid_due]
    new = [fid_new]
    due_post = PoolPosterior(alpha=1.0, beta=100.0)
    new_post = PoolPosterior(alpha=10.0, beta=5.0)   # new arm almost certain
    sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
    assert sel.pool_label == "new"
    assert sel.new_post.alpha == 9.0   # alpha decrements by 1
    assert sel.new_post.beta == 6.0    # beta increments by 1


def test_select_card_mab_due_arm_new_post_unchanged(conn):
    fid_due = _insert_fact_and_question(conn, "QDue4?", "ADue4")
    fid_new = _insert_fact_and_question(conn, "QNew4?", "ANew4", source_test=2, q_num=2)
    _seed_card_state(conn, fid_due, lapses=0, ease=2.5)
    rng = random.Random(0)
    lapsed = deque()
    due = [fid_due]
    new = [fid_new]
    due_post = PoolPosterior(alpha=100.0, beta=1.0)  # due arm almost certain
    new_post = PoolPosterior(alpha=3.0, beta=7.0)
    sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
    assert sel.pool_label == "due"
    assert sel.new_post == new_post    # unchanged when due arm chosen


# ---------------------------------------------------------------------------
# _select_card: forced pool cases (single pool available)
# ---------------------------------------------------------------------------

def test_select_card_due_only_reasoning(conn):
    fid = _insert_fact_and_question(conn, "QDueOnly?", "ADueOnly")
    _seed_card_state(conn, fid, lapses=0, ease=1.8,
                     due_date=(TODAY - timedelta(days=2)))
    rng = random.Random(0)
    lapsed = deque()
    due = [fid]
    new = []           # empty new pool → forced due, no MAB
    due_post = PoolPosterior(alpha=2.0, beta=2.0)
    new_post = PoolPosterior(alpha=1.0, beta=1.0)
    sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
    assert sel is not None
    assert sel.pool_label == "due"
    assert "Due only" in sel.reasoning
    assert "MAB" not in sel.reasoning
    assert "ease=1.80" in sel.reasoning
    assert "overdue 2d" in sel.reasoning


def test_select_card_new_only_reasoning(conn):
    fid = _insert_fact_and_question(conn, "QNewOnly?", "ANewOnly")
    rng = random.Random(0)
    lapsed = deque()
    due = []           # empty due pool → forced new, no MAB
    new = [fid]
    due_post = PoolPosterior(alpha=2.0, beta=2.0)
    new_post = PoolPosterior(alpha=5.0, beta=3.0)
    sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
    assert sel is not None
    assert sel.pool_label == "new"
    assert "New only" in sel.reasoning
    assert "MAB" not in sel.reasoning
    assert "1 unseen remaining" in sel.reasoning


# ---------------------------------------------------------------------------
# _drill_reasoning
# ---------------------------------------------------------------------------

def _seed_review(conn, fact_id, correct, reviewed_at):
    conn.execute(
        "INSERT INTO reviews"
        " (fact_id, question_id, reviewed_at, grade, correct, pool,"
        "  ease_after, interval_after)"
        " VALUES (?, 1, ?, 0, ?, 'drill', 2.5, 1)",
        (fact_id, reviewed_at, int(correct)),
    )
    conn.commit()


def test_drill_reasoning_includes_lapses_and_days(conn):
    fid = _insert_fact_and_question(conn, "QDrill?", "ADrill")
    _seed_card_state(
        conn, fid, lapses=3,
        last_reviewed_at=datetime(2026, 5, 6, 10, 0,
                                  tzinfo=timezone.utc).isoformat(),
    )
    _seed_review(conn, fid, correct=False,
                 reviewed_at=datetime(2026, 5, 4, 10, 0,
                                      tzinfo=timezone.utc).isoformat())
    result = _drill_reasoning(conn, fid, TODAY)
    # TODAY = date(2026, 5, 9)
    assert "lapses=3" in result
    assert "last seen 3d ago" in result   # 2026-05-06 → 3 days before TODAY
    assert "last wrong 5d ago" in result  # 2026-05-04 → 5 days before TODAY


def test_drill_reasoning_no_wrong_review(conn):
    fid = _insert_fact_and_question(conn, "QDrill2?", "ADrill2")
    _seed_card_state(conn, fid, lapses=1,
                     last_reviewed_at=datetime(2026, 5, 8, 10, 0,
                     tzinfo=timezone.utc).isoformat())
    # No wrong reviews inserted
    result = _drill_reasoning(conn, fid, TODAY)
    assert "lapses=1" in result
    assert "last seen 1d ago" in result
    assert "never wrong" in result
