import json
import random
import runpy
from io import StringIO
from unittest.mock import patch

import pytest

from lituk.db import init_db
from lituk.review import main
from lituk.review.cli import TerminalUI, _parse_answer
from lituk.review.presenter import Prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_fact_and_question(conn, q_text="Q?", a_text="Correct",
                               source_test=1, q_num=1,
                               choices=None, correct_letters=None,
                               is_multi=0, is_true_false=0, topic=None):
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


def _known_prompt(correct_at=0) -> Prompt:
    choices = ["Correct", "Wrong1", "Wrong2", "Wrong3"]
    order = [correct_at] + [i for i in range(4) if i != correct_at]
    shuffled = [choices[i] for i in order]
    return Prompt(
        fact_id=1, question_id=1, text="Q?",
        choices=shuffled,
        correct_indices=[0],  # after shuffle, correct is always first
        is_multi=False,
        is_true_false=False,
    )


# ---------------------------------------------------------------------------
# _parse_answer
# ---------------------------------------------------------------------------

def test_parse_answer_single_letter():
    assert _parse_answer("A", 4) == [0]


def test_parse_answer_case_insensitive():
    assert _parse_answer("b", 4) == [1]


def test_parse_answer_multi_comma():
    assert _parse_answer("A,C", 4) == [0, 2]


def test_parse_answer_out_of_range_ignored():
    assert _parse_answer("E", 4) == []


def test_parse_answer_deduplicates():
    assert _parse_answer("A A", 4) == [0]


# ---------------------------------------------------------------------------
# TerminalUI.show_prompt
# ---------------------------------------------------------------------------

def test_show_prompt_returns_valid_indices():
    ui = TerminalUI()
    prompt = _known_prompt()
    with patch("builtins.input", return_value="A"), \
         patch("sys.stdout", new_callable=StringIO):
        result = ui.show_prompt(prompt)
    assert result == [0]


def test_show_prompt_multi_hint_shown():
    ui = TerminalUI()
    prompt = Prompt(
        fact_id=1, question_id=1, text="Which TWO?",
        choices=["Red", "Blue", "Green", "Yellow"],
        correct_indices=[0, 1],
        is_multi=True, is_true_false=False,
    )
    with patch("builtins.input", return_value="A,B"), \
         patch("sys.stdout", new_callable=StringIO) as out:
        result = ui.show_prompt(prompt)
    assert result == [0, 1]
    assert "TWO" in out.getvalue()


def test_show_prompt_retries_on_invalid_input():
    ui = TerminalUI()
    prompt = _known_prompt()
    # "X" is out-of-range for 4 choices; "A" is valid
    inputs = iter(["X", "A"])
    with patch("builtins.input", side_effect=inputs), \
         patch("sys.stdout", new_callable=StringIO) as out:
        result = ui.show_prompt(prompt)
    assert result == [0]
    assert "Invalid" in out.getvalue()


# ---------------------------------------------------------------------------
# TerminalUI.show_feedback
# ---------------------------------------------------------------------------

def test_show_feedback_correct_returns_grade():
    ui = TerminalUI()
    prompt = _known_prompt()
    with patch("builtins.input", return_value="g"), \
         patch("sys.stdout", new_callable=StringIO):
        grade = ui.show_feedback(prompt, True)
    assert grade == 4


def test_show_feedback_wrong_prints_answer_returns_zero():
    ui = TerminalUI()
    prompt = _known_prompt(correct_at=0)
    with patch("sys.stdout", new_callable=StringIO) as out:
        grade = ui.show_feedback(prompt, False)
    assert grade == 0
    assert "Wrong" in out.getvalue()
    assert "Correct" in out.getvalue()  # the correct answer text


def test_show_feedback_retries_on_invalid_grade():
    ui = TerminalUI()
    prompt = _known_prompt()
    inputs = iter(["x", "g"])  # "x" not in grade map; "g" is Good
    with patch("builtins.input", side_effect=inputs), \
         patch("sys.stdout", new_callable=StringIO) as out:
        grade = ui.show_feedback(prompt, True)
    assert grade == 4
    assert "Enter" in out.getvalue()


# ---------------------------------------------------------------------------
# TerminalUI.show_summary
# ---------------------------------------------------------------------------

def test_show_summary_prints_score():
    from lituk.review.session import SessionResult
    ui = TerminalUI()
    result = SessionResult(correct=19, total=24, weak_facts=[])
    with patch("sys.stdout", new_callable=StringIO) as out:
        ui.show_summary(result)
    assert "19/24" in out.getvalue()


def test_show_summary_prints_weak_count():
    from lituk.review.session import SessionResult
    ui = TerminalUI()
    result = SessionResult(correct=18, total=24, weak_facts=[1, 2, 3])
    with patch("sys.stdout", new_callable=StringIO) as out:
        ui.show_summary(result)
    assert "3" in out.getvalue()


# ---------------------------------------------------------------------------
# TerminalUI.show_reasoning
# ---------------------------------------------------------------------------

def test_show_reasoning_prints_ansi_dim(capsys):
    ui = TerminalUI()
    ui.show_reasoning(
        "MAB: θ_due=0.72 → due | 8 due, 3 new | ease=2.10, overdue 3d"
    )
    captured = capsys.readouterr()
    assert "\033[2m" in captured.out
    assert "MAB:" in captured.out
    assert "\033[0m" in captured.out


def test_show_reasoning_includes_text_content(capsys):
    ui = TerminalUI()
    ui.show_reasoning("Lapsed: failed this session | lapses=2, last seen 1d ago")
    captured = capsys.readouterr()
    assert "Lapsed" in captured.out
    assert "lapses=2" in captured.out


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------

def test_main_exits_nonzero_on_empty_db(tmp_path):
    """An empty DB (no facts) should produce a helpful error, not silent 0/0."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path).close()
    with patch("sys.stdout", new_callable=StringIO), \
         patch("sys.stderr", new_callable=StringIO) as err:
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--size", "5"])
    assert exc.value.code != 0
    assert "ingest" in err.getvalue().lower()


def test_main_writes_review_row(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn)
    conn.close()

    # Use seed 0 — with this seed the presenter may put "Correct" anywhere.
    # Always provide "A" as answer; correct or not, exit code must be 0.
    # If correct: consumes grade "g". If wrong: no grade consumed.
    # Provide enough inputs for the worst case (up to size=1 + lapsed re-show
    # of size=1 would still end because size=1 total).
    rng = random.Random(0)
    inputs = iter(["A", "g"])
    with patch("builtins.input", side_effect=inputs), \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--size", "1"], _rng=rng)
    assert exc.value.code == 0

    conn = init_db(db_path)
    count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    conn.close()
    assert count >= 1


def test_main_wrong_then_correct(tmp_path):
    """Lapsed-in-session card comes back within a 3-card session."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    # choices=[A_correct, B_wrong, C_wrong, D_wrong]; use seed that keeps
    # "Correct" at index 0 so we can deterministically input "B" (wrong)
    # then "A" (correct).
    _insert_fact_and_question(conn)
    conn.close()

    # Seed 1 is chosen because with this seed and 4 choices, the first shuffle
    # may or may not put Correct at index 0. We control via rng parameter.
    # Instead of relying on specific seed behaviour, inject a mock RNG whose
    # shuffle() is a no-op so choices stay in original order (Correct = A).
    class FixedRNG(random.Random):
        def shuffle(self, x):
            pass  # no shuffle — Correct stays at index 0 (letter A)
        def choice(self, seq):
            return seq[0]
        def betavariate(self, alpha, beta):  # type: ignore[override]
            return 0.5

    rng = FixedRNG()
    # slot 1: "B" wrong (Correct is at A) → lapsed
    # slot 2: lapsed re-shown, "A" correct → grade "g"
    # slot 3: nothing left (1 fact, in card_state, due tomorrow) → end
    inputs = iter(["B", "A", "g"])
    with patch("builtins.input", side_effect=inputs), \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--size", "3"], _rng=rng)
    assert exc.value.code == 0

    conn = init_db(db_path)
    count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    conn.close()
    assert count == 2  # one wrong + one correct


# ---------------------------------------------------------------------------
# __main__ module entry point
# ---------------------------------------------------------------------------

def test_review_main_module_calls_main(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path).close()
    with patch("lituk.review.main") as mock_main:
        runpy.run_module("lituk.review", run_name="__main__")
    mock_main.assert_called_once_with()


def test_parse_topics_rejects_non_integer(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path).close()
    with patch("sys.stderr", new_callable=StringIO):
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--topic", "abc"])


def test_parse_topics_rejects_out_of_range(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path).close()
    with patch("sys.stderr", new_callable=StringIO):
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--topic", "6"])


def test_main_topic_flag_accepted(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn, topic=3)
    conn.close()

    rng = random.Random(0)
    inputs = iter(["A", "g"])
    with patch("builtins.input", side_effect=inputs), \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--size", "1", "--topic", "3"], _rng=rng)
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# --mode flag
# ---------------------------------------------------------------------------

def test_main_mode_drill_calls_run_drill_session(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    fid = _insert_fact_and_question(conn)
    conn.execute(
        "INSERT INTO card_state (fact_id, ease_factor, interval_days,"
        " repetitions, due_date, lapses) VALUES (?, 2.5, 1, 1, '2020-01-01', 1)",
        (fid,),
    )
    conn.commit()
    conn.close()
    with patch("lituk.review.run_drill_session") as mock_drill, \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--mode", "drill"])
    mock_drill.assert_called_once()


def test_main_mode_explore_calls_run_explore_session(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn)
    conn.close()
    with patch("lituk.review.run_explore_session") as mock_exp, \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--mode", "explore"])
    mock_exp.assert_called_once()


def test_main_mode_regular_calls_run_session(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn)
    conn.close()
    with patch("lituk.review.run_session") as mock_sess, \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--mode", "regular"])
    mock_sess.assert_called_once()


def test_main_default_mode_calls_run_session(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn)
    conn.close()
    with patch("lituk.review.run_session") as mock_sess, \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit):
            main(["--db", db_path])
    mock_sess.assert_called_once()


def test_main_invalid_mode_exits_two(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path).close()
    with patch("sys.stderr", new_callable=StringIO):
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--mode", "foo"])
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# --chapters alias
# ---------------------------------------------------------------------------

def test_main_chapters_flag_same_as_topic(tmp_path):
    """--chapters produces same topics list as --topic."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn, topic=1)
    conn.close()

    captured_kwargs: dict = {}

    def _capture_run_session(*args, **kwargs):
        captured_kwargs.update(kwargs)
        from lituk.review.session import SessionResult
        return SessionResult(correct=0, total=0, weak_facts=[])

    with patch("lituk.review.run_session", side_effect=_capture_run_session), \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--chapters", "1,3"])

    assert captured_kwargs.get("topics") == [1, 3]


def test_main_topic_flag_still_works_after_alias(tmp_path):
    """--topic still works (alias, not replacement)."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn, topic=2)
    conn.close()

    captured_kwargs: dict = {}

    def _capture_run_session(*args, **kwargs):
        captured_kwargs.update(kwargs)
        from lituk.review.session import SessionResult
        return SessionResult(correct=0, total=0, weak_facts=[])

    with patch("lituk.review.run_session", side_effect=_capture_run_session), \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--topic", "2"])

    assert captured_kwargs.get("topics") == [2]


# ---------------------------------------------------------------------------
# Pre-session banner
# ---------------------------------------------------------------------------

def test_banner_regular_mode(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn)
    conn.close()
    with patch("lituk.review.run_session"), \
         patch("sys.stdout", new_callable=StringIO) as out:
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--mode", "regular"])
    text = out.getvalue()
    assert "Regular mode" in text
    assert "due today" in text


def test_banner_drill_mode(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    fid = _insert_fact_and_question(conn)
    conn.execute(
        "INSERT INTO card_state (fact_id, ease_factor, interval_days,"
        " repetitions, due_date, lapses) VALUES (?, 2.5, 1, 1, '2020-01-01', 1)",
        (fid,),
    )
    conn.commit()
    conn.close()
    with patch("lituk.review.run_drill_session"), \
         patch("sys.stdout", new_callable=StringIO) as out:
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--mode", "drill"])
    text = out.getvalue()
    assert "Drill mode" in text
    assert "missed facts" in text


def test_banner_explore_mode(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn)
    conn.close()
    with patch("lituk.review.run_explore_session"), \
         patch("sys.stdout", new_callable=StringIO) as out:
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--mode", "explore"])
    text = out.getvalue()
    assert "Explore mode" in text
    assert "unseen" in text


# ---------------------------------------------------------------------------
# --dry-run flag
# ---------------------------------------------------------------------------

def test_dry_run_no_writes_to_disk(tmp_path):
    """After a dry-run session, the on-disk DB still has zero review rows."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn)
    conn.close()

    class FixedRNG(random.Random):
        def shuffle(self, x):
            pass
        def choice(self, seq):
            return seq[0]
        def betavariate(self, alpha, beta):  # type: ignore[override]
            return 0.5

    rng = FixedRNG()
    inputs = iter(["A", "g"])
    with patch("builtins.input", side_effect=inputs), \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--size", "1", "--dry-run"], _rng=rng)
    assert exc.value.code == 0

    # On-disk DB must still have zero reviews
    conn = init_db(db_path)
    count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    conn.close()
    assert count == 0


def test_dry_run_banner_contains_dry_run(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn)
    conn.close()
    with patch("lituk.review.run_session"), \
         patch("sys.stdout", new_callable=StringIO) as out:
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--dry-run"])
    text = out.getvalue()
    assert "dry run" in text


def test_dry_run_mode_drill_smoke(tmp_path):
    """--dry-run --mode drill runs without error when drill pool is non-empty."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    fid = _insert_fact_and_question(conn)
    conn.execute(
        "INSERT INTO card_state (fact_id, ease_factor, interval_days,"
        " repetitions, due_date, lapses) VALUES (?, 2.5, 1, 1, '2020-01-01', 1)",
        (fid,),
    )
    conn.commit()
    conn.close()
    with patch("lituk.review.run_drill_session"), \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--mode", "drill", "--dry-run"])
    assert exc.value.code == 0


def test_dry_run_mode_explore_smoke(tmp_path):
    """--dry-run --mode explore runs without error when unseen facts exist."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn)
    conn.close()
    with patch("lituk.review.run_explore_session"), \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--mode", "explore", "--dry-run"])
    assert exc.value.code == 0


def test_review_exits_nonzero_when_no_facts_regular(tmp_path):
    """Regular mode on an empty DB should error, not silently produce 0/0."""
    db_path = str(tmp_path / "empty.db")
    # init_db creates schema but no facts
    init_db(db_path).close()
    with patch("sys.stdout", new_callable=StringIO), \
         patch("sys.stderr", new_callable=StringIO) as err:
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path])
    assert exc.value.code != 0
    assert "ingest" in err.getvalue().lower()


def test_review_exits_nonzero_when_no_facts_explore(tmp_path):
    """Explore mode on an empty DB should error, not silently produce 0/0."""
    db_path = str(tmp_path / "empty.db")
    init_db(db_path).close()
    with patch("sys.stdout", new_callable=StringIO), \
         patch("sys.stderr", new_callable=StringIO) as err:
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--mode", "explore"])
    assert exc.value.code != 0
    assert "ingest" in err.getvalue().lower()


def test_review_dry_run_exits_nonzero_when_no_facts(tmp_path):
    """--dry-run on an empty DB should error — this is the exact reported bug."""
    db_path = str(tmp_path / "no_data.db")
    # Do NOT pre-initialise; main() must handle it via init_db in dry-run path
    with patch("sys.stdout", new_callable=StringIO), \
         patch("sys.stderr", new_callable=StringIO) as err:
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--dry-run"])
    assert exc.value.code != 0
    assert "ingest" in err.getvalue().lower()


def test_review_explore_exits_zero_when_all_facts_seen(tmp_path):
    """Explore mode with all facts already seen should exit 0 with a message."""
    db_path = str(tmp_path / "all_seen.db")
    conn = init_db(db_path)
    fid = _insert_fact_and_question(conn)
    # Mark the fact as seen (card_state row exists → unseen pool is empty)
    conn.execute(
        "INSERT INTO card_state (fact_id, ease_factor, interval_days,"
        " repetitions, due_date, lapses) VALUES (?, 2.5, 1, 1, '2099-01-01', 0)",
        (fid,),
    )
    conn.commit()
    conn.close()
    with patch("sys.stdout", new_callable=StringIO) as out:
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--mode", "explore"])
    assert exc.value.code == 0
    assert "explored" in out.getvalue().lower()


def test_review_exits_zero_with_message_when_no_drill_facts(tmp_path):
    """Drill mode with no lapses should exit 0 with a helpful info message."""
    db_path = str(tmp_path / "empty.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn)  # fact exists, but no lapses
    conn.close()
    with patch("sys.stdout", new_callable=StringIO) as out:
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--mode", "drill"])
    assert exc.value.code == 0
    assert "no missed" in out.getvalue().lower()


def test_dry_run_schema_initialised_on_fresh_db(tmp_path):
    """--dry-run calls init_db() so schema is created even on a brand-new file.

    Regression: the original code used bare sqlite3.connect() instead of
    init_db(), so the in-memory copy lacked card_state and the banner query
    raised OperationalError: no such table: card_state.
    """
    db_path = str(tmp_path / "brand_new.db")
    # No prior init_db. After main() runs (exits 1 because no facts), the
    # on-disk file must have the card_state table — proof that init_db() ran.
    with patch("sys.stdout", new_callable=StringIO), \
         patch("sys.stderr", new_callable=StringIO):
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--dry-run"])
    conn = init_db(db_path)
    conn.execute("SELECT COUNT(*) FROM card_state")  # raises if schema absent
    conn.close()


def test_dry_run_no_writes_mode_drill(tmp_path):
    """--dry-run --mode drill leaves the on-disk reviews table unchanged."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    fid = _insert_fact_and_question(conn)
    # Seed a lapse so the drill pool is non-empty
    conn.execute(
        "INSERT INTO card_state"
        " (fact_id, ease_factor, interval_days, repetitions, due_date, lapses)"
        " VALUES (?, 2.5, 1, 1, '2020-01-01', 1)",
        (fid,),
    )
    conn.commit()
    conn.close()

    class FixedRNG(random.Random):
        def shuffle(self, x):
            pass
        def choice(self, seq):
            return seq[0]
        def betavariate(self, alpha, beta):  # type: ignore[override]
            return 0.5

    inputs = iter(["A", "g"])
    with patch("builtins.input", side_effect=inputs), \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit) as exc:
            main(
                ["--db", db_path, "--mode", "drill", "--dry-run", "--size", "1"],
                _rng=FixedRNG(),
            )
    assert exc.value.code == 0
    conn = init_db(db_path)
    count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    conn.close()
    assert count == 0


def test_main_mode_drill_passes_chapters(tmp_path):
    """--mode drill passes --chapters to run_drill_session."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    fid = _insert_fact_and_question(conn, topic=1)
    conn.execute(
        "INSERT INTO card_state (fact_id, ease_factor, interval_days,"
        " repetitions, due_date, lapses) VALUES (?, 2.5, 1, 1, '2020-01-01', 1)",
        (fid,),
    )
    conn.commit()
    conn.close()
    captured: dict = {}

    def _capture(*args, **kwargs):
        captured.update(kwargs)
        from lituk.review.session import SessionResult
        return SessionResult(correct=0, total=0, weak_facts=[])

    with patch("lituk.review.run_drill_session", side_effect=_capture), \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--mode", "drill", "--chapters", "1,2"])
    assert captured.get("topics") == [1, 2]


def test_main_mode_explore_passes_chapters(tmp_path):
    """--mode explore passes --chapters to run_explore_session."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact_and_question(conn, topic=3)
    conn.close()
    captured: dict = {}

    def _capture(*args, **kwargs):
        captured.update(kwargs)
        from lituk.review.session import SessionResult
        return SessionResult(correct=0, total=0, weak_facts=[])

    with patch("lituk.review.run_explore_session", side_effect=_capture), \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit):
            main(["--db", db_path, "--mode", "explore", "--chapters", "3"])
    assert captured.get("topics") == [3]
