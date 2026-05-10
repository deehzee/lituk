# Explore Mode + Bandit Fix — Design Spec

Date: 2026-05-10

## Context

The LITUK study app has a regular session mode (SM-2 + Thompson-sampling bandit) and a
drill mode (historically weak cards). Two problems motivate this work:

1. **No pure explore mode.** When coverage is low, the user has no way to rapidly work
   through unseen facts without the bandit throttling them to 5 new cards per session.

2. **Bandit is miscalibrated from the start.** The "new" arm's reward signal is
   first-exposure accuracy, which is structurally low (you've never seen the card). The
   bandit learns "new arm → low reward → avoid" even when exploration is exactly what's
   needed. `new_cap=5` was a blunt workaround. The correct fix is to use signals that
   reflect actual learning need, not raw accuracy.

These are delivered as two independent PRs in dependency order.

---

## PR A — Explore Mode + Coverage UI

### What it does

Adds a new session mode that draws exclusively from unseen facts (no `card_state` row).
No bandit, no cap. Fills the session up to `config.size` (default 24). SM-2 updates and
within-session lapsed reinforcement work identically to regular and drill modes.

Also surfaces the explored coverage % on the home page, next to the Explore mode option,
updating dynamically as the chapter filter changes.

### Backend — `session.py`

New function `run_explore_session`, mirroring `run_drill_session` in structure:

```python
def run_explore_session(
    conn, today, rng, config, ui,
    topics=None, session_id=None,
) -> SessionResult:
    pool = _new_pool(conn, topics)
    rng.shuffle(pool)
    lapsed = deque()
    # ... same loop as run_drill_session, pool_label = "new"
```

- Pool: `_new_pool(conn, topics)` — facts with no `card_state` row
- Pool label stored in `reviews.pool`: `"new"` — no new label needed, same as bandit-
  chosen new cards
- No bandit state read or written
- `SessionConfig.new_cap` is not consulted (all slots go to new cards, subject only to
  `config.size`)

### Backend — `sessions.py`

Add `"explore"` to the worker dispatch:

```python
elif mode == "explore":
    run_explore_session(conn, today, rng, config, web_ui,
                        topics=chapters or None, session_id=sid)
```

### Backend — `routes_review.py`

```python
_VALID_MODES = {"regular", "drill", "explore"}
```

### Backend — `queries.py`

Extend `coverage()` to accept an optional topic filter:

```python
def coverage(
    conn: sqlite3.Connection,
    chapters: list[int] | None = None,
) -> dict:
    topic_sql = (
        f" WHERE f.topic IN ({','.join('?' * len(chapters))})"
        if chapters else ""
    )
    total = conn.execute(
        f"SELECT COUNT(*) FROM facts f{topic_sql}",
        list(chapters) if chapters else [],
    ).fetchone()[0]
    seen_sql = (
        "SELECT COUNT(*) FROM card_state cs"
        " JOIN facts f ON f.id = cs.fact_id" + topic_sql
    )
    seen = conn.execute(
        seen_sql, list(chapters) if chapters else []
    ).fetchone()[0]
    pct = (seen / total * 100.0) if total > 0 else 0.0
    return {"seen": seen, "total": total, "pct_seen": round(pct, 1)}
```

The existing `/api/dashboard` call to `queries.coverage(conn)` remains unchanged (no
chapters filter → global coverage).

### Backend — `routes_stats.py`

New endpoint:

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

### Frontend — `index.html`

Add Explore radio button to the mode fieldset, with a coverage hint span:

```html
<fieldset>
  <legend>Mode</legend>
  <label>
    <input type="radio" name="mode" value="regular" checked>
    Regular (SM-2 + bandit)
  </label>
  <label>
    <input type="radio" name="mode" value="drill">
    Drill (missed facts only)
  </label>
  <label>
    <input type="radio" name="mode" value="explore">
    Explore (unseen facts) <small id="coverage-hint"></small>
  </label>
</fieldset>
```

### Frontend — `app.js`

**Coverage hint helper** — add `updateCoverageHint()` inside `initHome()`:

```js
function updateCoverageHint() {
  const boxes = Array.from(
    document.querySelectorAll("input[name=chapters]:checked")
  ).map(b => b.value);
  const url = boxes.length
    ? "/api/coverage?chapters=" + boxes.join(",")
    : "/api/coverage";
  fetch(url)
    .then(r => r.json())
    .then(d => {
      document.getElementById("coverage-hint").textContent =
        "— " + d.seen + " / " + d.total + " explored (" + d.pct_seen + "%)";
    })
    .catch(() => {});
}
```

**On load:** the existing `/api/dashboard` fetch already runs on load. Reuse it to
populate the initial hint (global coverage) without an extra request — add to its
`.then` handler:

```js
document.getElementById("coverage-hint").textContent =
  "— " + d.coverage.seen + " / " + d.coverage.total +
  " explored (" + d.coverage.pct_seen + "%)";
```

**On chapter change:** attach a `change` listener to the `#chapter-checks` container
(event delegation covers dynamically created checkboxes) inside the existing
`fetch("/api/topics")` callback, after checkboxes are appended:

```js
container.addEventListener("change", updateCoverageHint);
```

This fires `updateCoverageHint()` on every checkbox tick, calling `/api/coverage`
with the current selection and updating `#coverage-hint`.

### Tests

- `test_session.py`: `run_explore_session` — empty pool exits early; facts get
  `card_state` rows; wrong answers come back within session; pool label is `"new"`.
- `test_web_routes_review.py`: `POST /api/sessions` with `mode=explore` succeeds.
- `test_web_queries.py`: `coverage()` with and without chapter filter.
- `test_web_routes_stats.py`: `GET /api/coverage` — no filter, with filter, bad filter.
- `test_web_e2e.py`: explore session smoke test (ingest + run explore session, assert
  `card_state` rows written).

---

## PR B — Bandit Fix

### Problem statement

The current bandit stores `alpha`/`beta` per arm in `pool_state` and updates them based
on raw accuracy:

- New arm: penalised for first-exposure misses → bandit learns to avoid exploration
- Due arm: rewarded for correct answers → bandit learns to exploit even when retention
  is already good

The fix: use signals that reflect *remaining learning need*, not raw accuracy.

### New reward signals

| arm  | posterior | meaning |
|------|-----------|---------|
| new  | `Beta(n_unexplored + 1, n_explored + 1)` | more unseen → arm wins more |
| due  | `Beta(n_wrong + 1, n_correct + 1)` | more failures → arm wins more |

**New arm:** θ_new declines naturally as coverage grows. At 0% explored θ_new ≈ 1.0;
at 90% explored θ_new ≈ 0.1. No explicit cap needed.

**Due arm:** θ_due reflects current retention difficulty. When you're passing due cards
easily (high correct), θ_due is low → bandit explores more. When you're struggling
(high wrong), θ_due is high → bandit exploits more.

Example outcomes with 1000 total facts:

| coverage | retention | θ_new (mean) | θ_due (mean) | favours |
|----------|-----------|-------------|-------------|---------|
| 0%       | —         | ≈ 1.00      | ≈ 0.50      | new     |
| 10%      | 70% correct | ≈ 0.90   | ≈ 0.30      | new     |
| 50%      | 70% correct | ≈ 0.50   | ≈ 0.30      | new     |
| 50%      | 40% correct | ≈ 0.50   | ≈ 0.60      | due     |
| 90%      | 95% correct | ≈ 0.10   | ≈ 0.05      | new (finish exploring) |
| 90%      | 50% correct | ≈ 0.10   | ≈ 0.50      | due     |

### Topic filtering

Both posteriors are conditioned on the active topic filter. When `--topic 2` is active,
only facts and reviews belonging to chapter 2 are counted. This ensures the bandit
reflects coverage and retention within the current study set, not globally.

### Recency window for due arm

The due arm uses the last 30 days of reviews to avoid over-concentrating the posterior
as historical counts accumulate. Only reviews with `pool IN ('due', 'lapsed', 'drill')`
count — first-exposure reviews (`pool = 'new'`) are excluded.

### Persistence

Posteriors are not stored — they are derived views of the DB state. Persistence across
sessions is implicit: as more cards are explored and more reviews accumulate, the next
session's fresh computation naturally reflects updated learning state.

### Changes to `bandit.py`

- `PoolPosterior` dataclass and `choose()` function: unchanged
- `update()` function: **removed** — no longer needed; posteriors are computed from DB
  counts, not updated incrementally from outcomes

### Changes to `session.py`

Remove `_load_posteriors()` and `_save_posteriors()`. Replace with two DB queries at
session start:

```python
def _compute_posteriors(
    conn, today, topics=None
) -> tuple[PoolPosterior, PoolPosterior]:
    topic_join = (
        " JOIN facts f ON f.id = cs.fact_id"
        f" WHERE f.topic IN ({','.join('?' * len(topics))})"
        if topics else ""
    )
    topic_params = list(topics) if topics else []

    # new arm: coverage
    n_explored = conn.execute(
        f"SELECT COUNT(*) FROM card_state cs{topic_join}", topic_params
    ).fetchone()[0]
    n_total = conn.execute(
        "SELECT COUNT(*) FROM facts"
        + (f" WHERE topic IN ({','.join('?' * len(topics))})" if topics else ""),
        topic_params,
    ).fetchone()[0]
    n_unexplored = n_total - n_explored

    # due arm: failure rate (last 30 days, seen cards only)
    due_topic_filter = (
        f" AND f.topic IN ({','.join('?' * len(topics))})" if topics else ""
    )
    cutoff = (today - timedelta(days=30)).isoformat()
    row = conn.execute(
        "SELECT SUM(CASE WHEN r.correct=0 THEN 1 ELSE 0 END) AS wrong,"
        "       SUM(CASE WHEN r.correct=1 THEN 1 ELSE 0 END) AS correct"
        " FROM reviews r JOIN facts f ON f.id = r.fact_id"
        f" WHERE r.pool IN ('due','lapsed','drill')"
        f"   AND date(r.reviewed_at) >= ?{due_topic_filter}",
        [cutoff] + topic_params,
    ).fetchone()
    n_wrong = row["wrong"] or 0
    n_correct = row["correct"] or 0

    return (
        PoolPosterior(alpha=n_unexplored + 1, beta=n_explored + 1),
        PoolPosterior(alpha=n_wrong + 1, beta=n_correct + 1),
    )
```

Mid-session updates: track `n_unexplored`, `n_wrong`, `n_correct` in-memory. After each
card, recompute posteriors from updated in-memory counts (no DB queries mid-session).

### Changes to `db.py`

- Remove `pool_state` `CREATE TABLE` and `CREATE INDEX` from `_SCHEMA`
- Remove `INSERT OR IGNORE INTO pool_state` seed rows from `init_db`
- Existing DBs: orphaned `pool_state` table and rows are left in place — harmless, and
  no migration is needed. `card_state` and `reviews` data is preserved intact.

### Changes to `SessionConfig`

```python
@dataclass(frozen=True)
class SessionConfig:
    size: int = 24
    # new_cap removed
```

### Changes to CLI (`__init__.py`)

Remove `--new-cap` argument.

### Tests

- `test_bandit.py`: remove `update()` tests; add tests for `choose()` with coverage-
  and failure-rate posteriors.
- `test_session.py`: remove `new_cap`-related tests; add tests for
  `_compute_posteriors()` — correct counts with and without topic filter; verify new arm
  weakens as explored count grows; verify due arm strengthens as wrong count grows.
- `test_db.py`: remove `pool_state` seed assertions.
- `test_review_cli.py`: remove `--new-cap` tests.

---

## Implementation order

1. **PR A** — explore mode + coverage UI (no bandit changes, self-contained)
2. **PR B** — bandit fix (builds on existing session machinery, no UI changes)
