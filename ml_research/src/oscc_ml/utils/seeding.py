"""Reproducibility: one function seeds Python, NumPy and torch and sets deterministic modes."""

from __future__ import annotations

import os
import random
from typing import Literal

import numpy as np
import torch


def seed_everything(seed: int, deterministic: Literal["strict", "warn"]) -> None:
    """Seed every RNG and enable deterministic algorithms.

    ``strict`` raises if a non-deterministic op is used (smoke runs, determinism tests);
    ``warn`` only warns (full GPU runs, where a few CUDA kernels have no deterministic variant).
    """
    # Required by cuBLAS for deterministic GEMMs; must be set before CUDA initializes.
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    np.random.seed(seed)  # noqa: NPY002 - legacy global RNG used by some libraries
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True, warn_only=deterministic == "warn")


def make_generator(seed: int) -> torch.Generator:
    """A dedicated generator for DataLoader shuffling and worker base seeds."""
    generator = torch.Generator()
    generator.manual_seed(seed)
    return generator


def worker_init_fn(worker_id: int) -> None:
    """Seed Python and NumPy in each DataLoader worker from torch's per-worker seed.

    torch derives each worker's seed from the DataLoader generator, so this is deterministic.
    """
    del worker_id
    worker_seed = torch.initial_seed() % 2**32
    random.seed(worker_seed)
    np.random.seed(worker_seed)  # noqa: NPY002
