# lituk-stats

Prints a study statistics dashboard equivalent to the web UI stats page.
Available as both `lituk stats` and the standalone `lituk-stats` script.

## Usage

```
lituk stats [--db PATH]
lituk-stats [--db PATH]
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `app/data/lituk.db` | Path to the SQLite database |

## Example Output

```
Coverage:  42 / 1080 facts seen (3.9%)
Streak:    3 days
Due today: 7 cards

By chapter:
  Values and Principles of the UK           72.5%
  What is the UK                            85.0%
  A Long and Illustrious History            61.3%
  A Modern Thriving Society                 78.9%
  The UK Government, the Law and Your Role  66.7%

Recent sessions:
  2026-05-11  22 / 24
  2026-05-10  19 / 24
  2026-05-09  24 / 24

Weak facts:
  • What year did the UK join the EEC?…  (5 lapses)
  • Who introduced the National Health…  (3 lapses)
```

## Sections

**Coverage** — how many facts you have reviewed at least once out of the
total facts in the database, with percentage.

**Streak** — how many consecutive days (up to and including today) you have
completed at least one review.

**Due today** — how many cards have a due date on or before today and are
ready to review in a regular session.

**By chapter** — per-chapter accuracy (percentage correct) across all
reviews ever recorded. Only shown when at least one review exists.

**Recent sessions** — the last 10 sessions ordered newest first, showing
the date and score (correct / total). Only shown when sessions exist.

**Weak facts** — up to 20 facts with the most lapses (incorrect answers
followed by the card being relearned), ordered by lapse count descending.
Each line is truncated to 60 characters. Only shown when lapses exist.

## Examples

```bash
cd app

# Default DB
uv run lituk stats

# Alternate DB
uv run lituk stats --db /tmp/scratch.db
```
