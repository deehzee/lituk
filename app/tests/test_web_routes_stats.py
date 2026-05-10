import json
from datetime import date, timedelta

import pytest

from lituk.db import init_db
from lituk.web import create_app
import lituk.web.sessions as _sessions


TODAY = date.today()


@pytest.fixture
def app_and_conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _sessions.configure(db_path)
    application = create_app(db_path)
    application.config["TESTING"] = True
    yield application, conn, db_path
    conn.close()


@pytest.fixture
def client(app_and_conn):
    app, conn, _ = app_and_conn
    return app.test_client()


@pytest.fixture
def seeded(app_and_conn):
    """DB with one fact per chapter + reviews + card_state."""
    _, conn, db_path = app_and_conn
    fids = {}
    qids = {}
    for ch in range(1, 6):
        conn.execute(
            "INSERT INTO facts (question_text, correct_answer_text, topic)"
            " VALUES (?,?,?)",
            (f"Q_ch{ch}?", "A", ch),
        )
        conn.commit()
        fid = conn.execute(
            "SELECT id FROM facts WHERE question_text=?", (f"Q_ch{ch}?",)
        ).fetchone()["id"]
        fids[ch] = fid
        conn.execute(
            "INSERT INTO questions"
            " (source_test, q_number, question_text, choices, correct_letters,"
            "  is_true_false, is_multi, fact_id)"
            " VALUES (?,?,?,?,?,0,0,?)",
            (ch, 1, f"Q_ch{ch}?", json.dumps(["A", "B"]),
             json.dumps(["A"]), fid),
        )
        conn.commit()
        qids[ch] = conn.execute(
            "SELECT id FROM questions WHERE source_test=? AND q_number=1",
            (ch,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT OR REPLACE INTO card_state"
            " (fact_id, ease_factor, interval_days, repetitions, due_date,"
            "  lapses)"
            " VALUES (?,2.5,1,1,?,0)",
            (fid, TODAY.isoformat()),
        )
        conn.commit()
    # Add one review per fact
    for ch in range(1, 6):
        conn.execute(
            "INSERT INTO reviews"
            " (fact_id, question_id, reviewed_at, grade, correct, pool,"
            "  ease_after, interval_after, session_id)"
            " VALUES (?,?,?,4,1,'new',2.5,1,'s1')",
            (fids[ch], qids[ch],
             TODAY.isoformat() + "T10:00:00+00:00"),
        )
    conn.commit()
    return fids, qids


# ---------------------------------------------------------------------------
# GET /api/topics
# ---------------------------------------------------------------------------

def test_topics_returns_five_chapters(client):
    resp = client.get("/api/topics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 5
    ids = {d["id"] for d in data}
    assert ids == {1, 2, 3, 4, 5}
    for item in data:
        assert "name" in item


# ---------------------------------------------------------------------------
# GET /api/dashboard
# ---------------------------------------------------------------------------

def test_dashboard_returns_all_keys(client, seeded):
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.get_json()
    for key in ("by_chapter", "recent", "weak", "coverage", "streak",
                "due_today"):
        assert key in data, f"missing key: {key}"


def test_dashboard_by_chapter_has_five_entries(client, seeded):
    data = client.get("/api/dashboard").get_json()
    assert len(data["by_chapter"]) == 5


def test_dashboard_coverage_reflects_seeded_facts(client, seeded):
    data = client.get("/api/dashboard").get_json()
    cov = data["coverage"]
    assert cov["seen"] == 5
    assert cov["total"] == 5
    assert cov["pct_seen"] == 100.0


def test_dashboard_due_today_counts_seeded_cards(client, seeded, app_and_conn):
    _, conn, _ = app_and_conn
    # All 5 facts have due_date = TODAY
    data = client.get("/api/dashboard").get_json()
    assert data["due_today"] == 5


def test_dashboard_streak_is_one_after_one_day_reviews(client, seeded):
    data = client.get("/api/dashboard").get_json()
    assert data["streak"] >= 1


def test_dashboard_recent_sessions_groups_by_session_id(client, seeded):
    data = client.get("/api/dashboard").get_json()
    assert len(data["recent"]) == 1
    assert data["recent"][0]["session_id"] == "s1"
    assert data["recent"][0]["total"] == 5


# ---------------------------------------------------------------------------
# GET /api/missed
# ---------------------------------------------------------------------------

def test_missed_empty_when_no_wrong_reviews(client, seeded):
    resp = client.get("/api/missed")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_missed_returns_wrong_reviews(client, app_and_conn):
    _, conn, _ = app_and_conn
    conn.execute(
        "INSERT INTO facts (question_text, correct_answer_text, topic)"
        " VALUES (?,?,?)",
        ("Missed Q?", "A", 3),
    )
    conn.commit()
    fid = conn.execute(
        "SELECT id FROM facts WHERE question_text='Missed Q?'"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO questions"
        " (source_test, q_number, question_text, choices, correct_letters,"
        "  is_true_false, is_multi, fact_id)"
        " VALUES (1,99,'Missed Q?',?,?,0,0,?)",
        (json.dumps(["A", "B"]), json.dumps(["A"]), fid),
    )
    conn.commit()
    qid = conn.execute(
        "SELECT id FROM questions WHERE source_test=1 AND q_number=99"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO reviews"
        " (fact_id, question_id, reviewed_at, grade, correct, pool,"
        "  ease_after, interval_after)"
        " VALUES (?,?,'2026-05-09T10:00:00+00:00',0,0,'new',2.0,1)",
        (fid, qid),
    )
    conn.commit()

    resp = client.get("/api/missed")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["fact_id"] == fid
    assert data[0]["miss_count"] == 1


def test_missed_chapters_filter(client, app_and_conn):
    _, conn, _ = app_and_conn
    for ch, qtext in [(3, "Missed ch3?"), (4, "Missed ch4?")]:
        conn.execute(
            "INSERT INTO facts (question_text, correct_answer_text, topic)"
            " VALUES (?,?,?)", (qtext, "A", ch),
        )
        conn.commit()
        fid = conn.execute(
            "SELECT id FROM facts WHERE question_text=?", (qtext,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO questions"
            " (source_test, q_number, question_text, choices,"
            "  correct_letters, is_true_false, is_multi, fact_id)"
            " VALUES (?,?,?,?,?,0,0,?)",
            (ch, ch * 10, qtext,
             json.dumps(["A", "B"]), json.dumps(["A"]), fid),
        )
        conn.commit()
        qid = conn.execute(
            "SELECT id FROM questions WHERE source_test=? AND q_number=?",
            (ch, ch * 10),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO reviews"
            " (fact_id, question_id, reviewed_at, grade, correct, pool,"
            "  ease_after, interval_after)"
            " VALUES (?,?,'2026-05-09T10:00:00+00:00',0,0,'new',2.0,1)",
            (fid, qid),
        )
        conn.commit()

    resp = client.get("/api/missed?chapters=3")
    assert resp.status_code == 200
    data = resp.get_json()
    assert all(r["question_text"] == "Missed ch3?" for r in data)


def test_missed_since_filter(client, app_and_conn):
    _, conn, _ = app_and_conn
    conn.execute(
        "INSERT INTO facts (question_text, correct_answer_text)"
        " VALUES (?,?)", ("Old Q?", "A"),
    )
    conn.commit()
    fid = conn.execute(
        "SELECT id FROM facts WHERE question_text='Old Q?'"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO questions"
        " (source_test, q_number, question_text, choices, correct_letters,"
        "  is_true_false, is_multi, fact_id)"
        " VALUES (1,200,'Old Q?',?,?,0,0,?)",
        (json.dumps(["A", "B"]), json.dumps(["A"]), fid),
    )
    conn.commit()
    qid = conn.execute(
        "SELECT id FROM questions WHERE source_test=1 AND q_number=200"
    ).fetchone()["id"]
    # old review
    conn.execute(
        "INSERT INTO reviews"
        " (fact_id, question_id, reviewed_at, grade, correct, pool,"
        "  ease_after, interval_after)"
        " VALUES (?,?,'2026-01-01T10:00:00+00:00',0,0,'new',2.0,1)",
        (fid, qid),
    )
    # recent review
    conn.execute(
        "INSERT INTO reviews"
        " (fact_id, question_id, reviewed_at, grade, correct, pool,"
        "  ease_after, interval_after)"
        " VALUES (?,?,'2026-05-09T10:00:00+00:00',0,0,'new',2.0,1)",
        (fid, qid),
    )
    conn.commit()

    resp = client.get("/api/missed?since=2026-05-01")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert "2026-05-09" in data[0]["reviewed_at"]
