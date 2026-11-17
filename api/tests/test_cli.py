from __future__ import annotations

from typer.testing import CliRunner

from app import __version__
from app.cli import cli


def test_version_command() -> None:
    result = CliRunner().invoke(cli, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_ensure_bucket_reports_storage_failure_cleanly() -> None:
    # Points at an unreachable endpoint from conftest; must exit 1, not crash with a traceback.
    result = CliRunner().invoke(cli, ["ensure-bucket"])
    assert result.exit_code == 1
