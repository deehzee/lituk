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
                               is_multi=0, is_true_false=0):
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
# main() integration
# ---------------------------------------------------------------------------

def test_main_exits_zero_on_empty_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path).close()
    with patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--size", "5"])
    assert exc.value.code == 0


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
        def betavariate(self, a, b):
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
