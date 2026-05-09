import sqlite3
from datetime import date


def by_chapter(conn: sqlite3.Connection) -> list[dict]:
    """Return % correct per chapter, all five chapters always present."""
    rows = conn.execute(
        "SELECT c.id AS chapter_id, c.name AS chapter_name,"
        "       COUNT(r.id) AS total,"
        "       COALESCE(SUM(r.correct), 0) AS correct"
        " FROM chapters c"
        " LEFT JOIN facts f ON f.topic = c.id"
        " LEFT JOIN reviews r ON r.fact_id = f.id"
        " GROUP BY c.id"
        " ORDER BY c.id"
    ).fetchall()
    result = []
    for row in rows:
        total = row["total"]
        correct = row["correct"]
        pct = (correct / total * 100.0) if total > 0 else 0.0
        result.append({
            "chapter_id": row["chapter_id"],
            "chapter_name": row["chapter_name"],
            "total": total,
            "correct": correct,
            "pct_correct": round(pct, 1),
        })
    return result


def recent_sessions(
    conn: sqlite3.Connection, limit: int = 10
) -> list[dict]:
    """Last N sessions grouped by session_id, ordered newest first."""
    rows = conn.execute(
        "SELECT session_id,"
        "       MIN(reviewed_at) AS started_at,"
        "       COUNT(*) AS total,"
        "       SUM(correct) AS correct"
        " FROM reviews"
        " WHERE session_id IS NOT NULL"
        " GROUP BY session_id"
        " ORDER BY started_at DESC"
        " LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "session_id": r["session_id"],
            "started_at": r["started_at"],
            "total": r["total"],
            "correct": r["correct"],
        }
        for r in rows
    ]


def weak_facts(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Top facts by lapse count, descending."""
    rows = conn.execute(
        "SELECT cs.fact_id, f.question_text, cs.lapses"
        " FROM card_state cs"
        " JOIN facts f ON f.id = cs.fact_id"
        " WHERE cs.lapses > 0"
        " ORDER BY cs.lapses DESC, cs.fact_id ASC"
        " LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "fact_id": r["fact_id"],
            "question_text": r["question_text"],
            "lapses": r["lapses"],
        }
        for r in rows
    ]


def coverage(conn: sqlite3.Connection) -> dict:
    """Fraction of all facts that have a card_state row."""
    total = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    seen = conn.execute("SELECT COUNT(*) FROM card_state").fetchone()[0]
    pct = (seen / total * 100.0) if total > 0 else 0.0
    return {"seen": seen, "total": total, "pct_seen": round(pct, 1)}


def streak(conn: sqlite3.Connection, today: date) -> int:
    """Current consecutive-day review streak ending on or before today."""
    rows = conn.execute(
        "SELECT DISTINCT date(reviewed_at) AS d"
        " FROM reviews"
        " WHERE date(reviewed_at) <= ?"
        " ORDER BY d DESC",
        (today.isoformat(),),
    ).fetchall()
    days = [r["d"] for r in rows]
    if not days:
        return 0
    count = 0
    expected = today
    for day_str in days:
        d = date.fromisoformat(day_str)
        if d == expected:
            count += 1
            expected = date.fromordinal(expected.toordinal() - 1)
        else:
            break
    return count


def due_today(conn: sqlite3.Connection, today: date) -> int:
    """Count of card_state rows due today or earlier."""
    row = conn.execute(
        "SELECT COUNT(*) FROM card_state WHERE due_date <= ?",
        (today.isoformat(),),
    ).fetchone()
    return row[0]


def missed_reviews(
    conn: sqlite3.Connection,
    chapters: list[int] | None = None,
    since: date | None = None,
) -> list[dict]:
    """All incorrect reviews with question details and per-fact miss count."""
    filters = ["r.correct = 0"]
    params: list = []

    if chapters:
        placeholders = ",".join("?" * len(chapters))
        filters.append(f"f.topic IN ({placeholders})")
        params.extend(chapters)
    if since:
        filters.append("date(r.reviewed_at) >= ?")
        params.append(since.isoformat())

    where = " AND ".join(filters)
    rows = conn.execute(
        f"SELECT r.id, r.fact_id, f.question_text,"
        f"       q.choices, q.correct_letters,"
        f"       r.reviewed_at,"
        f"       (SELECT COUNT(*) FROM reviews r2"
        f"         WHERE r2.fact_id = r.fact_id AND r2.correct = 0)"
        f"         AS miss_count"
        f" FROM reviews r"
        f" JOIN facts f ON f.id = r.fact_id"
        f" JOIN questions q ON q.id = r.question_id"
        f" WHERE {where}"
        f" ORDER BY r.reviewed_at DESC",
        params,
    ).fetchall()
    return [
        {
            "review_id": r["id"],
            "fact_id": r["fact_id"],
            "question_text": r["question_text"],
            "choices": r["choices"],
            "correct_letters": r["correct_letters"],
            "reviewed_at": r["reviewed_at"],
            "miss_count": r["miss_count"],
        }
        for r in rows
    ]
