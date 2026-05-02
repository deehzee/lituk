# PDF Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse all 45 mock test PDFs and load questions into a SQLite database.

**Architecture:** `pdftotext` (system binary) extracts raw text; a pure-Python
parser splits the text into questions and answers blocks, merges them, and writes
rows to SQLite. A thin CLI entry point (`python -m lituk.ingest`) drives the full
pipeline. SM-2 state columns are intentionally deferred to a later plan.

**Tech Stack:** Python 3.11+, uv, SQLite (stdlib `sqlite3`), `pdftotext` (system),
pytest

---

## File map

```
app/
  pyproject.toml           # uv project, pytest config
  lituk/
    __init__.py
    db.py                  # schema init, get_or_create_fact
    ingest/
      __init__.py          # main() entry point
      parser.py            # PDF → list[dict] (pure functions, no I/O except pdftotext)
      ingester.py          # conn + parser → DB writes
  tests/
    conftest.py            # shared fixtures (tmp DB, sample PDF path)
    test_parser.py         # unit tests for parser functions
    test_ingester.py       # integration tests against real DB
  data/
    .gitkeep               # empty dir committed; lituk.db is gitignored
```

---

## Task 1: Project scaffold

**Files:**
- Create: `app/pyproject.toml`
- Create: `app/lituk/__init__.py`
- Create: `app/lituk/ingest/__init__.py`
- Create: `app/data/.gitkeep`
- Create: `app/.gitignore`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p app/lituk/ingest app/tests app/data
touch app/lituk/__init__.py app/lituk/ingest/__init__.py
touch app/data/.gitkeep
```

- [ ] **Step 2: Write `app/pyproject.toml`**

```toml
[project]
name = "lituk"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.scripts]
lituk-ingest = "lituk.ingest:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = ["pytest"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Write `app/.gitignore`**

```
data/lituk.db
__pycache__/
*.pyc
.venv/
```

- [ ] **Step 4: Initialise uv project and install dev deps**

```bash
cd app
uv venv
uv pip install -e ".[dev]"
uv add --dev pytest
```

Expected: `.venv/` created, pytest available.

- [ ] **Step 5: Verify pytest runs**

```bash
cd app
uv run pytest
```

Expected: `no tests ran` (or similar — no errors).

- [ ] **Step 6: Commit**

```bash
git add app/
git commit -m "Add app project scaffold (uv + pytest)"
```

---

## Task 2: Database schema

**Files:**
- Create: `app/lituk/db.py`
- Create: `app/tests/conftest.py`
- Create: `app/tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

`app/tests/test_db.py`:

```python
import sqlite3
import pytest
from lituk.db import init_db, get_or_create_fact


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
```

`app/tests/conftest.py`:

```python
import pathlib

MOCK_TESTS_DIR = pathlib.Path(__file__).parents[2] / "britizen" / "mock_tests"
PDF_TEST_1 = MOCK_TESTS_DIR / "Life in the UK Test - Practice Test #1 of 45 [Updated for 2026].pdf"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd app && uv run pytest tests/test_db.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` for `lituk.db`.

- [ ] **Step 3: Write `app/lituk/db.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd app && uv run pytest tests/test_db.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/lituk/db.py app/tests/conftest.py app/tests/test_db.py
git commit -m "Add DB schema and get_or_create_fact"
```

---

## Task 3: PDF text extraction and cleaning

**Files:**
- Create: `app/lituk/ingest/parser.py`
- Create: `app/tests/test_parser.py`

- [ ] **Step 1: Write failing tests**

`app/tests/test_parser.py`:

```python
import pytest
from tests.conftest import PDF_TEST_1
from lituk.ingest.parser import extract_raw, clean_text


def test_extract_raw_returns_string():
    text = extract_raw(str(PDF_TEST_1))
    assert isinstance(text, str)
    assert len(text) > 100


def test_extract_raw_contains_answers_marker():
    text = extract_raw(str(PDF_TEST_1))
    assert "\nAnswers\n" in text


def test_clean_text_strips_urls():
    dirty = "Some text https://britizen.uk/practice/life-in-the-uk-test/1 more"
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd app && uv run pytest tests/test_parser.py -v
```

Expected: `ImportError` for `lituk.ingest.parser`.

- [ ] **Step 3: Write `app/lituk/ingest/parser.py` (extraction + cleaning only)**

```python
import re
import subprocess

_URL_RE    = re.compile(r'https?://\S+')
_DATE_RE   = re.compile(r'\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2}')
_TITLE_RE  = re.compile(
    r'Life in the UK Test - Practice Test #\d+ of 45 \[Updated for \d+\]'
)
_PAGENUM_RE = re.compile(r'^\d+/\d+$', re.MULTILINE)


def extract_raw(pdf_path: str) -> str:
    result = subprocess.run(
        ['pdftotext', pdf_path, '-'],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def clean_text(text: str) -> str:
    text = _URL_RE.sub('', text)
    text = _DATE_RE.sub('', text)
    text = _TITLE_RE.sub('', text)
    text = _PAGENUM_RE.sub('', text)
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd app && uv run pytest tests/test_parser.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/lituk/ingest/parser.py app/tests/test_parser.py
git commit -m "Add PDF text extraction and cleaning"
```

---

## Task 4: Parse questions block

**Files:**
- Modify: `app/lituk/ingest/parser.py`
- Modify: `app/tests/test_parser.py`

- [ ] **Step 1: Write failing tests**

Append to `app/tests/test_parser.py`:

```python
from lituk.ingest.parser import parse_questions_block

_SAMPLE_Q_BLOCK = """
1. What is known as Lent?
A.
The 40 days before Easter
B.
The 40 days after Christmas
C.
The 40 days before Christmas
D.
The 40 days after Easter

2. One TV licence covers all equipment at one address, but people who rent
different rooms in a shared house must buy a separate TV licence
A.
False
B.
True

3. Who can nominate life peers? (Select TWO)
A.
The Prime Minister
B.
The Monarchy
C.
The Speaker
D.
Leaders of other main political parties
"""


def test_parse_questions_block_count():
    qs = parse_questions_block(_SAMPLE_Q_BLOCK)
    assert len(qs) == 3


def test_parse_questions_block_text():
    qs = parse_questions_block(_SAMPLE_Q_BLOCK)
    assert qs[0]["question_text"] == "What is known as Lent?"


def test_parse_questions_block_choices():
    qs = parse_questions_block(_SAMPLE_Q_BLOCK)
    assert qs[0]["choices"] == [
        "The 40 days before Easter",
        "The 40 days after Christmas",
        "The 40 days before Christmas",
        "The 40 days after Easter",
    ]
    assert qs[0]["choice_letters"] == ["A", "B", "C", "D"]


def test_parse_questions_block_true_false():
    qs = parse_questions_block(_SAMPLE_Q_BLOCK)
    assert qs[1]["is_true_false"] is True
    assert qs[1]["is_multi"] is False


def test_parse_questions_block_multi():
    qs = parse_questions_block(_SAMPLE_Q_BLOCK)
    assert qs[2]["is_multi"] is True
    assert qs[2]["is_true_false"] is False
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd app && uv run pytest tests/test_parser.py::test_parse_questions_block_count -v
```

Expected: `ImportError` for `parse_questions_block`.

- [ ] **Step 3: Add `parse_questions_block` to `app/lituk/ingest/parser.py`**

```python
_CHOICE_LINE_RE  = re.compile(r'^([A-D])\.$')
_QUESTION_SPLIT  = re.compile(r'\n(\d+)\. ')


def parse_questions_block(block: str) -> list[dict]:
    parts = _QUESTION_SPLIT.split(block)
    # parts: [preamble, num, body, num, body, ...]
    questions = []
    for i in range(1, len(parts), 2):
        qnum = int(parts[i])
        body = parts[i + 1] if i + 1 < len(parts) else ''
        lines = [l.strip() for l in body.split('\n') if l.strip()]

        choice_start = next(
            (j for j, l in enumerate(lines) if _CHOICE_LINE_RE.match(l)),
            None,
        )
        if choice_start is None:
            q_text = ' '.join(lines)
            choices, letters = [], []
        else:
            q_text = ' '.join(lines[:choice_start])
            raw = lines[choice_start:]
            choices, letters = [], []
            cur_letter, cur_words = None, []
            for line in raw:
                m = _CHOICE_LINE_RE.match(line)
                if m:
                    if cur_letter is not None:
                        choices.append(' '.join(cur_words))
                        letters.append(cur_letter)
                    cur_letter, cur_words = m.group(1), []
                elif cur_letter is not None:
                    cur_words.append(line)
            if cur_letter is not None:
                choices.append(' '.join(cur_words))
                letters.append(cur_letter)

        is_tf = (
            len(choices) == 2
            and {c.lower() for c in choices} == {'true', 'false'}
        )
        is_multi = bool(re.search(r'\bTWO\b', q_text))

        questions.append({
            'q_number': qnum,
            'question_text': q_text,
            'choices': choices,
            'choice_letters': letters,
            'is_true_false': is_tf,
            'is_multi': is_multi,
        })
    return questions
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd app && uv run pytest tests/test_parser.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/lituk/ingest/parser.py app/tests/test_parser.py
git commit -m "Add questions block parser"
```

---

## Task 5: Parse answers block

**Files:**
- Modify: `app/lituk/ingest/parser.py`
- Modify: `app/tests/test_parser.py`

- [ ] **Step 1: Write failing tests**

Append to `app/tests/test_parser.py`:

```python
from lituk.ingest.parser import parse_answers_block

_SAMPLE_A_BLOCK = """
1.
A - The 40 days before Easter
The 40 days before Easter are known as Lent.

2.
B - True
One TV licence covers all equipment at one address.

3.
A - The Prime Minister
D - Leaders of other main political parties
Since 1958, the Prime Minister has had the power to nominate peers.
"""


def test_parse_answers_block_count():
    answers = parse_answers_block(_SAMPLE_A_BLOCK)
    assert len(answers) == 3


def test_parse_answers_block_single_correct():
    answers = parse_answers_block(_SAMPLE_A_BLOCK)
    assert answers[0]["q_number"] == 1
    assert answers[0]["correct_letters"] == ["A"]
    assert "Lent" in answers[0]["explanation"]


def test_parse_answers_block_multi_correct():
    answers = parse_answers_block(_SAMPLE_A_BLOCK)
    assert answers[2]["correct_letters"] == ["A", "D"]


def test_parse_answers_block_explanation_excludes_answer_lines():
    answers = parse_answers_block(_SAMPLE_A_BLOCK)
    assert "A - The Prime Minister" not in answers[2]["explanation"]
    assert "Since 1958" in answers[2]["explanation"]
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd app && uv run pytest tests/test_parser.py::test_parse_answers_block_count -v
```

Expected: `ImportError` for `parse_answers_block`.

- [ ] **Step 3: Add `parse_answers_block` to `app/lituk/ingest/parser.py`**

```python
_ANSWER_NUM_SPLIT = re.compile(r'\n(\d+)\.\n')
_ANSWER_LINE_RE   = re.compile(r'^([A-D]) - .+$')


def parse_answers_block(block: str) -> list[dict]:
    parts = _ANSWER_NUM_SPLIT.split(block)
    # parts: [preamble, num, body, num, body, ...]
    answers = []
    for i in range(1, len(parts), 2):
        qnum = int(parts[i])
        body = parts[i + 1] if i + 1 < len(parts) else ''
        lines = [l.strip() for l in body.split('\n') if l.strip()]

        correct_letters, explanation_lines = [], []
        for line in lines:
            if not explanation_lines and _ANSWER_LINE_RE.match(line):
                correct_letters.append(line[0])
            else:
                explanation_lines.append(line)

        answers.append({
            'q_number': qnum,
            'correct_letters': correct_letters,
            'explanation': ' '.join(explanation_lines),
        })
    return answers
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd app && uv run pytest tests/test_parser.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/lituk/ingest/parser.py app/tests/test_parser.py
git commit -m "Add answers block parser"
```

---

## Task 6: Full PDF parse (end-to-end)

**Files:**
- Modify: `app/lituk/ingest/parser.py`
- Modify: `app/tests/test_parser.py`

- [ ] **Step 1: Write failing tests**

Append to `app/tests/test_parser.py`:

```python
from lituk.ingest.parser import parse_pdf


def test_parse_pdf_question_count():
    rows = parse_pdf(str(PDF_TEST_1), test_num=1)
    assert len(rows) == 24


def test_parse_pdf_first_question():
    rows = parse_pdf(str(PDF_TEST_1), test_num=1)
    q = rows[0]
    assert q["q_number"] == 1
    assert "Lent" in q["question_text"]
    assert q["correct_letters"] == ["A"]
    assert q["source_test"] == 1


def test_parse_pdf_true_false_question():
    # Q12 in test 1 is a T/F question
    rows = parse_pdf(str(PDF_TEST_1), test_num=1)
    q = next(r for r in rows if r["q_number"] == 12)
    assert q["is_true_false"] == 1


def test_parse_pdf_multi_answer_question():
    # Q20 in test 1 is a Select TWO question
    rows = parse_pdf(str(PDF_TEST_1), test_num=1)
    q = next(r for r in rows if r["q_number"] == 20)
    assert q["is_multi"] == 1
    assert len(q["correct_letters"]) == 2


def test_parse_pdf_choices_is_json_string():
    import json
    rows = parse_pdf(str(PDF_TEST_1), test_num=1)
    choices = json.loads(rows[0]["choices"])
    assert isinstance(choices, list)
    assert len(choices) == 4
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd app && uv run pytest tests/test_parser.py::test_parse_pdf_question_count -v
```

Expected: `ImportError` for `parse_pdf`.

- [ ] **Step 3: Add `parse_pdf` to `app/lituk/ingest/parser.py`**

```python
import json as _json

_ANSWERS_SPLIT = re.compile(r'\nAnswers\n')


def parse_pdf(pdf_path: str, test_num: int) -> list[dict]:
    raw = extract_raw(pdf_path)
    text = clean_text(raw)

    halves = _ANSWERS_SPLIT.split(text, maxsplit=1)
    if len(halves) != 2:
        raise ValueError(f"No 'Answers' section found in {pdf_path}")

    q_block, a_block = halves
    questions = parse_questions_block(q_block)
    answers   = parse_answers_block(a_block)
    ans_map   = {a['q_number']: a for a in answers}

    rows = []
    for q in questions:
        n   = q['q_number']
        ans = ans_map.get(n, {'correct_letters': [], 'explanation': ''})

        letter_to_text = dict(zip(q['choice_letters'], q['choices']))
        correct_texts  = [letter_to_text.get(l, l) for l in ans['correct_letters']]

        rows.append({
            'source_test':        test_num,
            'q_number':           n,
            'question_text':      q['question_text'],
            'choices':            _json.dumps(q['choices']),
            'correct_letters':    _json.dumps(ans['correct_letters']),
            'correct_answer_text': ', '.join(correct_texts),
            'explanation':        ans.get('explanation', ''),
            'is_true_false':      int(q['is_true_false']),
            'is_multi':           int(q['is_multi']),
        })
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd app && uv run pytest tests/test_parser.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/lituk/ingest/parser.py app/tests/test_parser.py
git commit -m "Add full PDF parse (parse_pdf)"
```

---

## Task 7: Ingester (PDF → DB)

**Files:**
- Create: `app/lituk/ingest/ingester.py`
- Create: `app/tests/test_ingester.py`

- [ ] **Step 1: Write failing tests**

`app/tests/test_ingester.py`:

```python
import json
import pytest
from tests.conftest import PDF_TEST_1
from lituk.db import init_db
from lituk.ingest.ingester import ingest_pdf


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
    assert rows == 24  # all unique in one test


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
    ingest_pdf(conn, str(PDF_TEST_1), test_num=1)  # second run
    rows = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    assert rows == 24  # no duplicates


def test_ingest_pdf_choices_valid_json(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    ingest_pdf(conn, str(PDF_TEST_1), test_num=1)
    row = conn.execute("SELECT choices FROM questions WHERE q_number=1").fetchone()
    choices = json.loads(row["choices"])
    assert isinstance(choices, list)
    assert len(choices) == 4
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd app && uv run pytest tests/test_ingester.py -v
```

Expected: `ImportError` for `lituk.ingest.ingester`.

- [ ] **Step 3: Write `app/lituk/ingest/ingester.py`**

```python
import sqlite3

from lituk.db import get_or_create_fact
from lituk.ingest.parser import parse_pdf


def ingest_pdf(conn: sqlite3.Connection, pdf_path: str, test_num: int) -> int:
    rows = parse_pdf(pdf_path, test_num)
    inserted = 0
    for row in rows:
        fact_id = get_or_create_fact(
            conn, row['question_text'], row['correct_answer_text']
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO questions
                (source_test, q_number, question_text, choices,
                 correct_letters, explanation, is_true_false, is_multi, fact_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row['source_test'], row['q_number'], row['question_text'],
                row['choices'], row['correct_letters'], row['explanation'],
                row['is_true_false'], row['is_multi'], fact_id,
            ),
        )
        inserted += conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    return inserted
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd app && uv run pytest tests/test_ingester.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/lituk/ingest/ingester.py app/tests/test_ingester.py
git commit -m "Add PDF ingester (ingest_pdf)"
```

---

## Task 8: CLI entry point and full ingestion

**Files:**
- Modify: `app/lituk/ingest/__init__.py`
- Modify: `app/tests/test_ingester.py`

- [ ] **Step 1: Write failing test for full ingestion**

Append to `app/tests/test_ingester.py`:

```python
from tests.conftest import MOCK_TESTS_DIR
from lituk.ingest.ingester import ingest_all


def test_ingest_all_question_count(tmp_path):
    db_path = str(tmp_path / "lituk.db")
    ingest_all(db_path, str(MOCK_TESTS_DIR))
    import sqlite3
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    assert count == 45 * 24  # 1080


def test_ingest_all_facts_deduplicated(tmp_path):
    db_path = str(tmp_path / "lituk.db")
    ingest_all(db_path, str(MOCK_TESTS_DIR))
    import sqlite3
    conn = sqlite3.connect(db_path)
    facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    conn.close()
    # 1080 questions but ~1033 unique (question_text, correct_answer) pairs
    assert facts < 45 * 24
    assert facts > 1000
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd app && uv run pytest tests/test_ingester.py::test_ingest_all_question_count -v
```

Expected: `ImportError` for `ingest_all`.

- [ ] **Step 3: Add `ingest_all` to `app/lituk/ingest/ingester.py`**

```python
import pathlib
import re

def ingest_all(db_path: str, mock_tests_dir: str) -> None:
    from lituk.db import init_db
    conn = init_db(db_path)
    pdf_dir = pathlib.Path(mock_tests_dir)
    _num_re = re.compile(r'Practice Test #(\d+) of')
    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        m = _num_re.search(pdf_path.name)
        if not m:
            continue
        test_num = int(m.group(1))
        ingest_pdf(conn, str(pdf_path), test_num)
    conn.close()
```

- [ ] **Step 4: Write `app/lituk/ingest/__init__.py` (CLI entry)**

```python
import argparse
import pathlib

from lituk.ingest.ingester import ingest_all

_DEFAULT_DB  = pathlib.Path(__file__).parents[2] / "data" / "lituk.db"
_DEFAULT_DIR = pathlib.Path(__file__).parents[4] / "britizen" / "mock_tests"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest mock test PDFs into SQLite")
    parser.add_argument("--db",  default=str(_DEFAULT_DB),  help="Path to SQLite DB")
    parser.add_argument("--dir", default=str(_DEFAULT_DIR), help="Mock tests directory")
    args = parser.parse_args()
    print(f"Ingesting PDFs from {args.dir} into {args.db} ...")
    ingest_all(args.db, args.dir)
    print("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run all tests to verify they pass**

```bash
cd app && uv run pytest -v
```

Expected: all tests pass. Note: `test_ingest_all_*` will be slow (~10–30 s).

- [ ] **Step 6: Smoke-test the CLI**

```bash
cd app && uv run python -m lituk.ingest
```

Expected output:
```
Ingesting PDFs from .../britizen/mock_tests into .../app/data/lituk.db ...
Done.
```

Verify:
```bash
sqlite3 app/data/lituk.db "SELECT COUNT(*) FROM questions; SELECT COUNT(*) FROM facts;"
```

Expected: `1080` then a number between 1000 and 1080.

- [ ] **Step 7: Commit**

```bash
git add app/lituk/ingest/__init__.py app/lituk/ingest/ingester.py \
        app/tests/test_ingester.py
git commit -m "Add ingest_all and CLI entry point"
```

---

## Self-review

**Spec coverage:**
- PDF text extraction: Task 3 ✓
- Cleaning artifacts: Task 3 ✓
- Questions block parsing: Task 4 ✓
- Answers block parsing: Task 5 ✓
- Full PDF parse (merge Q+A): Task 6 ✓
- DB schema (questions + facts): Task 2 ✓
- Single PDF ingestion: Task 7 ✓
- Deduplication via facts table: Task 7 ✓
- Full ingestion of all 45 PDFs: Task 8 ✓
- CLI entry point: Task 8 ✓
- uv project scaffold: Task 1 ✓

**Placeholder scan:** None found.

**Type consistency:**
- `parse_pdf` returns `list[dict]` with keys `source_test`, `q_number`,
  `question_text`, `choices` (JSON str), `correct_letters` (JSON str),
  `correct_answer_text`, `explanation`, `is_true_false` (int), `is_multi` (int)
  — used consistently in `ingest_pdf` ✓
- `get_or_create_fact(conn, question_text, correct_answer_text) -> int`
  — signature matches all call sites ✓
- `ingest_pdf(conn, pdf_path, test_num) -> int` — consistent ✓
- `ingest_all(db_path, mock_tests_dir) -> None` — consistent ✓
