import argparse
import pathlib
from datetime import date

from lituk.db import init_db
from lituk.web.queries import (
    by_chapter,
    coverage,
    due_today,
    recent_sessions,
    streak,
    weak_facts,
)


_DEFAULT_DB = pathlib.Path(__file__).parents[2] / "data" / "lituk.db"


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="LITUK study statistics")
    parser.add_argument("--db", default=str(_DEFAULT_DB), help="Path to SQLite DB")
    parsed = parser.parse_args(args)

    conn = init_db(parsed.db)
    try:
        today = date.today()
        cov = coverage(conn)
        _streak = streak(conn, today)
        _due = due_today(conn, today)
        chapters = by_chapter(conn)
        recent = recent_sessions(conn)
        weak = weak_facts(conn)
    finally:
        conn.close()

    print(f"Coverage:  {cov['seen']} / {cov['total']} facts seen ({cov['pct_seen']}%)")
    print(f"Streak:    {_streak} day{'s' if _streak != 1 else ''}")
    print(f"Due today: {_due} card{'s' if _due != 1 else ''}")

    if chapters:
        print("\nBy chapter:")
        for ch in chapters:
            print(f"  {ch['chapter_name']:<45} {ch['pct_correct']}%")

    if recent:
        print("\nRecent sessions:")
        for s in recent:
            dt = s["started_at"][:10]
            print(f"  {dt}  {s['correct']} / {s['total']}")

    if weak:
        print("\nWeak facts:")
        for f in weak:
            text = f["question_text"]
            text = text[:60] + "…" if len(text) > 60 else text
            lapses = f["lapses"]
            print(f"  • {text}  ({lapses} lapse{'s' if lapses != 1 else ''})")
