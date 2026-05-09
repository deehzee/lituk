# lituk-tag

Tags every untagged fact with a chapter number (1–5) using Claude Haiku.
Reads chapter summaries from `ai/summary/` as context. Idempotent — skips
already-tagged facts unless `--retag` is passed.

Requires an `ANTHROPIC_API_KEY` environment variable.

## Usage

```
lituk-tag [--db PATH] [--summaries PATH] [--retag]
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `app/data/lituk.db` | Path to the SQLite database |
| `--summaries PATH` | `<repo-root>/ai/summary/` | Directory of chapter `.md` files |
| `--retag` | off | Re-tag facts that already have a topic assigned |

## Chapters

| Number | Name |
|--------|------|
| 1 | Values and Principles of the UK |
| 2 | What is the UK |
| 3 | A Long and Illustrious History |
| 4 | A Modern Thriving Society |
| 5 | The UK Government, the Law and Your Role |

## Example

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cd app
uv run lituk-tag
# Tagged 987 facts.
```

## Notes

- Run after `lituk-ingest`. Only needs to be run once (or after adding new
  questions with `lituk-ingest`).
- Sends facts to Claude Haiku (`claude-haiku-4-5-20251001`) in batches of 50
  with all chapter summaries as context (~32K tokens per batch).
- See `docs/superpowers/specs/2026-05-09-topic-tagging-design.md` for the
  full design.
