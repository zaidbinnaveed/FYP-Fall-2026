"""Architecture guards that complement the import-linter contracts in pyproject.toml."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

API_ROOT = Path(__file__).resolve().parents[1]


def test_importing_the_app_never_loads_torch() -> None:
    code = (
        "import sys, app.main, app.worker.loop, app.cli; "
        "bad = [m for m in ('torch', 'torchvision', 'transformers') if m in sys.modules]; "
        "sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code], cwd=API_ROOT, check=False
    )
    assert result.returncode == 0


def test_alembic_scaffold_loads_with_no_revisions_yet() -> None:
    """Revision 0001 (all 20 tables) belongs to Phase D1."""
    script = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))
    assert script.get_heads() == []
