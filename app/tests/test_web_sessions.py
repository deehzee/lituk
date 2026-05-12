import threading
import time
from datetime import date

from lituk.review.presenter import Prompt
from lituk.web.sessions import WebUI


TODAY = date(2026, 5, 9)


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


# ---------------------------------------------------------------------------
# State transitions and version increments
# ---------------------------------------------------------------------------

def test_initial_state_is_starting():
    ui = WebUI()
    assert ui.state.kind == "starting"
    assert ui.state.version == 0


def test_show_prompt_transitions_to_prompt_state():
    ui = WebUI()
    prompt = _make_prompt()
    t = threading.Thread(target=lambda: ui.submit_answer([0]))
    t.start()
    # Let the thread start and block on the queue
    time.sleep(0.05)
    # show_prompt blocks until answer arrives — drive it in this thread
    # Actually: submit_answer posts *before* show_prompt may block,
    # but queue.maxsize=1 means it's fine; show_prompt reads from queue
    t.join(timeout=1)
    # Call show_prompt after answer is pre-loaded
    ui2 = WebUI()
    ui2._answer_q.put([0])
    result = ui2.show_prompt(_make_prompt())
    assert ui2.state.kind == "prompt"
    assert result == [0]


def test_show_prompt_sets_state_before_blocking():
    """State must be 'prompt' while show_prompt is blocking for an answer."""
    ui = WebUI()
    prompt = _make_prompt()
    state_during_prompt = []

    def driver():
        time.sleep(0.05)
        state_during_prompt.append(ui.state.kind)
        ui.submit_answer([0])

    t = threading.Thread(target=driver)
    t.start()
    ui.show_prompt(prompt)
    t.join()
    assert state_during_prompt[0] == "prompt"


def test_show_prompt_strips_correct_indices_from_payload():
    """correct_indices must NOT appear in the prompt state payload."""
    ui = WebUI()
    prompt = _make_prompt(correct_indices=[1, 3])
    state_payload = []

    def driver():
        time.sleep(0.05)
        state_payload.append(dict(ui.state.payload))
        ui.submit_answer([1, 3])

    t = threading.Thread(target=driver)
    t.start()
    ui.show_prompt(prompt)
    t.join()
    assert "correct_indices" not in state_payload[0]


def test_show_feedback_correct_transitions_to_feedback():
    ui = WebUI()
    prompt = _make_prompt()
    ui._grade_q.put(4)
    grade = ui.show_feedback(prompt, correct=True)
    assert ui.state.kind == "feedback"
    assert grade == 4


def test_show_feedback_incorrect_returns_zero_after_grade_submitted():
    """On miss, show_feedback blocks until grade submitted, then returns 0."""
    ui = WebUI()
    prompt = _make_prompt(correct_indices=[1])
    grades = []

    def run():
        grades.append(ui.show_feedback(prompt, correct=False))

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.05)
    assert ui.state.kind == "feedback"
    ui.submit_grade(4)  # any grade value; return value will be 0
    t.join(timeout=1)
    assert grades == [0]


def test_show_feedback_incorrect_blocks_until_grade():
    """show_feedback(correct=False) must block on grade_q."""
    ui = WebUI()
    prompt = _make_prompt(correct_indices=[1])
    done = threading.Event()

    def run():
        ui.show_feedback(prompt, correct=False)
        done.set()

    t = threading.Thread(target=run)
    t.start()
    assert not done.wait(timeout=0.1), "show_feedback returned before grade"
    ui.submit_grade(0)
    assert done.wait(timeout=1.0), "show_feedback never returned after grade"
    t.join()


def test_show_feedback_reveals_correct_indices():
    ui = WebUI()
    prompt = _make_prompt(correct_indices=[2])
    ui._grade_q.put(4)
    ui.show_feedback(prompt, correct=True)
    assert ui.state.payload["correct_indices"] == [2]


def test_show_feedback_payload_includes_explanation():
    ui = WebUI()
    prompt = _make_prompt()
    ui._grade_q.put(4)
    ui.show_feedback(prompt, True)
    assert ui.state.payload["explanation"] == "The year was 1066."


def test_show_summary_transitions_to_summary():
    from lituk.review.session import SessionResult
    ui = WebUI()
    result = SessionResult(correct=20, total=24, weak_facts=[1, 2])
    ui.show_summary(result)
    assert ui.state.kind == "summary"
    assert ui.state.payload["correct"] == 20


def test_version_increments_on_each_transition():
    ui = WebUI()
    v0 = ui.state.version
    ui._grade_q.put(4)
    ui.show_feedback(_make_prompt(), correct=True)
    v1 = ui.state.version
    from lituk.review.session import SessionResult
    ui.show_summary(SessionResult(correct=1, total=1, weak_facts=[]))
    v2 = ui.state.version
    assert v1 > v0
    assert v2 > v1


# ---------------------------------------------------------------------------
# submit_answer / submit_grade routing
# ---------------------------------------------------------------------------

def test_submit_answer_unblocks_show_prompt():
    ui = WebUI()
    results = []
    t = threading.Thread(target=lambda: results.append(ui.show_prompt(_make_prompt())))
    t.start()
    time.sleep(0.05)
    ui.submit_answer([2])
    t.join(timeout=1)
    assert results == [[2]]


def test_submit_grade_unblocks_show_feedback():
    ui = WebUI()
    grades = []
    prompt = _make_prompt()
    t = threading.Thread(
        target=lambda: grades.append(ui.show_feedback(prompt, correct=True))
    )
    t.start()
    time.sleep(0.05)
    ui.submit_grade(5)
    t.join(timeout=1)
    assert grades == [5]


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
