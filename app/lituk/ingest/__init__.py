import argparse
import pathlib

from lituk.ingest.ingester import ingest_all

_DEFAULT_DB = pathlib.Path(__file__).parents[2] / "data" / "lituk.db"
_DEFAULT_DIR = pathlib.Path(__file__).parents[3] / "britizen" / "mock_tests"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest mock test PDFs into SQLite"
    )
    parser.add_argument(
        "--db", default=str(_DEFAULT_DB), help="Path to SQLite DB"
    )
    parser.add_argument(
        "--dir",
        default=str(_DEFAULT_DIR),
        help="Mock tests directory"
    )
    args = parser.parse_args()
    print(f"Ingesting PDFs from {args.dir} into {args.db} ...")
    ingest_all(args.db, args.dir)
    print("Done.")


if __name__ == "__main__":  # pragma: no cover
    main()
