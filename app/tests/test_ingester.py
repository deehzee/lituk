import json
import runpy
import sqlite3
from io import StringIO
from unittest.mock import patch

from lituk.db import init_db
from lituk.ingest import main as ingest_main
from lituk.ingest.ingester import ingest_all, ingest_pdf
from tests.conftest import MOCK_TESTS_DIR, PDF_TEST_1


def test_ingest_pdf_row_count(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    count = ingest_pdf(conn, str(PDF_TEST_1), test_num=1)
    assert count == 24


def test_ingest_pdf_questions_in_db(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    ingest_pdf(conn, str(PDF_TEST_1), test_num=1)
    rows = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    assert rows == 24


def test_ingest_pdf_facts_in_db(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    ingest_pdf(conn, str(PDF_TEST_1), test_num=1)
    rows = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    assert rows == 24


def test_ingest_pdf_fact_id_set(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    ingest_pdf(conn, str(PDF_TEST_1), test_num=1)
    null_facts = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE fact_id IS NULL"
    ).fetchone()[0]
    assert null_facts == 0


def test_ingest_pdf_idempotent(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    ingest_pdf(conn, str(PDF_TEST_1), test_num=1)
    ingest_pdf(conn, str(PDF_TEST_1), test_num=1)
    rows = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    assert rows == 24


def test_ingest_pdf_choices_valid_json(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    ingest_pdf(conn, str(PDF_TEST_1), test_num=1)
    row = conn.execute(
        "SELECT choices FROM questions WHERE q_number=1"
    ).fetchone()
    choices = json.loads(row["choices"])
    assert isinstance(choices, list)
    assert len(choices) == 4


def test_ingest_all_question_count(tmp_path):
    db_path = str(tmp_path / "lituk.db")
    ingest_all(db_path, str(MOCK_TESTS_DIR))
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    assert count == 45 * 24


def test_ingest_all_facts_deduplicated(tmp_path):
    db_path = str(tmp_path / "lituk.db")
    ingest_all(db_path, str(MOCK_TESTS_DIR))
    conn = sqlite3.connect(db_path)
    facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    conn.close()
    assert 1000 < facts < 45 * 24


def test_ingest_all_skips_non_matching_files(tmp_path):
    fake = tmp_path / "not_a_test.pdf"
    fake.write_bytes(b"")
    db_path = str(tmp_path / "lituk.db")
    ingest_all(db_path, str(tmp_path))
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    assert count == 0


def test_ingest_main_cli(tmp_path):
    db_path = str(tmp_path / "lituk.db")
    with patch("sys.argv", ["lituk-ingest", "--db", db_path,
                             "--dir", str(MOCK_TESTS_DIR)]), \
         patch("lituk.ingest.ingest_all") as mock_ingest, \
         patch("sys.stdout", new_callable=StringIO):
        ingest_main()
    mock_ingest.assert_called_once_with(db_path, str(MOCK_TESTS_DIR))


def test_ingest_main_module_calls_main():
    with patch("lituk.ingest.main") as mock_main:
        runpy.run_module("lituk.ingest", run_name="__main__")
    mock_main.assert_called_once_with()
