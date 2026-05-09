# Review Engine — Design Spec

**Date:** 2026-05-09
**Status:** Implemented (PR #2 + PR #3)

## Overview

A spaced-repetition review engine that pairs SM-2 (per-fact scheduling) with
a Thompson-sampling multi-armed bandit (session-level pool selection). Sessions
are fixed at 24 cards (matching the real LITUK exam). Facts answered wrong
during a session are immediately re-queued for reinforcement.

---

## 1. Architecture

Three pools, one selection rule per slot:

```
For each of 24 slots in a session:
  if lapsed-in-session queue non-empty:
      pop oldest from lapsed queue (mandatory)
  else:
      Thompson-sample θ_due, θ_new
      pick the higher → pull from that pool
  present prompt → grade → update state
  if wrong: push fact onto lapsed queue
```

**Pool definitions:**
- **Lapsed** — facts answered wrong earlier this session. Mandatory; counts
  toward the 24-card total.
- **Due** — facts with `card_state.due_date <= today`. Ordered by
  `(ease_factor ASC, due_date ASC)` — weakest and most-overdue first.
- **New** — facts with no `card_state` row yet. Capped at `new_cap`
  (default 5) per session to avoid overwhelm.

If the chosen pool is empty the engine falls back to the other (still
respecting `new_cap`). If all three are empty the session ends early.

---

## 2. SM-2 Scheduler (`scheduler.py`)

Standard SM-2 with lapse tracking.

```
grade 0 (Again / wrong):
    ease -= 0.2  (floor 1.3)
    interval = 1
    repetitions = 0
    lapses += 1

grade 3 (Hard):
    ease -= 0.15  (floor 1.3)
    interval: 1 → 6 → round(prev × ease)
    repetitions += 1

grade 4 (Good):
    ease unchanged
    interval: 1 → 6 → round(prev × ease)
    repetitions += 1

grade 5 (Easy):
    ease += 0.10
    interval: 1 → 6 → round(prev × ease)
    repetitions += 1

due_date = today + interval
```

### On miss (wrong answer)

The engine auto-grades 0 — no button shown; the UI reveals the correct
answer. The grade button (Again/Hard/Good/Easy) only appears on a correct
answer.

---

## 3. Bandit (`bandit.py`)

Thompson sampling with a Beta-Bernoulli model. Two arms: `due` and `new`.

```
Prior: Beta(1, 1) — uniform (seeded in pool_state table)

On each draw:
    sample θ_due ~ Beta(α_due, β_due)
    sample θ_new ~ Beta(α_new, β_new)
    choose the higher

After result:
    correct → α += 1
    wrong   → β += 1
```

`pool_state` is persisted to SQLite so the bandit carries learning across
sessions.

---

## 4. Presenter (`presenter.py`)

For each fact shown, a random `questions` row with that `fact_id` is selected
(so distractors vary between sessions). Choice order is shuffled; correct
indices are carried through the permutation.

Multi-answer facts require the user to select all correct choices; grading is
set-equality (order-independent).

---

## 5. Schema

### `card_state`

```sql
CREATE TABLE IF NOT EXISTS card_state (
    fact_id          INTEGER PRIMARY KEY REFERENCES facts(id),
    ease_factor      REAL    NOT NULL DEFAULT 2.5,
    interval_days    INTEGER NOT NULL DEFAULT 0,
    repetitions      INTEGER NOT NULL DEFAULT 0,
    due_date         TEXT    NOT NULL,            -- ISO date
    last_reviewed_at TEXT,                        -- ISO datetime
    lapses           INTEGER NOT NULL DEFAULT 0
);
```

### `pool_state`

```sql
CREATE TABLE IF NOT EXISTS pool_state (
    pool  TEXT PRIMARY KEY,   -- 'due' or 'new'
    alpha REAL NOT NULL DEFAULT 1.0,
    beta  REAL NOT NULL DEFAULT 1.0
);
```

Seeded with `('due', 1.0, 1.0)` and `('new', 1.0, 1.0)` on `init_db`.

### `reviews`

```sql
CREATE TABLE IF NOT EXISTS reviews (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id        INTEGER NOT NULL REFERENCES facts(id),
    question_id    INTEGER NOT NULL REFERENCES questions(id),
    reviewed_at    TEXT    NOT NULL,
    grade          INTEGER NOT NULL,    -- 0 / 3 / 4 / 5
    correct        INTEGER NOT NULL,    -- 0 or 1
    pool           TEXT    NOT NULL,    -- 'due' | 'new' | 'lapsed'
    ease_after     REAL    NOT NULL,
    interval_after INTEGER NOT NULL
);
```

---

## 6. Module Layout

```
app/lituk/review/
    __init__.py     # main() — argparse CLI entry
    __main__.py     # python -m lituk.review shim
    scheduler.py    # SM-2 (pure: no DB, no I/O)
    bandit.py       # Thompson sampling (pure)
    presenter.py    # prompt building + grading (reads DB, pure otherwise)
    session.py      # session loop; injected UI protocol
    cli.py          # TerminalUI: stdin/stdout implementation
```

`scheduler.py` and `bandit.py` are pure functions. `session.py` orchestrates
and writes state. `cli.py` implements the `UI` protocol so the same session
loop drives a future web UI without changes.

---

## 7. Topic Filtering

`run_session` accepts an optional `topics: list[int] | None` parameter.
When set, both the due and new pool queries add `AND f.topic IN (...)`.
Facts with `topic IS NULL` are excluded when a filter is active. The lapsed
queue is unaffected — once a fact is in the session it stays.

---

## 8. CLI Reference

See `docs/cli.md` for full flag documentation.

```
lituk-review                       # all topics, 24 cards
lituk-review --topic 3             # history only
lituk-review --topic 3,4 --size 5  # history + society, 5 cards
```
