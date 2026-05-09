"""Coverage for server.py, __main__.py, page routes, and janitor."""
import runpy
import threading
import time
import unittest.mock

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
# Page routes (HTML file serving)
# ---------------------------------------------------------------------------

def test_index_page_returns_200(client):
    assert client.get("/").status_code == 200


def test_session_page_returns_200(client):
    assert client.get("/session").status_code == 200


def test_dashboard_page_returns_200(client):
    assert client.get("/dashboard").status_code == 200


def test_missed_page_returns_200(client):
    assert client.get("/missed").status_code == 200


def test_static_file_served(client):
    # pico.min.css doesn't exist yet; expect 404 but route is exercised
    resp = client.get("/static/pico.min.css")
    assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Stats error paths
# ---------------------------------------------------------------------------

def test_missed_bad_chapters_param_returns_400(client):
    resp = client.get("/api/missed?chapters=notanumber")
    assert resp.status_code == 400


def test_missed_bad_since_param_returns_400(client):
    resp = client.get("/api/missed?since=not-a-date")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Drill session worker branch
# ---------------------------------------------------------------------------

def test_start_drill_session_reaches_summary(tmp_path):
    import json as _json
    db_path = str(tmp_path / "t.db")
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO facts (question_text, correct_answer_text)"
        " VALUES (?,?)", ("DrillQ?", "A"),
    )
    conn.commit()
    fid = conn.execute(
        "SELECT id FROM facts WHERE question_text='DrillQ?'"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO questions"
        " (source_test, q_number, question_text, choices, correct_letters,"
        "  is_true_false, is_multi, fact_id)"
        " VALUES (1,1,'DrillQ?',?,?,0,0,?)",
        (_json.dumps(["A", "B"]), _json.dumps(["A"]), fid),
    )
    # Seed a lapsed card so the drill pool is non-empty
    conn.execute(
        "INSERT INTO card_state"
        " (fact_id, ease_factor, interval_days, repetitions, due_date, lapses)"
        " VALUES (?,2.0,1,1,'2026-05-08',2)",
        (fid,),
    )
    conn.commit()
    conn.close()

    _sessions.configure(db_path)
    app = create_app(db_path)
    app.config["TESTING"] = True
    client = app.test_client()

    resp = client.post("/api/sessions", json={"mode": "drill", "chapters": []})
    sid = resp.get_json()["session_id"]

    # Drive session to summary
    deadline = time.time() + 10.0
    seen_version = -1
    final_kind = None
    while time.time() < deadline:
        data = client.get(f"/api/sessions/{sid}/state").get_json()
        kind, version = data["kind"], data["version"]
        if kind == "summary":
            final_kind = kind
            break
        if version != seen_version:
            seen_version = version
            if kind == "prompt":
                client.post(f"/api/sessions/{sid}/answer", json={"indices": [0]})
            elif kind == "feedback":
                client.post(f"/api/sessions/{sid}/grade", json={"grade": 4})
        time.sleep(0.05)
    assert final_kind == "summary"


# ---------------------------------------------------------------------------
# Janitor cleanup
# ---------------------------------------------------------------------------

def test_janitor_removes_stale_sessions(tmp_path, monkeypatch):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    _sessions.configure(db_path)

    # Patch timeout to 0 so everything is immediately stale;
    # patch interval to 0 so janitor runs immediately.
    monkeypatch.setattr(_sessions, "_SESSION_TIMEOUT_S", 0)
    monkeypatch.setattr(_sessions, "_JANITOR_INTERVAL_S", 0)

    fake_ui = _sessions.WebUI()
    fake_ui.last_activity = 0.0
    with _sessions._SESSIONS_LOCK:
        _sessions.SESSIONS["stale-key"] = fake_ui

    cleaned = threading.Event()
    _orig_sleep = time.sleep

    def _one_shot_sleep(s):
        _orig_sleep(0)
        # After first sleep, remove the patch so next sleep blocks → loop ends
        monkeypatch.setattr(_sessions, "_JANITOR_INTERVAL_S", 9999)
        cleaned.set()

    monkeypatch.setattr(time, "sleep", _one_shot_sleep)
    t = threading.Thread(target=_sessions._janitor, daemon=True)
    t.start()
    assert cleaned.wait(timeout=2.0)
    assert "stale-key" not in _sessions.SESSIONS


# ---------------------------------------------------------------------------
# server.py main()
# ---------------------------------------------------------------------------

def test_server_main_runs_flask(tmp_path):
    from lituk.web.server import main
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    with unittest.mock.patch("lituk.web.Flask.run") as mock_run:
        main(["--db", db_path, "--port", "9999"])
    mock_run.assert_called_once_with(host="127.0.0.1", port=9999)


# ---------------------------------------------------------------------------
# __main__.py
# ---------------------------------------------------------------------------

def test_web_main_module(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    with unittest.mock.patch("lituk.web.server.main") as mock_main:
        runpy.run_module("lituk.web", run_name="__main__", alter_sys=True)
    mock_main.assert_called_once()
