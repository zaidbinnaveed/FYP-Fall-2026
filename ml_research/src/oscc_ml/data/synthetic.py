"""Deterministic synthetic datasets for smoke runs and CI (ADR-0001 G-e).

These are NOT histology and carry no research meaning. They are written in exactly the prepared
dataset format (``oscc_ml.data.processed``) so that CI exercises the real training data path.
Their ``dataset_version`` always starts with ``synthetic``; reports refuse such runs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from oscc_ml.catalog import SYNTHETIC_PREFIX, is_synthetic
from oscc_ml.data.processed import (
    SPLITS,
    PatchMeta,
    PatchWriter,
    write_dataset_info,
    write_images_table,
)
from oscc_ml.preprocess import PREPROCESS_VERSION

__all__ = [
    "SYNTHETIC_DATASET_VERSION",
    "SYNTHETIC_PREFIX",
    "is_synthetic",
    "write_synthetic_dataset",
]

SYNTHETIC_DATASET_VERSION = "synthetic-smoke"


def synthetic_patch(rng: np.random.Generator, label: int, size: int) -> NDArray[np.uint8]:
    """Pink background; class 1 has more and darker purple blobs (a learnable difference)."""
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


def write_synthetic_dataset(
    root: Path,
    images_per_split: tuple[int, int, int],
    seed: int,
    *,
    patches_per_image: tuple[int, int] = (1, 1),
    patch_size: int = 224,
    dataset_version: str = SYNTHETIC_DATASET_VERSION,
) -> Path:
    """Write a balanced synthetic dataset. Images are grouped in pairs (same label) so grouped
    resampling is exercised; groups never cross splits. Returns ``root``."""
    if not is_synthetic(dataset_version):
        raise ValueError("synthetic datasets must have a dataset_version starting 'synthetic'")
    rng = np.random.default_rng(seed)
    image_rows = []
    counts: dict[str, dict[str, int]] = {}
    for split, n_images in zip(SPLITS, images_per_split, strict=True):
        if n_images < 4 or n_images % 4:
            raise ValueError("each split needs a multiple of 4 images (2 classes x pairs)")
        n_patches_total = 0
        with PatchWriter(root, split, patch_size) as writer:
            for i in range(n_images):
                label = (i // 2) % 2  # pairs: 0,0,1,1,0,0,...
                group_id = f"synthetic-{split}-g{i // 2:03d}"
                image_id = f"synthetic-{split}-{i:03d}"
                magnification = "100x" if i % 4 < 2 else "400x"
                low, high = patches_per_image
                n_patches = int(rng.integers(low, high + 1))
                for p in range(n_patches):
                    writer.add(
                        synthetic_patch(rng, label, patch_size),
                        PatchMeta(image_id, p, label, group_id, "synthetic", magnification),
                    )
                image_rows.append(
                    {
                        "image_id": image_id,
                        "split": split,
                        "label": label,
                        "group_id": group_id,
                        "source": "synthetic",
                        "magnification": magnification,
                        "n_patches": n_patches,
                    }
                )
                n_patches_total += n_patches
        counts[split] = {"images": n_images, "patches": n_patches_total}
    write_images_table(root, image_rows)
    write_dataset_info(
        root,
        {
            "dataset_version": dataset_version,
            "preprocess_version": PREPROCESS_VERSION,
            "patch_size": patch_size,
            "seed": seed,
            "counts": counts,
            "note": "synthetic data for pipeline checks only; not reportable",
        },
    )
    return root
