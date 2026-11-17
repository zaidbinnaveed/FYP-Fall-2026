"""Provenance written into every run folder: environment and git state."""

from __future__ import annotations

import importlib.metadata
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import torch


def _version(dist: str) -> str | None:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return None


def environment_info(device: torch.device) -> dict[str, Any]:
    """Library, CUDA and hardware versions; required in every run (team decision 4)."""
    cuda_available = torch.cuda.is_available()
    gpus = (
        [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
        if cuda_available
        else []
    )
    cudnn = torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else None
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "torch": torch.__version__,
        "torchvision": _version("torchvision"),
        "transformers": _version("transformers"),
        "numpy": _version("numpy"),
        "scikit-learn": _version("scikit-learn"),
        "oscc-ml": _version("oscc-ml"),
        "cuda_available": cuda_available,
        "cuda_version": torch.version.cuda,
        "cudnn_version": cudnn,
        "gpu_names": gpus,
        "device_used": str(device),
        "torch_num_threads": torch.get_num_threads(),
    }


def git_state(repo_dir: Path) -> dict[str, Any]:
    """Commit hash and whether the working tree had uncommitted changes."""

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
