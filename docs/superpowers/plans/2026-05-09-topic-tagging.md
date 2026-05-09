# Topic Tagging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add chapter-level topic tags to facts so the user can filter review
sessions by chapter (1–5) using `--topic N[,N]`.

**Architecture:** Three independent commits: (1) schema — add `chapters` table
and `topic` column to `facts`; (2) session filter — `_due_pool`/`_new_pool`
gain an optional `topics` param, wired up via `--topic` CLI flag; (3) tagger —
new `lituk-tag` CLI that uses Claude Haiku to classify untagged facts in
batches of 50, reading chapter summaries as context.

**Tech Stack:** Python 3.12, SQLite (via stdlib `sqlite3`), `anthropic` SDK
(Claude Haiku `claude-haiku-4-5-20251001`), `pytest` + `unittest.mock`.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/lituk/db.py` | Modify | Add `chapters` table + seed; add `topic` column to `facts` |
| `app/lituk/review/session.py` | Modify | `_due_pool`/`_new_pool` accept `topics`; pass through `run_session` |
| `app/lituk/review/__init__.py` | Modify | Add `--topic` argparse flag |
| `app/lituk/tag/__init__.py` | Create | `main()` entry point |
| `app/lituk/tag/__main__.py` | Create | `python -m lituk.tag` shim |
| `app/lituk/tag/tagger.py` | Create | `load_summaries`, `tag_facts` |
| `app/pyproject.toml` | Modify | Add `anthropic` dep + `lituk-tag` script |
| `app/tests/test_db.py` | Modify | chapters seeding, topic FK |
| `app/tests/test_session.py` | Modify | topic filter scenarios + e2e smoke |
| `app/tests/test_tagger.py` | Create | mock-based tagger tests |
| `app/tests/test_review_cli.py` | Modify | `--topic` flag integration test |

---

## Task 1: Schema — `chapters` table + `topic` column on `facts`

**Files:**
- Modify: `app/lituk/db.py`
- Modify: `app/tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Add to `app/tests/test_db.py`:

```python
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
```

Also add `import pytest` at the top of `test_db.py`.

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd app
uv run pytest tests/test_db.py::test_init_db_creates_chapters_table \
    tests/test_db.py::test_init_db_seeds_chapters \
    tests/test_db.py::test_facts_topic_column_accepts_null -v
```

Expected: FAIL — `chapters` table does not exist yet.

- [ ] **Step 3: Implement schema changes in `app/lituk/db.py`**

Replace the entire file with:

```python
import sqlite3


_SCHEMA = """
CREATE TABLE IF NOT EXISTS chapters (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    question_text       TEXT    NOT NULL,
    correct_answer_text TEXT    NOT NULL,
    topic               INTEGER REFERENCES chapters(id),
    UNIQUE (question_text, correct_answer_text)
);
CREATE INDEX IF NOT EXISTS idx_facts_topic ON facts(topic);

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

_CHAPTER_SEED = """
INSERT OR IGNORE INTO chapters VALUES (1, 'Values and Principles of the UK');
INSERT OR IGNORE INTO chapters VALUES (2, 'What is the UK');
INSERT OR IGNORE INTO chapters VALUES (3, 'A Long and Illustrious History');
INSERT OR IGNORE INTO chapters VALUES (4, 'A Modern Thriving Society');
INSERT OR IGNORE INTO chapters VALUES
    (5, 'The UK Government, the Law and Your Role');
"""

_POOL_SEED = """
INSERT OR IGNORE INTO pool_state (pool, alpha, beta) VALUES ('due', 1.0, 1.0);
INSERT OR IGNORE INTO pool_state (pool, alpha, beta) VALUES ('new', 1.0, 1.0);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.executescript(_CHAPTER_SEED)
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
```

- [ ] **Step 4: Run all tests to confirm they pass**

```bash
cd app
uv run pytest -q
```

Expected: all tests pass, including new `test_db.py` additions.

- [ ] **Step 5: Commit**

```bash
cd app
git add lituk/db.py tests/test_db.py
git commit -m "Add chapters table and topic column to facts"
```

---

## Task 2: Session filter — `--topic` flag

**Files:**
- Modify: `app/lituk/review/session.py`
- Modify: `app/lituk/review/__init__.py`
- Modify: `app/tests/test_session.py`
- Modify: `app/tests/test_review_cli.py`

- [ ] **Step 1: Write the failing tests**

Add to `app/tests/test_session.py` — first extend `_insert_fact_and_question`
to accept an optional `topic` parameter:

```python
def _insert_fact_and_question(conn, q_text, a_text, source_test, q_num,
                               choices=None, correct_letters=None, topic=None):
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
        " VALUES (?, ?, ?, ?, ?, 0, 0, ?)",
        (source_test, q_num, q_text, json.dumps(choices),
         json.dumps(correct_letters), fid),
    )
    conn.commit()
    return fid
```

Then add these test functions:

```python
# ---------------------------------------------------------------------------
# Topic filter
# ---------------------------------------------------------------------------

def test_topic_filter_excludes_other_chapters(conn):
    fid_ch3 = _insert_fact_and_question(conn, "Q_ch3?", "A", 1, 1, topic=3)
    fid_ch4 = _insert_fact_and_question(conn, "Q_ch4?", "A", 1, 2, topic=4)
    ui = StubUI()
    result = run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=[3],
    )
    shown_facts = {p.fact_id for p in ui.prompts_shown}
    assert fid_ch3 in shown_facts
    assert fid_ch4 not in shown_facts


def test_topic_filter_multi_chapter(conn):
    fid3 = _insert_fact_and_question(conn, "Q3?", "A", 1, 1, topic=3)
    fid4 = _insert_fact_and_question(conn, "Q4?", "A", 1, 2, topic=4)
    fid5 = _insert_fact_and_question(conn, "Q5?", "A", 1, 3, topic=5)
    ui = StubUI()
    run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=[3, 4],
    )
    shown_facts = {p.fact_id for p in ui.prompts_shown}
    assert fid3 in shown_facts
    assert fid4 in shown_facts
    assert fid5 not in shown_facts


def test_topic_filter_none_includes_all(conn):
    fid3 = _insert_fact_and_question(conn, "Q3?", "A", 1, 1, topic=3)
    fid_null = _insert_fact_and_question(conn, "Qnull?", "A", 1, 2, topic=None)
    ui = StubUI()
    run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=None,
    )
    shown_facts = {p.fact_id for p in ui.prompts_shown}
    assert fid3 in shown_facts
    assert fid_null in shown_facts


def test_topic_filter_excludes_null_topic_facts(conn):
    _insert_fact_and_question(conn, "Qnull?", "A", 1, 1, topic=None)
    fid3 = _insert_fact_and_question(conn, "Q3?", "A", 1, 2, topic=3)
    ui = StubUI()
    run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=[3],
    )
    shown_facts = {p.fact_id for p in ui.prompts_shown}
    assert fid3 in shown_facts
    # untagged fact must not appear when a topic filter is active
    null_fid = conn.execute(
        "SELECT id FROM facts WHERE question_text='Qnull?'"
    ).fetchone()["id"]
    assert null_fid not in shown_facts


def test_topic_filter_due_pool(conn):
    fid3 = _insert_fact_and_question(conn, "Q3?", "A", 1, 1, topic=3)
    fid4 = _insert_fact_and_question(conn, "Q4?", "A", 1, 2, topic=4)
    _seed_due_card(conn, fid3)
    _seed_due_card(conn, fid4)
    ui = StubUI()
    run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=[3],
    )
    shown_facts = {p.fact_id for p in ui.prompts_shown}
    assert fid3 in shown_facts
    assert fid4 not in shown_facts
```

Also extend `_insert_fact_and_question` in `app/tests/test_review_cli.py` to
accept an optional `topic=None` parameter (same change as in `test_session.py`
above — add `topic=None` to the signature, and after inserting the fact add:
`if topic is not None: conn.execute("UPDATE facts SET topic=? WHERE id=?", (topic, fid)); conn.commit()`).

Then add to `app/tests/test_review_cli.py`:

```python
def test_main_topic_flag_accepted(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    # fact tagged ch3; --topic 3 should include it
    _insert_fact_and_question(conn, topic=3)
    conn.close()

    rng = random.Random(0)
    inputs = iter(["A", "g"])
    with patch("builtins.input", side_effect=inputs), \
         patch("sys.stdout", new_callable=StringIO):
        with pytest.raises(SystemExit) as exc:
            main(["--db", db_path, "--size", "1", "--topic", "3"], _rng=rng)
    assert exc.value.code == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd app
uv run pytest tests/test_session.py::test_topic_filter_excludes_other_chapters \
    tests/test_session.py::test_topic_filter_none_includes_all -v
```

Expected: FAIL — `run_session` does not accept `topics` parameter.

- [ ] **Step 3: Implement session filter in `app/lituk/review/session.py`**

Replace `_due_pool` and `_new_pool` and update `run_session`:

```python
def _due_pool(
    conn: sqlite3.Connection, today: date, topics: list[int] | None = None
) -> list[int]:
    topic_sql = (
        f" AND f.topic IN ({','.join('?' * len(topics))})" if topics else ""
    )
    sql = (
        "SELECT cs.fact_id FROM card_state cs"
        " JOIN facts f ON f.id = cs.fact_id"
        f" WHERE cs.due_date <= ?{topic_sql}"
        " ORDER BY cs.ease_factor ASC, cs.due_date ASC"
    )
    params: list = [today.isoformat()] + (list(topics) if topics else [])
    return [r["fact_id"] for r in conn.execute(sql, params).fetchall()]


def _new_pool(
    conn: sqlite3.Connection, topics: list[int] | None = None
) -> list[int]:
    topic_sql = (
        f" AND f.topic IN ({','.join('?' * len(topics))})" if topics else ""
    )
    sql = (
        "SELECT f.id FROM facts f"
        " LEFT JOIN card_state cs ON f.id = cs.fact_id"
        f" WHERE cs.fact_id IS NULL{topic_sql}"
    )
    params: list = list(topics) if topics else []
    return [r["id"] for r in conn.execute(sql, params).fetchall()]
```

Update `run_session` signature and its first two lines:

```python
def run_session(
    conn: sqlite3.Connection,
    today: date,
    rng: random.Random,
    config: SessionConfig,
    ui: UI,
    topics: list[int] | None = None,
) -> SessionResult:
    due: list[int] = _due_pool(conn, today, topics)
    new: list[int] = _new_pool(conn, topics)
    # rest of function unchanged from here
```

- [ ] **Step 4: Implement `--topic` flag in `app/lituk/review/__init__.py`**

Add `_parse_topics` helper and the new argument:

```python
def _parse_topics(value: str) -> list[int]:
    try:
        topics = [int(t.strip()) for t in value.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid topic value: {value!r}")
    for t in topics:
        if not 1 <= t <= 5:
            raise argparse.ArgumentTypeError(f"Topic must be 1–5, got {t}")
    return topics


def main(
    args: list[str] | None = None,
    _rng: random.Random | None = None,
) -> None:
    parser = argparse.ArgumentParser(description="LITUK review session")
    parser.add_argument("--db", default=str(_DEFAULT_DB), help="Path to SQLite DB")
    parser.add_argument("--size", type=int, default=24, help="Cards per session")
    parser.add_argument(
        "--new-cap", type=int, default=5, dest="new_cap",
        help="Max new cards per session",
    )
    parser.add_argument(
        "--topic",
        type=_parse_topics,
        default=None,
        metavar="N[,N]",
        help="Chapter numbers to study, comma-separated (1–5). Default: all.",
    )
    parsed = parser.parse_args(args)

    conn = init_db(parsed.db)
    config = SessionConfig(size=parsed.size, new_cap=parsed.new_cap)
    run_session(
        conn, date.today(), _rng or random.Random(), config, TerminalUI(),
        topics=parsed.topic,
    )
    conn.close()
    sys.exit(0)
```

- [ ] **Step 5: Run all tests to confirm they pass**

```bash
cd app
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd app
git add lituk/review/session.py lituk/review/__init__.py \
    tests/test_session.py tests/test_review_cli.py
git commit -m "Add --topic filter to session and review CLI"
```

---

## Task 3: Tagger — `lituk-tag` CLI

**Files:**
- Create: `app/lituk/tag/__init__.py`
- Create: `app/lituk/tag/__main__.py`
- Create: `app/lituk/tag/tagger.py`
- Create: `app/tests/test_tagger.py`
- Modify: `app/pyproject.toml`

- [ ] **Step 1: Add `anthropic` dependency and `lituk-tag` script to `pyproject.toml`**

```toml
[project]
name = "lituk"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["anthropic"]

[project.scripts]
lituk-ingest = "lituk.ingest:main"
lituk-review = "lituk.review:main"
lituk-tag = "lituk.tag:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = ["pytest", "pytest-cov"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Then sync:

```bash
cd app
uv sync
```

- [ ] **Step 2: Write the failing tests in `app/tests/test_tagger.py`**

```python
import json
import re
from unittest.mock import MagicMock

import pytest

from lituk.db import get_or_create_fact, init_db
from lituk.tag.tagger import load_summaries, tag_facts


def _mock_client_dynamic():
    """Anthropic mock that parses fact IDs from the prompt and returns
    topic=3 for each."""
    client = MagicMock()

    def _respond(**kwargs):
        text = kwargs["messages"][0]["content"]
        ids = [int(m) for m in re.findall(r"ID=(\d+):", text)]
        response = MagicMock()
        msg = MagicMock()
        msg.text = json.dumps([{"id": fid, "topic": 3} for fid in ids])
        response.content = [msg]
        return response

    client.messages.create.side_effect = _respond
    return client


def _insert_fact(conn, q_text, a_text, topic=None):
    fid = get_or_create_fact(conn, q_text, a_text)
    if topic is not None:
        conn.execute("UPDATE facts SET topic=? WHERE id=?", (topic, fid))
        conn.commit()
    return fid


@pytest.fixture
def conn(tmp_path):
    c = init_db(str(tmp_path / "test.db"))
    yield c
    c.close()


def test_tag_facts_tags_untagged_fact(conn):
    fid = _insert_fact(conn, "What is Parliament?", "The legislature")
    count = tag_facts(conn, _mock_client_dynamic(), "SUMMARIES")
    assert count == 1
    row = conn.execute("SELECT topic FROM facts WHERE id=?", (fid,)).fetchone()
    assert row["topic"] == 3


def test_tag_facts_skips_already_tagged(conn):
    _insert_fact(conn, "What is Parliament?", "The legislature", topic=5)
    client = _mock_client_dynamic()
    count = tag_facts(conn, client, "SUMMARIES")
    assert count == 0
    client.messages.create.assert_not_called()


def test_tag_facts_retag_processes_tagged_facts(conn):
    fid = _insert_fact(conn, "What is Parliament?", "The legislature", topic=5)
    client = _mock_client_dynamic()
    count = tag_facts(conn, client, "SUMMARIES", retag=True)
    assert count == 1
    client.messages.create.assert_called_once()


def test_tag_facts_batches_101_facts_into_3_calls(conn):
    for i in range(101):
        _insert_fact(conn, f"Q{i}?", f"A{i}")
    client = _mock_client_dynamic()
    count = tag_facts(conn, client, "SUMMARIES", batch_size=50)
    assert count == 101
    assert client.messages.create.call_count == 3


def test_tag_facts_idempotent(conn):
    fid = _insert_fact(conn, "What is Parliament?", "The legislature")
    tag_facts(conn, _mock_client_dynamic(), "SUMMARIES")
    # second run: already tagged, should not call API
    client2 = _mock_client_dynamic()
    tag_facts(conn, client2, "SUMMARIES")
    client2.messages.create.assert_not_called()


def test_load_summaries_concatenates_files(tmp_path):
    (tmp_path / "ch1.md").write_text("Chapter 1 content here")
    (tmp_path / "ch2.md").write_text("Chapter 2 content here")
    result = load_summaries(str(tmp_path))
    assert "Chapter 1 content here" in result
    assert "Chapter 2 content here" in result


def test_load_summaries_includes_filenames(tmp_path):
    (tmp_path / "ch3_history.md").write_text("History content")
    result = load_summaries(str(tmp_path))
    assert "ch3_history" in result
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
cd app
uv run pytest tests/test_tagger.py -v
```

Expected: FAIL — `lituk.tag` module does not exist.

- [ ] **Step 4: Create `app/lituk/tag/tagger.py`**

```python
import json
import sqlite3
from pathlib import Path


def load_summaries(summaries_dir: str) -> str:
    path = Path(summaries_dir)
    parts = []
    for md_file in sorted(path.glob("*.md")):
        parts.append(f"## {md_file.stem}\n\n{md_file.read_text()}")
    return "\n\n---\n\n".join(parts)


def tag_facts(
    conn: sqlite3.Connection,
    client,
    summaries: str,
    batch_size: int = 50,
    retag: bool = False,
) -> int:
    if retag:
        rows = conn.execute(
            "SELECT id, question_text, correct_answer_text FROM facts"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, question_text, correct_answer_text"
            " FROM facts WHERE topic IS NULL"
        ).fetchall()

    facts = [dict(r) for r in rows]
    total_tagged = 0

    for start in range(0, len(facts), batch_size):
        batch = facts[start : start + batch_size]
        numbered = "\n".join(
            f"ID={f['id']}: Q: {f['question_text']} "
            f"A: {f['correct_answer_text']}"
            for f in batch
        )
        prompt = (
            "You are classifying Life in the UK (LITUK) exam questions"
            " by chapter.\n\n"
            f"CHAPTER SUMMARIES:\n{summaries}\n\n"
            "FACTS TO CLASSIFY:\n"
            f"{numbered}\n\n"
            "For each fact, determine which chapter (1-5) it belongs to"
            " based on the summaries above.\n"
            "Reply ONLY with a JSON array, no explanation:\n"
            '[{"id": <fact_id>, "topic": <1-5>}, ...]'
        )
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        results = json.loads(text)
        for item in results:
            conn.execute(
                "UPDATE facts SET topic=? WHERE id=?",
                (item["topic"], item["id"]),
            )
        conn.commit()
        total_tagged += len(results)

    return total_tagged
```

- [ ] **Step 5: Create `app/lituk/tag/__init__.py`**

```python
import argparse
import pathlib
import sys

import anthropic

from lituk.db import init_db
from lituk.tag.tagger import load_summaries, tag_facts


_DEFAULT_DB = pathlib.Path(__file__).parents[2] / "data" / "lituk.db"
_DEFAULT_SUMMARIES = pathlib.Path(__file__).parents[3] / "ai" / "summary"


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Tag LITUK facts by chapter using Claude Haiku"
    )
    parser.add_argument("--db", default=str(_DEFAULT_DB),
                        help="Path to SQLite DB")
    parser.add_argument(
        "--summaries", default=str(_DEFAULT_SUMMARIES),
        help="Directory of chapter summary .md files "
             "(default: ../ai/summary/ relative to repo root)",
    )
    parser.add_argument(
        "--retag", action="store_true",
        help="Re-tag facts that already have a topic assigned",
    )
    parsed = parser.parse_args(args)

    conn = init_db(parsed.db)
    client = anthropic.Anthropic()
    summaries = load_summaries(parsed.summaries)
    count = tag_facts(conn, client, summaries, retag=parsed.retag)
    print(f"Tagged {count} facts.")
    conn.close()
    sys.exit(0)
```

- [ ] **Step 6: Create `app/lituk/tag/__main__.py`**

```python
from lituk.tag import main

main()
```

- [ ] **Step 7: Run all tests to confirm they pass**

```bash
cd app
uv run pytest -q
```

Expected: all tests pass, 100% coverage.

- [ ] **Step 8: Commit**

```bash
cd app
git add lituk/tag/ tests/test_tagger.py pyproject.toml
git commit -m "Add lituk-tag CLI for LLM-based chapter classification"
```

---

## Task 4: End-to-end smoke + design spec commit

**Files:**
- Modify: `app/tests/test_session.py`
- `docs/superpowers/specs/2026-05-09-topic-tagging-design.md` (commit to repo)

- [ ] **Step 1: Write the e2e smoke test**

Add to `app/tests/test_session.py`:

```python
# ---------------------------------------------------------------------------
# End-to-end smoke: ingest → tag → session with topic filter
# ---------------------------------------------------------------------------

def test_e2e_ingest_tag_session_with_topic_filter(conn, tmp_path):
    """Insert facts manually (simulating ingest) then tag them with a mock
    tagger, run a session filtered to ch3, and verify only ch3 facts appear
    in reviews."""
    import re
    import json as _json
    from unittest.mock import MagicMock
    from lituk.tag.tagger import tag_facts

    # Insert ch3 and ch5 facts
    fid3 = _insert_fact_and_question(conn, "History Q?", "History A", 1, 1)
    fid5 = _insert_fact_and_question(conn, "Civics Q?", "Civics A", 1, 2)

    # Tag with mock client: assigns topic based on question content
    def _respond(**kwargs):
        text = kwargs["messages"][0]["content"]
        ids = [int(m) for m in re.findall(r"ID=(\d+):", text)]
        mapping = {fid3: 3, fid5: 5}
        response = MagicMock()
        msg = MagicMock()
        msg.text = _json.dumps(
            [{"id": fid, "topic": mapping.get(fid, 3)} for fid in ids]
        )
        response.content = [msg]
        return response

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _respond
    tag_facts(conn, mock_client, "SUMMARIES")

    # Run session filtered to ch3
    ui = StubUI()
    run_session(
        conn, TODAY, random.Random(0), SessionConfig(size=5), ui,
        topics=[3],
    )

    # Only ch3 fact should appear in reviews
    review_fact_ids = {
        row["fact_id"]
        for row in conn.execute("SELECT fact_id FROM reviews").fetchall()
    }
    assert fid3 in review_fact_ids
    assert fid5 not in review_fact_ids
```

- [ ] **Step 2: Run test to confirm it passes**

```bash
cd app
uv run pytest tests/test_session.py::test_e2e_ingest_tag_session_with_topic_filter -v
```

Expected: PASS (no implementation needed — all pieces are in place).

- [ ] **Step 3: Run full suite with coverage**

```bash
cd app
uv run pytest --cov=lituk --cov-report=term-missing -q
```

Expected: all tests pass, 100% coverage.

- [ ] **Step 4: Commit e2e test + design spec**

```bash
cd /Users/djn/proj/lituk
git add app/tests/test_session.py \
    docs/superpowers/specs/2026-05-09-topic-tagging-design.md \
    docs/superpowers/plans/2026-05-09-topic-tagging.md
git commit -m "Add e2e smoke test for topic-filtered session + design docs"
```

---

## Verification

```bash
cd app
uv run pytest --cov=lituk --cov-report=term-missing -q   # all pass, 100% coverage
uv run lituk-ingest                                       # populate DB (idempotent)
uv run lituk-tag                                          # tag facts (real API)
uv run lituk-review --topic 3 --size 5                    # ch3 session
uv run lituk-review --topic 3,4 --size 5                  # ch3+4 session
sqlite3 data/lituk.db "SELECT topic, COUNT(*) FROM facts GROUP BY topic;"
```
