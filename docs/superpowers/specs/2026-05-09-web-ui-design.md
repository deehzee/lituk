# Web UI — Design Spec

**Date:** 2026-05-09
**Status:** Planned (PR pending)

## Overview

A browser-based study interface served from localhost. The web UI reuses the
existing `lituk.review` session core — the same `run_session` loop and SM-2 +
bandit engine that drives the CLI — by implementing the `UI` protocol behind
an HTTP bridge. No changes are needed to `scheduler.py`, `bandit.py`, or
`presenter.py`.

Three entry points: review sessions, a missed-questions view with drill mode,
and a stats dashboard.

Out of scope: web UI for ingest or tag (CLI only); multi-user / auth;
streak calendar; due-forecast charts.

---

## 1. Architecture

### 1.1 Sync-to-HTTP bridge (worker thread per session)

The existing `run_session` is a synchronous blocking loop. Each HTTP session
runs in a worker thread. The `WebUI` class implements the `UI` protocol using
two `queue.Queue` objects:

```
Browser            Flask             Worker thread
-------            -----             -------------
POST /api/sessions  →  spawn thread  run_session(conn, ..., web_ui)
                                           │
GET  .../state      →  read WebUI    show_prompt(p):
                   ←  {kind:'prompt'}    state = prompt; BLOCK on answer_q
POST .../answer     →  answer_q.put(idx)
                                     (unblocks) → show_feedback(p, correct):
GET  .../state      ←  {kind:'feedback'}   state = feedback; BLOCK on grade_q
POST .../grade      →  grade_q.put(g)
                                     (unblocks) → … next card or show_summary
GET  .../state      ←  {kind:'summary'}
```

Polling interval: 300 ms (`setInterval` in the browser). Single-user
localhost; efficiency is not a concern.

### 1.2 State model

```python
@dataclass
class WebState:
    kind:    str   # 'starting' | 'prompt' | 'feedback' | 'summary' | 'ended'
    payload: dict  # JSON-serialisable; 'prompt' payload never includes
                   # correct_indices (server strips them before setting state)
    version: int   # increments on every transition; client skips re-render
                   # if version unchanged
```

### 1.3 Session lifecycle

- **Start**: `POST /api/sessions {mode, chapters}` → server creates UUID,
  `WebUI`, worker thread; stores in `SESSIONS[uuid]`; returns `{session_id}`.
- **Drive**: client polls `GET /api/sessions/{id}/state`; renders based on
  `kind`.
- **Submit answer**: `POST /api/sessions/{id}/answer {indices: [...]}`.
- **Submit grade**: `POST /api/sessions/{id}/grade {grade: 3|4|5}`. On a
  miss the client still calls this endpoint (server ignores the value; the
  loop already forced grade 0).
- **End**: when `kind == 'summary'`, worker thread has exited.
- **Cleanup**: a janitor thread (60 s interval) drops sessions with
  `last_activity > 30 min`.

### 1.4 Concurrent sessions

Two browser tabs carry different `session_id` values; each session has its
own `WebUI` and DB connection. SQLite's default serialisation handles two
concurrent writers without configuration.

---

## 2. Drill Mode

A drill session pulls only from the *missed-fact pool*: facts with
`card_state.lapses > 0`, ordered by `lapses DESC, last_reviewed_at ASC`.

Key differences from a regular session:

| | Regular | Drill |
|---|---|---|
| Pool selection | Thompson-sampling bandit | Missed-fact pool, no bandit |
| `reviews.pool` value | `'due'` / `'new'` / `'lapsed'` | `'drill'` |
| SM-2 update | ✓ | ✓ (same `sm2_update` call) |
| Bandit posteriors updated | ✓ | ✗ |
| Session size | 24 (configurable) | 24, or end early if fewer misses |
| Lapsed-in-session queue | ✓ | ✓ |

Implementation: new function `run_drill_session(conn, today, rng, config,
ui, topics=None, session_id=None)` in `session.py`. Both `run_session` and
`run_drill_session` share a private helper `_present_and_grade(...)` to
avoid duplication.

---

## 3. Schema Additions

### `reviews.session_id` (migration)

```sql
ALTER TABLE reviews ADD COLUMN session_id TEXT;
CREATE INDEX IF NOT EXISTS idx_reviews_session ON reviews(session_id);
```

Applied conditionally in `init_db` via `PRAGMA table_info(reviews)` check —
idempotent. Existing rows get `NULL`; stats queries treat `NULL` as
"ungrouped historic review".

The CLI (`lituk-review`, `lituk-tag`) generates a UUID per session and
passes it through so CLI sessions also appear on the dashboard.

---

## 4. Module Layout

New package `app/lituk/web/` mirroring `app/lituk/review/`:

```
app/lituk/web/
    __init__.py        # create_app() Flask factory; registers blueprints
    __main__.py        # python -m lituk.web shim
    server.py          # main(): argparse + app.run(host='127.0.0.1')
    sessions.py        # WebUI, SESSIONS dict, janitor thread
    routes_review.py   # /api/sessions, /state, /answer, /grade
    routes_stats.py    # /api/dashboard, /api/missed, /api/topics
    queries.py         # pure SQL helpers (no Flask imports)
    static/
        pico.min.css   # vendored Pico.css ~10 KB (Apache 2.0)
        app.css        # ~50 lines: card layout, grade-button colours
        app.js         # ~300 lines: session driver, page dispatching
        index.html     # home page
        session.html   # active session view
        dashboard.html # stats dashboard
        missed.html    # missed-questions history + drill trigger
```

---

## 5. HTTP API

All endpoints exchange JSON. Errors return `{"error": "..."}` with the
appropriate HTTP status (400 Bad Request / 404 Not Found / 409 Conflict).

### Review endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/sessions` | `{mode: 'regular'|'drill', chapters: [int]}` | `{session_id: str}` |
| `GET` | `/api/sessions/<id>/state` | — | `{kind, payload, version}` |
| `POST` | `/api/sessions/<id>/answer` | `{indices: [int]}` | `204` |
| `POST` | `/api/sessions/<id>/grade` | `{grade: int}` | `204` |
| `DELETE` | `/api/sessions/<id>` | — | `204` |

**Prompt payload** (kind `'prompt'`, `correct_indices` deliberately absent):

```json
{
  "fact_id": 42,
  "question_id": 107,
  "text": "Which year did ...",
  "choices": ["1066", "1215", "1649", "1832"],
  "is_multi": false,
  "is_true_false": false
}
```

**Feedback payload** (kind `'feedback'`, `correct_indices` now revealed):

```json
{
  "correct": true,
  "choices": ["1066", "1215", "1649", "1832"],
  "correct_indices": [1]
}
```

### Stats endpoints

| Method | Path | Query params | Returns |
|---|---|---|---|
| `GET` | `/api/topics` | — | `[{id, name}]` |
| `GET` | `/api/dashboard` | — | `{by_chapter, recent, weak, coverage, streak, due_today}` |
| `GET` | `/api/missed` | `chapters`, `since` | `[{fact_id, question_text, your_choices, correct_choices, reviewed_at, miss_count}]` |

### Page routes (serve static HTML)

| Path | File |
|---|---|
| `/` | `static/index.html` |
| `/session` | `static/session.html` |
| `/dashboard` | `static/dashboard.html` |
| `/missed` | `static/missed.html` |

---

## 6. Dashboard Tiles

| Tile | Source query | Content |
|---|---|---|
| Per-chapter accuracy | `queries.by_chapter` | Table of % correct per chapter 1–5 |
| Recent sessions | `queries.recent_sessions` | Last 10 sessions: date, score (e.g. 21/24) |
| Weak facts | `queries.weak_facts` | Top 20 facts by lapse count; links to missed view |
| Coverage | `queries.coverage` | "You've seen N / M facts (X%)" |
| Streak | `queries.streak` | "N-day streak" headline |
| Due today | `queries.due_today` | Pill on the start-session button |

No charting library — per-chapter accuracy bars are CSS `<div>` widths
computed from percentages.

---

## 7. Frontend Behaviour

- **Routing**: plain `<a>` anchors between pages; no SPA framework. Each
  HTML page loads `app.js` (with `data-page` on `<body>`) and dispatches
  to its initialiser.
- **Session driver** (`/session?id=...`): polls `/state` every 300 ms;
  re-renders only when `version` changes. Renders three view states:
  - `prompt`: question text + choice buttons (multi-select toggles +
    Submit for multi-answer; single-click for single-answer).
  - `feedback` (correct): highlights choices; shows Hard / Good / Easy
    buttons (no Again — server-side only).
  - `feedback` (miss): highlights correct choices; shows Continue button
    (posts grade, server ignores value).
  - `summary`: score, weak-fact count, back-to-home link.
- **Dashboard**: single `fetch('/api/dashboard')` on load; plain DOM
  manipulation to fill tiles.
- **Missed page**: `fetch('/api/missed')` on load; re-fetches on filter
  change (chapter checkboxes, date input). "Drill these" posts
  `{mode:'drill', chapters:[...]}` to `/api/sessions`.
- **Home**: fetches `due_today` from dashboard endpoint to populate pill;
  chapter checkboxes feed the session start form.

---

## 8. Security Notes

- `correct_indices` is never included in the `'prompt'` state payload —
  only revealed in `'feedback'`. Verified by a dedicated unit test.
- Server binds to `127.0.0.1` only (`--host` default); not accessible
  off-host.
- No auth — acceptable for a single-user localhost tool.

---

## 9. Testing Strategy

100% coverage per `CLAUDE.md`. One DB per test via `tmp_path`.

| Test file | Coverage |
|---|---|
| `test_db.py` (extended) | `session_id` migration; idempotency |
| `test_session.py` (extended) | `run_drill_session`; `session_id` write-through; `_present_and_grade` extraction |
| `test_web_queries.py` | All `queries.py` functions on seeded DB |
| `test_web_sessions.py` | `WebUI` Protocol conformance; `correct_indices` strip; version increments; grade ignored on miss |
| `test_web_routes_review.py` | All review endpoints via Flask `test_client`; happy path + error paths |
| `test_web_routes_stats.py` | All stats endpoints; filter params |
| `test_web_e2e.py` | ingest 1 PDF → full HTTP session → DB assertions; drill session |

Static assets (HTML/CSS/JS) are not unit-tested; covered by the end-to-end
test and the manual smoke checklist in the implementation plan.

---

## 10. Implementation Order

See `docs/superpowers/plans/2026-05-09-web-ui.md` for the full task
breakdown with checkboxes:

1. Schema migration (`reviews.session_id`)
2. Drill mode + `session_id` threading in `session.py`
3. Thread `session_id` through CLI entry point
4. SQL helpers (`queries.py`)
5. `WebUI` + session store (`sessions.py`)
6. Review API routes
7. Stats API routes
8. Flask app factory + entry point + `pyproject.toml`
9. Static frontend (HTML + CSS + JS)
10. End-to-end test
