import argparse
import pathlib
import sys

import anthropic

from lituk.db import init_db
from lituk.tag.tagger import load_summaries, tag_facts


_DEFAULT_DB = pathlib.Path(__file__).parents[2] / "data" / "lituk.db"
_DEFAULT_SUMMARIES = pathlib.Path(__file__).parents[3] / "ai" / "summary"


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Tag LITUK facts by chapter using Claude Haiku"
    )
    parser.add_argument("--db", default=str(_DEFAULT_DB),
                        help="Path to SQLite DB")
    parser.add_argument(
        "--summaries", default=str(_DEFAULT_SUMMARIES),
        help="Directory of chapter summary .md files",
    )
    parser.add_argument(
        "--retag", action="store_true",
        help="Re-tag facts that already have a topic assigned",
    )
    parsed = parser.parse_args(args)

    conn = init_db(parsed.db)
    client = anthropic.Anthropic()
    summaries = load_summaries(parsed.summaries)
    count = tag_facts(conn, client, summaries, retag=parsed.retag)
    print(f"Tagged {count} facts.")
    conn.close()
    sys.exit(0)
