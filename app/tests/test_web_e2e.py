"""End-to-end test: ingest 1 PDF → run full HTTP sessions → verify DB state."""
import time

import pytest

from lituk.db import init_db
from lituk.ingest.ingester import ingest_pdf
from lituk.web import create_app
import lituk.web.sessions as _sessions
from tests.conftest import PDF_TEST_1


@pytest.fixture
def e2e_client(tmp_path):
    db_path = str(tmp_path / "e2e.db")
    conn = init_db(db_path)
    ingest_pdf(conn, str(PDF_TEST_1), test_num=1)
    conn.close()

    _sessions.configure(db_path)
    app = create_app(db_path)
    app.config["TESTING"] = True
    yield app.test_client(), db_path


def _drive_to_summary(client, sid, timeout=30.0):
    deadline = time.time() + timeout
    seen_version = -1
    while time.time() < deadline:
        data = client.get(f"/api/sessions/{sid}/state").get_json()
        kind, version = data["kind"], data["version"]
        if kind == "summary":
            return data
        if version != seen_version:
            seen_version = version
            if kind == "prompt":
                client.post(f"/api/sessions/{sid}/answer",
                            json={"indices": [0]})
            elif kind == "feedback":
                client.post(f"/api/sessions/{sid}/grade",
                            json={"grade": 4})
        time.sleep(0.05)
    raise TimeoutError(f"Session {sid} never reached summary in {timeout}s")


# ---------------------------------------------------------------------------
# Regular session end-to-end
# ---------------------------------------------------------------------------

def test_e2e_regular_session_reviews_logged(e2e_client):
    client, db_path = e2e_client
    resp = client.post("/api/sessions",
                       json={"mode": "regular", "chapters": []})
    assert resp.status_code == 200
    sid = resp.get_json()["session_id"]

    summary = _drive_to_summary(client, sid)
    assert summary["payload"]["total"] >= 1

    conn = init_db(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE session_id=?", (sid,)
    ).fetchone()[0]
    conn.close()
    assert count == summary["payload"]["total"]


def test_e2e_regular_session_card_state_grows(e2e_client):
    client, db_path = e2e_client
    resp = client.post("/api/sessions",
                       json={"mode": "regular", "chapters": []})
    sid = resp.get_json()["session_id"]
    _drive_to_summary(client, sid)

    conn = init_db(db_path)
    seen = conn.execute("SELECT COUNT(*) FROM card_state").fetchone()[0]
    conn.close()
    assert seen > 0


def test_e2e_regular_session_pool_state_moves(e2e_client):
    client, db_path = e2e_client
    resp = client.post("/api/sessions",
                       json={"mode": "regular", "chapters": []})
    sid = resp.get_json()["session_id"]
    _drive_to_summary(client, sid)

    conn = init_db(db_path)
    rows = {r["pool"]: r for r in
            conn.execute("SELECT pool, alpha, beta FROM pool_state").fetchall()}
    conn.close()
    # At least one bandit arm should have moved off the Beta(1,1) prior
    assert rows["new"]["alpha"] > 1.0 or rows["new"]["beta"] > 1.0


def test_e2e_prompt_payload_never_contains_correct_indices(e2e_client):
    """Server must never send correct_indices in a prompt state payload."""
    client, db_path = e2e_client
    resp = client.post("/api/sessions",
                       json={"mode": "regular", "chapters": []})
    sid = resp.get_json()["session_id"]

    leaked = False
    deadline = time.time() + 5.0
    seen_version = -1
    cards_checked = 0

    while time.time() < deadline and cards_checked < 3:
        data = client.get(f"/api/sessions/{sid}/state").get_json()
        kind, version = data["kind"], data["version"]
        if kind == "summary":
            break
        if version != seen_version:
            seen_version = version
            if kind == "prompt":
                if "correct_indices" in data["payload"]:
                    leaked = True
                    break
                cards_checked += 1
                client.post(f"/api/sessions/{sid}/answer",
                            json={"indices": [0]})
            elif kind == "feedback":
                client.post(f"/api/sessions/{sid}/grade",
                            json={"grade": 4})
        time.sleep(0.05)

    assert not leaked, "correct_indices leaked in prompt payload!"


# ---------------------------------------------------------------------------
# Drill session end-to-end
# ---------------------------------------------------------------------------

def test_e2e_drill_session_after_lapses(e2e_client):
    client, db_path = e2e_client

    # First run a regular session to build card_state
    resp = client.post("/api/sessions",
                       json={"mode": "regular", "chapters": []})
    sid1 = resp.get_json()["session_id"]
    _drive_to_summary(client, sid1)

    # Manually set lapses on some facts so the drill pool is non-empty
    conn = init_db(db_path)
    conn.execute(
        "UPDATE card_state SET lapses = 2 WHERE rowid IN "
        "(SELECT rowid FROM card_state LIMIT 3)"
    )
    conn.commit()
    conn.close()

    # Run drill session
    resp = client.post("/api/sessions",
                       json={"mode": "drill", "chapters": []})
    assert resp.status_code == 200
    sid2 = resp.get_json()["session_id"]
    summary = _drive_to_summary(client, sid2)
    assert summary["payload"]["total"] >= 1

    # Verify drill reviews are tagged pool='drill'
    conn = init_db(db_path)
    drill_count = conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE pool='drill' AND session_id=?",
        (sid2,),
    ).fetchone()[0]
    conn.close()
    assert drill_count >= 1


# ---------------------------------------------------------------------------
# Two concurrent sessions
# ---------------------------------------------------------------------------

def test_e2e_two_concurrent_sessions_independent(e2e_client):
    client, db_path = e2e_client
    r1 = client.post("/api/sessions",
                     json={"mode": "regular", "chapters": []}).get_json()
    r2 = client.post("/api/sessions",
                     json={"mode": "regular", "chapters": []}).get_json()
    sid1, sid2 = r1["session_id"], r2["session_id"]
    assert sid1 != sid2

    # Both sessions should return independent states
    s1 = client.get(f"/api/sessions/{sid1}/state").get_json()
    s2 = client.get(f"/api/sessions/{sid2}/state").get_json()
    assert s1["kind"] in ("starting", "prompt")
    assert s2["kind"] in ("starting", "prompt")


# ---------------------------------------------------------------------------
# Explore session end-to-end
# ---------------------------------------------------------------------------

def test_e2e_explore_session_writes_card_state_for_new_facts(e2e_client):
    client, db_path = e2e_client

    conn = init_db(db_path)
    n_facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    n_explored_before = conn.execute(
        "SELECT COUNT(*) FROM card_state"
    ).fetchone()[0]
    conn.close()
    assert n_explored_before == 0

    resp = client.post("/api/sessions",
                       json={"mode": "explore", "chapters": []})
    assert resp.status_code == 200
    sid = resp.get_json()["session_id"]
    summary = _drive_to_summary(client, sid)
    assert summary["payload"]["total"] >= 1

    conn = init_db(db_path)
    n_explored_after = conn.execute(
        "SELECT COUNT(*) FROM card_state"
    ).fetchone()[0]
    new_reviews = conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE pool='new' AND session_id=?",
        (sid,),
    ).fetchone()[0]
    conn.close()

    assert n_explored_after > n_explored_before
    assert n_explored_after <= n_facts
    assert new_reviews >= 1


def test_e2e_explore_session_only_shows_unseen_facts(e2e_client):
    client, db_path = e2e_client

    # Run a regular session first to mark some facts as seen
    resp = client.post("/api/sessions",
                       json={"mode": "regular", "chapters": []})
    sid1 = resp.get_json()["session_id"]
    _drive_to_summary(client, sid1)

    conn = init_db(db_path)
    seen_after_regular = conn.execute(
        "SELECT COUNT(*) FROM card_state"
    ).fetchone()[0]
    conn.close()

    # Explore session should only touch previously unseen facts
    resp = client.post("/api/sessions",
                       json={"mode": "explore", "chapters": []})
    sid2 = resp.get_json()["session_id"]
    _drive_to_summary(client, sid2)

    conn = init_db(db_path)
    explore_reviews = conn.execute(
        "SELECT DISTINCT r.fact_id FROM reviews r"
        " JOIN card_state cs ON cs.fact_id = r.fact_id"
        " WHERE r.session_id=? AND r.pool='new'",
        (sid2,),
    ).fetchall()
    # All facts shown in explore session must have been unseen before it started
    explore_fact_ids = {r["fact_id"] for r in explore_reviews}
    originally_seen = conn.execute(
        "SELECT fact_id FROM reviews WHERE session_id=?", (sid1,)
    ).fetchall()
    originally_seen_ids = {r["fact_id"] for r in originally_seen}
    conn.close()
    assert explore_fact_ids.isdisjoint(originally_seen_ids)
