# Topic Tagging — Design Spec

**Date:** 2026-05-09
**Status:** Approved

## Overview

Add chapter-level topic tags to facts so the user can filter review sessions by
topic. Tagging is a one-time LLM-assisted operation (Claude Haiku); the session
engine gains an optional `--topic` flag.

---

## 1. Schema Changes

### New table: `chapters`

```sql
CREATE TABLE IF NOT EXISTS chapters (
    id   INTEGER PRIMARY KEY,   -- 1–5
    name TEXT NOT NULL
);
```

Seeded in `init_db` via `INSERT OR IGNORE` (same pattern as `pool_state`):

```sql
INSERT OR IGNORE INTO chapters VALUES (1, 'Values and Principles of the UK');
INSERT OR IGNORE INTO chapters VALUES (2, 'What is the UK');
INSERT OR IGNORE INTO chapters VALUES (3, 'A Long and Illustrious History');
INSERT OR IGNORE INTO chapters VALUES (4, 'A Modern Thriving Society');
INSERT OR IGNORE INTO chapters VALUES (5, 'The UK Government, the Law and Your Role');
```

### Modified table: `facts`

Add `topic` directly to the `CREATE TABLE facts` DDL in `_SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS facts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    question_text       TEXT    NOT NULL,
    correct_answer_text TEXT    NOT NULL,
    topic               INTEGER REFERENCES chapters(id),
    UNIQUE (question_text, correct_answer_text)
);
CREATE INDEX IF NOT EXISTS idx_facts_topic ON facts(topic);
```

`topic` is nullable — `NULL` means untagged. The index makes topic-filtered
pool queries fast. The FK ensures only valid chapter numbers 1–5 are stored.

Existing DBs should be deleted and recreated; all data is repopulatable via
`lituk-ingest` (run it, then `lituk-tag`).

---

## 2. LLM Tagger (`lituk-tag`)

### Purpose

A one-shot CLI that classifies every untagged fact into one of the 5 chapters
using Claude Haiku. Idempotent: re-running only processes `WHERE topic IS NULL`
facts unless `--retag` is passed.

### Module layout

```
app/lituk/tag/
    __init__.py     # main() — argparse entry point
    __main__.py     # `python -m lituk.tag` shim
    tagger.py       # core classification logic
```

Registered in `pyproject.toml`:
```toml
lituk-tag = "lituk.tag:main"
```

### Algorithm

1. Load all 22 chapter summary files from `ai/summary/` into a single context
   string (~32K tokens total).
2. Fetch untagged facts:
   ```sql
   SELECT id, question_text, correct_answer_text
   FROM facts WHERE topic IS NULL
   ```
3. Send facts to Claude Haiku in batches of 50. Each request includes:
   - All 5 chapter summaries as context
   - A numbered list of fact `(question_text, correct_answer_text)` pairs
   - Instruction: classify each fact into chapter 1–5; return JSON array of
     `{"id": N, "topic": M}` objects.
4. Write results: `UPDATE facts SET topic = ? WHERE id = ?`

### CLI

```
lituk-tag                         # tag all untagged facts (default)
lituk-tag --db path/to/lituk.db   # specify DB path
lituk-tag --retag                 # retag all facts, including already-tagged
lituk-tag --summaries path/       # override summary dir (default: ../ai/summary/ relative to CWD)
```

### `tagger.py` contract

```python
def load_summaries(summaries_dir: str) -> str:
    """Read all *.md files from summaries_dir, concatenate with chapter headers."""

def tag_facts(
    conn: sqlite3.Connection,
    client,                     # anthropic.Anthropic instance
    summaries: str,
    batch_size: int = 50,
    retag: bool = False,
) -> int:
    """Classify untagged facts. Returns count of facts tagged."""
```

---

## 3. Session Filter

### `run_session` signature

```python
def run_session(
    conn, today, rng, config, ui,
    topics: list[int] | None = None,
) -> SessionResult:
```

`topics=None` means all topics (existing behaviour, no SQL change).
`topics=[3, 4]` adds `AND f.topic IN (3, 4)` to the due and new pool queries.

Facts with `topic IS NULL` are included when `topics=None` and excluded when
any topic filter is active.

Lapsed-in-session queue is unaffected: once a fact enters the session it stays
regardless of topic.

### `review/__init__.py` CLI change

```python
parser.add_argument(
    "--topic",
    type=str,
    default=None,
    metavar="N[,N]",
    help="Comma-separated chapter numbers to study (e.g. 3 or 3,4). "
         "Default: all topics.",
)
# parsed as:
topics = [int(t) for t in args.topic.split(",")] if args.topic else None
```

### Examples

```
lituk-review                  # all topics (unchanged behaviour)
lituk-review --topic 3        # history only
lituk-review --topic 3,4      # history + modern society
```

---

## 4. Files Modified / Created

| File | Change |
|------|--------|
| `app/lituk/db.py` | Add `chapters` table + seed; add `topic` column + index to `facts` DDL |
| `app/lituk/review/__init__.py` | Add `--topic` argparse arg; pass `topics` to `run_session` |
| `app/lituk/review/session.py` | Accept `topics` param; add `WHERE topic IN (...)` to pool queries |
| `app/lituk/tag/__init__.py` | New: `main()` entry point |
| `app/lituk/tag/__main__.py` | New: `python -m lituk.tag` shim |
| `app/lituk/tag/tagger.py` | New: `load_summaries`, `tag_facts` |
| `app/pyproject.toml` | Add `lituk-tag` script entry |
| `app/tests/test_db.py` | Extend: chapters seeding, topic FK |
| `app/tests/test_tagger.py` | New: mock Anthropic client, batching, idempotency |
| `app/tests/test_session.py` | Extend: topic filter scenarios |

---

## 5. Testing Strategy

### `test_db.py` additions
- `chapters` table has exactly 5 rows after `init_db`
- `facts.topic` column exists, accepts `NULL` and 1–5, rejects 99 (FK violation)

### `test_tagger.py` (new)
- Mock Anthropic client; assert prompt contains chapter summaries and fact text
- Assert `UPDATE facts SET topic = ?` called with returned value
- Batch boundary: 101 facts → 3 batches (50 / 50 / 1)
- `--retag` flag: already-tagged facts are reprocessed
- Idempotency: running tagger twice yields the same tags

### `test_session.py` additions
- `topics=[3]` excludes facts tagged with other chapters
- `topics=[3, 4]` includes facts from both chapters
- `topics=None` includes all facts (existing tests unaffected)
- Facts with `topic IS NULL` included when `topics=None`, excluded otherwise

### End-to-end smoke
Extend existing smoke test: ingest 1 PDF → run tagger with mocked LLM → run
session with `topics=[3]` → assert only ch3 facts appear in `reviews`.

---

## 6. Out of Scope

- Per-topic statistics / progress display (separate plan)
- Tagging at ingest time (would couple LLM calls into ingestion)
- Multi-label tagging (one fact → multiple chapters)
- Web UI topic filtering
