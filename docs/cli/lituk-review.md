# lituk-review

Runs an interactive spaced-repetition review session in the terminal. Uses
SM-2 for scheduling and Thompson sampling to balance due vs. new cards.

## Usage

```
lituk-review [--db PATH] [--size N] [--new-cap N] [--topic N[,N]]
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `app/data/lituk.db` | Path to the SQLite database |
| `--size N` | `24` | Number of cards per session (24 matches the real exam) |
| `--new-cap N` | `5` | Maximum new cards introduced per session |
| `--topic N[,N]` | all | Chapter numbers to study, comma-separated (1–5) |

## Examples

```bash
cd app

# Full session, all topics
uv run lituk-review

# History only, 24 cards
uv run lituk-review --topic 3

# History + modern society, quick 5-card practice
uv run lituk-review --topic 3,4 --size 5

# Introduce more new cards per session
uv run lituk-review --new-cap 10
```

## Session Flow

1. Each card shows the question and choices (A/B/C/D).
2. Type your answer (e.g. `A` or `A,C` for multi-answer questions).
3. **If correct:** type your grade — `a` Again, `h` Hard, `g` Good, `e` Easy.
4. **If wrong:** the correct answer is shown; card is re-queued within the
   session.
5. Session ends after `--size` cards or when all pools are empty.
6. Summary shows score and number of weak cards.

## Grade Keys

| Key | Grade | SM-2 Effect |
|-----|-------|-------------|
| `a` | Again (0) | Lapse: interval reset to 1 day, ease −0.2 |
| `h` | Hard (3) | Ease −0.15, slow interval growth |
| `g` | Good (4) | Ease unchanged, normal interval growth |
| `e` | Easy (5) | Ease +0.10, faster interval growth |

## Notes

- `--topic` filters both the due pool and the new pool. Facts with no topic
  assigned (`NULL`) are excluded when a filter is active.
- Run `lituk-tag` first to enable `--topic` filtering.
- Pool state (bandit α/β values) is persisted across sessions.
- See `docs/superpowers/specs/2026-05-09-review-engine-design.md` for the
  full SM-2 and bandit design.
