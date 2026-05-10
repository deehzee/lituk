import argparse
import pathlib
import random
import sys
import uuid
from datetime import date

from lituk.db import init_db
from lituk.review.cli import TerminalUI
from lituk.review.session import SessionConfig, run_session


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
        "--topic",
        type=_parse_topics,
        default=None,
        metavar="N[,N]",
        help="Chapter numbers to study, comma-separated (1-5). Default: all.",
    )
    parsed = parser.parse_args(args)

    conn = init_db(parsed.db)
    config = SessionConfig(size=parsed.size)
    run_session(
        conn, date.today(), _rng or random.Random(), config, TerminalUI(),
        topics=parsed.topic,
        session_id=str(uuid.uuid4()),
    )
    conn.close()
    sys.exit(0)
