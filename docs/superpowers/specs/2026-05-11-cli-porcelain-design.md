# CLI Porcelain Mode — Design Spec

**Date:** 2026-05-11
**Status:** Implemented

## Overview

The app currently has four separate script entry points (`lituk-ingest`,
`lituk-review`, `lituk-tag`, `lituk-web`). There is no top-level `lituk`
command, making the tool harder to discover and use.

The porcelain mode adds a unified `lituk` dispatcher that routes
`lituk <subcommand>` to the appropriate existing main function. It also
enriches `lituk review` with three session modes, a `--dry-run` flag, and a
pre-session information banner, and adds a new `lituk stats` subcommand that
prints the study dashboard equivalent to the web UI stats page.

**In scope:**
- `lituk` top-level dispatcher (subcommands: ingest, tag, review, web, stats)
- Three review modes: regular, drill, explore
- `--chapters` alias for `--topic` in `lituk review`
- `--dry-run` flag for `lituk review`
- Pre-session info banner for `lituk review`
- `lituk stats` subcommand (dashboard-equivalent terminal output)
- CLI docs for new command and updated review docs

**Out of scope:**
- Changes to SM-2 / bandit engine logic
- Changes to ingest / tag / web subcommand behaviour
- Interactive TUI / curses interface
- Remote / multi-user use cases

---

## 1. Architecture

### 1.1 Dispatcher pattern

`app/lituk/cli/__init__.py` implements `main(argv)` which:

1. Reads `argv[0]` as the subcommand name.
2. Dispatches to the subcommand's `main(rest)` function via a simple
   `if/elif` chain (no argparse subparsers to avoid flag conflicts).
3. Prints usage and exits 0 on `--help` / no args; prints error and exits 2
   on unknown subcommand.

Subcommands are imported lazily inside the dispatch branch to avoid circular
imports and to keep startup time fast when the user types `lituk --help`.

No flag redefinition: each subcommand owns its own argparse parser. The
dispatcher does not inspect or modify subcommand flags.

```
lituk ingest [flags]   →  lituk.ingest.main(flags)
lituk tag    [flags]   →  lituk.tag.main(flags)
lituk review [flags]   →  lituk.review.main(flags)
lituk web    [flags]   →  lituk.web.server.main(flags)
lituk stats  [flags]   →  lituk.stats.main(flags)
```

The existing `lituk-ingest`, `lituk-review`, `lituk-tag`, and `lituk-web`
scripts remain as aliases and continue to work unchanged.

### 1.2 `lituk.ingest.main()` shim

`lituk.ingest.main()` currently accepts no arguments and calls
`parser.parse_args()` (reads `sys.argv`). It is changed to
`main(args: list[str] | None = None)` with `parser.parse_args(args)` so the
dispatcher can pass the remainder of `argv` directly.

---

## 2. Three Review Modes

`lituk review --mode {regular|drill|explore}` selects which session runner
is called. All three call the same engine functions that the web UI uses.

| Mode | Pool | Bandit | `reviews.pool` value | Notes |
|------|------|--------|----------------------|-------|
| `regular` | due + new | Thompson sampling | `due` / `new` / `lapsed` | Default; SM-2 + MAB |
| `drill` | lapses > 0 | None | `drill` / `lapsed` | Missed facts only |
| `explore` | no card_state | None | `new` / `lapsed` | Unseen facts only |

Implementation: `lituk.review.main()` reads `parsed.mode` and dispatches to
`run_session`, `run_drill_session`, or `run_explore_session` from
`lituk.review.session`. All three already exist from the web-UI feature.

`--chapters N[,N]` is added as an alias for the existing `--topic` flag,
both pointing to `dest="chapters"`. Existing tests that use `--topic` are
unaffected because argparse supports multiple option strings for one argument.

---

## 3. `--dry-run` Design

`--dry-run` runs the session against an in-memory copy of the on-disk DB so
that all SM-2 and review writes are discarded when the session exits.

Implementation uses the Python `sqlite3` backup API:

```python
import sqlite3 as _sqlite3
_src = _sqlite3.connect(parsed.db)
conn = _sqlite3.connect(":memory:")
_src.backup(conn)
_src.close()
conn.row_factory = _sqlite3.Row
```

After the session the in-memory connection is closed normally; the on-disk
file is untouched. This is the simplest possible approach — no transaction
savepoints, no mock objects, no filesystem temp files.

The pre-session banner appends "(dry run — no state will be saved)" to
signal the mode clearly.

---

## 4. `lituk stats` Subcommand

Prints a dashboard equivalent to the web UI stats page, using the same
`lituk.web.queries` functions.

### 4.1 Queries used

| Section | Function |
|---------|----------|
| Coverage line | `coverage(conn)` |
| Streak line | `streak(conn, today)` |
| Due today line | `due_today(conn, today)` |
| By chapter table | `by_chapter(conn)` |
| Recent sessions | `recent_sessions(conn)` |
| Weak facts | `weak_facts(conn)` |

### 4.2 Output format

```
Coverage:  N / M facts seen (X%)
Streak:    N day(s)
Due today: N card(s)

By chapter:
  <chapter name padded to 45 chars>     X%
  ...

Recent sessions:
  YYYY-MM-DD  N / M
  ...

Weak facts:
  • <question text truncated to 60 chars>…  (N lapse(s))
  ...
```

Sections "By chapter", "Recent sessions", and "Weak facts" are omitted when
the query returns no rows (empty DB or no lapses yet).

---

## 5. Pre-Session Banner

Printed to stdout after the DB connection is opened and before the session
runner is called.

| Mode | Banner content |
|------|---------------|
| `regular` | `Regular mode  •  N due today  •  M facts total` |
| `drill` | `Drill mode  •  N missed facts ready` |
| `explore` | `Explore mode  •  N unseen of M total` |

Appended when `--dry-run` is active: `  (dry run — no state will be saved)`

The banner always uses the same DB connection (or in-memory copy for dry-run)
that the session will use, so the counts are consistent.

---

## 6. Testing Strategy

100% coverage per `CLAUDE.md`. One DB per test via `tmp_path`.

| Test file | Coverage target |
|-----------|----------------|
| `app/tests/test_cli_porcelain.py` | `lituk/cli/__init__.py`, `lituk/cli/__main__.py` |
| `app/tests/test_review_cli.py` (extended) | `lituk/review/__init__.py` — mode dispatch, `--chapters`, `--dry-run`, banner |
| `app/tests/test_stats.py` | `lituk/stats/__init__.py`, `lituk/stats/__main__.py` |

---

## 7. Implementation Order

See `docs/superpowers/plans/2026-05-11-cli-porcelain.md` for the full task
breakdown with checkboxes.

1. Design spec + implementation plan docs (this file)
2. Unified `lituk` dispatcher + ingest shim fix
3. Three review modes + `--chapters` alias
4. `--dry-run` flag
5. Pre-session info banner
6. `lituk stats` subcommand
7. CLI docs
