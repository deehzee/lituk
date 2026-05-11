# Life in the UK — Study Tool

## Purpose

This repo supports preparing for the Life in the UK (LITUK) test for ILR. It contains:

1. **Source material** — britizen.uk study guide PDF, chapter summaries, 45 mock test PDFs
2. **AI-generated study notes** — narrative-style summaries
3. **A spaced-repetition study app** (in progress) — extracts questions from mock tests
   and quizzes him using SM-2 + MAB

## Repo layout

```
britizen/
  life-in-uk-guide.pdf       # main study guide (primary source)
  summary-ch[1-5]-*.txt      # britizen.uk chapter revision notes
  mock_tests/                # 45 practice test PDFs (#1–45)
ai/
  instructions.md            # study preferences + resource links
  summary/                   # AI-generated chapter summaries
  cinematic/                 # vivid/story-driven versions for hard-to-remember sections
deb/
  *.md                       # handwritten notes
app/                         # study app (to be built)
  data/                      # extracted questions + SM-2 state (SQLite)
  cli/                       # CLI entry point
  web/                       # web UI (HTML/JS, served by Python)
  core/                      # shared logic: PDF parsing, SM-2 engine, MAB scheduler
```

## App architecture decisions

- **Env/package management**: `uv`
- **Language**: Python (backend + PDF parsing + SM-2 engine)
- **Storage**: SQLite (single file, no server)
- **UI**: two interfaces sharing the same core:
  - CLI — for quick terminal sessions
  - Web — HTML/JS served by a lightweight Python HTTP server (no heavy framework)
- **Review algorithm**: SM-2 (Anki-style) for scheduling *when* to show a card;
  multi-armed bandit (epsilon-greedy or Thompson sampling) for prioritizing
  *which due card* to show next within a session
- **Data schema** (planned):
  - `questions` table: `id`, `source_test`, `question_text`, `choices` (JSON array),
    `correct_index`, `topic_tag`
  - `reviews` table: `question_id`, `reviewed_at`, `outcome` (correct/incorrect),
    `ease_factor`, `interval_days`, `due_date`

## PDF extraction findings

From probing all 45 mock test PDFs (`britizen/mock_tests/`):

- Text-extractable via `pdftotext` (already installed) — no OCR needed
- 24 questions per test, always
- Choices: always A/B/C/D; A/B only for True/False questions
- Never more than 4 choices
- Multi-answer questions signalled by "TWO" in the question text
  (e.g. "Select TWO", "Which TWO")
- PDF structure: questions block, then `Answers` on its own line, then answers block
- Answer format: `{N}.\n{letter} - {answer text}\n{optional 2nd letter line}\n{explanation}`

**Parsing gotcha:** when a question straddles a page break, the PDF page title
("Life in the UK Test - Practice Test #N of 45 [Updated for 2026]") bleeds into
the last choice. Strip page headers/titles/URLs before parsing choices.

**Duplicates across tests:** 42 question texts appear in more than one test (max 3
times). Same question text always has the same type (single/multi/T-F) and the
same correct answer, but distractor (wrong) options can differ across tests.
Do not deduplicate by question text — store each occurrence as its own row.
SM-2 state should be keyed on `(question_text, correct_answer_text)` so the
same fact isn't relearned from scratch when encountered in a different test.

## Source of truth

When writing new summaries or verifying facts: use `britizen/life-in-uk-guide.pdf` as
the primary source. The britizen `.txt` summaries and the `ai/summary/` files are
supplementary. Do not rely solely on the cheat sheet.

## External resources (read-only reference)

- Main site: https://britizen.uk/
- Mock tests: https://britizen.uk/practice/life-in-the-uk-test
- May supplement with reputable external sources (Wikipedia, gov.uk); avoid unvetted
  sources

## Conventions

### File organisation

- AI-generated summaries: `ai/summary/ch{N}_{M}-{slug}.md`
- Cinematic/story-driven variants: `ai/cinematic/`
- Personal notes: `deb/`
- App code: `app/` (structure TBD as the app is built)
- Commit messages: `Add ...`, `Update ...`, `Fix ...` — no co-author footers for study
  content commits; use them for app code commits
- Prefer small, frequent commits — logical edits together, one concern per commit
- When following a plan, do not execute steps outside the plan's tasks

### Formatting

- **All files**: max line width 90 characters, no trailing whitespaces.
- **Markdown**: wrap at 90 chars wherever possible without breaking rendering (don't
  break URLs, code spans, or table cells)
- **Python imports**: three sections in order — (1) standard library, (2) third-party,
  (3) first-party; alphabetical within each section; blank line between sections

### Testing

- 100% test coverage
- End to end test
