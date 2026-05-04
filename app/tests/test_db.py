import sqlite3

from lituk.db import get_or_create_fact, init_db


def test_init_db_creates_tables(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "questions" in tables
    assert "facts" in tables
    conn.close()


def test_get_or_create_fact_inserts(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    fid = get_or_create_fact(conn, "What colour is the sky?", "Blue")
    assert isinstance(fid, int)
    row = conn.execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone()
    assert row is not None


def test_get_or_create_fact_idempotent(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    fid1 = get_or_create_fact(conn, "What colour is the sky?", "Blue")
    fid2 = get_or_create_fact(conn, "What colour is the sky?", "Blue")
    assert fid1 == fid2
    count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    assert count == 1
