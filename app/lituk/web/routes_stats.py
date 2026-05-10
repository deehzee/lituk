from datetime import date

from flask import Blueprint, jsonify, request

from lituk.db import init_db
from lituk.web import queries
from lituk.web import sessions as _sessions

bp = Blueprint("stats", __name__)


def _get_conn():
    return init_db(_sessions._db_path)


@bp.get("/api/topics")
def get_topics():
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name FROM chapters ORDER BY id"
        ).fetchall()
        return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])
    finally:
        conn.close()


@bp.get("/api/dashboard")
def get_dashboard():
    conn = _get_conn()
    try:
        today = date.today()
        return jsonify({
            "by_chapter": queries.by_chapter(conn),
            "recent": queries.recent_sessions(conn),
            "weak": queries.weak_facts(conn),
            "coverage": queries.coverage(conn),
            "streak": queries.streak(conn, today),
            "due_today": queries.due_today(conn, today),
        })
    finally:
        conn.close()


@bp.get("/api/coverage")
def get_coverage():
    chapters_raw = request.args.get("chapters")
    chapters: list[int] | None = None
    if chapters_raw:
        try:
            chapters = [int(c) for c in chapters_raw.split(",") if c.strip()]
        except ValueError:
            return jsonify(error="chapters must be comma-separated integers"), 400
    conn = _get_conn()
    try:
        return jsonify(queries.coverage(conn, chapters=chapters))
    finally:
        conn.close()


@bp.get("/api/missed")
def get_missed():
    chapters_raw = request.args.get("chapters")
    since_raw = request.args.get("since")

    chapters: list[int] | None = None
    if chapters_raw:
        try:
            chapters = [int(c) for c in chapters_raw.split(",") if c.strip()]
        except ValueError:
            return jsonify(error="chapters must be comma-separated integers"), 400

    since: date | None = None
    if since_raw:
        try:
            since = date.fromisoformat(since_raw)
        except ValueError:
            return jsonify(error="since must be YYYY-MM-DD"), 400

    conn = _get_conn()
    try:
        return jsonify(queries.missed_reviews(conn, chapters=chapters, since=since))
    finally:
        conn.close()
