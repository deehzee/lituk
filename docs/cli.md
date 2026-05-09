# CLI Reference

All commands are run from the `app/` directory using `uv run <command>`.

---

## `lituk-ingest`

Extracts questions from the 45 britizen.uk mock test PDFs and loads them into
SQLite. Idempotent — safe to re-run; existing rows are skipped.

**Usage**

```
lituk-ingest [--db PATH] [--dir PATH]
```

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `app/data/lituk.db` | Path to the SQLite database |
| `--dir PATH` | `<repo-root>/britizen/mock_tests/` | Directory of mock test PDFs |

**Example**

```bash
cd app
uv run lituk-ingest
# Ingesting PDFs from .../britizen/mock_tests into .../data/lituk.db ...
# Done.
```

**Notes**

- Requires `pdftotext` to be installed (`brew install poppler` on macOS).
- Ingests all `*.pdf` files matching the naming pattern
  `Practice Test #N of 45 [Updated for YYYY].pdf`.
- Run once after cloning, or after deleting and recreating the database.

---

## `lituk-tag`

Tags every untagged fact with a chapter number (1–5) using Claude Haiku.
Reads chapter summaries from `ai/summary/` as context. Idempotent — skips
already-tagged facts unless `--retag` is passed.

Requires an `ANTHROPIC_API_KEY` environment variable.

**Usage**

```
lituk-tag [--db PATH] [--summaries PATH] [--retag]
```

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `app/data/lituk.db` | Path to the SQLite database |
| `--summaries PATH` | `<repo-root>/ai/summary/` | Directory of chapter `.md` files |
| `--retag` | off | Re-tag facts that already have a topic assigned |

**Chapters**

| Number | Name |
|--------|------|
| 1 | Values and Principles of the UK |
| 2 | What is the UK |
| 3 | A Long and Illustrious History |
| 4 | A Modern Thriving Society |
| 5 | The UK Government, the Law and Your Role |

**Example**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cd app
uv run lituk-tag
# Tagged 987 facts.
```

**Notes**

- Run after `lituk-ingest`. Only needs to be run once (or after adding new
  questions).
- Sends facts to Claude Haiku in batches of 50 with all chapter summaries
  as context (~32K tokens per batch).
- Uses model `claude-haiku-4-5-20251001`.

---

## `lituk-review`

Runs an interactive spaced-repetition review session in the terminal. Uses
SM-2 for scheduling and Thompson sampling to balance due vs. new cards.

**Usage**

```
lituk-review [--db PATH] [--size N] [--new-cap N] [--topic N[,N]]
```

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `app/data/lituk.db` | Path to the SQLite database |
| `--size N` | `24` | Number of cards per session (24 matches the real exam) |
| `--new-cap N` | `5` | Maximum new cards introduced per session |
| `--topic N[,N]` | all | Chapter numbers to study, comma-separated (1–5) |

**Examples**

```bash
cd app

# Full session, all topics
uv run lituk-review

# History only, 24 cards
uv run lituk-review --topic 3

# History + modern society, quick 5-card practice
uv run lituk-review --topic 3,4 --size 5

# Introduce more new cards per session
uv run lituk-review --new-cap 10
```

**Session flow**

1. Each card shows the question and choices (A/B/C/D).
2. Type your answer (e.g. `A` or `A,C` for multi-answer questions).
3. **If correct:** type your grade — `a` Again, `h` Hard, `g` Good, `e` Easy.
4. **If wrong:** the correct answer is shown; card is re-queued within the
   session.
5. Session ends after `--size` cards or when all pools are empty.
6. Summary shows score and number of weak cards.

**Grade keys**

| Key | Grade | SM-2 effect |
|-----|-------|-------------|
| `a` | Again (0) | Lapse: interval reset to 1 day, ease −0.2 |
| `h` | Hard (3) | Ease −0.15, slow interval growth |
| `g` | Good (4) | Ease unchanged, normal interval growth |
| `e` | Easy (5) | Ease +0.10, faster interval growth |

**Notes**

- `--topic` filters both the due pool and the new pool. Facts with no topic
  assigned (`NULL`) are excluded when a filter is active.
- Run `lituk-tag` first if you want `--topic` filtering to work.
- Pool state (bandit α/β values) is persisted across sessions.

---

## Typical First-Time Setup

```bash
cd app

# 1. Populate the database
uv run lituk-ingest

# 2. Tag facts by chapter (needs ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
uv run lituk-tag

# 3. Start studying
uv run lituk-review
```

## Verify Database State

```bash
# Question and fact counts
sqlite3 data/lituk.db "SELECT COUNT(*) FROM questions; SELECT COUNT(*) FROM facts;"

# Facts per chapter
sqlite3 data/lituk.db "
SELECT c.id, c.name, COUNT(f.id) AS facts
FROM chapters c LEFT JOIN facts f ON f.topic = c.id
GROUP BY c.id ORDER BY c.id;"

# Untagged facts
sqlite3 data/lituk.db "SELECT COUNT(*) FROM facts WHERE topic IS NULL;"

# Review history
sqlite3 data/lituk.db "SELECT COUNT(*) FROM reviews;"
```
