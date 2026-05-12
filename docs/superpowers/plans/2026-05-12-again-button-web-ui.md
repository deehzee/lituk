# Again Button Web UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Again" (grade 0) button to the web UI's correct-answer grade area,
matching the CLI's four-option grading behaviour.

**Architecture:** Two front-end files change; no backend, no tests. The existing grade
button rendering loop in `app.js` gains one extra entry; `app.css` gains one colour rule.

**Tech Stack:** Vanilla JS, CSS, served by the Python HTTP server in `app/lituk/web/`.

---

### Task 1: Add "Again" button and colour rule

**Files:**
- Modify: `app/lituk/web/static/app.js:179`
- Modify: `app/lituk/web/static/app.css:33`

- [ ] **Step 1: Edit `app.js` — prepend "Again" to the grade array**

  In `app/lituk/web/static/app.js`, change line 179 from:

  ```js
  [["Hard","3"],["Good","4"],["Easy","5"]].forEach(([label, grade]) => {
  ```

  to:

  ```js
  [["Again","0"],["Hard","3"],["Good","4"],["Easy","5"]].forEach(([label, grade]) => {
  ```

- [ ] **Step 2: Edit `app.css` — add colour rule for grade-0 button**

  In `app/lituk/web/static/app.css`, after the existing `.grade-btn[data-grade="3"]`
  rule (line 33), insert:

  ```css
  .grade-btn[data-grade="0"] { background: #c0392b; color: #fff; border: none; }
  ```

  The grade-button block should then read:

  ```css
  .grade-btn[data-grade="0"] { background: #c0392b; color: #fff; border: none; }
  .grade-btn[data-grade="3"] { background: #e67e22; color: #fff; border: none; }
  .grade-btn[data-grade="4"] { background: #27ae60; color: #fff; border: none; }
  .grade-btn[data-grade="5"] { background: #2980b9; color: #fff; border: none; }
  ```

- [ ] **Step 3: Verify manually**

  Start the dev server:

  ```bash
  cd app && uv run python -m lituk.web.server --port 8765
  ```

  Open `http://127.0.0.1:8765`, start a session, answer a question correctly.
  Confirm four buttons appear in order: **Again** (red) · **Hard** (orange) ·
  **Good** (green) · **Easy** (blue). Clicking "Again" should advance to the next
  card (grade 0 submitted, same behaviour as an incorrect answer).

- [ ] **Step 4: Commit**

  ```bash
  git add app/lituk/web/static/app.js app/lituk/web/static/app.css
  git commit -m "Add Again button to web UI grade area (issue #24)"
  ```

- [ ] **Step 5: Close the issue**

  ```bash
  gh issue close 24 --comment "Again button added in this commit."
  ```
