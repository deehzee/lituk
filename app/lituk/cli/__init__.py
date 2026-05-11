import sys


_USAGE = """\
Usage: lituk <subcommand> [options]

Subcommands:
  ingest    Ingest mock test PDFs into the database
  tag       Tag facts with chapter numbers using Claude
  review    Run an interactive review session
  web       Start the web study server
  stats     Show study statistics

Run 'lituk <subcommand> --help' for subcommand options.
"""


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE, end="")
        sys.exit(0)
    cmd, rest = argv[0], argv[1:]
    if cmd == "ingest":
        from lituk.ingest import main as _m
        _m(rest)
    elif cmd == "tag":
        from lituk.tag import main as _m
        _m(rest)
    elif cmd == "review":
        from lituk.review import main as _m
        _m(rest)
    elif cmd == "web":
        from lituk.web.server import main as _m
        _m(rest)
    elif cmd == "stats":
        from lituk.stats import main as _m
        _m(rest)
    else:
        print(f"lituk: unknown subcommand '{cmd}'", file=sys.stderr)
        print("Run 'lituk --help' for usage.", file=sys.stderr)
        sys.exit(2)
