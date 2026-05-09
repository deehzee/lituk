import sqlite3


_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    question_text       TEXT    NOT NULL,
    correct_answer_text TEXT    NOT NULL,
    UNIQUE (question_text, correct_answer_text)
);

CREATE TABLE IF NOT EXISTS questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_test     INTEGER NOT NULL,
    q_number        INTEGER NOT NULL,
    question_text   TEXT    NOT NULL,
    choices         TEXT    NOT NULL,
    correct_letters TEXT    NOT NULL,
    explanation     TEXT,
    is_true_false   INTEGER NOT NULL DEFAULT 0,
    is_multi        INTEGER NOT NULL DEFAULT 0,
    fact_id         INTEGER REFERENCES facts(id),
    UNIQUE (source_test, q_number)
);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def get_or_create_fact(
    conn: sqlite3.Connection,
    question_text: str,
    correct_answer_text: str,
) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO facts (question_text, correct_answer_text)"
        " VALUES (?, ?)",
        (question_text, correct_answer_text),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM facts WHERE question_text=? AND correct_answer_text=?",
        (question_text, correct_answer_text),
    ).fetchone()
    return row["id"]
