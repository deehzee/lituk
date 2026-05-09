import pytest

from lituk.db import get_or_create_fact, init_db


def test_init_db_creates_review_tables(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "card_state" in tables
    assert "pool_state" in tables
    assert "reviews" in tables
    conn.close()


def test_init_db_seeds_pool_state(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    rows = conn.execute(
        "SELECT pool, alpha, beta FROM pool_state ORDER BY pool"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["pool"] == "due"
    assert rows[0]["alpha"] == 1.0
    assert rows[0]["beta"] == 1.0
    assert rows[1]["pool"] == "new"
    assert rows[1]["alpha"] == 1.0
    assert rows[1]["beta"] == 1.0
    conn.close()


def test_init_db_pool_state_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = init_db(db_path)
    count = conn.execute("SELECT COUNT(*) FROM pool_state").fetchone()[0]
    assert count == 2
    conn.close()


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


def test_init_db_creates_chapters_table(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "chapters" in tables
    conn.close()


def test_init_db_seeds_chapters(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    rows = conn.execute(
        "SELECT id, name FROM chapters ORDER BY id"
    ).fetchall()
    assert len(rows) == 5
    assert rows[0]["id"] == 1
    assert rows[0]["name"] == "Values and Principles of the UK"
    assert rows[4]["id"] == 5
    assert rows[4]["name"] == "The UK Government, the Law and Your Role"
    conn.close()


def test_init_db_chapters_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = init_db(db_path)
    count = conn.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
    assert count == 5
    conn.close()


def test_facts_topic_column_accepts_null(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    fid = get_or_create_fact(conn, "Q?", "A")
    row = conn.execute("SELECT topic FROM facts WHERE id=?", (fid,)).fetchone()
    assert row["topic"] is None
    conn.close()


def test_facts_topic_column_accepts_valid_chapter(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    fid = get_or_create_fact(conn, "Q?", "A")
    conn.execute("UPDATE facts SET topic=3 WHERE id=?", (fid,))
    conn.commit()
    row = conn.execute("SELECT topic FROM facts WHERE id=?", (fid,)).fetchone()
    assert row["topic"] == 3
    conn.close()


def test_facts_topic_fk_rejects_invalid_chapter(tmp_path):
    import sqlite3 as _sqlite3
    conn = init_db(str(tmp_path / "test.db"))
    conn.execute("PRAGMA foreign_keys = ON")
    fid = get_or_create_fact(conn, "Q?", "A")
    with pytest.raises(_sqlite3.IntegrityError):
        conn.execute("UPDATE facts SET topic=99 WHERE id=?", (fid,))
        conn.commit()
    conn.close()
