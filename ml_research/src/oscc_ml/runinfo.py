"""Provenance written into every run folder: environment and git state."""

from __future__ import annotations

import importlib.metadata
import os
import platform
import sys
from typing import Any

import torch

from oscc_ml.utils.gitinfo import git_state

__all__ = ["environment_info", "git_state"]


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
    # torch.backends.cudnn has no type annotations.
    cudnn_ok = torch.backends.cudnn.is_available()  # type: ignore[no-untyped-call]
    cudnn = torch.backends.cudnn.version() if cudnn_ok else None  # type: ignore[no-untyped-call]
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
