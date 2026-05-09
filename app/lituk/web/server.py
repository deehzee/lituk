import argparse
import pathlib

from lituk.web import create_app
from lituk.web.sessions import start_janitor


_DEFAULT_DB = pathlib.Path(__file__).parents[2] / "data" / "lituk.db"


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="LITUK web study server")
    parser.add_argument(
        "--db", default=str(_DEFAULT_DB), help="Path to SQLite database"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="Port to listen on (default: 8765)"
    )
    parsed = parser.parse_args(args)

    app = create_app(parsed.db)
    start_janitor()
    app.run(host=parsed.host, port=parsed.port)
