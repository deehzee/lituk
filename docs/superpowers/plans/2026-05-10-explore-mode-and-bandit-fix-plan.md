# Explore Mode + Bandit Fix — Implementation Plan

## Context

The LITUK study app has two issues with its current review flow:

1. **No pure explore mode.** Regular mode caps new cards per session (`new_cap=5`), which
   throttles users when coverage is low — only 5 of 24 cards introduce new material,
   even when 90% of facts are unexplored. Users need a way to rapidly build coverage
   without that throttle.

2. **The MAB bandit's reward signal is wrong.** The "new" arm is penalised for first-
   exposure misses (structurally unavoidable), so the bandit learns to under-explore. The
   "due" arm is rewarded for correct answers, so it under-exploits cards that need work.
   `new_cap=5` was a blunt workaround that compounds the problem.

This work is delivered in two independent PRs:

- **PR A**: New explore-only session mode, plus a coverage hint shown on the home page
  next to the Explore radio button (updates when chapter filter changes).
- **PR B**: Replace the bandit's accuracy-based signals with signals that reflect actual
  learning need — new arm uses coverage (`Beta(unexplored+1, explored+1)`), due arm uses
  failure rate (`Beta(wrong+1, correct+1)`), both topic-filtered, 30-day recency window.
  Remove `new_cap` and `pool_state`.

The full design rationale is at
`docs/superpowers/specs/2026-05-10-explore-mode-and-bandit-fix-design.md`.

PR A is delivered first because it's self-contained and doesn't touch bandit code.

---

## PR A — Explore Mode + Coverage UI

Branch: `feature/explore-mode`

### Backend changes

**`app/lituk/review/session.py`** — add `run_explore_session` following the structure
of the existing `run_drill_session` (lines 283-329) but using `_new_pool()` instead of
`_drill_pool()`. Pool label in `reviews.pool` is `"new"` (no separate `"explore"`
label). No bandit state loaded or saved. SM-2 updates and within-session lapsed
reinforcement work identically.

Reuse: `_new_pool()` (line 50), `_present_and_grade()` (line 180), `_load_card_state()`,
`_save_card_state()`, `_save_review()`.

**`app/lituk/web/sessions.py`** — import `run_explore_session`; add branch in `worker()`
at line 112-121:
```python
elif mode == "explore":
    run_explore_session(conn, today, rng, config, web_ui,
                        topics=chapters or None, session_id=sid)
```

**`app/lituk/web/routes_review.py`** — extend `_VALID_MODES` at line 8 to include
`"explore"`:
```python
_VALID_MODES = {"regular", "drill", "explore"}
```

**`app/lituk/web/queries.py`** — extend `coverage()` at line 80 to accept
`chapters: list[int] | None = None`. When chapters is truthy, join `card_state` to
`facts` and filter both `facts` count and `card_state` count by topic. Same query
pattern as `missed_reviews()` at lines 121-169.

**`app/lituk/web/routes_stats.py`** — add `/api/coverage` endpoint following the
pattern of `get_missed()` at lines 45-68 for chapter parsing:
```python
@bp.get("/api/coverage")
def get_coverage():
    chapters_raw = request.args.get("chapters")
    chapters = None
    if chapters_raw:
        try:
            chapters = [int(c) for c in chapters_raw.split(",") if c.strip()]
        except ValueError:
            return jsonify(error="chapters must be comma-separated integers"), 400
    conn = _get_conn()
    try:
        return jsonify(queries.coverage(conn, chapters=chapters))
    finally:
        conn.close()
```

### Frontend changes

**`app/lituk/web/static/index.html`** — add a third radio button in the Mode fieldset
(after the existing two at lines 27-34):
```html
<label>
  <input type="radio" name="mode" value="explore">
  Explore (unseen facts) <small id="coverage-hint"></small>
</label>
```

**`app/lituk/web/static/app.js`** — modify `initHome()` (starts at line 14):

1. Inside the existing `/api/dashboard` `.then` handler (line 18), after the due-pill
   logic, populate the initial coverage hint from `d.coverage`:
   ```js
   document.getElementById("coverage-hint").textContent =
     "— " + d.coverage.seen + " / " + d.coverage.total +
     " explored (" + d.coverage.pct_seen + "%)";
   ```

2. Define `updateCoverageHint()` inside `initHome()`:
   ```js
   function updateCoverageHint() {
     const boxes = Array.from(
       document.querySelectorAll("input[name=chapters]:checked")
     ).map(b => b.value);
     const url = boxes.length
       ? "/api/coverage?chapters=" + boxes.join(",")
       : "/api/coverage";
     fetch(url).then(r => r.json()).then(d => {
       document.getElementById("coverage-hint").textContent =
         "— " + d.seen + " / " + d.total + " explored (" + d.pct_seen + "%)";
     }).catch(() => {});
   }
   ```

3. Inside the existing `fetch("/api/topics")` `.then` handler (line 27-37), after the
   `forEach` loop that appends checkboxes, attach a delegated change listener to the
   container:
   ```js
   container.addEventListener("change", updateCoverageHint);
   ```

### Tests

**`app/tests/test_session.py`** — add tests for `run_explore_session`:
- Empty `_new_pool` exits early (`total < size`)
- One unexplored fact → session writes `card_state` row, `reviews` row with `pool="new"`
- Wrong answer pushes fact to lapsed queue and is re-shown within session
- Topic filter restricts the pool to the requested chapters

**`app/tests/test_web_routes_review.py`** — add: `POST /api/sessions` with
`{"mode": "explore"}` returns a `session_id`.

**`app/tests/test_web_queries.py`** — add: `coverage(conn, chapters=[1])` filters
correctly; `coverage(conn, chapters=None)` matches the existing global behaviour.

**`app/tests/test_web_routes_stats.py`** — add: `GET /api/coverage` (no filter),
`GET /api/coverage?chapters=1,2` (valid filter), `GET /api/coverage?chapters=bad`
(400 error).

**`app/tests/test_web_e2e.py`** — add an explore-mode smoke test mirroring
`test_e2e_drill_session_after_lapses` (lines 134-167): ingest a PDF, start an
explore session, drive it to completion via the stub UI loop, assert `card_state`
rows were written for the previously unexplored facts.

### Commit structure for PR A

Per user feedback in memory: one commit per module + its tests, not one giant commit.
Order:
1. `queries.coverage` topic filter + tests
2. `/api/coverage` endpoint + tests
3. `run_explore_session` + tests
4. `sessions.py` and `routes_review.py` wiring + tests
5. Frontend (`index.html` + `app.js`) + e2e test

### Verification (PR A)

```bash
cd app
uv sync
uv run pytest -q                                       # all green
uv run pytest --cov=lituk --cov-report=term-missing    # 100% coverage
uv run lituk-web                                       # start server
# Open http://localhost:5000 in browser:
#  - Confirm "Explore (unseen facts) — N / M explored (X%)" appears
#  - Tick chapter checkboxes, hint updates with topic-filtered coverage
#  - Pick Explore mode, start a session, complete a card, verify reviews.pool='new'
sqlite3 data/lituk.db \
  "SELECT pool, COUNT(*) FROM reviews GROUP BY pool;"
```

---

## PR B — Bandit Fix

Branch: `feature/bandit-fix` (off `main` after PR A merges)

### Backend changes

**`app/lituk/db.py`** — remove `pool_state` from `_SCHEMA` (lines 44-48) and remove
`_POOL_SEED` (lines 73-76) and its `executescript` call in `init_db` (line 87 or
nearby — confirm with code).

Existing DBs retain the `pool_state` table with stale rows (harmless, orphaned). No
`DROP TABLE` migration — the user explicitly wants existing learning state preserved
across schema changes (see memory: DB migration policy).

**`app/lituk/review/bandit.py`** — remove `update()` function (no longer needed).
Keep `PoolPosterior` dataclass and `choose()` function.

**`app/lituk/review/session.py`** — major changes inside `run_session`:

1. Remove `_load_posteriors()` and `_save_posteriors()` helpers (lines 81-107).

2. Add `_compute_posteriors(conn, today, topics) -> (due_post, new_post)` that runs two
   DB queries:
   - Counts: `n_total` (facts), `n_explored` (card_state rows), `n_unexplored = n_total
     - n_explored`. All optionally filtered by topic.
   - Failure rate: `SUM(CASE WHEN correct=0)` and `SUM(CASE WHEN correct=1)` from
     `reviews` where `pool IN ('due','lapsed','drill')` AND `date(reviewed_at) >= today
     - 30 days`, optionally joined to facts for topic filter.
   - Returns `(PoolPosterior(n_wrong+1, n_correct+1), PoolPosterior(n_unexplored+1,
     n_explored+1))`.

3. In `run_session`, replace `_load_posteriors(conn)` with
   `_compute_posteriors(conn, today, topics)`.

4. Track `n_unexplored`, `n_wrong`, `n_correct` in-memory throughout the session loop.
   After each card, recompute posteriors in-memory (no DB writes):
   - When `pool_label == "new"`: `n_unexplored -= 1`, `n_explored += 1`
   - When `pool_label in ("due", "lapsed")` (drill mode handled by `run_drill_session`,
     not relevant here): on correct → `n_correct += 1`; on wrong → `n_wrong += 1`

5. Remove the `_save_posteriors(conn, due_post, new_post)` call (line 264).

6. Remove `bandit_update` import (line 9) and all `bandit_update` call sites.

**`app/lituk/review/session.py`** — also update `SessionConfig`:
```python
@dataclass(frozen=True)
class SessionConfig:
    size: int = 24
    # new_cap removed
```

Remove the `new_cap` check inside `run_session` (line 236 reference to
`new_drawn < config.new_cap`). The new-arm logic falls back to picking from `new`
whenever `due` is empty, and vice versa.

**`app/lituk/review/__init__.py`** — remove `--new-cap` argument from argparse (lines
34-37) and the `new_cap=parsed.new_cap` kwarg passed to `SessionConfig` (line 48).

**Need to add** `from datetime import timedelta` to `session.py` imports for the
30-day cutoff calculation.

### Tests to update

**`app/tests/test_bandit.py`** — remove `update()` tests. Keep `PoolPosterior` and
`choose()` tests; add tests verifying `choose` selects the higher-α arm under fixed
seeds (which represents either coverage signal or failure signal — the choose function
doesn't care which interpretation).

**`app/tests/test_session.py`** — remove:
- `test_one_card_session_updates_pool_state` (around line 128-135)
- `test_drill_session_does_not_update_pool_state` (around line 515-529)
- Any `new_cap` tests

Add:
- `test_compute_posteriors_no_topics` — DB with N facts, M explored, K wrong & K' right
  due-pool reviews in last 30 days → returns expected Beta params.
- `test_compute_posteriors_with_topics` — same, filtered to one chapter.
- `test_compute_posteriors_excludes_old_reviews` — review > 30 days old not counted.
- `test_compute_posteriors_excludes_new_pool_reviews` — review with `pool='new'` not
  counted toward due arm.
- `test_run_session_no_new_cap` — session with 30 unexplored facts, 0 due, can fill
  all 24 slots with new cards (no longer capped at 5).
- `test_run_session_updates_in_memory_counts` — verify mid-session bandit choices
  reflect updated counts.

**`app/tests/test_db.py`** — remove:
- `test_init_db_seeds_pool_state`
- `test_init_db_pool_state_idempotent`
- `"pool_state" in tables` assertion in `test_init_db_creates_review_tables`

**`app/tests/test_web_e2e.py`** — remove `test_e2e_regular_session_pool_state_moves`
(around lines 81-90). Add a replacement that verifies the new behaviour: after a
session, query `card_state` and `reviews` tables to confirm SM-2 state is correct
and bandit posteriors are derivable from DB state.

**`app/tests/test_review_cli.py`** — remove any `--new-cap` argument tests.

### Commit structure for PR B

1. Remove `pool_state` from schema + update db tests
2. Add `_compute_posteriors` + tests
3. Refactor `run_session` to use new posteriors + remove `_save_posteriors`/`new_cap`
4. Remove `bandit.update` + clean up `test_bandit.py`
5. Remove `--new-cap` from CLI + tests

### Verification (PR B)

```bash
cd app
uv sync
uv run pytest -q                                       # all green
uv run pytest --cov=lituk --cov-report=term-missing    # 100% coverage
uv run lituk-web                                       # start server
# Manual smoke:
#  - Fresh DB: regular session should be mostly new cards (high θ_new)
#  - After ~50% explored: balance shifts noticeably
#  - High accuracy on due cards: bandit favours new (you're beating it)
sqlite3 data/lituk.db "SELECT COUNT(*) FROM pool_state;"
# In a NEW DB: error "no such table" expected
# In existing DB: still shows old rows (harmless)
```

---

## Files to modify

### PR A
- `app/lituk/review/session.py` — add `run_explore_session`
- `app/lituk/web/sessions.py` — dispatch `"explore"` mode
- `app/lituk/web/routes_review.py` — `_VALID_MODES`
- `app/lituk/web/queries.py` — `coverage()` topic filter
- `app/lituk/web/routes_stats.py` — `/api/coverage` endpoint
- `app/lituk/web/static/index.html` — Explore radio + hint span
- `app/lituk/web/static/app.js` — coverage hint logic
- `app/tests/test_session.py`, `test_web_routes_review.py`, `test_web_queries.py`,
  `test_web_routes_stats.py`, `test_web_e2e.py`

### PR B
- `app/lituk/db.py` — remove `pool_state` from schema/seed
- `app/lituk/review/bandit.py` — remove `update()`
- `app/lituk/review/session.py` — `_compute_posteriors`, drop `_load`/`_save`,
  in-memory tracking, remove `new_cap`
- `app/lituk/review/__init__.py` — remove `--new-cap` CLI flag
- `app/tests/test_db.py`, `test_bandit.py`, `test_session.py`, `test_web_e2e.py`,
  `test_review_cli.py`

---

## Sequencing & process

Per memory feedback:
- Feature branch + worktree + PR workflow for each PR
- Small commits with tests (one commit per module + its tests, not one big commit)
- PR A merges to main before PR B branches off
