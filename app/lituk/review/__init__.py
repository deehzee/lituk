import argparse
import pathlib
import random
import sys
from datetime import date

from lituk.db import init_db
from lituk.review.cli import TerminalUI
from lituk.review.session import SessionConfig, run_session


_DEFAULT_DB = pathlib.Path(__file__).parents[2] / "data" / "lituk.db"


def main(
    args: list[str] | None = None,
    _rng: random.Random | None = None,
) -> None:
    parser = argparse.ArgumentParser(description="LITUK review session")
    parser.add_argument("--db", default=str(_DEFAULT_DB), help="Path to SQLite DB")
    parser.add_argument("--size", type=int, default=24, help="Cards per session")
    parser.add_argument(
        "--new-cap", type=int, default=5, dest="new_cap",
        help="Max new cards per session"
    )
    parsed = parser.parse_args(args)

    conn = init_db(parsed.db)
    config = SessionConfig(size=parsed.size, new_cap=parsed.new_cap)
    run_session(conn, date.today(), _rng or random.Random(), config, TerminalUI())
    conn.close()
    sys.exit(0)
