"""Deterministic synthetic images for the CPU smoke run (ADR-0001 G-e).

These are NOT histology and carry no research meaning. They exist only to exercise the training
pipeline end to end. Runs that use them have ``dataset_version == SYNTHETIC_DATASET_VERSION`` and
``smoke: true``, and the report generator refuses them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

SYNTHETIC_DATASET_VERSION = "synthetic-smoke"
LABELS = {0: "non_oscc", 1: "oscc"}


@dataclass(frozen=True)
class PatchRecord:
    image_id: str
    patch_index: int
    label: int  # 1 = oscc, 0 = non_oscc
    pixels: NDArray[np.uint8]  # HxWx3 RGB


def _make_image(rng: np.random.Generator, label: int, size: int) -> NDArray[np.uint8]:
    # Pink background for both classes; class 1 gets more and darker purple blobs. A learnable
    # difference keeps the smoke run meaningful as a pipeline check (loss can go down).
    base = np.array([230, 170, 200], dtype=np.float64)
    image = np.tile(base, (size, size, 1)) + rng.normal(0.0, 12.0, (size, size, 3))
    yy, xx = np.mgrid[0:size, 0:size]
    blobs = 40 if label == 1 else 10
    colour = np.array([90, 40, 140], dtype=np.float64) if label == 1 else np.array([170, 110, 170])
    for _ in range(blobs):
        cy, cx = rng.integers(0, size, 2)
        radius = rng.integers(4, 12)
        mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= radius**2
        image[mask] = colour + rng.normal(0.0, 8.0, 3)
    return np.clip(image, 0, 255).astype(np.uint8)


def make_split(name: str, count: int, seed: int, size: int = 224) -> list[PatchRecord]:
    """``count`` single-patch images, half per class, alternating labels; fully seed-determined."""
    if count % 2:
        raise ValueError("count must be even so both classes are balanced")
    offsets = {"train": 0, "val": 1, "test": 2}
    rng = np.random.default_rng([seed, offsets[name]])
    records = []
    for i in range(count):
        label = i % 2
        records.append(
            PatchRecord(
                image_id=f"synthetic-{name}-{i:03d}",
                patch_index=0,
                label=label,
                pixels=_make_image(rng, label, size),
            )
        )
    return records
