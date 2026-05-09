# lituk-ingest

Extracts questions from the 45 britizen.uk mock test PDFs and loads them into
SQLite. Idempotent — safe to re-run; existing rows are skipped.

## Usage

```
lituk-ingest [--db PATH] [--dir PATH]
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `app/data/lituk.db` | Path to the SQLite database |
| `--dir PATH` | `<repo-root>/britizen/mock_tests/` | Directory of mock test PDFs |

## Example

```bash
cd app
uv run lituk-ingest
# Ingesting PDFs from .../britizen/mock_tests into .../data/lituk.db ...
# Done.
```

## Notes

- Requires `pdftotext` to be installed (`brew install poppler` on macOS).
- Ingests all `*.pdf` files matching the naming pattern
  `Practice Test #N of 45 [Updated for YYYY].pdf`.
- Run once after cloning, or after deleting and recreating the database.
- See `docs/superpowers/specs/2026-05-09-pdf-ingestion-design.md` for the
  full parsing and deduplication design.
