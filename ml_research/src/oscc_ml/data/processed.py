"""On-disk format of a prepared dataset, shared by ``prepare`` (Phase R1) and training.

    <root>/dataset.json            dataset_version, preprocess_version, patch size, counts
    <root>/images.csv              one row per image: image_id, split, label, group_id,
                                   source, magnification, n_patches
    <root>/patches_<split>.u8      raw uint8 array, shape (n, 224, 224, 3), RGB, row-major
    <root>/patches_<split>.csv     row i describes patch i: image_id, patch_index, label,
                                   group_id, source, magnification

Patches are appended one at a time by :class:`PatchWriter`, so preparing a dataset never holds
it in memory, and training reads them through ``numpy.memmap`` (random access, no decoding).
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np
import pandas as pd
import torch
from numpy.typing import NDArray
from torch.utils.data import Dataset

from oscc_ml.preprocess import to_float_tensor

SPLITS = ("train", "val", "test")
PATCH_COLUMNS = ["image_id", "patch_index", "label", "group_id", "source", "magnification"]
IMAGE_COLUMNS = [
    "image_id",
    "split",
    "label",
    "group_id",
    "source",
    "magnification",
    "n_patches",
]
LABEL_NAMES = {0: "non_oscc", 1: "oscc"}


@dataclass(frozen=True)
class PatchMeta:
    image_id: str
    patch_index: int
    label: int
    group_id: str
    source: str
    magnification: str


class PatchWriter:
    """Append-only writer for one split. Use as a context manager."""

    def __init__(self, root: Path, split: str, patch_size: int) -> None:
        if split not in SPLITS:
            raise ValueError(f"unknown split {split!r}")
        root.mkdir(parents=True, exist_ok=True)
        self.patch_size = patch_size
        self.count = 0
        self._bin = (root / f"patches_{split}.u8").open("wb")
        self._csv_handle = (root / f"patches_{split}.csv").open("w", newline="", encoding="utf-8")
        self._csv = csv.DictWriter(self._csv_handle, fieldnames=PATCH_COLUMNS)
        self._csv.writeheader()

    def add(self, pixels: NDArray[np.uint8], meta: PatchMeta) -> None:
        expected = (self.patch_size, self.patch_size, 3)
        if pixels.shape != expected or pixels.dtype != np.uint8:
            raise ValueError(f"patch must be uint8 {expected}, got {pixels.dtype} {pixels.shape}")
        self._bin.write(np.ascontiguousarray(pixels).tobytes())
        self._csv.writerow(
            {
                "image_id": meta.image_id,
                "patch_index": meta.patch_index,
                "label": meta.label,
                "group_id": meta.group_id,
                "source": meta.source,
                "magnification": meta.magnification,
            }
        )
        self.count += 1

    def close(self) -> None:
        self._bin.close()
        self._csv_handle.close()

    def __enter__(self) -> PatchWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def write_images_table(root: Path, rows: Iterable[dict[str, Any]]) -> None:
    frame = pd.DataFrame(list(rows), columns=IMAGE_COLUMNS)
    frame.to_csv(root / "images.csv", index=False)


def write_dataset_info(root: Path, info: dict[str, Any]) -> None:
    (root / "dataset.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n", "utf-8")


def read_dataset_info(root: Path) -> dict[str, Any]:
    path = root / "dataset.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found: this folder is not a prepared dataset "
            "(run `oscc-ml prepare` first, or pass --data-root)"
        )
    data: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return data


def read_patch_index(root: Path, split: str) -> pd.DataFrame:
    frame = pd.read_csv(
        root / f"patches_{split}.csv",
        dtype={"image_id": str, "group_id": str, "source": str, "magnification": str},
    )
    return frame


def open_patches(root: Path, split: str, n: int, patch_size: int) -> NDArray[np.uint8]:
    path = root / f"patches_{split}.u8"
    expected = n * patch_size * patch_size * 3
    actual = path.stat().st_size
    if actual != expected:
        raise ValueError(
            f"{path.name}: {actual} bytes on disk, expected {expected} for {n} patches"
        )
    return np.memmap(path, dtype=np.uint8, mode="r", shape=(n, patch_size, patch_size, 3))


class MemmapPatchDataset(Dataset[tuple[torch.Tensor, torch.Tensor, int]]):
    """Training/evaluation dataset over one split. The memmap is opened lazily in each worker,
    so only the path is pickled to DataLoader workers (Windows spawn friendly)."""

    def __init__(self, root: Path, split: str, transform: Any) -> None:
        info = read_dataset_info(root)
        self.root = root
        self.split = split
        self.patch_size = int(info["patch_size"])
        self.index = read_patch_index(root, split)
        self.transform = transform
        self._array: NDArray[np.uint8] | None = None

    def __len__(self) -> int:
        return len(self.index)

    def _patches(self) -> NDArray[np.uint8]:
        if self._array is None:
            self._array = open_patches(self.root, self.split, len(self.index), self.patch_size)
        return self._array

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state["_array"] = None
        return state

    def __getitem__(self, i: int) -> tuple[torch.Tensor, torch.Tensor, int]:
        pixels = np.array(self._patches()[i])  # copy out of the memmap
        x = self.transform(to_float_tensor(pixels))
        return x, torch.tensor(float(self.index.at[i, "label"])), i

    def labels(self) -> list[int]:
        return [int(v) for v in self.index["label"].tolist()]
