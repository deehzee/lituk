# lituk

The unified LITUK study tool. Dispatches to subcommands.

## Usage

```
lituk <subcommand> [options]
```

## Subcommands

| Subcommand | Description |
|------------|-------------|
| `lituk ingest` | Ingest mock test PDFs into the database |
| `lituk tag` | Tag facts with chapter numbers using Claude |
| `lituk review` | Run an interactive review session |
| `lituk web` | Start the web study server |
| `lituk stats` | Show study statistics |

Run `lituk <subcommand> --help` for options.

The individual `lituk-ingest`, `lituk-review`, `lituk-tag`, and `lituk-web`
scripts remain available as aliases.

## Examples

```bash
cd app
uv run lituk review                       # regular SM-2 session
uv run lituk review --mode drill          # missed facts only
uv run lituk review --mode explore        # unseen facts only
uv run lituk review --dry-run --size 3    # test UI, no DB writes
uv run lituk stats                        # study dashboard
uv run lituk web                          # start web UI
```
