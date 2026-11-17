"""THE single preprocessing module, shared by training (``oscc-ml prepare``) and the inference
service (Phase D2). Any change here must bump ``PREPROCESS_VERSION``; the parity test (D2) keeps
training and inference identical.

Tiling rule (decision O5, accepted):
* If both sides are below ``resize_if_both_sides_below`` (448 px): resize the whole image to
  224 x 224 (bilinear) -> one patch.
* Otherwise: non-overlapping 224 x 224 grid from the top-left corner (partial edge tiles are
  dropped); keep patches whose tissue fraction is >= ``min_tissue_fraction`` (0.5), where tissue
  = saturation above the image's Otsu threshold; if more than ``max_patches_per_image`` (64)
  remain, keep that many evenly spaced (in raster order).
* If no patch reaches the tissue threshold, keep the single patch with the most tissue
  (``mode = "grid_fallback"``), so no image is silently lost; the manifest records it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from numpy.typing import NDArray
from PIL import Image

PREPROCESS_VERSION = "pp-0.2.0"

IMAGENET_MEAN: tuple[float, float, float] = (0.485, 0.456, 0.406)
IMAGENET_STD: tuple[float, float, float] = (0.229, 0.224, 0.225)


def to_float_tensor(image: NDArray[np.uint8]) -> torch.Tensor:
    """HxWx3 uint8 RGB -> 3xHxW float32 in [0, 1]."""
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"expected HxWx3 uint8 RGB, got {image.dtype} {image.shape}")
    return torch.from_numpy(np.ascontiguousarray(image)).permute(2, 0, 1).float().div_(255.0)


def normalize(
    tensor: torch.Tensor,
    mean: tuple[float, float, float] = IMAGENET_MEAN,
    std: tuple[float, float, float] = IMAGENET_STD,
) -> torch.Tensor:
    """Channel-wise ``(x - mean) / std`` on a 3xHxW or Nx3xHxW float tensor."""
    shape = (3, 1, 1) if tensor.ndim == 3 else (1, 3, 1, 1)
    m = torch.tensor(mean, dtype=tensor.dtype).view(shape)
    s = torch.tensor(std, dtype=tensor.dtype).view(shape)
    return (tensor - m) / s


def load_rgb(image: Image.Image) -> NDArray[np.uint8]:
    """Any PIL image -> HxWx3 uint8 RGB (alpha dropped, palette/greyscale expanded)."""
    return np.asarray(image.convert("RGB"), dtype=np.uint8)


def saturation(rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """HSV saturation scaled to 0..255."""
    as_int = rgb.astype(np.int32)
    high = as_int.max(axis=2)
    low = as_int.min(axis=2)
    with np.errstate(divide="ignore", invalid="ignore"):
        sat = np.where(high > 0, (high - low) * 255 // np.maximum(high, 1), 0)
    return sat.astype(np.uint8)


def otsu_threshold(values: NDArray[np.uint8]) -> int:
    """Otsu's threshold on uint8 data: maximizes between-class variance. Returns t such that
    foreground is ``values > t``."""
    hist = np.bincount(values.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    if total == 0:
        return 0
    levels = np.arange(256, dtype=np.float64)
    weight_bg = np.cumsum(hist)
    weight_fg = total - weight_bg
    cum_mean = np.cumsum(hist * levels)
    mean_total = cum_mean[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        mean_bg = cum_mean / weight_bg
        mean_fg = (mean_total - cum_mean) / weight_fg
        between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
    between = np.nan_to_num(between, nan=0.0, posinf=0.0, neginf=0.0)
    return int(np.argmax(between))


@dataclass(frozen=True)
class TilingParams:
    patch_size: int = 224
    resize_if_both_sides_below: int = 448
    min_tissue_fraction: float = 0.5
    max_patches_per_image: int = 64


@dataclass
class TilingResult:
    patches: list[NDArray[np.uint8]]
    coords: list[tuple[int, int]]  # (top, left) in the original image; (0, 0) for resize
    tissue_fractions: list[float]
    mode: str  # "resize" | "grid" | "grid_fallback"
    grid_candidates: int  # number of full grid tiles before filtering


def tile_image(rgb: NDArray[np.uint8], params: TilingParams | None = None) -> TilingResult:
    params = params or TilingParams()
    size = params.patch_size
    height, width = rgb.shape[:2]
    if height < params.resize_if_both_sides_below and width < params.resize_if_both_sides_below:
        resized = Image.fromarray(rgb).resize((size, size), Image.Resampling.BILINEAR)
        return TilingResult([load_rgb(resized)], [(0, 0)], [1.0], "resize", 1)

    sat = saturation(rgb)
    mask = sat > otsu_threshold(sat)
    rows, cols = height // size, width // size
    coords: list[tuple[int, int]] = []
    fractions: list[float] = []
    for r in range(rows):
        for c in range(cols):
            top, left = r * size, c * size
            coords.append((top, left))
            fractions.append(float(mask[top : top + size, left : left + size].mean()))
    if not coords:  # one side >= 448 but the other < 224: cannot form a full tile
        resized = Image.fromarray(rgb).resize((size, size), Image.Resampling.BILINEAR)
        return TilingResult([load_rgb(resized)], [(0, 0)], [1.0], "resize", 0)

    keep = [i for i, f in enumerate(fractions) if f >= params.min_tissue_fraction]
    mode = "grid"
    if not keep:
        keep = [int(np.argmax(fractions))]
        mode = "grid_fallback"
    if len(keep) > params.max_patches_per_image:
        picks = np.linspace(0, len(keep) - 1, params.max_patches_per_image).round().astype(int)
        keep = [keep[i] for i in picks]
    patches = [
        np.ascontiguousarray(rgb[t : t + size, lft : lft + size])
        for t, lft in (coords[i] for i in keep)
    ]
    return TilingResult(
        patches,
        [coords[i] for i in keep],
        [fractions[i] for i in keep],
        mode,
        len(coords),
    )
