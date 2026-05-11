import runpy
import sys
from unittest.mock import patch

import pytest

from lituk.cli import main


# ---------------------------------------------------------------------------
# Usage / help
# ---------------------------------------------------------------------------

def test_main_no_args_prints_usage_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Usage:" in out
    assert "ingest" in out


def test_main_help_flag_prints_usage_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Usage:" in out


def test_main_short_help_flag_prints_usage_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["-h"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Usage:" in out


# ---------------------------------------------------------------------------
# Unknown subcommand
# ---------------------------------------------------------------------------

def test_main_unknown_subcommand_exits_two(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["unknown-cmd"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "unknown subcommand" in err
    assert "unknown-cmd" in err


# ---------------------------------------------------------------------------
# Delegation to subcommands
# ---------------------------------------------------------------------------

def test_main_delegates_review():
    with patch("lituk.review.main") as mock_main:
        main(["review", "--help"])
    mock_main.assert_called_once_with(["--help"])


def test_main_delegates_ingest():
    with patch("lituk.ingest.main") as mock_main:
        main(["ingest", "--help"])
    mock_main.assert_called_once_with(["--help"])


def test_main_delegates_tag():
    with patch("lituk.tag.main") as mock_main:
        main(["tag", "--help"])
    mock_main.assert_called_once_with(["--help"])


def test_main_delegates_web():
    with patch("lituk.web.server.main") as mock_main:
        main(["web", "--help"])
    mock_main.assert_called_once_with(["--help"])


def test_main_delegates_stats():
    with patch("lituk.stats.main") as mock_main:
        main(["stats", "--help"])
    mock_main.assert_called_once_with(["--help"])


# ---------------------------------------------------------------------------
# sys.argv default
# ---------------------------------------------------------------------------

def test_main_reads_sysargv_when_argv_none():
    """When called with no argument, reads sys.argv[1:]."""
    with patch.object(sys, "argv", ["lituk"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# __main__ shim
# ---------------------------------------------------------------------------

def test_cli_main_module_callable():
    """python -m lituk.cli shim: importing the module works without error."""
    with patch("lituk.cli.main") as mock_main:
        runpy.run_module("lituk.cli", run_name="__main__")
    mock_main.assert_called_once_with()


# ---------------------------------------------------------------------------
# lituk.ingest.main now accepts args parameter
# ---------------------------------------------------------------------------

def test_ingest_main_accepts_args_parameter():
    """lituk.ingest.main() can be called with an explicit args list."""
    from lituk.ingest import main as ingest_main
    import inspect
    sig = inspect.signature(ingest_main)
    assert "argv" in sig.parameters
