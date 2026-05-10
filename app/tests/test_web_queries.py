import json
import random
from datetime import date, timedelta

from lituk.db import init_db
from lituk.web.queries import (
    by_chapter,
    coverage,
    due_today,
    missed_reviews,
    recent_sessions,
    streak,
    weak_facts,
)


TODAY = date(2026, 5, 9)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_fact(conn, q, a, topic=None):
    conn.execute(
        "INSERT OR IGNORE INTO facts (question_text, correct_answer_text)"
        " VALUES (?, ?)",
        (q, a),
    )
    conn.commit()
    fid = conn.execute(
        "SELECT id FROM facts WHERE question_text=? AND correct_answer_text=?",
        (q, a),
    ).fetchone()["id"]
    if topic is not None:
        conn.execute("UPDATE facts SET topic=? WHERE id=?", (topic, fid))
        conn.commit()
    return fid


def _insert_question(conn, fid, src, qnum):
    conn.execute(
        "INSERT OR IGNORE INTO questions"
        " (source_test, q_number, question_text, choices, correct_letters,"
        "  is_true_false, is_multi, fact_id)"
        " VALUES (?, ?, ?, ?, ?, 0, 0, ?)",
        (src, qnum, "Q?", json.dumps(["A", "B"]), json.dumps(["A"]), fid),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM questions WHERE source_test=? AND q_number=?",
        (src, qnum),
    ).fetchone()["id"]


def _insert_review(conn, fid, qid, correct, pool="new",
                   reviewed_at=None, session_id=None):
    if reviewed_at is None:
        reviewed_at = TODAY.isoformat() + "T12:00:00+00:00"
    conn.execute(
        "INSERT INTO reviews"
        " (fact_id, question_id, reviewed_at, grade, correct, pool,"
        "  ease_after, interval_after, session_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fid, qid, reviewed_at, 4, int(correct), pool, 2.5, 1, session_id),
    )
    conn.commit()


def _seed_card_state(conn, fid, lapses=0, due=None):
    if due is None:
        due = TODAY - timedelta(days=1)
    conn.execute(
        "INSERT OR REPLACE INTO card_state"
        " (fact_id, ease_factor, interval_days, repetitions, due_date, lapses)"
        " VALUES (?, 2.5, 1, 1, ?, ?)",
        (fid, due.isoformat(), lapses),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# by_chapter
# ---------------------------------------------------------------------------

def test_by_chapter_returns_accuracy_per_chapter(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A", topic=3)
    qid = _insert_question(conn, fid, 1, 1)
    _insert_review(conn, fid, qid, correct=True)
    _insert_review(conn, fid, qid, correct=False)
    rows = by_chapter(conn)
    ch3 = next(r for r in rows if r["chapter_id"] == 3)
    assert ch3["total"] == 2
    assert ch3["correct"] == 1
    assert abs(ch3["pct_correct"] - 50.0) < 0.01


def test_by_chapter_excludes_untagged_facts(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A", topic=None)
    qid = _insert_question(conn, fid, 1, 1)
    _insert_review(conn, fid, qid, correct=True)
    rows = by_chapter(conn)
    totals = [r["total"] for r in rows]
    assert sum(totals) == 0


def test_by_chapter_returns_all_five_chapters(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    rows = by_chapter(conn)
    assert len(rows) == 5
    assert {r["chapter_id"] for r in rows} == {1, 2, 3, 4, 5}


# ---------------------------------------------------------------------------
# recent_sessions
# ---------------------------------------------------------------------------

def test_recent_sessions_groups_by_session_id(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A")
    qid = _insert_question(conn, fid, 1, 1)
    _insert_review(conn, fid, qid, correct=True, session_id="s1",
                   reviewed_at="2026-05-09T10:00:00+00:00")
    _insert_review(conn, fid, qid, correct=False, session_id="s1",
                   reviewed_at="2026-05-09T10:01:00+00:00")
    _insert_review(conn, fid, qid, correct=True, session_id="s2",
                   reviewed_at="2026-05-09T11:00:00+00:00")
    rows = recent_sessions(conn)
    assert len(rows) == 2
    s1 = next(r for r in rows if r["session_id"] == "s1")
    assert s1["total"] == 2
    assert s1["correct"] == 1


def test_recent_sessions_excludes_null_session_id(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A")
    qid = _insert_question(conn, fid, 1, 1)
    _insert_review(conn, fid, qid, correct=True, session_id=None)
    rows = recent_sessions(conn)
    assert rows == []


def test_recent_sessions_respects_limit(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A")
    qid = _insert_question(conn, fid, 1, 1)
    for i in range(15):
        _insert_review(conn, fid, qid, correct=True, session_id=f"s{i}",
                       reviewed_at=f"2026-05-{i+1:02d}T10:00:00+00:00")
    rows = recent_sessions(conn, limit=5)
    assert len(rows) == 5


# ---------------------------------------------------------------------------
# weak_facts
# ---------------------------------------------------------------------------

def test_weak_facts_ordered_by_lapses_desc(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid1 = _insert_fact(conn, "Q1?", "A")
    fid2 = _insert_fact(conn, "Q2?", "A")
    _seed_card_state(conn, fid1, lapses=3)
    _seed_card_state(conn, fid2, lapses=1)
    rows = weak_facts(conn)
    assert rows[0]["fact_id"] == fid1
    assert rows[0]["lapses"] == 3


def test_weak_facts_excludes_no_lapse_facts(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A")
    _seed_card_state(conn, fid, lapses=0)
    rows = weak_facts(conn)
    assert rows == []


def test_weak_facts_respects_limit(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    for i in range(25):
        fid = _insert_fact(conn, f"Q{i}?", "A")
        _seed_card_state(conn, fid, lapses=i + 1)
    rows = weak_facts(conn, limit=10)
    assert len(rows) == 10


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------

def test_coverage_zero_when_no_facts_seen(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _insert_fact(conn, "Q?", "A")
    result = coverage(conn)
    assert result["seen"] == 0
    assert result["total"] == 1
    assert result["pct_seen"] == 0.0


def test_coverage_full_when_all_seen(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A")
    _seed_card_state(conn, fid)
    result = coverage(conn)
    assert result["seen"] == 1
    assert result["total"] == 1
    assert result["pct_seen"] == 100.0


def test_coverage_zero_when_no_facts_at_all(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    result = coverage(conn)
    assert result["pct_seen"] == 0.0
    assert result["total"] == 0


def test_coverage_chapter_filter_counts_only_that_chapter(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid1 = _insert_fact(conn, "Q1?", "A", topic=1)
    _insert_fact(conn, "Q2?", "B", topic=2)
    _seed_card_state(conn, fid1)
    result = coverage(conn, chapters=[1])
    assert result["seen"] == 1
    assert result["total"] == 1
    assert result["pct_seen"] == 100.0


def test_coverage_chapter_filter_excludes_other_chapters(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid1 = _insert_fact(conn, "Q1?", "A", topic=1)
    _insert_fact(conn, "Q2?", "B", topic=2)
    _seed_card_state(conn, fid1)
    result = coverage(conn, chapters=[2])
    assert result["seen"] == 0
    assert result["total"] == 1
    assert result["pct_seen"] == 0.0


def test_coverage_chapter_filter_multiple_chapters(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid1 = _insert_fact(conn, "Q1?", "A", topic=1)
    _insert_fact(conn, "Q2?", "B", topic=2)
    _insert_fact(conn, "Q3?", "C", topic=3)
    _seed_card_state(conn, fid1)
    result = coverage(conn, chapters=[1, 2])
    assert result["seen"] == 1
    assert result["total"] == 2
    assert result["pct_seen"] == 50.0


def test_coverage_no_filter_matches_global(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid1 = _insert_fact(conn, "Q1?", "A", topic=1)
    _insert_fact(conn, "Q2?", "B", topic=2)
    _seed_card_state(conn, fid1)
    result = coverage(conn, chapters=None)
    assert result["seen"] == 1
    assert result["total"] == 2
    assert result["pct_seen"] == 50.0


# ---------------------------------------------------------------------------
# streak
# ---------------------------------------------------------------------------

def test_streak_zero_when_no_reviews(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    assert streak(conn, TODAY) == 0


def test_streak_one_on_review_today(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A")
    qid = _insert_question(conn, fid, 1, 1)
    _insert_review(conn, fid, qid, correct=True,
                   reviewed_at=TODAY.isoformat() + "T10:00:00+00:00")
    assert streak(conn, TODAY) == 1


def test_streak_consecutive_days(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A")
    qid = _insert_question(conn, fid, 1, 1)
    for i in range(3):
        d = TODAY - timedelta(days=i)
        _insert_review(conn, fid, qid, correct=True,
                       reviewed_at=d.isoformat() + "T10:00:00+00:00")
    assert streak(conn, TODAY) == 3


def test_streak_breaks_on_gap(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A")
    qid = _insert_question(conn, fid, 1, 1)
    # reviewed today and 3 days ago, gap on days 1 and 2
    for offset in (0, 3):
        d = TODAY - timedelta(days=offset)
        _insert_review(conn, fid, qid, correct=True,
                       reviewed_at=d.isoformat() + "T10:00:00+00:00")
    assert streak(conn, TODAY) == 1


def test_streak_zero_when_only_old_reviews(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A")
    qid = _insert_question(conn, fid, 1, 1)
    _insert_review(conn, fid, qid, correct=True,
                   reviewed_at="2026-01-01T10:00:00+00:00")
    assert streak(conn, TODAY) == 0


# ---------------------------------------------------------------------------
# due_today
# ---------------------------------------------------------------------------

def test_due_today_counts_overdue_and_today(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid1 = _insert_fact(conn, "Q1?", "A")
    fid2 = _insert_fact(conn, "Q2?", "A")
    fid3 = _insert_fact(conn, "Q3?", "A")
    _seed_card_state(conn, fid1, due=TODAY)
    _seed_card_state(conn, fid2, due=TODAY - timedelta(days=1))
    _seed_card_state(conn, fid3, due=TODAY + timedelta(days=1))
    assert due_today(conn, TODAY) == 2


def test_due_today_zero_when_no_cards(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    assert due_today(conn, TODAY) == 0


# ---------------------------------------------------------------------------
# missed_reviews
# ---------------------------------------------------------------------------

def test_missed_reviews_returns_only_incorrect(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A")
    qid = _insert_question(conn, fid, 1, 1)
    _insert_review(conn, fid, qid, correct=False)
    _insert_review(conn, fid, qid, correct=True)
    rows = missed_reviews(conn)
    assert len(rows) == 1
    assert rows[0]["fact_id"] == fid


def test_missed_reviews_includes_chapter_name(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid_tagged = _insert_fact(conn, "Q3?", "A", topic=3)
    fid_null = _insert_fact(conn, "Qnull?", "A")
    qid3 = _insert_question(conn, fid_tagged, 1, 1)
    qid_null = _insert_question(conn, fid_null, 1, 2)
    _insert_review(conn, fid_tagged, qid3, correct=False)
    _insert_review(conn, fid_null, qid_null, correct=False)
    rows = {r["fact_id"]: r for r in missed_reviews(conn)}
    assert rows[fid_tagged]["chapter_name"] is not None
    assert rows[fid_tagged]["topic_id"] == 3
    assert rows[fid_null]["chapter_name"] is None
    assert rows[fid_null]["topic_id"] is None


def test_missed_reviews_chapter_filter(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid3 = _insert_fact(conn, "Q3?", "A", topic=3)
    fid4 = _insert_fact(conn, "Q4?", "A", topic=4)
    qid3 = _insert_question(conn, fid3, 1, 1)
    qid4 = _insert_question(conn, fid4, 1, 2)
    _insert_review(conn, fid3, qid3, correct=False)
    _insert_review(conn, fid4, qid4, correct=False)
    rows = missed_reviews(conn, chapters=[3])
    assert all(r["fact_id"] == fid3 for r in rows)


def test_missed_reviews_since_filter(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A")
    qid = _insert_question(conn, fid, 1, 1)
    _insert_review(conn, fid, qid, correct=False,
                   reviewed_at="2026-04-01T10:00:00+00:00")
    _insert_review(conn, fid, qid, correct=False,
                   reviewed_at="2026-05-09T10:00:00+00:00")
    rows = missed_reviews(conn, since=date(2026, 5, 1))
    assert len(rows) == 1
    assert "2026-05-09" in rows[0]["reviewed_at"]


def test_missed_reviews_includes_miss_count(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    fid = _insert_fact(conn, "Q?", "A")
    qid = _insert_question(conn, fid, 1, 1)
    _insert_review(conn, fid, qid, correct=False)
    _insert_review(conn, fid, qid, correct=False)
    rows = missed_reviews(conn)
    assert rows[0]["miss_count"] == 2
