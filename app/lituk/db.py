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

CREATE TABLE IF NOT EXISTS card_state (
    fact_id          INTEGER PRIMARY KEY REFERENCES facts(id),
    ease_factor      REAL    NOT NULL DEFAULT 2.5,
    interval_days    INTEGER NOT NULL DEFAULT 0,
    repetitions      INTEGER NOT NULL DEFAULT 0,
    due_date         TEXT    NOT NULL,
    last_reviewed_at TEXT,
    lapses           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_card_state_due ON card_state(due_date);

CREATE TABLE IF NOT EXISTS pool_state (
    pool  TEXT PRIMARY KEY,
    alpha REAL NOT NULL DEFAULT 1.0,
    beta  REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS reviews (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id        INTEGER NOT NULL REFERENCES facts(id),
    question_id    INTEGER NOT NULL REFERENCES questions(id),
    reviewed_at    TEXT    NOT NULL,
    grade          INTEGER NOT NULL,
    correct        INTEGER NOT NULL,
    pool           TEXT    NOT NULL,
    ease_after     REAL    NOT NULL,
    interval_after INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_fact ON reviews(fact_id);
"""

_POOL_SEED = """
INSERT OR IGNORE INTO pool_state (pool, alpha, beta) VALUES ('due', 1.0, 1.0);
INSERT OR IGNORE INTO pool_state (pool, alpha, beta) VALUES ('new', 1.0, 1.0);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.executescript(_POOL_SEED)
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
