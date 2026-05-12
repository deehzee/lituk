# Design: Show explanation snippet in feedback (issue #21)

## Background

When a question is answered in a review session the feedback screen shows whether
the answer was correct and highlights the right choice. Issue #21 asks for the
relevant study snippet to also appear, so the user can read the source material
immediately after answering.

The mock test PDFs already contain an explanation paragraph for every answer.
The parser (`ingest/parser.py`) already extracts these, the ingester stores them
in `questions.explanation`, and the DB confirms all 1080 questions have non-empty
values. No new data source, LLM, or re-ingest is needed.

## Behaviour

- Show the explanation snippet as part of the feedback screen after every answer,
  whether correct or incorrect.
- Placement: after the correct-answer line / grade label, before the grade buttons.
- Applies to both the CLI and the web UI.

## Files changed

### `app/lituk/review/presenter.py`

- Add `explanation: str` field to the `Prompt` dataclass.
- Extend the `SELECT` in `build_prompt()` to include `explanation` from the
  `questions` row that is already fetched by `fact_id`.

### `app/lituk/review/cli.py`

`TerminalUI.show_feedback()` currently:
```
  Correct!               ← correct path
  Wrong! Answer: <text>  ← wrong path
```

Becomes:
```
  Correct!               ← correct path
  Wrong! Answer: <text>  ← wrong path
  <explanation>          ← always, indented 2 spaces
```

### `app/lituk/web/sessions.py`

`WebUI.show_feedback()` adds `"explanation": prompt.explanation` to the feedback
state payload so the frontend can render it.

### `app/lituk/web/static/session.html`

Add a `<p id="fb-explanation">` element in the feedback view, positioned after
the grade label and before the grade buttons.

### `app/lituk/web/static/app.js`

`renderFeedback()` sets `fb-explanation` text content from `payload.explanation`.

## Tests

- `tests/test_presenter.py` — include `explanation` in `Prompt` fixture
  construction; assert `build_prompt()` populates it.
- `tests/test_review_cli.py` — assert explanation is printed in `show_feedback()`
  for both correct and incorrect outcomes.
- `tests/test_web_sessions.py` — assert `explanation` is present in the feedback
  state payload.
- `tests/test_web_e2e.py` — assert explanation text appears in the feedback HTML
  after answering (if applicable to the existing e2e harness).

## Out of scope

- No DB schema changes.
- No re-ingestion of PDFs.
- No LLM or external API calls.
- No changes to the stats, tag, or ingest modules.
