# CLI Porcelain Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a unified `lituk` dispatcher, enrich `lituk review` with three
session modes, a `--dry-run` flag, and a pre-session banner, and add a
`lituk stats` subcommand.

**Architecture:** Dispatcher pattern routes `argv[0]` to each subsystem's
existing `main()`. No flag redefinition — each subcommand owns its parser.
Three review modes call the same `run_session` / `run_drill_session` /
`run_explore_session` functions the web UI uses. `--dry-run` uses the
`sqlite3` backup API to clone the DB into `:memory:`. Stats uses the same
`lituk.web.queries` helpers as the web dashboard.

**Tech Stack:** Python 3.12, `sqlite3`, `argparse`, `pytest`.

**Design spec:**
`docs/superpowers/specs/2026-05-11-cli-porcelain-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/lituk/ingest/__init__.py` | Modify | Add `args` param to `main()`; pass to `parse_args` |
| `app/lituk/cli/__init__.py` | Create | Dispatcher: routes subcommands to subsystem mains |
| `app/lituk/cli/__main__.py` | Create | `python -m lituk.cli` shim |
| `app/lituk/review/__init__.py` | Modify | Add `--mode`, `--chapters`, `--dry-run`, banner |
| `app/lituk/stats/__init__.py` | Create | `lituk stats` subcommand: dashboard-style output |
| `app/lituk/stats/__main__.py` | Create | `python -m lituk.stats` shim |
| `app/pyproject.toml` | Modify | Add `lituk` and `lituk-stats` script entries |
| `app/tests/test_cli_porcelain.py` | Create | 100% coverage of `lituk/cli/__init__.py` |
| `app/tests/test_review_cli.py` | Modify | Cover modes, `--chapters`, `--dry-run`, banner |
| `app/tests/test_stats.py` | Create | 100% coverage of `lituk/stats/__init__.py` |
| `docs/cli/lituk.md` | Create | Top-level command docs |
| `docs/cli/lituk-stats.md` | Create | Stats subcommand docs |
| `docs/cli/lituk-review.md` | Modify | Add `--mode`, `--chapters`, `--dry-run` docs |

---

## Task 1: Design spec + implementation plan docs

**Files:** `docs/superpowers/specs/2026-05-11-cli-porcelain-design.md`,
`docs/superpowers/plans/2026-05-11-cli-porcelain.md`

- [x] **Step 1 (spec):** Write design spec covering dispatcher pattern,
  three review modes table, `--dry-run` sqlite3 backup approach, stats
  subcommand queries and output format, pre-session banner per mode.
- [x] **Step 2 (plan):** Write this plan file with file map and per-task
  checkboxes in Step 1/2/3/4 structure.
- [x] **Step 3 (verify):** Confirm both files render correctly (line width
  ≤ 90, no broken markdown).
- [x] **Step 4 (commit):**
  ```
  Add design spec and implementation plan for CLI porcelain mode
  ```

---

## Task 2: Unified `lituk` dispatcher + ingest shim fix

**Files:** `app/lituk/ingest/__init__.py`, `app/lituk/cli/__init__.py`,
`app/lituk/cli/__main__.py`, `app/pyproject.toml`,
`app/tests/test_cli_porcelain.py`

- [x] **Step 1 (failing tests):** Write `test_cli_porcelain.py` covering:
  - `main([])` exits 0 and prints usage
  - `main(["--help"])` exits 0 and prints usage
  - `main(["unknown"])` exits 2 and prints error to stderr
  - `main(["review", "--help"])` delegates to `lituk.review.main`
  - `main(["ingest", "--help"])` delegates to `lituk.ingest.main`
  - `main(["tag", "--help"])` delegates to `lituk.tag.main`
  - `main(["web", "--help"])` delegates to `lituk.web.server.main`
  - `main(["stats", "--help"])` delegates to `lituk.stats.main`
  - `python -m lituk.cli` shim imports without error
- [x] **Step 2 (implement):** Fix `lituk.ingest.main()`; create
  `lituk/cli/__init__.py` dispatcher; create `lituk/cli/__main__.py`;
  add `lituk` entry to `pyproject.toml`.
- [x] **Step 3 (verify):**
  ```bash
  cd app && uv run pytest tests/test_cli_porcelain.py -v
  cd app && uv run pytest --cov=lituk --cov-report=term-missing -q
  ```
  All pass, 100% coverage.
- [x] **Step 4 (commit):**
  ```
  Add unified lituk dispatcher and fix ingest main() to accept args
  ```

---

## Task 3: Three review modes + `--chapters` alias

**Files:** `app/lituk/review/__init__.py`,
`app/tests/test_review_cli.py`

- [x] **Step 1 (failing tests):** Extend `test_review_cli.py` with:
  - `--mode drill` patches `run_drill_session` and asserts called
  - `--mode explore` patches `run_explore_session` and asserts called
  - Default (no `--mode`) calls `run_session`
  - Invalid `--mode foo` exits 2
  - `--chapters 1,3` produces same `topics=[1,3]` as `--topic 1,3`
- [x] **Step 2 (implement):** Add `--mode` and `--chapters`/`--topic`
  combined argument to `lituk.review.main()`; dispatch based on mode.
- [x] **Step 3 (verify):**
  ```bash
  cd app && uv run pytest --cov=lituk --cov-report=term-missing -q
  ```
  All pass including existing `--topic` tests. 100% coverage.
- [x] **Step 4 (commit):**
  ```
  Add --mode {regular,drill,explore} and --chapters alias to lituk review
  ```

---

## Task 4: `--dry-run` flag

**Files:** `app/lituk/review/__init__.py`,
`app/tests/test_review_cli.py`

- [x] **Step 1 (failing tests):** Add tests:
  - `--dry-run` with seeded 1-fact DB: after session, on-disk DB has zero
    reviews rows (no writes leaked)
  - `--dry-run --mode drill` smoke test
  - `--dry-run --mode explore` smoke test
- [x] **Step 2 (implement):** Add `--dry-run` argument; replace
  `conn = init_db(parsed.db)` with sqlite3 backup API branch.
- [x] **Step 3 (verify):**
  ```bash
  cd app && uv run pytest --cov=lituk --cov-report=term-missing -q
  ```
  100% coverage.
- [x] **Step 4 (commit):**
  ```
  Add --dry-run flag: run session against in-memory DB copy
  ```

---

## Task 5: Pre-session info banner

**Files:** `app/lituk/review/__init__.py`,
`app/tests/test_review_cli.py`

- [x] **Step 1 (failing tests):** Add tests using `capsys` or
  `StringIO` patch:
  - Regular mode banner contains "Regular mode" and "due today"
  - Drill mode banner contains "Drill mode" and "missed facts"
  - Explore mode banner contains "Explore mode" and "unseen"
  - `--dry-run` banner contains "dry run"
- [x] **Step 2 (implement):** Add banner computation and `print(_banner)`
  after connection open, before session dispatch.
- [x] **Step 3 (verify):**
  ```bash
  cd app && uv run pytest --cov=lituk --cov-report=term-missing -q
  ```
  100% coverage.
- [x] **Step 4 (commit):**
  ```
  Add pre-session info banner to lituk review
  ```

---

## Task 6: `lituk stats` subcommand

**Files:** `app/lituk/stats/__init__.py`, `app/lituk/stats/__main__.py`,
`app/pyproject.toml`, `app/tests/test_stats.py`

- [x] **Step 1 (failing tests):** Write `test_stats.py` covering:
  - `main(["--db", path])` exits without error; stdout has "Coverage:",
    "Streak:", "Due today:"
  - Empty DB: section headers "By chapter:", "Recent sessions:",
    "Weak facts:" absent (or present but empty)
  - With seeded data: chapter row, recent session, weak fact appear
  - `--help` exits 0
  - `__main__` module imports without error
- [x] **Step 2 (implement):** Create `lituk/stats/__init__.py` and
  `lituk/stats/__main__.py`; add `lituk-stats` to `pyproject.toml`.
- [x] **Step 3 (verify):**
  ```bash
  cd app && uv run pytest tests/test_stats.py -v
  cd app && uv run pytest --cov=lituk --cov-report=term-missing -q
  ```
  100% coverage.
- [x] **Step 4 (commit):**
  ```
  Add lituk stats subcommand with dashboard-equivalent output
  ```

---

## Task 7: CLI docs

**Files:** `docs/cli/lituk.md`, `docs/cli/lituk-stats.md`,
`docs/cli/lituk-review.md`

- [x] **Step 1:** Create `docs/cli/lituk.md` with subcommand table and
  usage examples.
- [x] **Step 2:** Create `docs/cli/lituk-stats.md` with `--db` flag doc,
  example output, section explanations.
- [x] **Step 3:** Update `docs/cli/lituk-review.md`: add `--mode`,
  `--chapters`, `--dry-run` rows to options table; update `--topic` row;
  add "Session Banner" section; update examples.
- [x] **Step 4 (commit):**
  ```
  Add lituk porcelain docs and update lituk-review docs
  ```

---

## Verification

```bash
cd app
uv sync
uv run pytest --cov=lituk --cov-report=term-missing -q   # 100% coverage

# Smoke checks (no live DB needed):
uv run lituk --help
uv run lituk review --help
uv run lituk stats --help
```
