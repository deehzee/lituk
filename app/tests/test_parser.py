import json
import unittest.mock as mock

import pytest

from tests.conftest import PDF_TEST_1

from lituk.ingest.parser import (
    clean_text,
    extract_raw,
    parse_answers_block,
    parse_pdf,
    parse_questions_block,
)


def test_extract_raw_returns_string():
    text = extract_raw(str(PDF_TEST_1))
    assert isinstance(text, str)
    assert len(text) > 100


def test_extract_raw_contains_answers_marker():
    text = extract_raw(str(PDF_TEST_1))
    assert "\nAnswers\n" in text


def test_clean_text_strips_urls():
    dirty = "Some text https://britizen.uk/practice/1 more"
    assert "https://" not in clean_text(dirty)


def test_clean_text_strips_page_title():
    dirty = (
        "Some choice text\n"
        "Life in the UK Test - Practice Test #1 of 45 [Updated for 2026]\n"
        "more text"
    )
    result = clean_text(dirty)
    assert "Practice Test" not in result


def test_clean_text_strips_dates():
    dirty = "02/05/2026, 18:11\nSome content"
    assert "02/05/2026" not in clean_text(dirty)


def test_clean_text_strips_page_numbers():
    dirty = "line one\n1/13\nline two\n2/13\nline three"
    result = clean_text(dirty)
    assert "1/13" not in result
    assert "2/13" not in result


_SAMPLE_Q_BLOCK = """
1. What is known as Lent?
A.
The 40 days before Easter
B.
The 40 days after Christmas
C.
The 40 days before Christmas
D.
The 40 days after Easter

2. One TV licence covers all equipment at one address, but people who rent
different rooms in a shared house must buy a separate TV licence
A.
False
B.
True

3. Who can nominate life peers? (Select TWO)
A.
The Prime Minister
B.
The Monarchy
C.
The Speaker
D.
Leaders of other main political parties
"""


def test_parse_questions_block_count():
    qs = parse_questions_block(_SAMPLE_Q_BLOCK)
    assert len(qs) == 3


def test_parse_questions_block_text():
    qs = parse_questions_block(_SAMPLE_Q_BLOCK)
    assert qs[0]["question_text"] == "What is known as Lent?"


def test_parse_questions_block_choices():
    qs = parse_questions_block(_SAMPLE_Q_BLOCK)
    assert qs[0]["choices"] == [
        "The 40 days before Easter",
        "The 40 days after Christmas",
        "The 40 days before Christmas",
        "The 40 days after Easter",
    ]
    assert qs[0]["choice_letters"] == ["A", "B", "C", "D"]


def test_parse_questions_block_true_false():
    qs = parse_questions_block(_SAMPLE_Q_BLOCK)
    assert qs[1]["is_true_false"] is True
    assert qs[1]["is_multi"] is False


def test_parse_questions_block_multi():
    qs = parse_questions_block(_SAMPLE_Q_BLOCK)
    assert qs[2]["is_multi"] is True
    assert qs[2]["is_true_false"] is False


def test_parse_questions_block_no_choices():
    block = """
1. What is this question?

2. Another question?"""
    qs = parse_questions_block(block)
    assert len(qs) == 2
    assert qs[0]["question_text"] == "What is this question?"
    assert qs[0]["choices"] == []
    assert qs[0]["choice_letters"] == []


_SAMPLE_A_BLOCK = """
1.
A - The 40 days before Easter
The 40 days before Easter are known as Lent.

2.
B - True
One TV licence covers all equipment at one address.

3.
A - The Prime Minister
D - Leaders of other main political parties
Since 1958, the Prime Minister has had the power to nominate peers.
"""


def test_parse_answers_block_count():
    answers = parse_answers_block(_SAMPLE_A_BLOCK)
    assert len(answers) == 3


def test_parse_answers_block_single_correct():
    answers = parse_answers_block(_SAMPLE_A_BLOCK)
    assert answers[0]["q_number"] == 1
    assert answers[0]["correct_letters"] == ["A"]
    assert "Lent" in answers[0]["explanation"]


def test_parse_answers_block_multi_correct():
    answers = parse_answers_block(_SAMPLE_A_BLOCK)
    assert answers[2]["correct_letters"] == ["A", "D"]


def test_parse_answers_block_explanation_excludes_answer_lines():
    answers = parse_answers_block(_SAMPLE_A_BLOCK)
    assert "A - The Prime Minister" not in answers[2]["explanation"]
    assert "Since 1958" in answers[2]["explanation"]


def test_parse_pdf_question_count():
    rows = parse_pdf(str(PDF_TEST_1), test_num=1)
    assert len(rows) == 24


def test_parse_pdf_first_question():
    rows = parse_pdf(str(PDF_TEST_1), test_num=1)
    q = rows[0]
    assert q["q_number"] == 1
    assert "Lent" in q["question_text"]
    assert q["correct_letters"] == ["A"]
    assert q["source_test"] == 1


def test_parse_pdf_true_false_question():
    rows = parse_pdf(str(PDF_TEST_1), test_num=1)
    q = next(r for r in rows if r["q_number"] == 12)
    assert q["is_true_false"] == 1


def test_parse_pdf_multi_answer_question():
    rows = parse_pdf(str(PDF_TEST_1), test_num=1)
    q = next(r for r in rows if r["q_number"] == 20)
    assert q["is_multi"] == 1
    assert len(q["correct_letters"]) == 2


def test_parse_pdf_choices_is_json_string():
    rows = parse_pdf(str(PDF_TEST_1), test_num=1)
    choices = json.loads(rows[0]["choices"])
    assert isinstance(choices, list)
    assert len(choices) == 4


def test_parse_pdf_raises_on_missing_answers_section(tmp_path):
    fake_pdf = tmp_path / "fake.pdf"
    # Create a minimal valid PDF with no Answers section
    # We can't easily create a real PDF, so patch extract_raw instead
    with mock.patch(
        "lituk.ingest.parser.extract_raw", return_value="No answers here"
    ):
        with pytest.raises(ValueError, match="No 'Answers' section"):
            parse_pdf("any_path.pdf", test_num=1)
