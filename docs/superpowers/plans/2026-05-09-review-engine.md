# SM-2 + MAB Review Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the spaced-repetition review engine that schedules cards using
SM-2 and selects pools using Thompson sampling, with a terminal UI and a thin
`lituk-review` CLI.

**Architecture:** Pure modules (`scheduler`, `bandit`) take explicit inputs and
return values — no DB, no I/O. `presenter` reads the DB but is otherwise pure.
`session` orchestrates and writes state. `cli` handles I/O via the `UI`
protocol so the same session loop can drive a future web UI without changes.

**Tech Stack:** Python 3.12, SQLite (`sqlite3`), `pytest`, `random.Random`
(seeded for deterministic tests).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/lituk/db.py` | Modify | Add `card_state`, `pool_state`, `reviews` tables + pool seed |
| `app/lituk/review/scheduler.py` | Create | SM-2 update (pure) |
| `app/lituk/review/bandit.py` | Create | Thompson sampling (pure) |
| `app/lituk/review/presenter.py` | Create | Prompt building + grading (reads DB) |
| `app/lituk/review/session.py` | Create | Session loop + DB writes |
| `app/lituk/review/cli.py` | Create | `TerminalUI` — stdin/stdout UI implementation |
| `app/lituk/review/__init__.py` | Create | `main()` — argparse entry point |
| `app/lituk/review/__main__.py` | Create | `python -m lituk.review` shim |
| `app/pyproject.toml` | Modify | Add `lituk-review` script entry |
| `app/tests/test_scheduler.py` | Create | SM-2 table-driven tests |
| `app/tests/test_bandit.py` | Create | Bandit tests with seeded RNG |
| `app/tests/test_presenter.py` | Create | Prompt building with fixture DB |
| `app/tests/test_session.py` | Create | End-to-end session tests with stub UI |
| `app/tests/test_review_cli.py` | Create | `main()` integration tests |

---

## Task 1: Schema — `card_state`, `pool_state`, `reviews`

**Files:** `app/lituk/db.py`, `app/tests/test_db.py`

- [ ] **Step 1: Write failing tests**

```python
def test_init_db_creates_review_tables(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "card_state" in tables
    assert "pool_state" in tables
    assert "reviews" in tables

def test_init_db_seeds_pool_state(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    rows = conn.execute(
        "SELECT pool, alpha, beta FROM pool_state ORDER BY pool"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["pool"] == "due"
    assert rows[1]["pool"] == "new"
    assert rows[0]["alpha"] == rows[0]["beta"] == 1.0
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd app && uv run pytest tests/test_db.py::test_init_db_creates_review_tables -v
```

- [ ] **Step 3: Extend `_SCHEMA` in `db.py`**

Add to `_SCHEMA`:

```sql
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
```

Add `_POOL_SEED` constant and call it in `init_db`:

```python
_POOL_SEED = """
INSERT OR IGNORE INTO pool_state (pool, alpha, beta) VALUES ('due', 1.0, 1.0);
INSERT OR IGNORE INTO pool_state (pool, alpha, beta) VALUES ('new', 1.0, 1.0);
"""
```

- [ ] **Step 4: Run all tests — confirm pass**

```bash
cd app && uv run pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add lituk/db.py tests/test_db.py
git commit -m "Add card_state, pool_state, reviews tables to schema"
```

---

## Task 2: SM-2 Scheduler

**Files:** `app/lituk/review/scheduler.py`, `app/tests/test_scheduler.py`

- [ ] **Step 1: Write failing tests**

```python
from datetime import date
from lituk.review.scheduler import CardState, initial_state, update

TODAY = date(2026, 5, 9)

def test_initial_state():
    s = initial_state(TODAY)
    assert s.ease == 2.5
    assert s.interval == 0
    assert s.repetitions == 0
    assert s.due_date == TODAY

def test_lapse_resets_interval_and_reps():
    s = initial_state(TODAY)
    s2 = update(s, 0, TODAY)
    assert s2.interval == 1
    assert s2.repetitions == 0
    assert s2.lapses == 1
    assert s2.ease < 2.5

def test_good_grade_first_rep_gives_interval_1():
    s = initial_state(TODAY)
    s2 = update(s, 4, TODAY)
    assert s2.interval == 1
    assert s2.repetitions == 1

def test_good_grade_second_rep_gives_interval_6():
    s = update(initial_state(TODAY), 4, TODAY)
    s2 = update(s, 4, TODAY)
    assert s2.interval == 6

def test_ease_floor_at_1_3():
    s = CardState(ease=1.3, interval=1, repetitions=1,
                  due_date=TODAY, lapses=0)
    s2 = update(s, 0, TODAY)
    assert s2.ease == 1.3

def test_easy_grade_increases_ease():
    s = initial_state(TODAY)
    s2 = update(s, 5, TODAY)
    assert s2.ease == 2.6
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd app && uv run pytest tests/test_scheduler.py -v
```

- [ ] **Step 3: Implement `scheduler.py`**

```python
from dataclasses import dataclass
from datetime import date, timedelta

@dataclass(frozen=True)
class CardState:
    ease: float
    interval: int
    repetitions: int
    due_date: date
    lapses: int

def initial_state(today: date) -> CardState:
    return CardState(ease=2.5, interval=0, repetitions=0,
                     due_date=today, lapses=0)

_EASE_DELTA = {3: -0.15, 4: 0.0, 5: 0.10}
_EASE_FLOOR = 1.3

def update(state: CardState, grade: int, today: date) -> CardState:
    if grade < 3:
        new_ease = max(_EASE_FLOOR, state.ease - 0.2)
        new_interval, new_reps = 1, 0
        new_lapses = state.lapses + 1
    else:
        new_ease = max(_EASE_FLOOR, state.ease + _EASE_DELTA[grade])
        new_reps = state.repetitions + 1
        if new_reps == 1:
            new_interval = 1
        elif new_reps == 2:
            new_interval = 6
        else:
            new_interval = round(state.interval * new_ease)
        new_lapses = state.lapses
    return CardState(ease=new_ease, interval=new_interval,
                     repetitions=new_reps,
                     due_date=today + timedelta(days=new_interval),
                     lapses=new_lapses)
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd app && uv run pytest tests/test_scheduler.py -v
```

- [ ] **Step 5: Commit**

```bash
git add lituk/review/scheduler.py tests/test_scheduler.py
git commit -m "Add SM-2 scheduler"
```

---

## Task 3: Bandit

**Files:** `app/lituk/review/bandit.py`, `app/tests/test_bandit.py`

- [ ] **Step 1: Write failing tests**

```python
import random
from lituk.review.bandit import PoolPosterior, choose, update

def test_update_correct_increments_alpha():
    p = PoolPosterior(alpha=1.0, beta=1.0)
    p2 = update(p, correct=True)
    assert p2.alpha == 2.0 and p2.beta == 1.0

def test_update_wrong_increments_beta():
    p = PoolPosterior(alpha=1.0, beta=1.0)
    p2 = update(p, correct=False)
    assert p2.alpha == 1.0 and p2.beta == 2.0

def test_choose_favours_higher_sample():
    # With seed 0, due arm samples higher
    rng = random.Random(0)
    due = PoolPosterior(alpha=10.0, beta=1.0)   # strong due
    new = PoolPosterior(alpha=1.0, beta=10.0)   # weak new
    assert choose(rng, due, new) == "due"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd app && uv run pytest tests/test_bandit.py -v
```

- [ ] **Step 3: Implement `bandit.py`**

```python
import random
from dataclasses import dataclass

@dataclass(frozen=True)
class PoolPosterior:
    alpha: float
    beta: float

def choose(rng: random.Random, due: PoolPosterior,
           new: PoolPosterior) -> str:
    theta_due = rng.betavariate(due.alpha, due.beta)
    theta_new = rng.betavariate(new.alpha, new.beta)
    return "due" if theta_due >= theta_new else "new"

def update(post: PoolPosterior, correct: bool) -> PoolPosterior:
    if correct:
        return PoolPosterior(alpha=post.alpha + 1, beta=post.beta)
    return PoolPosterior(alpha=post.alpha, beta=post.beta + 1)
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd app && uv run pytest tests/test_bandit.py -v
```

- [ ] **Step 5: Commit**

```bash
git add lituk/review/bandit.py tests/test_bandit.py
git commit -m "Add Thompson sampling bandit"
```

---

## Task 4: Presenter

**Files:** `app/lituk/review/presenter.py`, `app/tests/test_presenter.py`

- [ ] **Step 1: Write failing tests** (fixture DB with known facts/questions)

Key assertions:
- `build_prompt` returns correct `fact_id`, `question_id`, permuted choices
- Correct indices survive the permutation
- `grade_answer` is order-independent (set equality)
- True/False and multi-answer shapes handled

- [ ] **Step 2–4: Implement and verify**

`build_prompt(conn, fact_id, rng)`:
1. `SELECT` a random `questions` row where `fact_id = ?`
2. Parse `choices` (JSON) and `correct_letters` (JSON)
3. Map letters → indices in the original list
4. Shuffle choices; carry the correct-index set through the permutation
5. Return `Prompt` dataclass

`grade_answer(prompt, user_indices)`:
- Returns `True` iff `set(user_indices) == set(prompt.correct_indices)`

- [ ] **Step 5: Commit**

```bash
git add lituk/review/presenter.py tests/test_presenter.py
git commit -m "Add prompt presenter and grader"
```

---

## Task 5: Session Loop

**Files:** `app/lituk/review/session.py`, `app/tests/test_session.py`

- [ ] **Step 1: Write failing tests** (stub `UI` always answers correctly)

Key scenarios (see `test_session.py` for full code):
- 1-card session writes one `reviews` row, one `card_state` row, updates
  `pool_state`
- Lapsed card reappears within the session, counts toward total
- Empty new pool falls back to due; empty due falls back to new
- `new_cap` is respected
- All pools empty → `SessionResult.total == 0`
- `weak_facts` populated on lapse, empty on all-correct

- [ ] **Step 2–4: Implement `session.py`**

`run_session(conn, today, rng, config, ui, topics=None)`:
- Load due/new pools (filtered by `topics` if provided)
- Load `pool_state` posteriors
- 24-slot loop: lapsed queue → bandit → present → grade → update SM-2 +
  bandit + DB
- Return `SessionResult(correct, total, weak_facts)`

- [ ] **Step 5: Commit**

```bash
git add lituk/review/session.py tests/test_session.py
git commit -m "Add session loop with SM-2 + bandit integration"
```

---

## Task 6: Terminal UI + CLI Entry Point

**Files:** `app/lituk/review/cli.py`, `app/lituk/review/__init__.py`,
`app/lituk/review/__main__.py`, `app/pyproject.toml`,
`app/tests/test_review_cli.py`

- [ ] **Step 1: Write failing tests** (monkeypatch `input()`)

Key scenarios:
- `show_prompt` renders choices, returns valid indices, retries on invalid
  input
- `show_feedback` returns grade on correct, returns 0 on wrong
- `main()` with `--size 1` exits 0, writes at least one `reviews` row
- `--topic` flag accepted and passed through to session

- [ ] **Step 2–4: Implement**

`TerminalUI` renders `--- Card N ---`, choices as A/B/C/D, grade prompt
`[a]gain [h]ard [g]ood [e]asy`.

`main()` wires `init_db → TerminalUI → run_session → sys.exit(0)`.

Register in `pyproject.toml`:
```toml
lituk-review = "lituk.review:main"
```

- [ ] **Step 5: Run full suite with coverage**

```bash
cd app && uv run pytest --cov=lituk --cov-report=term-missing -q
```

Expected: 100% coverage.

- [ ] **Step 6: Commit**

```bash
git add lituk/review/ tests/test_review_cli.py pyproject.toml
git commit -m "Add TerminalUI and lituk-review CLI entry point"
```

---

## Verification

```bash
cd app
uv run pytest --cov=lituk --cov-report=term-missing -q   # 100% coverage
uv run python -m lituk.ingest                             # populate DB
uv run lituk-review --size 5                              # interactive smoke
sqlite3 data/lituk.db "SELECT COUNT(*) FROM reviews;"
sqlite3 data/lituk.db "SELECT * FROM pool_state;"
```
