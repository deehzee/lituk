import json
import runpy
from datetime import date, datetime, timezone
from io import StringIO
from unittest.mock import patch

import pytest

from lituk.db import init_db
from lituk.stats import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_fact_and_question(
    conn, q_text="Q?", a_text="Correct",
    source_test=1, q_num=1,
    choices=None, correct_letters=None,
    is_multi=0, is_true_false=0, topic=None,
):
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
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (source_test, q_num, q_text, json.dumps(choices),
         json.dumps(correct_letters), is_true_false, is_multi, fid),
    )
    conn.commit()
    return fid


def _insert_review(conn, fact_id, question_id, correct=1, pool="due",
                   session_id=None, at=None):
    if at is None:
        at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO reviews"
        " (fact_id, question_id, reviewed_at, grade, correct, pool,"
        "  ease_after, interval_after, session_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fact_id, question_id, at, 4, correct, pool, 2.5, 1, session_id),
    )
    conn.commit()


def _insert_card_state(conn, fact_id, lapses=0, due_date=None):
    if due_date is None:
        due_date = date.today().isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO card_state"
        " (fact_id, ease_factor, interval_days, repetitions,"
        "  due_date, last_reviewed_at, lapses)"
        " VALUES (?, 2.5, 1, 1, ?, ?, ?)",
        (fact_id, due_date, datetime.now(timezone.utc).isoformat(), lapses),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Basic output
# ---------------------------------------------------------------------------

def test_main_basic_output(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path).close()
    with patch("sys.stdout", new_callable=StringIO) as out:
        main(["--db", db_path])
    text = out.getvalue()
    assert "Coverage:" in text
    assert "Streak:" in text
    assert "Due today:" in text


def test_main_empty_db_no_section_headers(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path).close()
    with patch("sys.stdout", new_callable=StringIO) as out:
        main(["--db", db_path])
    text = out.getvalue()
    # No facts → by_chapter returns rows (chapters always seeded) but with
    # 0 total — actually by_chapter always returns 5 rows.
    # Recent sessions and Weak facts are absent for empty DB.
    assert "Recent sessions:" not in text
    assert "Weak facts:" not in text


def test_main_with_chapter_data_shows_by_chapter(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn, topic=3)
    conn.close()

    with patch("sys.stdout", new_callable=StringIO) as out:
        main(["--db", db_path])
    text = out.getvalue()
    assert "By chapter:" in text
    assert "History" in text  # chapter 3 name contains "History"


def test_main_with_recent_session_shows_section(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    fid = _insert_fact_and_question(conn)
    qid = conn.execute("SELECT id FROM questions WHERE fact_id=?", (fid,)
                       ).fetchone()["id"]
    _insert_review(conn, fid, qid, correct=1, session_id="sess-001")
    conn.close()

    with patch("sys.stdout", new_callable=StringIO) as out:
        main(["--db", db_path])
    text = out.getvalue()
    assert "Recent sessions:" in text
    assert "sess" in text or "/" in text  # date or score present


def test_main_with_weak_fact_shows_section(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    fid = _insert_fact_and_question(conn, q_text="Hard question?")
    _insert_card_state(conn, fid, lapses=3)
    conn.close()

    with patch("sys.stdout", new_callable=StringIO) as out:
        main(["--db", db_path])
    text = out.getvalue()
    assert "Weak facts:" in text
    assert "Hard question" in text
    assert "3 lapses" in text


def test_main_weak_fact_single_lapse_grammar(tmp_path):
    """1 lapse → singular 'lapse', not 'lapses'."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    fid = _insert_fact_and_question(conn)
    _insert_card_state(conn, fid, lapses=1)
    conn.close()

    with patch("sys.stdout", new_callable=StringIO) as out:
        main(["--db", db_path])
    text = out.getvalue()
    assert "1 lapse)" in text


def test_main_long_question_text_truncated(tmp_path):
    """Question text longer than 60 chars is truncated with ellipsis."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    long_q = "A" * 70 + "?"
    fid = _insert_fact_and_question(conn, q_text=long_q)
    _insert_card_state(conn, fid, lapses=2)
    conn.close()

    with patch("sys.stdout", new_callable=StringIO) as out:
        main(["--db", db_path])
    text = out.getvalue()
    assert "…" in text
    # Full text should NOT appear
    assert long_q not in text


def test_main_streak_singular(tmp_path):
    """Streak of 1 → 'day' not 'days'."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    fid = _insert_fact_and_question(conn)
    qid = conn.execute("SELECT id FROM questions WHERE fact_id=?", (fid,)
                       ).fetchone()["id"]
    today_iso = date.today().isoformat() + "T12:00:00+00:00"
    _insert_review(conn, fid, qid, at=today_iso)
    conn.close()

    with patch("sys.stdout", new_callable=StringIO) as out:
        main(["--db", db_path])
    text = out.getvalue()
    assert "1 day\n" in text or "1 day " in text


def test_main_due_today_singular(tmp_path):
    """Exactly 1 due card → 'card' not 'cards'."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    fid = _insert_fact_and_question(conn)
    _insert_card_state(conn, fid, due_date=date.today().isoformat())
    conn.close()

    with patch("sys.stdout", new_callable=StringIO) as out:
        main(["--db", db_path])
    text = out.getvalue()
    assert "1 card\n" in text or "1 card " in text


# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------

def test_main_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# __main__ shim
# ---------------------------------------------------------------------------

def test_stats_main_module_callable():
    with patch("lituk.stats.main") as mock_main:
        runpy.run_module("lituk.stats", run_name="__main__")
    mock_main.assert_called_once_with()
