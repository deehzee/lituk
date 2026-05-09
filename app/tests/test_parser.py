from tests.conftest import PDF_TEST_1

from lituk.ingest.parser import clean_text, extract_raw


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
