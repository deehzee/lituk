import json
import time

import pytest

from lituk.db import init_db
from lituk.web import create_app
import lituk.web.sessions as _sessions


@pytest.fixture
def app(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _sessions.configure(db_path)
    application = create_app(db_path)
    application.config["TESTING"] = True
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /api/sessions
# ---------------------------------------------------------------------------

def test_post_sessions_returns_session_id(client):
    resp = client.post(
        "/api/sessions",
        json={"mode": "regular", "chapters": []},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "session_id" in data
    assert isinstance(data["session_id"], str)


def test_post_sessions_invalid_mode_returns_400(client):
    resp = client.post(
        "/api/sessions",
        json={"mode": "unknown", "chapters": []},
    )
    assert resp.status_code == 400


def test_post_sessions_missing_body_returns_400(client):
    resp = client.post("/api/sessions", data="not json",
                       content_type="text/plain")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/sessions/<id>/state
# ---------------------------------------------------------------------------

def test_get_state_unknown_session_returns_404(client):
    resp = client.get("/api/sessions/nonexistent/state")
    assert resp.status_code == 404


def test_get_state_returns_kind_payload_version(client):
    resp = client.post(
        "/api/sessions",
        json={"mode": "regular", "chapters": []},
    )
    sid = resp.get_json()["session_id"]
    resp2 = client.get(f"/api/sessions/{sid}/state")
    assert resp2.status_code == 200
    data = resp2.get_json()
    assert "kind" in data
    assert "payload" in data
    assert "version" in data


# ---------------------------------------------------------------------------
# POST /api/sessions/<id>/answer
# ---------------------------------------------------------------------------

def test_post_answer_unknown_session_returns_404(client):
    resp = client.post(
        "/api/sessions/bad/answer",
        json={"indices": [0]},
    )
    assert resp.status_code == 404


def test_post_answer_empty_indices_returns_400(client):
    resp_s = client.post(
        "/api/sessions",
        json={"mode": "regular", "chapters": []},
    )
    sid = resp_s.get_json()["session_id"]
    resp = client.post(
        f"/api/sessions/{sid}/answer",
        json={"indices": []},
    )
    assert resp.status_code == 400


def test_post_answer_missing_indices_returns_400(client):
    resp_s = client.post(
        "/api/sessions",
        json={"mode": "regular", "chapters": []},
    )
    sid = resp_s.get_json()["session_id"]
    resp = client.post(
        f"/api/sessions/{sid}/answer",
        json={},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/sessions/<id>/grade
# ---------------------------------------------------------------------------

def test_post_grade_unknown_session_returns_404(client):
    resp = client.post(
        "/api/sessions/bad/grade",
        json={"grade": 4},
    )
    assert resp.status_code == 404


def test_post_grade_invalid_grade_returns_400(client):
    resp_s = client.post(
        "/api/sessions",
        json={"mode": "regular", "chapters": []},
    )
    sid = resp_s.get_json()["session_id"]
    resp = client.post(
        f"/api/sessions/{sid}/grade",
        json={"grade": 99},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/sessions/<id>
# ---------------------------------------------------------------------------

def test_delete_unknown_session_returns_404(client):
    resp = client.delete("/api/sessions/nonexistent")
    assert resp.status_code == 404


def test_delete_session_removes_it(client):
    resp_s = client.post(
        "/api/sessions",
        json={"mode": "regular", "chapters": []},
    )
    sid = resp_s.get_json()["session_id"]
    resp_d = client.delete(f"/api/sessions/{sid}")
    assert resp_d.status_code == 204
    resp_g = client.get(f"/api/sessions/{sid}/state")
    assert resp_g.status_code == 404


# ---------------------------------------------------------------------------
# Full happy-path: drive a one-card session end-to-end
# ---------------------------------------------------------------------------

def _wait_for_kind(client, sid, kind, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/sessions/{sid}/state")
        data = resp.get_json()
        if data["kind"] == kind:
            return data
        time.sleep(0.05)
    raise TimeoutError(f"Never reached kind={kind!r}")


def _drive_session_to_summary(client, sid, timeout=10.0):
    """Drive a session by responding to every prompt/feedback until summary."""
    import time as _time
    deadline = _time.time() + timeout
    seen_version = -1
    while _time.time() < deadline:
        resp = client.get(f"/api/sessions/{sid}/state")
        data = resp.get_json()
        kind, version = data["kind"], data["version"]

        if kind == "summary":
            return data
        if version == seen_version:
            _time.sleep(0.05)
            continue
        seen_version = version

        if kind == "prompt":
            assert "correct_indices" not in data["payload"]
            client.post(f"/api/sessions/{sid}/answer", json={"indices": [0]})
        elif kind == "feedback":
            assert "correct_indices" in data["payload"]
            client.post(f"/api/sessions/{sid}/grade", json={"grade": 4})
        _time.sleep(0.05)
    raise TimeoutError("Session never reached summary")


def test_full_regular_session_one_card(tmp_path):
    """Drive a single-card regular session through the HTTP API."""
    from lituk.db import init_db as _init_db
    import json as _json
    db_path = str(tmp_path / "t.db")
    conn = _init_db(db_path)
    conn.execute(
        "INSERT INTO facts (question_text, correct_answer_text) VALUES (?,?)",
        ("Q1?", "Correct"),
    )
    conn.commit()
    fid = conn.execute(
        "SELECT id FROM facts WHERE question_text='Q1?'"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO questions"
        " (source_test, q_number, question_text, choices, correct_letters,"
        "  is_true_false, is_multi, fact_id)"
        " VALUES (1,1,'Q1?',?,?,0,0,?)",
        (_json.dumps(["Correct", "Wrong"]), _json.dumps(["A"]), fid),
    )
    conn.commit()
    conn.close()

    _sessions.configure(db_path)
    app = create_app(db_path)
    app.config["TESTING"] = True
    client = app.test_client()

    resp = client.post("/api/sessions", json={"mode": "regular", "chapters": []})
    sid = resp.get_json()["session_id"]

    summary = _drive_session_to_summary(client, sid)
    assert summary["payload"]["total"] >= 1
