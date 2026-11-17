"""Patch datasets and the train-only augmentation pipeline (SDS Appendix A)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import torch
from torch.utils.data import Dataset
from torchvision.transforms import v2

from oscc_ml.config import Augmentation, Normalization
from oscc_ml.data.synthetic import PatchRecord
from oscc_ml.preprocess import normalize, to_float_tensor

Transform = Callable[[torch.Tensor], torch.Tensor]


class RandomRotate90(torch.nn.Module):
    """Rotate by k x 90 degrees, k uniform in {0, 1, 2, 3} (uses torch's seeded RNG)."""

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        k = int(torch.randint(0, 4, (1,)).item())
        return torch.rot90(x, k, dims=(-2, -1))


def train_transform(aug: Augmentation, norm: Normalization) -> Transform:
    steps: list[torch.nn.Module] = []
    if aug.horizontal_flip:
        steps.append(v2.RandomHorizontalFlip(p=0.5))
    if aug.vertical_flip:
        steps.append(v2.RandomVerticalFlip(p=0.5))
    if aug.rotate_90:
        steps.append(RandomRotate90())
    cj = aug.color_jitter
    steps.append(
        v2.ColorJitter(
            brightness=cj.brightness, contrast=cj.contrast, saturation=cj.saturation, hue=cj.hue
        )
    )
    pipeline = v2.Compose(steps)

    def apply(x: torch.Tensor) -> torch.Tensor:
        return normalize(pipeline(x), norm.mean, norm.std)

    return apply


def eval_transform(norm: Normalization) -> Transform:
    def apply(x: torch.Tensor) -> torch.Tensor:
        return normalize(x, norm.mean, norm.std)

    return apply


class PatchDataset(Dataset[tuple[torch.Tensor, torch.Tensor, int]]):
    """Returns ``(normalized 3xHxW tensor, float label, row index)``."""

    def __init__(self, records: Sequence[PatchRecord], transform: Transform) -> None:
        self.records = list(records)
        self.transform = transform

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor, int]:
        record = self.records[index]
        x = self.transform(to_float_tensor(record.pixels))
        return x, torch.tensor(float(record.label)), index
