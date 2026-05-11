# Snippet Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the explanation snippet from the mock test answer block in the
review feedback screen, after every answer (correct or wrong), in both the CLI
and web UI.

**Architecture:** `explanation` is already parsed and stored in `questions.explanation`
for all 1080 questions. The change threads it through `Prompt` → `show_feedback()`
in the CLI and web `WebUI`, and renders it in the web frontend.

**Tech Stack:** Python 3.12, SQLite, Flask, vanilla JS. Tests: pytest.
Run tests from `app/` directory: `cd app && .venv/bin/pytest`.

---

### Task 1: Add `explanation` to `Prompt` and `build_prompt()`

**Files:**
- Modify: `app/lituk/review/presenter.py`
- Modify: `app/tests/test_presenter.py`
- Modify: `app/tests/test_review_cli.py` (fix broken `Prompt` construction sites)
- Modify: `app/tests/test_web_sessions.py` (fix broken `Prompt` construction site)

- [ ] **Step 1: Write the failing test**

In `app/tests/test_presenter.py`, update `_insert_question()` to store an
explanation, then add a new test at the end of the file:

```python
def _insert_question(conn, fact_id, source_test, q_number, choices, correct_letters,
                     is_true_false=0, is_multi=0, explanation="Test explanation."):
    conn.execute(
        "INSERT INTO questions"
        " (source_test, q_number, question_text, choices, correct_letters,"
        "  explanation, is_true_false, is_multi, fact_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            source_test, q_number,
            "Question text",
            json.dumps(choices),
            json.dumps(correct_letters),
            explanation,
            is_true_false, is_multi, fact_id,
        ),
    )
    conn.commit()
```

```python
def test_build_prompt_has_explanation(conn, single_answer_fact):
    rng = random.Random(0)
    prompt = build_prompt(conn, single_answer_fact, rng)
    assert prompt.explanation == "Test explanation."
```

- [ ] **Step 2: Run test to verify it fails**

```
cd app && .venv/bin/pytest tests/test_presenter.py::test_build_prompt_has_explanation -v
```

Expected: FAIL — `Prompt` has no attribute `explanation`.

- [ ] **Step 3: Add `explanation` to `Prompt` and update `build_prompt()`**

In `app/lituk/review/presenter.py`:

```python
@dataclass(frozen=True)
class Prompt:
    fact_id: int
    question_id: int
    text: str
    choices: list[str]
    correct_indices: list[int]
    is_multi: bool
    is_true_false: bool
    explanation: str
```

Update the SQL in `build_prompt()` to fetch `explanation`:

```python
    rows = conn.execute(
        "SELECT id, question_text, choices, correct_letters, explanation,"
        " is_true_false, is_multi FROM questions WHERE fact_id = ?",
        (fact_id,),
    ).fetchall()
```

Update the `return Prompt(...)` call at the end of `build_prompt()`:

```python
    return Prompt(
        fact_id=fact_id,
        question_id=row["id"],
        text=row["question_text"],
        choices=shuffled,
        correct_indices=new_correct,
        is_multi=bool(row["is_multi"]),
        is_true_false=bool(row["is_true_false"]),
        explanation=row["explanation"] or "",
    )
```

- [ ] **Step 4: Fix `Prompt` construction sites in other test files**

`app/tests/test_review_cli.py` — update `_known_prompt()` (line 52) and the
inline `Prompt(...)` in `test_show_prompt_multi_hint_shown` (line 104):

```python
def _known_prompt(correct_at=0) -> Prompt:
    choices = ["Correct", "Wrong1", "Wrong2", "Wrong3"]
    order = [correct_at] + [i for i in range(4) if i != correct_at]
    shuffled = [choices[i] for i in order]
    return Prompt(
        fact_id=1, question_id=1, text="Q?",
        choices=shuffled,
        correct_indices=[0],
        is_multi=False,
        is_true_false=False,
        explanation="Correct is the right answer.",
    )
```

```python
def test_show_prompt_multi_hint_shown():
    ui = TerminalUI()
    prompt = Prompt(
        fact_id=1, question_id=1, text="Which TWO?",
        choices=["Red", "Blue", "Green", "Yellow"],
        correct_indices=[0, 1],
        is_multi=True, is_true_false=False,
        explanation="Red and Blue are primary colours.",
    )
    ...
```

`app/tests/test_web_sessions.py` — update `_make_prompt()` (line 13):

```python
def _make_prompt(correct_indices=None):
    if correct_indices is None:
        correct_indices = [0]
    return Prompt(
        fact_id=1,
        question_id=1,
        text="What year?",
        choices=["1066", "1215", "1649", "1832"],
        correct_indices=correct_indices,
        is_multi=False,
        is_true_false=False,
        explanation="The year was 1066.",
    )
```

- [ ] **Step 5: Run all tests to verify they pass**

```
cd app && .venv/bin/pytest -v
```

Expected: all 305 + 1 = 306 tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/lituk/review/presenter.py \
        app/tests/test_presenter.py \
        app/tests/test_review_cli.py \
        app/tests/test_web_sessions.py
git commit -m "Add explanation field to Prompt and build_prompt()"
```

---

### Task 2: Show explanation in CLI `show_feedback()`

**Files:**
- Modify: `app/lituk/review/cli.py`
- Modify: `app/tests/test_review_cli.py`

- [ ] **Step 1: Write the failing tests**

Add these two tests to `app/tests/test_review_cli.py` (after the existing
`show_feedback` tests around line 151):

```python
def test_show_feedback_correct_shows_explanation():
    ui = TerminalUI()
    prompt = _known_prompt()
    with patch("builtins.input", return_value="g"), \
         patch("sys.stdout", new_callable=StringIO) as out:
        ui.show_feedback(prompt, True)
    assert "Correct is the right answer." in out.getvalue()


def test_show_feedback_wrong_shows_explanation():
    ui = TerminalUI()
    prompt = _known_prompt(correct_at=0)
    with patch("sys.stdout", new_callable=StringIO) as out:
        ui.show_feedback(prompt, False)
    assert "Correct is the right answer." in out.getvalue()
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd app && .venv/bin/pytest tests/test_review_cli.py::test_show_feedback_correct_shows_explanation tests/test_review_cli.py::test_show_feedback_wrong_shows_explanation -v
```

Expected: both FAIL — explanation not printed.

- [ ] **Step 3: Update `show_feedback()` in `cli.py`**

Replace the `show_feedback` method in `app/lituk/review/cli.py`:

```python
    def show_feedback(self, prompt: Prompt, correct: bool) -> int:
        if correct:
            print("  Correct!")
            print(f"  {prompt.explanation}")
            while True:
                raw = input(
                    "  Grade: [a]gain  [h]ard  [g]ood  [e]asy: "
                ).strip().lower()
                if raw in _LETTER_TO_GRADE:
                    print()
                    return _LETTER_TO_GRADE[raw]
                print("  Enter a, h, g, or e.")
        else:
            correct_text = ", ".join(
                prompt.choices[i] for i in sorted(prompt.correct_indices)
            )
            print(f"  Wrong! Answer: {correct_text}")
            print(f"  {prompt.explanation}")
            print()
            return 0
```

- [ ] **Step 4: Run all tests to verify they pass**

```
cd app && .venv/bin/pytest -v
```

Expected: all 308 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/lituk/review/cli.py app/tests/test_review_cli.py
git commit -m "Show explanation snippet in CLI feedback"
```

---

### Task 3: Include explanation in web feedback state payload

**Files:**
- Modify: `app/lituk/web/sessions.py`
- Modify: `app/tests/test_web_sessions.py`

- [ ] **Step 1: Write the failing test**

Add this test to `app/tests/test_web_sessions.py` (after the existing
`show_feedback` tests):

```python
def test_show_feedback_payload_includes_explanation():
    ui = WebUI()
    prompt = _make_prompt()
    ui._grade_q.put(4)
    ui.show_feedback(prompt, True)
    assert ui.state.payload["explanation"] == "The year was 1066."
```

- [ ] **Step 2: Run test to verify it fails**

```
cd app && .venv/bin/pytest tests/test_web_sessions.py::test_show_feedback_payload_includes_explanation -v
```

Expected: FAIL — `explanation` not in payload.

- [ ] **Step 3: Add `explanation` to the feedback payload in `sessions.py`**

In `app/lituk/web/sessions.py`, update `WebUI.show_feedback()`:

```python
    def show_feedback(self, prompt: Prompt, correct: bool) -> int:
        self._set_state("feedback", {
            "correct": correct,
            "choices": prompt.choices,
            "correct_indices": prompt.correct_indices,
            "explanation": prompt.explanation,
        })
        grade = self._grade_q.get()
        return grade if correct else 0
```

- [ ] **Step 4: Run all tests to verify they pass**

```
cd app && .venv/bin/pytest -v
```

Expected: all 309 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/lituk/web/sessions.py app/tests/test_web_sessions.py
git commit -m "Include explanation in web feedback state payload"
```

---

### Task 4: Render explanation in the web frontend

**Files:**
- Modify: `app/lituk/web/static/session.html`
- Modify: `app/lituk/web/static/app.js`

No new Python tests — the e2e test drives sessions by polling state and posting
grades; it does not assert on rendered HTML content.

- [ ] **Step 1: Add `fb-explanation` element to `session.html`**

In `app/lituk/web/static/session.html`, inside `#view-feedback > .card`, add
`<p id="fb-explanation"></p>` between `#fb-choices` and `#grade-area`:

```html
  <!-- Feedback view -->
  <div id="view-feedback" class="hidden">
    <div class="card">
      <p id="fb-question-text"></p>
      <div id="fb-choices" class="choices"></div>
      <p id="fb-explanation" style="margin-top:1rem"></p>
      <div id="grade-area" style="margin-top:1rem">
        <p id="grade-label"></p>
        <div class="grade-btns" id="grade-btns"></div>
      </div>
    </div>
  </div>
```

- [ ] **Step 2: Set explanation text in `renderFeedback()` in `app.js`**

In `app/lituk/web/static/app.js`, inside `renderFeedback(payload)`, add one
line immediately after the `fbChoices.innerHTML = ""` / choices-building block
and before the `gradeArea` / `gradeBtns` block. The correct insertion point is
after the `fbChoices.forEach(...)` loop (around line 170):

```js
    document.getElementById("fb-explanation").textContent =
      payload.explanation || "";
```

- [ ] **Step 3: Run all tests to verify nothing is broken**

```
cd app && .venv/bin/pytest -v
```

Expected: all 309 tests pass.

- [ ] **Step 4: Smoke-test in the browser**

Start the dev server:

```bash
cd app && .venv/bin/lituk-web --db data/lituk.db
```

Open `http://localhost:5000`, start a session, answer a question. Verify:
- Correct answer: explanation paragraph appears below the highlighted choice,
  above the grade buttons.
- Wrong answer: explanation appears below the "Incorrect" label.

- [ ] **Step 5: Commit**

```bash
git add app/lituk/web/static/session.html app/lituk/web/static/app.js
git commit -m "Render explanation snippet in web feedback view"
```
