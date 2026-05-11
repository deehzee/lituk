import argparse
import pathlib
import random
import sys
import uuid
from datetime import date

from lituk.db import init_db
from lituk.review.cli import TerminalUI
from lituk.review.session import (
    SessionConfig,
    run_drill_session,
    run_explore_session,
    run_session,
)
from lituk.web.queries import coverage, due_today


_DEFAULT_DB = pathlib.Path(__file__).parents[2] / "data" / "lituk.db"


def _parse_topics(value: str) -> list[int]:
    try:
        topics = [int(t.strip()) for t in value.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid topic value: {value!r}")
    for t in topics:
        if not 1 <= t <= 5:
            raise argparse.ArgumentTypeError(f"Topic must be 1-5, got {t}")
    return topics


def main(
    args: list[str] | None = None,
    _rng: random.Random | None = None,
) -> None:
    parser = argparse.ArgumentParser(description="LITUK review session")
    parser.add_argument("--db", default=str(_DEFAULT_DB), help="Path to SQLite DB")
    parser.add_argument("--size", type=int, default=24, help="Cards per session")
    parser.add_argument(
        "--mode",
        choices=["regular", "drill", "explore"],
        default="regular",
        help=(
            "Session mode: regular (SM-2 + bandit), drill (missed facts), "
            "explore (unseen facts). Default: regular."
        ),
    )
    parser.add_argument(
        "--chapters", "--topic",
        type=_parse_topics,
        default=None,
        dest="chapters",
        metavar="N[,N]",
        help="Chapter numbers to study, comma-separated (1-5). Default: all.",
    )
    parsed = parser.parse_args(args)

    conn = init_db(parsed.db)
    _today = date.today()

    if parsed.mode == "regular":
        _due = due_today(conn, _today)
        _total = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        _banner = f"Regular mode  •  {_due} due today  •  {_total} facts total"
    elif parsed.mode == "drill":
        _n = conn.execute(
            "SELECT COUNT(*) FROM card_state WHERE lapses > 0"
        ).fetchone()[0]
        _banner = f"Drill mode  •  {_n} missed facts ready"
    else:  # explore
        _cov = coverage(conn)
        _unseen = _cov["total"] - _cov["seen"]
        _banner = f"Explore mode  •  {_unseen} unseen of {_cov['total']} total"
    print(_banner)

    config = SessionConfig(size=parsed.size)
    rng = _rng or random.Random()
    sid = str(uuid.uuid4())

    if parsed.mode == "drill":
        run_drill_session(
            conn, _today, rng, config, TerminalUI(),
            topics=parsed.chapters, session_id=sid,
        )
    elif parsed.mode == "explore":
        run_explore_session(
            conn, _today, rng, config, TerminalUI(),
            topics=parsed.chapters, session_id=sid,
        )
    else:
        run_session(
            conn, _today, rng, config, TerminalUI(),
            topics=parsed.chapters, session_id=sid,
        )

    conn.close()
    sys.exit(0)
