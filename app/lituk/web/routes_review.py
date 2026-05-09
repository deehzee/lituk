from flask import Blueprint, jsonify, request

from lituk.web import sessions as _sessions

bp = Blueprint("review", __name__)

_VALID_GRADES = {0, 3, 4, 5}
_VALID_MODES = {"regular", "drill"}


@bp.post("/api/sessions")
def create_session():
    body = request.get_json(silent=True)
    if not body or "mode" not in body:
        return jsonify(error="mode required"), 400
    mode = body.get("mode")
    if mode not in _VALID_MODES:
        return jsonify(error=f"mode must be one of {sorted(_VALID_MODES)}"), 400
    chapters = body.get("chapters") or []
    sid = _sessions.start_session(mode, chapters if chapters else None)
    return jsonify(session_id=sid)


@bp.get("/api/sessions/<sid>/state")
def get_state(sid: str):
    ui = _sessions.get_session(sid)
    if ui is None:
        return jsonify(error="session not found"), 404
    s = ui.state
    return jsonify(kind=s.kind, payload=s.payload, version=s.version)


@bp.post("/api/sessions/<sid>/answer")
def submit_answer(sid: str):
    ui = _sessions.get_session(sid)
    if ui is None:
        return jsonify(error="session not found"), 404
    body = request.get_json(silent=True) or {}
    indices = body.get("indices")
    if not indices:
        return jsonify(error="indices must be a non-empty list"), 400
    ui.submit_answer(indices)
    return "", 204


@bp.post("/api/sessions/<sid>/grade")
def submit_grade(sid: str):
    ui = _sessions.get_session(sid)
    if ui is None:
        return jsonify(error="session not found"), 404
    body = request.get_json(silent=True) or {}
    grade = body.get("grade")
    if grade not in _VALID_GRADES:
        return jsonify(error=f"grade must be one of {sorted(_VALID_GRADES)}"), 400
    ui.submit_grade(grade)
    return "", 204


@bp.delete("/api/sessions/<sid>")
def delete_session(sid: str):
    ui = _sessions.get_session(sid)
    if ui is None:
        return jsonify(error="session not found"), 404
    _sessions.remove_session(sid)
    return "", 204
