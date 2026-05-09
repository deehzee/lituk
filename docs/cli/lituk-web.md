# lituk-web

Starts a local web server for browser-based study sessions. Provides the
same SM-2 + bandit review engine as `lituk-review` but in a browser
interface, plus a missed-questions history, drill mode, and a stats
dashboard.

Binds to `127.0.0.1` only — not accessible off-host.

## Usage

```
lituk-web [--db PATH] [--host HOST] [--port PORT]
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `app/data/lituk.db` | Path to the SQLite database |
| `--host HOST` | `127.0.0.1` | Interface to bind (do not expose to 0.0.0.0) |
| `--port PORT` | `8765` | Port to listen on |

## Examples

```bash
cd app

# Start with defaults
uv run lituk-web

# Custom port
uv run lituk-web --port 9000

# Explicit DB path
uv run lituk-web --db /path/to/lituk.db

# Run as a module (alternative)
uv run python -m lituk.web
```

Then open `http://127.0.0.1:8765/` in a browser.

## Pages

| URL | Description |
|-----|-------------|
| `/` | Home — start a review or drill session; shows due-today count |
| `/session?id=<id>` | Active session — driven by polling the session state API |
| `/dashboard` | Stats — per-chapter accuracy, recent sessions, weak facts, coverage, streak |
| `/missed` | Missed-questions history — filter by chapter and date; launch drill |

## Session Flow

1. Choose chapters (or leave blank for all) and click **Start session**.
2. Each card shows the question and choices.
3. **If correct:** select your grade — **Hard**, **Good**, or **Easy**.
4. **If wrong:** the correct answer is highlighted; click **Continue**.
   The card is re-queued for later in the same session.
5. Session ends after 24 cards or when all pools are empty.
6. Summary shows your score and number of weak cards.

## Drill Mode

Drill sessions pull only from cards you have previously answered incorrectly
(facts with at least one lapse). Start a drill from:

- The **Missed** page — click **Drill these** (respects your chapter and
  date filters).
- The home page — select **Drill** mode before starting.

Drill answers update SM-2 state exactly like regular sessions: getting a
card right in drill advances its interval and ease, reducing future pressure
on the algorithm.

## Grade Buttons

| Button | Grade | SM-2 Effect |
|--------|-------|-------------|
| Hard | 3 | Ease −0.15, slow interval growth |
| Good | 4 | Ease unchanged, normal interval growth |
| Easy | 5 | Ease +0.10, faster interval growth |

On a wrong answer no grade is shown — the engine automatically applies
grade 0 (lapse).

## Dashboard Tiles

| Tile | Description |
|------|-------------|
| Per-chapter accuracy | % correct broken down by chapter 1–5 |
| Recent sessions | Last 10 sessions with date and score |
| Weak facts | Top 20 facts by lapse count |
| Coverage | % of all facts you've seen at least once |
| Streak | Current consecutive days with at least one review |

## Notes

- Run `lituk-ingest` before starting the server to populate the database.
- Run `lituk-tag` before using chapter filters to assign topic labels to
  facts.
- Session state is held in memory; restarting the server abandons any
  session in progress (completed reviews are already persisted).
- See `docs/superpowers/specs/2026-05-09-web-ui-design.md` for the full
  architecture and API reference.
