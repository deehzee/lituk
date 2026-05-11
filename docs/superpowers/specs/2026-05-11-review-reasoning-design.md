# Review Reasoning Display — Design Spec

**Issue:** #16
**Date:** 2026-05-11
**Status:** Approved

## Overview

When a card is chosen during a review session, surface the reasoning behind
that choice to the user. In CLI mode this appears as a dim grey line just
before the question. In web mode it appears as a print line on the terminal
running `lituk-web`.

Explore mode emits no reasoning (selection is random from unseen cards; nothing
to explain).

---

## Architecture & Data Flow

Changes across four files:

```
run_session loop
  _select_card(rng, lapsed, due, new, due_post, new_post, conn, today)
    → choose_with_samples()         # get θ_due, θ_new, arm
    → DB query for card stats       # ease/overdue (due) or lapses/last_seen (lapsed)
    → returns Selection
  ui.show_reasoning(sel.reasoning)
  _present_and_grade(...)
```

---

## Component Changes

### 1. `bandit.py` — expose Thompson samples

Add `choose_with_samples` returning the sampled θ values alongside the arm
decision. Rewrite `choose` as a thin wrapper so existing callers are unchanged.

```python
def choose_with_samples(
    rng: random.Random, due: PoolPosterior, new: PoolPosterior
) -> tuple[str, float, float]:   # arm, theta_due, theta_new
    theta_due = rng.betavariate(due.alpha, due.beta)
    theta_new = rng.betavariate(new.alpha, new.beta)
    return ("due" if theta_due >= theta_new else "new"), theta_due, theta_new


def choose(rng: random.Random, due: PoolPosterior, new: PoolPosterior) -> str:
    arm, _, _ = choose_with_samples(rng, due, new)
    return arm
```

### 2. `session.py` — `Selection` dataclass + `_select_card`

New frozen dataclass:

```python
@dataclass(frozen=True)
class Selection:
    fact_id: int
    pool_label: str
    reasoning: str
    new_post: PoolPosterior  # updated when new arm chosen; else unchanged
```

New function `_select_card(rng, lapsed, due, new, due_post, new_post, conn,
today) -> Selection | None` (None only when all pools are empty). It mutates
`lapsed`/`due`/`new` in-place (pops the chosen card) and composes the
reasoning string.

`run_session` loop updated to:

```python
sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, today)
if sel is None:
    break
new_post = sel.new_post
ui.show_reasoning(sel.reasoning)
correct, _ = _present_and_grade(conn, today, ui, sel.fact_id,
                                sel.pool_label, rng, session_id)
```

New helper `_drill_reasoning(conn, fact_id, today) -> str` for drill mode
(queries `card_state` for lapses, last_reviewed_at, and most recent wrong
review).

### 3. `UI` Protocol + implementations

New method added to the `UI` Protocol:

```python
def show_reasoning(self, text: str) -> None: ...
```

Called once per card immediately before `show_prompt`. Not called in explore
mode.

**`TerminalUI`:**

```python
def show_reasoning(self, text: str) -> None:
    print(f"\033[2m  {text}\033[0m")   # ANSI dim (grey)
```

**`WebUI`:**

```python
def show_reasoning(self, text: str) -> None:
    print(f"  → {text}", flush=True)   # appears on server terminal
```

Note: the codebase uses `print()` throughout; logging is deferred to issue #25.

---

## Reasoning Strings

### Regular mode (`run_session`)

| Case | Format |
|------|--------|
| Lapsed card | `Lapsed: failed this session \| lapses=3, last seen 5d ago` |
| MAB → due (both pools available) | `MAB: θ_due=0.72(α=6,β=3) > θ_new=0.41(α=4,β=5) → due \| 8 due, 312 new \| ease=2.10, overdue 3d` |
| MAB → new (both pools available) | `MAB: θ_new=0.63(α=4,β=2) > θ_due=0.51(α=6,β=5) → new \| 312 new, 8 due` |
| Due only (no unseen cards) | `Due only (no unseen) \| ease=2.10, overdue 3d` |
| New only (no due cards) | `New only (no due) \| 312 unseen remaining` |

### Drill mode (`run_drill_session`)

```
Drill: lapses=3, last seen 5d ago, last wrong 7d ago
```

### Explore mode (`run_explore_session`)

No reasoning emitted. Selection is random from unseen; nothing to explain.

---

## DB Queries for Per-Card Stats

**Lapsed card** (regular mode):

```sql
SELECT lapses, last_reviewed_at FROM card_state WHERE fact_id = ?
```

Days since last seen = `(today - last_reviewed_at.date()).days`.

**Due card** (regular mode):

```sql
SELECT ease_factor, due_date FROM card_state WHERE fact_id = ?
```

Overdue days = `(today - due_date).days`.

**Drill card**:

```sql
SELECT lapses, last_reviewed_at FROM card_state WHERE fact_id = ?
```

Last wrong:

```sql
SELECT reviewed_at FROM reviews
WHERE fact_id = ? AND correct = 0
ORDER BY reviewed_at DESC LIMIT 1
```

Days since last wrong = `(today - reviewed_at.date()).days`.

---

## Testing

### `test_bandit.py`

- `choose_with_samples` returns the correct arm and θ values consistent with
  which draw was larger.

### `test_session.py`

- `_select_card` unit tests: real in-memory DB, fixed-seed RNG. One test per
  case (lapsed, MAB→due, MAB→new, due-only, new-only). Assert `pool_label`
  and key substrings in `reasoning`.
- `_drill_reasoning` with seeded `card_state` and `reviews` rows. Assert on
  lapses, last-seen days, last-wrong days.
- Existing session integration tests updated: `StubUI.reasonings` asserts
  `show_reasoning` is called once per card shown.

### `test_review_cli.py`

- `TerminalUI.show_reasoning` emits ANSI dim codes around the text
  (captured via `capsys`).

### `test_web_sessions.py`

- `WebUI.show_reasoning` prints to stdout with `→` prefix (captured via
  `capsys`).

### `StubUI` update

```python
def show_reasoning(self, text: str) -> None:
    self.reasonings.append(text)
```

---

## Out of Scope

- Logging infrastructure (tracked in issue #25)
- Reasoning in explore mode
- Persisting reasoning strings to the database
