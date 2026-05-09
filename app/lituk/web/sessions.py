import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date

from lituk.db import init_db
from lituk.review.presenter import Prompt
from lituk.review.session import (
    SessionConfig,
    SessionResult,
    run_drill_session,
    run_session,
)


@dataclass
class WebState:
    kind: str    # 'starting'|'prompt'|'feedback'|'summary'|'ended'
    payload: dict
    version: int


class WebUI:
    """UI Protocol implementation that bridges run_session to HTTP polling."""

    def __init__(self) -> None:
        self.state = WebState(kind="starting", payload={}, version=0)
        self._answer_q: queue.Queue[list[int]] = queue.Queue(maxsize=1)
        self._grade_q: queue.Queue[int] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self.last_activity = time.monotonic()

    def _set_state(self, kind: str, payload: dict) -> None:
        with self._lock:
            self.state = WebState(
                kind=kind,
                payload=payload,
                version=self.state.version + 1,
            )
            self.last_activity = time.monotonic()

    def show_prompt(self, prompt: Prompt) -> list[int]:
        self._set_state("prompt", {
            "fact_id": prompt.fact_id,
            "question_id": prompt.question_id,
            "text": prompt.text,
            "choices": prompt.choices,
            "is_multi": prompt.is_multi,
            "is_true_false": prompt.is_true_false,
        })
        return self._answer_q.get()

    def show_feedback(self, prompt: Prompt, correct: bool) -> int:
        self._set_state("feedback", {
            "correct": correct,
            "choices": prompt.choices,
            "correct_indices": prompt.correct_indices,
        })
        if not correct:
            return 0
        return self._grade_q.get()

    def show_summary(self, result: SessionResult) -> None:
        self._set_state("summary", asdict(result))

    def submit_answer(self, indices: list[int]) -> None:
        self._answer_q.put(indices)
        self.last_activity = time.monotonic()

    def submit_grade(self, grade: int) -> None:
        self._grade_q.put(grade)
        self.last_activity = time.monotonic()


# Module-level session registry
SESSIONS: dict[str, WebUI] = {}
_SESSIONS_LOCK = threading.Lock()

_SESSION_TIMEOUT_S = 1800  # 30 minutes
_JANITOR_INTERVAL_S = 60

_db_path: str = ""


def configure(db_path: str) -> None:
    """Called at app startup to set the database path."""
    global _db_path
    _db_path = db_path


def start_session(
    mode: str,
    chapters: list[int] | None,
) -> str:
    """Create a session, spawn its worker thread, return the session_id."""
    sid = str(uuid.uuid4())
    web_ui = WebUI()

    with _SESSIONS_LOCK:
        SESSIONS[sid] = web_ui

    def worker() -> None:
        conn = init_db(_db_path)
        today = date.today()
        config = SessionConfig()
        try:
            if mode == "drill":
                run_drill_session(
                    conn, today, __import__("random").Random(), config,
                    web_ui, topics=chapters or None, session_id=sid,
                )
            else:
                run_session(
                    conn, today, __import__("random").Random(), config,
                    web_ui, topics=chapters or None, session_id=sid,
                )
        finally:
            conn.close()
            web_ui._set_state("ended", {})

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return sid


def get_session(sid: str) -> WebUI | None:
    with _SESSIONS_LOCK:
        return SESSIONS.get(sid)


def remove_session(sid: str) -> None:
    with _SESSIONS_LOCK:
        SESSIONS.pop(sid, None)


def _janitor() -> None:
    while True:
        time.sleep(_JANITOR_INTERVAL_S)
        cutoff = time.monotonic() - _SESSION_TIMEOUT_S
        with _SESSIONS_LOCK:
            stale = [sid for sid, ui in SESSIONS.items()
                     if ui.last_activity < cutoff]
            for sid in stale:
                del SESSIONS[sid]


def start_janitor() -> None:
    t = threading.Thread(target=_janitor, daemon=True)
    t.start()
