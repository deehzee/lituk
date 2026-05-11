import json
import random

import pytest

from lituk.db import init_db
from lituk.review.presenter import Prompt, build_prompt, grade_answer


def _insert_fact(conn, qtext, atext):
    conn.execute(
        "INSERT OR IGNORE INTO facts (question_text, correct_answer_text)"
        " VALUES (?, ?)",
        (qtext, atext),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM facts WHERE question_text=? AND correct_answer_text=?",
        (qtext, atext),
    ).fetchone()["id"]


def _insert_question(conn, fact_id, source_test, q_number, choices, correct_letters,
                     is_true_false=0, is_multi=0, explanation="Test explanation."):
    conn.execute(
        "INSERT INTO questions"
        " (source_test, q_number, question_text, choices, correct_letters,"
        "  explanation, is_true_false, is_multi, fact_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            source_test, q_number,
            "Question text",
            json.dumps(choices),
            json.dumps(correct_letters),
            explanation,
            is_true_false, is_multi, fact_id,
        ),
    )
    conn.commit()


@pytest.fixture
def conn(tmp_path):
    c = init_db(str(tmp_path / "test.db"))
    yield c
    c.close()


@pytest.fixture
def single_answer_fact(conn):
    choices = ["Paris", "London", "Berlin", "Madrid"]
    fid = _insert_fact(conn, "Capital of France?", "Paris")
    _insert_question(conn, fid, 1, 1, choices, ["A"])
    return fid


@pytest.fixture
def multi_answer_fact(conn):
    choices = ["Red", "Blue", "Green", "Yellow"]
    fid = _insert_fact(conn, "Which TWO are primary colours?", "Red and Blue")
    _insert_question(conn, fid, 1, 2, choices, ["A", "B"], is_multi=1)
    return fid


@pytest.fixture
def true_false_fact(conn):
    choices = ["True", "False"]
    fid = _insert_fact(conn, "Is the sky blue?", "True")
    _insert_question(conn, fid, 1, 3, choices, ["A"], is_true_false=1)
    return fid


# --- build_prompt ---

def test_build_prompt_returns_prompt_type(conn, single_answer_fact):
    rng = random.Random(0)
    prompt = build_prompt(conn, single_answer_fact, rng)
    assert isinstance(prompt, Prompt)


def test_build_prompt_has_all_choices(conn, single_answer_fact):
    rng = random.Random(0)
    prompt = build_prompt(conn, single_answer_fact, rng)
    assert len(prompt.choices) == 4
    assert set(prompt.choices) == {"Paris", "London", "Berlin", "Madrid"}


def test_build_prompt_correct_index_points_to_paris(conn, single_answer_fact):
    rng = random.Random(0)
    prompt = build_prompt(conn, single_answer_fact, rng)
    assert len(prompt.correct_indices) == 1
    assert prompt.choices[prompt.correct_indices[0]] == "Paris"


def test_build_prompt_shuffles_choices(conn, single_answer_fact):
    original = ["Paris", "London", "Berlin", "Madrid"]
    orders = set()
    for seed in range(20):
        rng = random.Random(seed)
        prompt = build_prompt(conn, single_answer_fact, rng)
        orders.add(tuple(prompt.choices))
    assert len(orders) > 1, "choices should be shuffled differently across seeds"


def test_build_prompt_multi_answer(conn, multi_answer_fact):
    rng = random.Random(1)
    prompt = build_prompt(conn, multi_answer_fact, rng)
    assert prompt.is_multi is True
    assert len(prompt.correct_indices) == 2
    correct_texts = {prompt.choices[i] for i in prompt.correct_indices}
    assert correct_texts == {"Red", "Blue"}


def test_build_prompt_true_false(conn, true_false_fact):
    rng = random.Random(2)
    prompt = build_prompt(conn, true_false_fact, rng)
    assert prompt.is_true_false is True
    assert len(prompt.choices) == 2
    assert prompt.choices[prompt.correct_indices[0]] == "True"


def test_build_prompt_picks_random_row_when_multiple(conn):
    choices_a = ["A1", "A2", "A3", "A4"]
    choices_b = ["B1", "B2", "B3", "B4"]
    fid = _insert_fact(conn, "Multi-test question?", "A1")
    _insert_question(conn, fid, 1, 1, choices_a, ["A"])
    _insert_question(conn, fid, 2, 1, choices_b, ["A"])
    seen = set()
    for seed in range(30):
        rng = random.Random(seed)
        prompt = build_prompt(conn, fid, rng)
        seen.add(frozenset(prompt.choices))
    assert len(seen) == 2, "should use both rows across different seeds"


# --- grade_answer ---

def test_grade_answer_correct_single(conn, single_answer_fact):
    rng = random.Random(0)
    prompt = build_prompt(conn, single_answer_fact, rng)
    assert grade_answer(prompt, prompt.correct_indices) is True


def test_grade_answer_wrong_single(conn, single_answer_fact):
    rng = random.Random(0)
    prompt = build_prompt(conn, single_answer_fact, rng)
    wrong = [i for i in range(len(prompt.choices))
             if i not in prompt.correct_indices]
    assert grade_answer(prompt, wrong[:1]) is False


def test_grade_answer_order_independent_multi(conn, multi_answer_fact):
    rng = random.Random(1)
    prompt = build_prompt(conn, multi_answer_fact, rng)
    reversed_indices = list(reversed(prompt.correct_indices))
    assert grade_answer(prompt, reversed_indices) is True


def test_grade_answer_partial_multi_is_wrong(conn, multi_answer_fact):
    rng = random.Random(1)
    prompt = build_prompt(conn, multi_answer_fact, rng)
    assert grade_answer(prompt, prompt.correct_indices[:1]) is False


def test_build_prompt_has_explanation(conn, single_answer_fact):
    rng = random.Random(0)
    prompt = build_prompt(conn, single_answer_fact, rng)
    assert prompt.explanation == "Test explanation."
