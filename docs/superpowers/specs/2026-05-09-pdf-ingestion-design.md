# PDF Ingestion — Design Spec

**Date:** 2026-05-09
**Status:** Implemented (PR #1)

## Overview

Extract all questions and answers from 45 britizen.uk mock test PDFs and store
them in SQLite. The ingestion is idempotent: re-running is safe and only inserts
rows that don't already exist.

---

## 1. Source Material

45 PDFs in `britizen/mock_tests/`, named:

```
Life in the UK Test - Practice Test #N of 45 [Updated for 2026].pdf
```

Each PDF has exactly 24 questions with choices A/B/C/D (A/B only for
True/False questions), followed by an `Answers` section with the correct
letter(s) and an explanation per question.

---

## 2. Parsing Strategy

Text is extracted with `pdftotext` (no OCR needed — PDFs are text-based).
Parsing happens in two passes over the raw text:

1. **Questions block** — everything before the `Answers` line.
   Split on `\n{N}. ` to isolate each question. Extract question text and
   choices (lines matching `^[A-D]\.$` mark choice starts).

2. **Answers block** — everything after the `Answers` line.
   Split on `\n{N}.\n` to isolate each answer. Extract correct letter(s)
   (lines matching `^[A-D] - .+$`) and explanation text.

**Page-break artifact:** when a question straddles a page break, the PDF
title bleeds into the last choice. All of the following are stripped before
parsing:
- Page titles: `Life in the UK Test - Practice Test #N of 45 [Updated for YYYY]`
- Timestamps: `DD/MM/YYYY, HH:MM`
- Page numbers: `N/M`
- URLs: `https?://...`

**Question types** (detected automatically):
- **True/False** — exactly 2 choices and `{True, False}` as the choice set
- **Multi-answer** — `\bTWO\b` in the question text
- **Single-answer** — everything else

---

## 3. Data Model

### `facts` table

The unit of spaced repetition. Two questions with the same text and correct
answer are the same fact — SM-2 state is shared across tests.

```sql
CREATE TABLE IF NOT EXISTS facts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    question_text       TEXT    NOT NULL,
    correct_answer_text TEXT    NOT NULL,
    topic               INTEGER REFERENCES chapters(id),
    UNIQUE (question_text, correct_answer_text)
);
```

`get_or_create_fact(conn, question_text, correct_answer_text)` uses
`INSERT OR IGNORE` + `SELECT` to ensure idempotency.

### `questions` table

One row per question per test. Distractors (wrong options) can differ across
tests for the same fact.

```sql
CREATE TABLE IF NOT EXISTS questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_test     INTEGER NOT NULL,
    q_number        INTEGER NOT NULL,
    question_text   TEXT    NOT NULL,
    choices         TEXT    NOT NULL,     -- JSON array of strings
    correct_letters TEXT    NOT NULL,     -- JSON array e.g. ["A"] or ["A","C"]
    explanation     TEXT,
    is_true_false   INTEGER NOT NULL DEFAULT 0,
    is_multi        INTEGER NOT NULL DEFAULT 0,
    fact_id         INTEGER REFERENCES facts(id),
    UNIQUE (source_test, q_number)
);
```

---

## 4. Module Layout

```
app/lituk/ingest/
    __init__.py     # main() — argparse CLI entry
    __main__.py     # python -m lituk.ingest shim
    parser.py       # PDF text extraction and parsing (pure)
    ingester.py     # DB writes: ingest_pdf, ingest_all
```

`parser.py` is pure (no DB, no I/O beyond pdftotext subprocess).
`ingester.py` calls the parser and writes results to SQLite.

---

## 5. Duplicates Policy

42 question texts appear in more than one test (max 3 occurrences). The same
question always has the same correct answer across tests, but distractors can
differ. Policy:

- **Do not deduplicate** `questions` rows — each occurrence is its own row
  (different distractors are study-relevant).
- **Do deduplicate** `facts` — `UNIQUE (question_text, correct_answer_text)`
  ensures SM-2 state is keyed on the underlying knowledge, not the test.

---

## 6. CLI Reference

See `docs/cli.md` for full flag documentation.

```
lituk-ingest                         # ingest all PDFs from default location
lituk-ingest --db path/to/lituk.db   # specify DB path
lituk-ingest --dir path/to/pdfs/     # specify PDF directory
```

Defaults:
- `--db`: `app/data/lituk.db`
- `--dir`: `<repo-root>/britizen/mock_tests/`
