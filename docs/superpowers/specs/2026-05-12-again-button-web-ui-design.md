# Design: Add "Again" Button to Web UI (Issue #24)

## Problem

The CLI presents four self-grading options after a correct answer — Again, Hard, Good,
Easy — mapped to SM-2 grades 0, 3, 4, 5. The web UI only shows Hard, Good, Easy (grades
3–5). This inconsistency means web users cannot express "I got it right but want to see
it again soon."

## Solution

Add an "Again" button (grade 0) to the correct-answer grade area in the web UI, styled
red and positioned first — matching Anki convention and the CLI's left-to-right order.

## Changes

### `app/lituk/web/static/app.js`

In the correct-answer branch of `showFeedback`, prepend `["Again", "0"]` to the grade
button array:

```js
// before
[["Hard","3"],["Good","4"],["Easy","5"]].forEach(...)

// after
[["Again","0"],["Hard","3"],["Good","4"],["Easy","5"]].forEach(...)
```

### `app/lituk/web/static/app.css`

Add a colour rule for grade-0 buttons, consistent with the existing Hard/Good/Easy scheme:

```css
.grade-btn[data-grade="0"] { background: #c0392b; color: #fff; border: none; }
```

## Behaviour

- Clicking "Again" submits grade 0 to `POST /api/sessions/{sid}/grade`.
- The scheduler treats grade 0 identically to an incorrect answer: ease −0.2, interval
  reset to 1 day, reps reset to 0, lapse counter incremented.
- The incorrect-answer path (single "Continue" button → grade 0) is unchanged.

## Scope

No backend changes. No new tests required beyond what already covers the grade-0 path
in `routes_review` and `sessions`.
