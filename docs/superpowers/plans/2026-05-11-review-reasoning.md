# Review Reasoning Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface why each card was chosen during a review session as a dim grey
line in CLI and a print line on the web server terminal.

**Architecture:** Add `choose_with_samples` to `bandit.py` to expose Thompson draws;
extract a `_select_card` function from `run_session` that returns a `Selection`
dataclass including the reasoning string; add `show_reasoning(text)` to the `UI`
Protocol and both implementations.

**Tech Stack:** Python 3.12, SQLite via `sqlite3`, pytest, `uv` for running tests.

**Spec:** `docs/superpowers/specs/2026-05-11-review-reasoning-design.md`

---

## File Map

| File | Change |
|------|--------|
| `app/lituk/review/bandit.py` | Add `choose_with_samples`; rewrite `choose` as wrapper |
| `app/lituk/review/session.py` | Add `Selection`, `_select_card`, `_drill_reasoning`; refactor `run_session`; update `run_drill_session` |
| `app/lituk/review/cli.py` | Add `TerminalUI.show_reasoning` |
| `app/lituk/web/sessions.py` | Add `WebUI.show_reasoning` |
| `app/tests/test_bandit.py` | Tests for `choose_with_samples` |
| `app/tests/test_session.py` | Tests for `_select_card`, `_drill_reasoning`; update `StubUI`; integration assertions |
| `app/tests/test_review_cli.py` | Test for `TerminalUI.show_reasoning` |
| `app/tests/test_web_sessions.py` | Test for `WebUI.show_reasoning` |

---

## Task 1: `choose_with_samples` in `bandit.py`

**Files:**
- Modify: `app/lituk/review/bandit.py`
- Test: `app/tests/test_bandit.py`

- [ ] **Step 1: Write the failing tests**

  Add to `app/tests/test_bandit.py`:

  ```python
  from lituk.review.bandit import PoolPosterior, choose, choose_with_samples


  def test_choose_with_samples_returns_due_arm_and_thetas():
      rng = random.Random(42)
      due = PoolPosterior(alpha=100.0, beta=1.0)
      new = PoolPosterior(alpha=1.0, beta=100.0)
      arm, theta_due, theta_new = choose_with_samples(rng, due, new)
      assert arm == "due"
      assert theta_due > theta_new


  def test_choose_with_samples_returns_new_arm_and_thetas():
      rng = random.Random(42)
      due = PoolPosterior(alpha=1.0, beta=100.0)
      new = PoolPosterior(alpha=100.0, beta=1.0)
      arm, theta_due, theta_new = choose_with_samples(rng, due, new)
      assert arm == "new"
      assert theta_new > theta_due


  def test_choose_with_samples_thetas_are_floats():
      rng = random.Random(7)
      due = PoolPosterior(alpha=2.0, beta=2.0)
      new = PoolPosterior(alpha=2.0, beta=2.0)
      arm, theta_due, theta_new = choose_with_samples(rng, due, new)
      assert isinstance(theta_due, float)
      assert isinstance(theta_new, float)
      assert 0.0 <= theta_due <= 1.0
      assert 0.0 <= theta_new <= 1.0
  ```

  Update the existing import line at the top of `test_bandit.py`:

  ```python
  from lituk.review.bandit import PoolPosterior, choose, choose_with_samples
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_bandit.py::test_choose_with_samples_returns_due_arm_and_thetas -v
  ```

  Expected: `ImportError: cannot import name 'choose_with_samples'`

- [ ] **Step 3: Implement `choose_with_samples` and rewrite `choose`**

  Replace the existing `choose` function in `app/lituk/review/bandit.py` with:

  ```python
  def choose_with_samples(
      rng: random.Random, due: PoolPosterior, new: PoolPosterior
  ) -> tuple[str, float, float]:
      theta_due = rng.betavariate(due.alpha, due.beta)
      theta_new = rng.betavariate(new.alpha, new.beta)
      return ("due" if theta_due >= theta_new else "new"), theta_due, theta_new


  def choose(rng: random.Random, due: PoolPosterior, new: PoolPosterior) -> str:
      arm, _, _ = choose_with_samples(rng, due, new)
      return arm
  ```

- [ ] **Step 4: Run all bandit tests**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_bandit.py -v
  ```

  Expected: all PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add app/lituk/review/bandit.py app/tests/test_bandit.py
  git commit -m "Add choose_with_samples to expose Thompson draws for reasoning"
  ```

---

## Task 2: `Selection` dataclass + `_select_card` — lapsed case

**Files:**
- Modify: `app/lituk/review/session.py`
- Test: `app/tests/test_session.py`

- [ ] **Step 1: Write the failing test**

  Add the following import and test to `app/tests/test_session.py`. Place it after
  the existing imports and before the first test class:

  ```python
  from collections import deque
  from datetime import datetime, timezone

  from lituk.review.bandit import PoolPosterior
  from lituk.review.session import (
      ...,          # keep existing imports
      Selection,
      _select_card,
  )
  ```

  Update the existing import of `session` symbols — add `Selection` and
  `_select_card` to the `from lituk.review.session import (...)` block.

  Then add these test functions after the `_seed_due_card` helper:

  ```python
  def _seed_card_state(conn, fact_id, lapses=1, last_reviewed_at=None,
                       ease=2.5, interval=1, due_date=None):
      if last_reviewed_at is None:
          last_reviewed_at = datetime(2026, 5, 4, 12, 0, 0,
                                      tzinfo=timezone.utc).isoformat()
      if due_date is None:
          due_date = TODAY.isoformat()
      conn.execute(
          "INSERT OR REPLACE INTO card_state"
          " (fact_id, ease_factor, interval_days, repetitions,"
          "  due_date, last_reviewed_at, lapses)"
          " VALUES (?, ?, ?, 1, ?, ?, ?)",
          (fact_id, ease, interval, due_date, last_reviewed_at, lapses),
      )
      conn.commit()


  # ---------------------------------------------------------------------------
  # _select_card: lapsed case
  # ---------------------------------------------------------------------------

  def test_select_card_lapsed_returns_lapsed_label(conn):
      fid = _insert_fact_and_question(conn, "Q?", "A")
      _seed_card_state(conn, fid, lapses=2,
                       last_reviewed_at=datetime(2026, 5, 4, 12, 0,
                       tzinfo=timezone.utc).isoformat())
      rng = random.Random(1)
      lapsed = deque([fid])
      due = []
      new = []
      due_post = PoolPosterior(alpha=1.0, beta=1.0)
      new_post = PoolPosterior(alpha=1.0, beta=1.0)
      sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
      assert sel is not None
      assert sel.pool_label == "lapsed"
      assert sel.fact_id == fid
      assert "Lapsed" in sel.reasoning
      assert "lapses=2" in sel.reasoning
      assert "last seen 5d ago" in sel.reasoning


  def test_select_card_lapsed_pops_from_deque(conn):
      fid = _insert_fact_and_question(conn, "Q2?", "A2")
      _seed_card_state(conn, fid, lapses=1)
      lapsed = deque([fid])
      due = []
      new = []
      due_post = PoolPosterior(alpha=1.0, beta=1.0)
      new_post = PoolPosterior(alpha=1.0, beta=1.0)
      _select_card(random.Random(0), lapsed, due, new,
                   due_post, new_post, conn, TODAY)
      assert len(lapsed) == 0


  def test_select_card_all_empty_returns_none(conn):
      lapsed = deque()
      due = []
      new = []
      due_post = PoolPosterior(alpha=1.0, beta=1.0)
      new_post = PoolPosterior(alpha=1.0, beta=1.0)
      sel = _select_card(random.Random(0), lapsed, due, new,
                         due_post, new_post, conn, TODAY)
      assert sel is None
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_session.py::test_select_card_lapsed_returns_lapsed_label -v
  ```

  Expected: `ImportError: cannot import name 'Selection'`

- [ ] **Step 3: Add `Selection` and stub `_select_card` to `session.py`**

  Add after the existing imports in `app/lituk/review/session.py`. Also update the
  import from `lituk.review.bandit` to include `choose_with_samples`:

  ```python
  from lituk.review.bandit import PoolPosterior, choose, choose_with_samples
  ```

  Add the `Selection` dataclass and `_select_card` function (lapsed branch only for
  now, other branches raise `NotImplementedError`). Place them after
  `_compute_posteriors` and before `_load_card_state`:

  ```python
  @dataclass(frozen=True)
  class Selection:
      fact_id: int
      pool_label: str
      reasoning: str
      new_post: PoolPosterior


  def _select_card(
      rng: random.Random,
      lapsed: deque[int],
      due: list[int],
      new: list[int],
      due_post: PoolPosterior,
      new_post: PoolPosterior,
      conn: sqlite3.Connection,
      today: date,
  ) -> "Selection | None":
      if lapsed:
          fact_id = lapsed.popleft()
          row = conn.execute(
              "SELECT lapses, last_reviewed_at FROM card_state WHERE fact_id=?",
              (fact_id,),
          ).fetchone()
          lapses = row["lapses"] if row else 0
          if row and row["last_reviewed_at"]:
              last_dt = datetime.fromisoformat(row["last_reviewed_at"])
              days_ago = (today - last_dt.date()).days
              last_seen = f"last seen {days_ago}d ago"
          else:
              last_seen = "never seen"
          reasoning = f"Lapsed: failed this session | lapses={lapses}, {last_seen}"
          return Selection(
              fact_id=fact_id,
              pool_label="lapsed",
              reasoning=reasoning,
              new_post=new_post,
          )

      if not due and not new:
          return None

      raise NotImplementedError("remaining branches not yet implemented")
  ```

  Note: `datetime` is already imported in `session.py`; confirm the import line
  reads `from datetime import date, datetime, timedelta, timezone`.

- [ ] **Step 4: Run lapsed tests**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_session.py::test_select_card_lapsed_returns_lapsed_label tests/test_session.py::test_select_card_lapsed_pops_from_deque tests/test_session.py::test_select_card_all_empty_returns_none -v
  ```

  Expected: all PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add app/lituk/review/session.py app/tests/test_session.py
  git commit -m "Add Selection dataclass and _select_card lapsed branch"
  ```

---

## Task 3: `_select_card` — all non-lapsed cases

**Files:**
- Modify: `app/lituk/review/session.py`
- Test: `app/tests/test_session.py`

**Key invariant:** The `both` flag (whether both pools were non-empty) must be
captured BEFORE any pop, so the reasoning string correctly reflects whether MAB
was used. Checking `if due and new` after a `due.pop(0)` would falsely produce
"Due only" reasoning when only one due card existed.

- [ ] **Step 1: Write the failing tests**

  Add to `app/tests/test_session.py` after the lapsed-case tests. Each MAB test
  inserts cards into BOTH pools so the `both` condition is True:

  ```python
  # ---------------------------------------------------------------------------
  # _select_card: MAB cases (both pools non-empty)
  # ---------------------------------------------------------------------------

  def test_select_card_mab_due_arm_label_and_reasoning(conn):
      fid_due = _insert_fact_and_question(conn, "QDue?", "ADue")
      fid_new = _insert_fact_and_question(conn, "QNew?", "ANew", source_test=2, q_num=2)
      _seed_card_state(conn, fid_due, lapses=0, ease=2.1,
                       due_date=(TODAY - timedelta(days=3)).isoformat())
      rng = random.Random(0)
      lapsed = deque()
      due = [fid_due]
      new = [fid_new]   # both non-empty → MAB used
      due_post = PoolPosterior(alpha=100.0, beta=1.0)   # due arm almost certain
      new_post = PoolPosterior(alpha=1.0, beta=100.0)
      sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
      assert sel is not None
      assert sel.pool_label == "due"
      assert sel.fact_id == fid_due
      assert "MAB" in sel.reasoning
      assert "→ due" in sel.reasoning
      assert "ease=2.10" in sel.reasoning
      assert "overdue 3d" in sel.reasoning


  def test_select_card_mab_new_arm_label_and_reasoning(conn):
      fid_due = _insert_fact_and_question(conn, "QDue2?", "ADue2")
      fid_new = _insert_fact_and_question(conn, "QNew2?", "ANew2", source_test=2, q_num=2)
      _seed_card_state(conn, fid_due, lapses=0, ease=2.5)
      rng = random.Random(0)
      lapsed = deque()
      due = [fid_due]
      new = [fid_new]   # both non-empty → MAB used
      due_post = PoolPosterior(alpha=1.0, beta=100.0)
      new_post = PoolPosterior(alpha=100.0, beta=1.0)  # new arm almost certain
      sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
      assert sel is not None
      assert sel.pool_label == "new"
      assert sel.fact_id == fid_new
      assert "MAB" in sel.reasoning
      assert "→ new" in sel.reasoning


  def test_select_card_mab_new_arm_updates_new_post(conn):
      fid_due = _insert_fact_and_question(conn, "QDue3?", "ADue3")
      fid_new = _insert_fact_and_question(conn, "QNew3?", "ANew3", source_test=2, q_num=2)
      _seed_card_state(conn, fid_due, lapses=0, ease=2.5)
      rng = random.Random(0)
      lapsed = deque()
      due = [fid_due]
      new = [fid_new]
      due_post = PoolPosterior(alpha=1.0, beta=100.0)
      new_post = PoolPosterior(alpha=10.0, beta=5.0)   # new arm almost certain
      sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
      assert sel.pool_label == "new"
      assert sel.new_post.alpha == 9.0   # alpha decrements by 1
      assert sel.new_post.beta == 6.0    # beta increments by 1


  def test_select_card_mab_due_arm_new_post_unchanged(conn):
      fid_due = _insert_fact_and_question(conn, "QDue4?", "ADue4")
      fid_new = _insert_fact_and_question(conn, "QNew4?", "ANew4", source_test=2, q_num=2)
      _seed_card_state(conn, fid_due, lapses=0, ease=2.5)
      rng = random.Random(0)
      lapsed = deque()
      due = [fid_due]
      new = [fid_new]
      due_post = PoolPosterior(alpha=100.0, beta=1.0)  # due arm almost certain
      new_post = PoolPosterior(alpha=3.0, beta=7.0)
      sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
      assert sel.pool_label == "due"
      assert sel.new_post == new_post    # unchanged when due arm chosen


  # ---------------------------------------------------------------------------
  # _select_card: forced pool cases (single pool available)
  # ---------------------------------------------------------------------------

  def test_select_card_due_only_reasoning(conn):
      fid = _insert_fact_and_question(conn, "QDueOnly?", "ADueOnly")
      _seed_card_state(conn, fid, lapses=0, ease=1.8,
                       due_date=(TODAY - timedelta(days=2)).isoformat())
      rng = random.Random(0)
      lapsed = deque()
      due = [fid]
      new = []           # empty new pool → forced due, no MAB
      due_post = PoolPosterior(alpha=2.0, beta=2.0)
      new_post = PoolPosterior(alpha=1.0, beta=1.0)
      sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
      assert sel is not None
      assert sel.pool_label == "due"
      assert "Due only" in sel.reasoning
      assert "MAB" not in sel.reasoning
      assert "ease=1.80" in sel.reasoning
      assert "overdue 2d" in sel.reasoning


  def test_select_card_new_only_reasoning(conn):
      fid = _insert_fact_and_question(conn, "QNewOnly?", "ANewOnly")
      rng = random.Random(0)
      lapsed = deque()
      due = []           # empty due pool → forced new, no MAB
      new = [fid]
      due_post = PoolPosterior(alpha=2.0, beta=2.0)
      new_post = PoolPosterior(alpha=5.0, beta=3.0)
      sel = _select_card(rng, lapsed, due, new, due_post, new_post, conn, TODAY)
      assert sel is not None
      assert sel.pool_label == "new"
      assert "New only" in sel.reasoning
      assert "MAB" not in sel.reasoning
      assert "1 unseen remaining" in sel.reasoning
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_session.py::test_select_card_mab_due_arm_label_and_reasoning -v
  ```

  Expected: `NotImplementedError: remaining branches not yet implemented`

- [ ] **Step 3: Implement the remaining branches in `_select_card`**

  Replace the `raise NotImplementedError(...)` line and the `if not due and not new`
  block in `_select_card` with:

  ```python
      if not due and not new:
          return None

      n_due = len(due)
      n_new = len(new)
      both = n_due > 0 and n_new > 0   # captured BEFORE any pop

      if both:
          arm, theta_due, theta_new = choose_with_samples(rng, due_post, new_post)
      elif due:
          arm = "due"
          theta_due = theta_new = 0.0
      else:
          arm = "new"
          theta_due = theta_new = 0.0

      if arm == "due":
          fact_id = due.pop(0)
          row = conn.execute(
              "SELECT ease_factor, due_date FROM card_state WHERE fact_id=?",
              (fact_id,),
          ).fetchone()
          ease = row["ease_factor"] if row else 0.0
          due_d = date.fromisoformat(row["due_date"]) if row else today
          overdue = (today - due_d).days
          if both:
              reasoning = (
                  f"MAB: θ_due={theta_due:.2f}"
                  f"(α={due_post.alpha:.0f},β={due_post.beta:.0f})"
                  f" > θ_new={theta_new:.2f}"
                  f"(α={new_post.alpha:.0f},β={new_post.beta:.0f})"
                  f" → due | {n_due} due, {n_new} new"
                  f" | ease={ease:.2f}, overdue {overdue}d"
              )
          else:
              reasoning = f"Due only (no unseen) | ease={ease:.2f}, overdue {overdue}d"
          return Selection(
              fact_id=fact_id,
              pool_label="due",
              reasoning=reasoning,
              new_post=new_post,
          )
      else:  # arm == "new"
          fact_id = new.pop(0)
          updated_new_post = PoolPosterior(
              alpha=new_post.alpha - 1, beta=new_post.beta + 1
          )
          if both:
              reasoning = (
                  f"MAB: θ_new={theta_new:.2f}"
                  f"(α={new_post.alpha:.0f},β={new_post.beta:.0f})"
                  f" > θ_due={theta_due:.2f}"
                  f"(α={due_post.alpha:.0f},β={due_post.beta:.0f})"
                  f" → new | {n_new} new, {n_due} due"
              )
          else:
              reasoning = f"New only (no due) | {n_new} unseen remaining"
          return Selection(
              fact_id=fact_id,
              pool_label="new",
              reasoning=reasoning,
              new_post=updated_new_post,
          )
  ```

- [ ] **Step 4: Run all `_select_card` tests**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_session.py -k "select_card" -v
  ```

  Expected: all PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add app/lituk/review/session.py app/tests/test_session.py
  git commit -m "Add _select_card MAB and forced-arm branches with correct both-flag"
  ```

---

---

## Task 4: `_drill_reasoning`

**Files:**
- Modify: `app/lituk/review/session.py`
- Test: `app/tests/test_session.py`

- [ ] **Step 1: Write the failing tests**

  Add to the imports in `app/tests/test_session.py`:

  ```python
  from lituk.review.session import (
      ...,   # keep existing
      _drill_reasoning,
  )
  ```

  Add the test functions:

  ```python
  # ---------------------------------------------------------------------------
  # _drill_reasoning
  # ---------------------------------------------------------------------------

  def _seed_review(conn, fact_id, correct, reviewed_at):
      conn.execute(
          "INSERT INTO reviews"
          " (fact_id, question_id, reviewed_at, grade, correct, pool,"
          "  ease_after, interval_after)"
          " VALUES (?, 1, ?, 0, ?, 'drill', 2.5, 1)",
          (fact_id, reviewed_at, int(correct)),
      )
      conn.commit()


  def test_drill_reasoning_includes_lapses_and_days(conn):
      fid = _insert_fact_and_question(conn, "QDrill?", "ADrill")
      _seed_card_state(
          conn, fid, lapses=3,
          last_reviewed_at=datetime(2026, 5, 6, 10, 0,
                                    tzinfo=timezone.utc).isoformat(),
      )
      _seed_review(conn, fid, correct=False,
                   reviewed_at=datetime(2026, 5, 4, 10, 0,
                                        tzinfo=timezone.utc).isoformat())
      result = _drill_reasoning(conn, fid, TODAY)
      # TODAY = date(2026, 5, 9)
      assert "lapses=3" in result
      assert "last seen 3d ago" in result   # 2026-05-06 → 3 days ago
      assert "last wrong 5d ago" in result  # 2026-05-04 → 5 days ago


  def test_drill_reasoning_no_wrong_review(conn):
      fid = _insert_fact_and_question(conn, "QDrill2?", "ADrill2")
      _seed_card_state(conn, fid, lapses=1,
                       last_reviewed_at=datetime(2026, 5, 8, 10, 0,
                       tzinfo=timezone.utc).isoformat())
      # No wrong reviews inserted
      result = _drill_reasoning(conn, fid, TODAY)
      assert "lapses=1" in result
      assert "last seen 1d ago" in result
      assert "never wrong" in result
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_session.py::test_drill_reasoning_includes_lapses_and_days -v
  ```

  Expected: `ImportError: cannot import name '_drill_reasoning'`

- [ ] **Step 3: Implement `_drill_reasoning`**

  Add after the `_select_card` function in `app/lituk/review/session.py`:

  ```python
  def _drill_reasoning(
      conn: sqlite3.Connection, fact_id: int, today: date
  ) -> str:
      row = conn.execute(
          "SELECT lapses, last_reviewed_at FROM card_state WHERE fact_id=?",
          (fact_id,),
      ).fetchone()
      lapses = row["lapses"] if row else 0
      if row and row["last_reviewed_at"]:
          last_dt = datetime.fromisoformat(row["last_reviewed_at"])
          days_ago = (today - last_dt.date()).days
          last_seen = f"last seen {days_ago}d ago"
      else:
          last_seen = "never seen"

      wrong_row = conn.execute(
          "SELECT reviewed_at FROM reviews"
          " WHERE fact_id=? AND correct=0"
          " ORDER BY reviewed_at DESC LIMIT 1",
          (fact_id,),
      ).fetchone()
      if wrong_row:
          wrong_dt = datetime.fromisoformat(wrong_row["reviewed_at"])
          wrong_days = (today - wrong_dt.date()).days
          last_wrong = f"last wrong {wrong_days}d ago"
      else:
          last_wrong = "never wrong"

      return f"Drill: lapses={lapses}, {last_seen}, {last_wrong}"
  ```

- [ ] **Step 4: Run drill reasoning tests**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_session.py -k "drill_reasoning" -v
  ```

  Expected: all PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add app/lituk/review/session.py app/tests/test_session.py
  git commit -m "Add _drill_reasoning helper for drill session card stats"
  ```

---

## Task 5: `UI` Protocol + `TerminalUI.show_reasoning` + `StubUI`

**Files:**
- Modify: `app/lituk/review/session.py` (UI Protocol)
- Modify: `app/lituk/review/cli.py`
- Modify: `app/tests/test_session.py` (StubUI)
- Test: `app/tests/test_review_cli.py`

- [ ] **Step 1: Write the failing test**

  Add to `app/tests/test_review_cli.py` (after the `show_summary` tests):

  ```python
  # ---------------------------------------------------------------------------
  # TerminalUI.show_reasoning
  # ---------------------------------------------------------------------------

  def test_show_reasoning_prints_ansi_dim(capsys):
      ui = TerminalUI()
      ui.show_reasoning("MAB: θ_due=0.72 → due | 8 due, 3 new | ease=2.10, overdue 3d")
      captured = capsys.readouterr()
      assert "\033[2m" in captured.out
      assert "MAB:" in captured.out
      assert "\033[0m" in captured.out


  def test_show_reasoning_includes_text_content(capsys):
      ui = TerminalUI()
      ui.show_reasoning("Lapsed: failed this session | lapses=2, last seen 1d ago")
      captured = capsys.readouterr()
      assert "Lapsed" in captured.out
      assert "lapses=2" in captured.out
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_review_cli.py::test_show_reasoning_prints_ansi_dim -v
  ```

  Expected: `AttributeError: 'TerminalUI' object has no attribute 'show_reasoning'`

- [ ] **Step 3: Add `show_reasoning` to the `UI` Protocol in `session.py`**

  In `app/lituk/review/session.py`, update the `UI` Protocol:

  ```python
  class UI(Protocol):
      def show_reasoning(self, text: str) -> None: ...
      def show_prompt(self, prompt: Prompt) -> list[int]: ...
      def show_feedback(self, prompt: Prompt, correct: bool) -> int: ...
      def show_summary(self, result: SessionResult) -> None: ...
  ```

- [ ] **Step 4: Implement `TerminalUI.show_reasoning`**

  Add to `app/lituk/review/cli.py` inside the `TerminalUI` class, after
  `__init__` and before `show_prompt`:

  ```python
  def show_reasoning(self, text: str) -> None:
      print(f"\033[2m  {text}\033[0m")
  ```

- [ ] **Step 5: Update `StubUI` in `test_session.py`**

  In `app/tests/test_session.py`, update `StubUI`:

  ```python
  class StubUI:
      """Always answers correctly (index 0 in prompt.correct_indices) and grades Good."""

      def __init__(self, always_correct=True, grade=4):
          self.always_correct = always_correct
          self.grade = grade
          self.prompts_shown: list[Prompt] = []
          self.feedbacks: list[tuple[Prompt, bool]] = []
          self.reasonings: list[str] = []

      def show_reasoning(self, text: str) -> None:
          self.reasonings.append(text)

      def show_prompt(self, prompt: Prompt) -> list[int]:
          self.prompts_shown.append(prompt)
          if self.always_correct:
              return list(prompt.correct_indices)
          wrong = [i for i in range(len(prompt.choices))
                   if i not in prompt.correct_indices]
          return wrong[:1] if wrong else list(prompt.correct_indices)

      def show_feedback(self, prompt: Prompt, correct: bool) -> int:
          self.feedbacks.append((prompt, correct))
          if not correct:
              return 0
          return self.grade

      def show_summary(self, result: SessionResult) -> None:
          pass
  ```

- [ ] **Step 6: Run all CLI and session tests**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_review_cli.py tests/test_session.py -v
  ```

  Expected: all PASS.

- [ ] **Step 7: Commit**

  ```bash
  git add app/lituk/review/session.py app/lituk/review/cli.py app/tests/test_session.py app/tests/test_review_cli.py
  git commit -m "Add show_reasoning to UI Protocol, TerminalUI, and StubUI"
  ```

---

## Task 6: `WebUI.show_reasoning`

**Files:**
- Modify: `app/lituk/web/sessions.py`
- Test: `app/tests/test_web_sessions.py`

- [ ] **Step 1: Write the failing test**

  Add to `app/tests/test_web_sessions.py`:

  ```python
  # ---------------------------------------------------------------------------
  # WebUI.show_reasoning
  # ---------------------------------------------------------------------------

  def test_show_reasoning_prints_to_stdout(capsys):
      ui = WebUI()
      ui.show_reasoning("MAB: θ_due=0.72 → due | 8 due, 3 new")
      captured = capsys.readouterr()
      assert "→" in captured.out
      assert "MAB:" in captured.out


  def test_show_reasoning_includes_text(capsys):
      ui = WebUI()
      ui.show_reasoning("Drill: lapses=2, last seen 3d ago, last wrong 5d ago")
      captured = capsys.readouterr()
      assert "Drill:" in captured.out
      assert "lapses=2" in captured.out
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_web_sessions.py::test_show_reasoning_prints_to_stdout -v
  ```

  Expected: `AttributeError: 'WebUI' object has no attribute 'show_reasoning'`

- [ ] **Step 3: Implement `WebUI.show_reasoning`**

  Add to the `WebUI` class in `app/lituk/web/sessions.py`, after `__init__`
  and before `_set_state`:

  ```python
  def show_reasoning(self, text: str) -> None:
      print(f"  → {text}", flush=True)
  ```

- [ ] **Step 4: Run web session tests**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_web_sessions.py -v
  ```

  Expected: all PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add app/lituk/web/sessions.py app/tests/test_web_sessions.py
  git commit -m "Add WebUI.show_reasoning printing to server terminal"
  ```

---

## Task 7: Wire `_select_card` into `run_session`

**Files:**
- Modify: `app/lituk/review/session.py`
- Test: `app/tests/test_session.py`

- [ ] **Step 1: Add integration assertions to existing session tests**

  In `app/tests/test_session.py`, find any existing test that calls `run_session`
  with a `StubUI` and assert on `reasonings`. The existing session tests use
  `StubUI`; add assertions like:

  ```python
  # At the end of any test that calls run_session with stub_ui:
  assert len(stub_ui.reasonings) == result.total
  ```

  Specifically, find tests that pattern-match `run_session(..., ui=stub_ui, ...)` or
  `run_session(conn, TODAY, rng, config, ui)` and add the assertion. If the tests
  don't have a named `stub_ui` variable, introduce one. Example — if there is a test
  like:

  ```python
  def test_run_session_correct_all(conn):
      ...
      ui = StubUI()
      result = run_session(conn, TODAY, rng, SessionConfig(size=3), ui)
      assert result.correct == 3
  ```

  Update it to also assert:
  ```python
      assert len(ui.reasonings) == result.total
  ```

- [ ] **Step 2: Run tests to verify the new assertions currently fail**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/test_session.py -v 2>&1 | grep -E "FAIL|PASS|ERROR"
  ```

  The tests that call `run_session` should still pass (the assertion doesn't fail
  yet) — but once we wire in `show_reasoning`, if it's called 0 times currently,
  the assertions will fail. If they pass now (because `show_reasoning` is not called
  yet), note that they will correctly fail once we remove the old selection logic
  without wiring in the new one.

- [ ] **Step 3: Refactor `run_session` to use `_select_card`**

  Replace the `run_session` body in `app/lituk/review/session.py`. The new version
  removes `n_unexplored` and `n_explored` (managed inside `_select_card` now) and
  replaces the selection block with a `_select_card` call:

  ```python
  def run_session(
      conn: sqlite3.Connection,
      today: date,
      rng: random.Random,
      config: SessionConfig,
      ui: UI,
      topics: list[int] | None = None,
      session_id: str | None = None,
  ) -> SessionResult:
      due: list[int] = _due_pool(conn, today, topics)
      new: list[int] = _new_pool(conn, topics)
      rng.shuffle(new)
      new_post, due_post = _compute_posteriors(conn, today, topics)

      cutoff = (today - timedelta(days=30)).isoformat()
      row = conn.execute(
          "SELECT"
          " SUM(CASE WHEN correct=0 THEN 1 ELSE 0 END) AS wrong,"
          " SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) AS correct"
          " FROM reviews WHERE pool IN ('due','lapsed','drill')"
          " AND date(reviewed_at) >= ?",
          (cutoff,),
      ).fetchone()
      n_wrong = row["wrong"] or 0
      n_correct = row["correct"] or 0

      lapsed: deque[int] = deque()
      correct_count = 0
      total = 0
      weak: set[int] = set()

      for _ in range(config.size):
          sel = _select_card(
              rng, lapsed, due, new, due_post, new_post, conn, today
          )
          if sel is None:
              break
          new_post = sel.new_post
          ui.show_reasoning(sel.reasoning)

          correct, _ = _present_and_grade(
              conn, today, ui, sel.fact_id, sel.pool_label, rng, session_id
          )

          if sel.pool_label in ("due", "lapsed"):
              if correct:
                  n_correct += 1
              else:
                  n_wrong += 1
              due_post = PoolPosterior(alpha=n_wrong + 1, beta=n_correct + 1)

          if correct:
              correct_count += 1
          else:
              weak.add(sel.fact_id)
              lapsed.append(sel.fact_id)

          total += 1

      result = SessionResult(
          correct=correct_count,
          total=total,
          weak_facts=sorted(weak),
      )
      ui.show_summary(result)
      return result
  ```

  Also update the import at the top of `session.py` — `choose` is no longer called
  directly from `run_session` (it's called inside `_select_card` via
  `choose_with_samples`). The import line becomes:

  ```python
  from lituk.review.bandit import PoolPosterior, choose_with_samples
  ```

  Remove `choose` from the import (it's still exported from `bandit.py` but no
  longer needed in `session.py`).

- [ ] **Step 4: Run the full test suite**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/ -v
  ```

  Expected: all PASS. Fix any failures before proceeding.

- [ ] **Step 5: Commit**

  ```bash
  git add app/lituk/review/session.py app/tests/test_session.py
  git commit -m "Wire _select_card and show_reasoning into run_session"
  ```

---

## Task 8: Wire `_drill_reasoning` into `run_drill_session`

**Files:**
- Modify: `app/lituk/review/session.py`
- Test: `app/tests/test_session.py`

- [ ] **Step 1: Add integration assertions to drill session tests**

  Find existing tests that call `run_drill_session` with a `StubUI` and add:

  ```python
  assert len(ui.reasonings) == result.total
  ```

  `run_drill_session` shows reasoning for every card (both initial drill cards and
  lapsed re-shows), so `len(reasonings)` must equal `result.total`.

- [ ] **Step 2: Update `run_drill_session` to call `show_reasoning`**

  In `app/lituk/review/session.py`, update `run_drill_session`. Add the
  `_drill_reasoning` call before `_present_and_grade` in both the lapsed and
  drill branches:

  ```python
  def run_drill_session(
      conn: sqlite3.Connection,
      today: date,
      rng: random.Random,
      config: SessionConfig,
      ui: UI,
      topics: list[int] | None = None,
      session_id: str | None = None,
  ) -> SessionResult:
      pool: list[int] = _drill_pool(conn, topics)
      rng.shuffle(pool)

      lapsed: deque[int] = deque()
      correct_count = 0
      total = 0
      weak: set[int] = set()

      for _ in range(config.size):
          if lapsed:
              fact_id = lapsed.popleft()
              pool_label = "lapsed"
          else:
              if not pool:
                  break
              fact_id = pool.pop(0)
              pool_label = "drill"

          ui.show_reasoning(_drill_reasoning(conn, fact_id, today))

          correct, _ = _present_and_grade(
              conn, today, ui, fact_id, pool_label, rng, session_id
          )

          if correct:
              correct_count += 1
          else:
              weak.add(fact_id)
              lapsed.append(fact_id)

          total += 1

      result = SessionResult(
          correct=correct_count,
          total=total,
          weak_facts=sorted(weak),
      )
      ui.show_summary(result)
      return result
  ```

- [ ] **Step 3: Run the full test suite**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/ -v
  ```

  Expected: all PASS. Fix any failures before proceeding.

- [ ] **Step 4: Commit**

  ```bash
  git add app/lituk/review/session.py app/tests/test_session.py
  git commit -m "Wire _drill_reasoning and show_reasoning into run_drill_session"
  ```

---

## Task 9: Final check and push

- [ ] **Step 1: Run the complete test suite one final time**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/ -v --tb=short
  ```

  Expected: all PASS, 0 failures.

- [ ] **Step 2: Check coverage (optional sanity check)**

  ```bash
  cd /Users/djn/proj/lituk/app && uv run pytest tests/ --cov=lituk --cov-report=term-missing
  ```

  Expected: 100% coverage (or close to it; any gaps should be in unreachable paths).

- [ ] **Step 3: Commit spec and plan on the feature branch**

  The spec and plan docs were written on `main` (before the branch was created).
  Stage and commit them now:

  ```bash
  git add docs/superpowers/specs/2026-05-11-review-reasoning-design.md
  git add docs/superpowers/plans/2026-05-11-review-reasoning.md
  git commit -m "Add spec and plan for review reasoning display (#16)"
  ```

- [ ] **Step 4: Open a PR**

  Use the `commit-commands:commit-push-pr` skill, or:

  ```bash
  git push -u origin <branch-name>
  gh pr create --title "Add reasoning display for card selection (#16)" \
    --body "Surfaces why each card was chosen during review sessions.

  - CLI: dim grey line before each question
  - Web: print line on the server terminal
  - Regular mode: full MAB reasoning with Beta posteriors and θ draws
  - Drill mode: card stats (lapses, last seen, last wrong)
  - Explore mode: no reasoning (random from unseen)

  Closes #16"
  ```
