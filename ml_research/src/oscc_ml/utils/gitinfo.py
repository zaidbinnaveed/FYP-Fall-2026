"""Git provenance for run folders and result archives (no heavy imports)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def git_state(repo_dir: Path) -> dict[str, Any]:
    """Commit hash and whether tracked files had uncommitted changes."""

    def run(*args: str) -> str | None:
        try:
            out = subprocess.run(  # noqa: S603 - fixed git arguments
                ["git", *args],  # noqa: S607 - git from PATH
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip()

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain", "--untracked-files=no")
    return {
        "git_commit": commit or "unknown",
        "git_dirty": None if status is None else bool(status),
    }
