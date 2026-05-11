# lituk-review

Runs an interactive spaced-repetition review session in the terminal. Uses
SM-2 for scheduling and Thompson sampling to balance due vs. new cards.
Available as both `lituk review` and the standalone `lituk-review` script.

## Usage

```
lituk review [--db PATH] [--size N] [--mode MODE] [--chapters N[,N]]
             [--dry-run]
lituk-review [--db PATH] [--size N] [--mode MODE] [--chapters N[,N]]
             [--dry-run]
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `app/data/lituk.db` | Path to the SQLite database |
| `--size N` | `24` | Number of cards per session (24 matches the real exam) |
| `--mode MODE` | `regular` | Session mode: `regular`, `drill`, or `explore` |
| `--chapters N[,N]` | all | Chapter numbers to study, comma-separated (1–5). `--topic` is an alias. |
| `--topic N[,N]` | all | Alias for `--chapters` (retained for compatibility) |
| `--dry-run` | off | Run against an in-memory copy of the DB; discard all writes on exit |

## Session Modes

| Mode | Pool | Description |
|------|------|-------------|
| `regular` | Due + new cards | SM-2 scheduling + Thompson-sampling bandit. Default. |
| `drill` | Missed facts only | Facts with at least one lapse (`card_state.lapses > 0`), ordered by lapse count descending. No bandit. |
| `explore` | Unseen facts only | Facts not yet in `card_state` (never reviewed). Shuffled randomly. No bandit. |

All three modes update SM-2 state and write review records.

## Session Banner

Before the first card, a one-line banner is printed showing the current
state of the chosen pool:

| Mode | Banner |
|------|--------|
| `regular` | `Regular mode  •  N due today  •  M facts total` |
| `drill` | `Drill mode  •  N missed facts ready` |
| `explore` | `Explore mode  •  N unseen of M total` |

When `--dry-run` is active, the banner appends:
`  (dry run — no state will be saved)`

## Examples

```bash
cd app

# Regular session, all chapters
uv run lituk-review

# Drill missed facts, 10-card session
uv run lituk-review --mode drill --size 10

# Explore unseen facts in chapter 3 only
uv run lituk-review --mode explore --chapters 3

# History + modern society, quick 5-card practice
uv run lituk-review --chapters 3,4 --size 5

# Test the UI without touching the DB
uv run lituk-review --dry-run --size 3

# Same using the --topic alias
uv run lituk-review --topic 3,4 --size 5
```

## Session Flow

1. The pre-session banner is printed (see above).
2. Each card shows the question and choices (A/B/C/D).
3. Type your answer (e.g. `A` or `A,C` for multi-answer questions).
4. **If correct:** type your grade — `a` Again, `h` Hard, `g` Good, `e` Easy.
5. **If wrong:** the correct answer is shown; card is re-queued within the
   session.
6. Session ends after `--size` cards or when the pool is exhausted.
7. Summary shows score and number of weak cards.

## Grade Keys

| Key | Grade | SM-2 Effect |
|-----|-------|-------------|
| `a` | Again (0) | Lapse: interval reset to 1 day, ease −0.2 |
| `h` | Hard (3) | Ease −0.15, slow interval growth |
| `g` | Good (4) | Ease unchanged, normal interval growth |
| `e` | Easy (5) | Ease +0.10, faster interval growth |

## Notes

- `--chapters` / `--topic` filters both the due pool and the new pool.
  Facts with no topic assigned (`NULL`) are excluded when a filter is active.
- Run `lituk-tag` first to enable chapter filtering.
- See `docs/superpowers/specs/2026-05-09-review-engine-design.md` for the
  full SM-2 and bandit design.
