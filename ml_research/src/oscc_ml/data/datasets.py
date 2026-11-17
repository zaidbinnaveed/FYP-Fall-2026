"""Train-only augmentation and evaluation transforms (SDS Appendix A)."""

from __future__ import annotations

from collections.abc import Callable

import torch
from torchvision.transforms import v2

from oscc_ml.config import Augmentation, Normalization
from oscc_ml.preprocess import normalize

Transform = Callable[[torch.Tensor], torch.Tensor]


class RandomRotate90(torch.nn.Module):
    """Rotate by k x 90 degrees, k uniform in {0, 1, 2, 3} (uses torch's seeded RNG)."""

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        k = int(torch.randint(0, 4, (1,)).item())
        return torch.rot90(x, k, dims=(-2, -1))


class TrainTransform:
    """Flips, 90-degree rotations, mild colour jitter, then ImageNet normalization.

    A class (not a closure) so it pickles into DataLoader workers on Windows.
    """

    def __init__(self, aug: Augmentation, norm: Normalization) -> None:
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
                brightness=cj.brightness,
                contrast=cj.contrast,
                saturation=cj.saturation,
                hue=cj.hue,
            )
        )
        self.pipeline = v2.Compose(steps)
        self.mean = norm.mean
        self.std = norm.std

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        return normalize(self.pipeline(x), self.mean, self.std)


class EvalTransform:
    def __init__(self, norm: Normalization) -> None:
        self.mean = norm.mean
        self.std = norm.std

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        return normalize(x, self.mean, self.std)
