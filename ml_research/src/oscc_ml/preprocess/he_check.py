"""H&E colour-profile check (FR-2.2): is an uploaded image plausibly an H&E-stained histology frame?

A heuristic screen, not a classifier. It rejects images whose stain colour statistics fall outside
the ranges seen on H&E training images (``configs/he_profile.json``, written by
``oscc-ml he-calibrate``). It is used ONLY to validate uploads (the API, Phase D2) and by
``oscc-ml he-evaluate``; ``prepare`` and training never call it, so it does not affect patches or
``PREPROCESS_VERSION``.

Features (image downscaled so its longer side is at most 512 px, bilinear):

* ``stained_fraction``: share of pixels with optical density (OD, summed over R, G, B) above
  ``OD_STAIN_THRESHOLD`` (anything darker than glass/white background).
* On stained pixels only:
  * ``saturation_mean``: mean HSV saturation (0-1); near 0 for greyscale images.
  * ``hue_mean``: saturation-weighted circular mean hue in degrees, unwrapped to [90, 450) so the
    pink-purple H&E range (~260-370) is continuous (red = 360, orange = 390, green = 120,
    blue = 240).
  * ``hue_concentration``: length of the weighted mean hue vector (1 = one hue, 0 = all hues).
  * ``od_green_share``: mean green OD / mean total OD. Haematoxylin and eosin both absorb green
    most, so this share is high on H&E.
  * ``od_red_share``: mean red OD / mean total OD.
  * ``flat_fraction``: share of stained pixels identical to their right and lower neighbours in
    all channels (solid fills, screenshots and graphics; microscope photos have sensor noise).

Accepted range per feature: the 1st-99th percentile span on the calibration images, widened by
``MARGIN`` of that span on each side and clipped to the feature's natural bounds. An image passes
only if every feature is inside its range; the result names the features that failed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

HE_PROFILE_VERSION = "he-0.1.0"
MAX_SIDE = 512
OD_STAIN_THRESHOLD = 0.3
MIN_STAINED_PIXELS = 500
MARGIN = 0.25
FEATURES: tuple[str, ...] = (
    "stained_fraction",
    "saturation_mean",
    "hue_mean",
    "hue_concentration",
    "od_green_share",
    "od_red_share",
    "flat_fraction",
)
BOUNDS: dict[str, tuple[float, float]] = {
    "stained_fraction": (0.0, 1.0),
    "saturation_mean": (0.0, 1.0),
    "hue_mean": (90.0, 450.0),
    "hue_concentration": (0.0, 1.0),
    "od_green_share": (0.0, 1.0),
    "od_red_share": (0.0, 1.0),
    "flat_fraction": (0.0, 1.0),
}
NO_STAIN = "no_stained_tissue"


def _downscale(rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    height, width = rgb.shape[:2]
    scale = MAX_SIDE / max(height, width)
    if scale >= 1:
        return rgb
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return np.asarray(Image.fromarray(rgb).resize(size, Image.Resampling.BILINEAR), np.uint8)


def he_features(rgb: NDArray[np.uint8]) -> dict[str, float]:
    """Colour statistics of an HxWx3 uint8 RGB image. Features are NaN when fewer than
    ``MIN_STAINED_PIXELS`` pixels are stained (an empty or white image)."""
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"expected HxWx3 uint8 RGB, got {rgb.dtype} {rgb.shape}")
    small = _downscale(rgb)
    pixels = small.astype(np.float64)
    od = -np.log10(np.maximum(pixels, 1.0) / 255.0)
    od_sum = od.sum(axis=2)
    stained = od_sum > OD_STAIN_THRESHOLD
    features: dict[str, float] = {name: float("nan") for name in FEATURES}
    features["stained_fraction"] = float(stained.mean())
    if int(stained.sum()) < MIN_STAINED_PIXELS:
        return features

    values = pixels[stained] / 255.0
    high, low = values.max(axis=1), values.min(axis=1)
    chroma = high - low
    sat = np.where(high > 0, chroma / np.maximum(high, 1e-12), 0.0)
    r, g, b = values[:, 0], values[:, 1], values[:, 2]
    safe = np.maximum(chroma, 1e-12)
    hue = (
        np.where(
            high == r,
            ((g - b) / safe) % 6,
            np.where(high == g, (b - r) / safe + 2, (r - g) / safe + 4),
        )
        * 60.0
    )
    weight = sat * (chroma > 0)
    total = weight.sum()
    if total > 0:
        angle = np.deg2rad(hue)
        x = float((weight * np.cos(angle)).sum() / total)
        y = float((weight * np.sin(angle)).sum() / total)
        mean = float(np.rad2deg(np.arctan2(y, x))) % 360.0
        features["hue_mean"] = mean if mean >= 90.0 else mean + 360.0
        features["hue_concentration"] = float(np.hypot(x, y))
    else:  # no chroma at all (greyscale)
        features["hue_mean"] = 90.0
        features["hue_concentration"] = 0.0
    features["saturation_mean"] = float(sat.mean())
    od_stained = od[stained]
    od_total = float(od_stained.sum())
    features["od_red_share"] = float(od_stained[:, 0].sum()) / od_total
    features["od_green_share"] = float(od_stained[:, 1].sum()) / od_total
    same_right = np.all(small[:-1, :-1] == small[:-1, 1:], axis=2)
    same_down = np.all(small[:-1, :-1] == small[1:, :-1], axis=2)
    flat = (same_right & same_down)[stained[:-1, :-1]]
    features["flat_fraction"] = float(flat.mean()) if flat.size else 1.0
    return features


@dataclass(frozen=True)
class HEProfile:
    ranges: dict[str, tuple[float, float]]
    version: str = HE_PROFILE_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "rule": (
                "pass if every feature is within [low, high]; ranges = 1st-99th percentile of "
                f"the calibration images widened by {MARGIN:g} of the span, clipped to bounds"
            ),
            "max_side": MAX_SIDE,
            "od_stain_threshold": OD_STAIN_THRESHOLD,
            "min_stained_pixels": MIN_STAINED_PIXELS,
            "ranges": {k: {"low": lo, "high": hi} for k, (lo, hi) in self.ranges.items()},
            **self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> HEProfile:
        if data.get("version") != HE_PROFILE_VERSION:
            raise ValueError(
                f"H&E profile version {data.get('version')!r} != {HE_PROFILE_VERSION!r}; "
                "re-run `oscc-ml he-calibrate`"
            )
        ranges = {k: (float(v["low"]), float(v["high"])) for k, v in data["ranges"].items()}
        missing = set(FEATURES) - set(ranges)
        if missing:
            raise ValueError(f"H&E profile lacks ranges for {sorted(missing)}")
        reserved = {"version", "rule", "max_side", "od_stain_threshold", "min_stained_pixels"}
        metadata = {k: v for k, v in data.items() if k not in reserved | {"ranges"}}
        return cls(ranges=ranges, metadata=metadata)

    @classmethod
    def load(cls, path: Path) -> HEProfile:
        return cls.from_dict(json.loads(path.read_text("utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", "utf-8")


@dataclass(frozen=True)
class HECheckResult:
    passed: bool
    failed: list[str]
    features: dict[str, float]


def calibrate(
    rows: Iterable[Mapping[str, float]], metadata: dict[str, Any] | None = None
) -> HEProfile:
    """Accepted ranges from the features of H&E calibration images."""
    table: dict[str, list[float]] = {name: [] for name in FEATURES}
    count = 0
    for row in rows:
        count += 1
        for name in FEATURES:
            value = float(row[name])
            if np.isfinite(value):
                table[name].append(value)
    if count < 5:
        raise ValueError(f"need at least 5 calibration images, got {count}")
    ranges: dict[str, tuple[float, float]] = {}
    for name in FEATURES:
        values = np.asarray(table[name])
        if values.size < 5:
            raise ValueError(f"feature {name} is undefined on most calibration images")
        q_low, q_high = np.percentile(values, [1, 99])
        span = max(float(q_high - q_low), 1e-6)
        low_bound, high_bound = BOUNDS[name]
        ranges[name] = (
            max(low_bound, float(q_low) - MARGIN * span),
            min(high_bound, float(q_high) + MARGIN * span),
        )
    return HEProfile(ranges=ranges, metadata={"n_calibration_images": count, **(metadata or {})})


def check_features(features: Mapping[str, float], profile: HEProfile) -> HECheckResult:
    if not np.isfinite(features.get("saturation_mean", float("nan"))):
        return HECheckResult(False, [NO_STAIN], dict(features))
    failed = [
        name
        for name in FEATURES
        if not (profile.ranges[name][0] <= float(features[name]) <= profile.ranges[name][1])
    ]
    return HECheckResult(not failed, failed, dict(features))


def check_he(rgb: NDArray[np.uint8], profile: HEProfile) -> HECheckResult:
    """FR-2.2: does this RGB image match the H&E colour profile?"""
    return check_features(he_features(rgb), profile)
