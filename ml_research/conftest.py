"""Test-session disk safeguards (old laptops with a small system drive).

* ``OSCC_WORK_DIR`` (optional): when set, pytest's ``--basetemp`` and ``TMP``/``TEMP`` for the
  test process and its subprocesses go under ``<OSCC_WORK_DIR>/pytest`` and ``<OSCC_WORK_DIR>/tmp``,
  and the basetemp is deleted when the session ends. When unset (CI, the university machine)
  pytest's own defaults apply unchanged.
* A free-disk check stops the session before any test runs if the drive holding the repository or
  the temp root has less than ``OSCC_MIN_FREE_GB`` (default 5) GB free. Set it to 0 to disable.
* ``pyproject.toml`` sets ``tmp_path_retention_policy = "none"`` so no old temp folders are kept.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_OWNED_BASETEMP: Path | None = None


def _min_free_gb() -> float:
    try:
        return float(os.environ.get("OSCC_MIN_FREE_GB", "5"))
    except ValueError:
        return 5.0


def _free_gb(path: Path) -> float:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free / 1024**3


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    global _OWNED_BASETEMP
    work = os.environ.get("OSCC_WORK_DIR", "").strip()
    if work:
        root = Path(work).expanduser().resolve()
        tmp = root / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        for var in ("TMP", "TEMP", "TMPDIR"):
            os.environ[var] = str(tmp)
        tempfile.tempdir = str(tmp)
        if not config.option.basetemp:
            (root / "pytest").mkdir(parents=True, exist_ok=True)
            _OWNED_BASETEMP = root / "pytest" / f"run-{os.getpid()}"
            config.option.basetemp = str(_OWNED_BASETEMP)

    limit = _min_free_gb()
    if limit > 0:
        temp_root = Path(config.option.basetemp or tempfile.gettempdir())
        for label, path in (("repository", Path(config.rootpath)), ("temp", temp_root)):
            free = _free_gb(path)
            if free < limit:
                pytest.exit(
                    f"only {free:.1f} GB free on the {label} drive ({path}); at least {limit:g} GB "
                    "is needed. Free some space or set OSCC_WORK_DIR to a larger drive "
                    "(OSCC_MIN_FREE_GB=0 disables this check).",
                    returncode=3,
                )


def pytest_unconfigure(config: pytest.Config) -> None:
    if _OWNED_BASETEMP is not None:
        shutil.rmtree(_OWNED_BASETEMP, ignore_errors=True)
