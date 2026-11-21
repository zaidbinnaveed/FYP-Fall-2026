"""``oscc-ml he-calibrate`` / ``he-evaluate``: build and measure the H&E colour-profile check.

* Calibration: features (``oscc_ml.preprocess.he_check``) of H&E originals -> ``he_profile.json``.
* False-reject rate (FRR): share of H&E images the check rejects. Reported twice:
  in-sample (the profile under test) and k-fold cross-validated (recalibrated without the
  held-out fold, which is the honest estimate when calibration and test images are the same).
* False-accept rate (FAR): share of non-histology images the check accepts, per category.
  Offline only, nothing is downloaded:
  - scikit-image's bundled sample images (files shipped inside the package);
  - generated images: solid colours, gradients, noise, UI-like screenshots;
  - greyscale copies of the H&E images under test (hard negatives).

Publisher ``aug_*`` copies are skipped: they are crops/resizes of the originals.
"""

from __future__ import annotations

import io
import json
import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from oscc_ml.paths import ML_ROOT, SAMPLE_DIR
from oscc_ml.preprocess import load_rgb
from oscc_ml.preprocess.he_check import (
    FEATURES,
    HE_PROFILE_VERSION,
    HEProfile,
    calibrate,
    check_features,
    he_features,
)
from oscc_ml.utils.io import iso, utc_now

DEFAULT_PROFILE = ML_ROOT / "configs" / "he_profile.json"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
SKIMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}


def he_images(folders: list[Path]) -> list[Path]:
    """H&E originals under the folders (recursive, sorted), publisher ``aug_*`` copies skipped."""
    paths: list[Path] = []
    for folder in folders:
        if not folder.is_dir():
            raise FileNotFoundError(f"{folder} is not a folder")
        paths += [
            p
            for p in folder.rglob("*")
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES and not p.name.startswith("aug_")
        ]
    found = sorted(set(paths))
    if not found:
        raise FileNotFoundError(f"no images in {[str(f) for f in folders]}")
    return found


def _rgb(path: Path) -> NDArray[np.uint8]:
    with Image.open(path) as image:
        return load_rgb(image)


def features_of(paths: list[Path]) -> list[dict[str, float]]:
    return [he_features(_rgb(p)) for p in paths]


def run_calibration(folders: list[Path], out: Path = DEFAULT_PROFILE) -> HEProfile:
    paths = he_images(folders)
    profile = calibrate(
        features_of(paths),
        metadata={
            "calibration_images": [f.as_posix() for f in folders],
            "created_at": iso(utc_now()),
            "note": "calibrated on the images listed above (aug_ copies skipped)",
        },
    )
    profile.save(out)
    return profile


# --------------------------------------------------------------------------- negatives


def skimage_samples() -> Iterator[tuple[str, NDArray[np.uint8]]]:
    """Image files shipped inside scikit-image's ``data`` package folder (no download)."""
    import skimage.data

    folder = Path(skimage.data.__file__).parent
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in SKIMAGE_SUFFIXES:
            continue
        try:
            with Image.open(path) as image:
                image.load()
                if image.mode in {"I", "I;16", "F"}:  # 16-bit / float: rescale to 8 bit
                    array = np.asarray(image, dtype=np.float64)
                    span = max(float(array.max() - array.min()), 1e-9)
                    scaled = ((array - array.min()) / span * 255).astype(np.uint8)
                    rgb = load_rgb(Image.fromarray(scaled))
                else:
                    rgb = load_rgb(image)
        except (OSError, ValueError):
            continue
        if min(rgb.shape[:2]) >= 32:
            yield path.stem, rgb


def _solid(rng: np.random.Generator, n: int) -> Iterator[tuple[str, NDArray[np.uint8]]]:
    fixed = [
        (255, 255, 255), (0, 0, 0), (128, 128, 128), (230, 170, 200), (200, 120, 200),
        (150, 90, 180), (255, 0, 0), (0, 128, 0), (0, 0, 255), (255, 200, 220),
    ]  # fmt: skip
    colours = fixed + [tuple(int(v) for v in rng.integers(0, 256, 3)) for _ in range(n - 10)]
    for i, colour in enumerate(colours[:n]):
        yield f"solid_{i:02d}", np.full((480, 640, 3), colour, dtype=np.uint8)


def _gradients(rng: np.random.Generator, n: int) -> Iterator[tuple[str, NDArray[np.uint8]]]:
    yy, xx = np.mgrid[0:480, 0:640]
    for i in range(n):
        a = rng.integers(0, 256, 3).astype(np.float64)
        b = rng.integers(0, 256, 3).astype(np.float64)
        if i % 4 == 0:  # pink -> purple, the hardest case
            a, b = np.array([235.0, 180, 210]), np.array([120.0, 60, 150])
        if i % 3 == 2:
            t = np.hypot(yy - 240, xx - 320) / math.hypot(240, 320)
        else:
            angle = rng.uniform(0, math.pi)
            t = (xx * math.cos(angle) + yy * math.sin(angle)) / (640 + 480)
        t = (t - t.min()) / max(float(t.max() - t.min()), 1e-9)
        image = a[None, None, :] * (1 - t[..., None]) + b[None, None, :] * t[..., None]
        if i % 5 == 4:  # greyscale gradient
            image = np.repeat(image.mean(axis=2, keepdims=True), 3, axis=2)
        yield f"gradient_{i:02d}", image.round().astype(np.uint8)


def _noise(rng: np.random.Generator, n: int) -> Iterator[tuple[str, NDArray[np.uint8]]]:
    for i in range(n):
        kind = i % 4
        image: NDArray[Any]
        if kind == 0:
            image = rng.integers(0, 256, (480, 640, 3))
        elif kind == 1:  # gaussian noise around H&E pink
            image = rng.normal([220, 160, 200], 30, (480, 640, 3))
        elif kind == 2:  # greyscale noise
            image = np.repeat(rng.integers(0, 256, (480, 640, 1)), 3, axis=2)
        else:  # coarse blocky noise (upscaled)
            small = rng.integers(0, 256, (12, 16, 3)).astype(np.uint8)
            image = np.asarray(Image.fromarray(small).resize((640, 480), Image.Resampling.NEAREST))
        yield f"noise_{i:02d}", np.clip(image, 0, 255).astype(np.uint8)


def _screenshot(rng: np.random.Generator, index: int) -> NDArray[np.uint8]:
    dark = index % 3 == 2
    background = (32, 33, 36) if dark else (255, 255, 255)
    text = (230, 230, 230) if dark else (30, 30, 30)
    accent = tuple(int(v) for v in rng.integers(0, 256, 3))
    image = Image.new("RGB", (800, 560), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 800, 36), fill=accent)  # title/navigation bar
    draw.text((12, 10), f"Window {index}  File  Edit  View  Help", fill=(255, 255, 255))
    if index % 2 == 0:
        draw.rectangle((0, 36, 180, 560), fill=(240, 240, 245) if not dark else (45, 45, 50))
        for k in range(10):
            draw.text((14, 52 + 28 * k), f"Menu item {k}", fill=text)
    left = 200 if index % 2 == 0 else 20
    y = 56
    while y < 520:
        width = int(rng.integers(150, 560))
        draw.text((left, y), "Lorem ipsum dolor sit amet " * (width // 160 + 1), fill=text)
        y += int(rng.integers(18, 30))
        if rng.random() < 0.15:
            colour = tuple(int(v) for v in rng.integers(0, 256, 3))
            draw.rounded_rectangle((left, y, left + 120, y + 32), radius=6, fill=colour)
            draw.text((left + 14, y + 10), "Button", fill=(255, 255, 255))
            y += 44
    if index % 4 == 1:  # a pinkish photo-like block inside the page
        block = rng.normal([210, 150, 190], 25, (160, 220, 3)).clip(0, 255).astype(np.uint8)
        image.paste(Image.fromarray(block), (540, 300))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG" if index % 2 else "PNG", quality=90)
    buffer.seek(0)
    with Image.open(buffer) as reloaded:
        return load_rgb(reloaded)


def _screenshots(rng: np.random.Generator, n: int) -> Iterator[tuple[str, NDArray[np.uint8]]]:
    for i in range(n):
        yield f"screenshot_{i:02d}", _screenshot(rng, i)


def _greyscale(paths: list[Path]) -> Iterator[tuple[str, NDArray[np.uint8]]]:
    for path in paths:
        grey = Image.fromarray(_rgb(path)).convert("L")
        yield f"grey_{path.stem}", load_rgb(grey)


def negative_sets(he_paths: list[Path], seed: int = 42) -> dict[str, Iterator[Any]]:
    """Category -> lazy iterator of (name, rgb). Generated images use fixed seeds."""
    return {
        "scikit-image samples": skimage_samples(),
        "solid colours": _solid(np.random.default_rng(seed), 24),
        "gradients": _gradients(np.random.default_rng(seed + 1), 24),
        "noise": _noise(np.random.default_rng(seed + 2), 24),
        "screenshots": _screenshots(np.random.default_rng(seed + 3), 40),
        "greyscale H&E": _greyscale(he_paths),
    }


# --------------------------------------------------------------------------- evaluation


@dataclass
class Evaluation:
    he_folders: list[str]
    n_he: int
    frr_in_sample: float
    frr_cv: float
    folds: int
    rejected_in_sample: list[dict[str, Any]]
    far: dict[str, dict[str, Any]]
    profile_version: str
    is_sample: bool

    def far_overall(self) -> tuple[int, int]:
        accepted = sum(v["accepted"] for v in self.far.values())
        total = sum(v["n"] for v in self.far.values())
        return accepted, total


def cross_validated_frr(features: list[dict[str, float]], folds: int, seed: int = 42) -> float:
    order = np.random.default_rng(seed).permutation(len(features))
    rejected = 0
    for fold in range(folds):
        held = set(order[fold::folds].tolist())
        train = [f for i, f in enumerate(features) if i not in held]
        profile = calibrate(train)
        rejected += sum(not check_features(features[i], profile).passed for i in held)
    return rejected / len(features)


def evaluate(folders: list[Path], profile: HEProfile, folds: int = 5, seed: int = 42) -> Evaluation:
    paths = he_images(folders)
    feats = features_of(paths)
    results = [check_features(f, profile) for f in feats]
    rejected = [
        {"image": p.name, "failed": r.failed}
        for p, r in zip(paths, results, strict=True)
        if not r.passed
    ]
    far: dict[str, dict[str, Any]] = {}
    for category, items in negative_sets(paths, seed).items():
        n, accepted_names = 0, []
        for name, rgb in items:
            n += 1
            if check_features(he_features(rgb), profile).passed:
                accepted_names.append(name)
        far[category] = {"n": n, "accepted": len(accepted_names), "accepted_names": accepted_names}
    sample_root = SAMPLE_DIR.resolve()
    return Evaluation(
        he_folders=[str(f) for f in folders],
        n_he=len(paths),
        frr_in_sample=len(rejected) / len(paths),
        frr_cv=cross_validated_frr(feats, folds, seed),
        folds=folds,
        rejected_in_sample=rejected,
        far=far,
        profile_version=profile.version,
        is_sample=all(sample_root in p.resolve().parents for p in paths),
    )


def to_markdown(result: Evaluation, profile: HEProfile) -> str:
    accepted, total = result.far_overall()
    banner = (
        "> **SAMPLE ONLY — H&E images from the 60-image development sample.** The false-reject "
        "rate on the full test split is still to be measured (university run, then "
        "`oscc-ml he-evaluate --images <test split folders>`)."
        if result.is_sample
        else f"> H&E images: {', '.join(result.he_folders)}"
    )
    rows = [
        f"| {cat} | {v['n']} | {v['accepted']} | {100 * v['accepted'] / v['n']:.1f}% |"
        if v["n"]
        else f"| {cat} | 0 | 0 | n/a |"
        for cat, v in result.far.items()
    ]
    ranges = [
        f"| `{name}` | {profile.ranges[name][0]:.4f} | {profile.ranges[name][1]:.4f} |"
        for name in FEATURES
    ]
    accepted_list = [
        f"- {cat}: {', '.join(v['accepted_names'])}"
        for cat, v in result.far.items()
        if v["accepted"]
    ]
    rejected_list = [f"- {r['image']}: {', '.join(r['failed'])}" for r in result.rejected_in_sample]
    return "\n".join(
        [
            "# H&E colour-profile check (FR-2.2): evaluation",
            "",
            banner,
            "",
            "Generated by `oscc-ml he-evaluate`. Heuristic upload screen, not a diagnostic model.",
            "",
            f"- Profile: `{profile.version}`, calibrated on "
            f"{profile.metadata.get('n_calibration_images')} images "
            f"({', '.join(profile.metadata.get('calibration_images', []))}).",
            f"- H&E images evaluated: **{result.n_he}** (publisher `aug_` copies skipped).",
            "",
            "## False-reject rate on H&E images",
            "",
            f"- In-sample (profile above, which saw these images): "
            f"**{100 * result.frr_in_sample:.1f}%** ({len(result.rejected_in_sample)} / "
            f"{result.n_he}).",
            f"- {result.folds}-fold cross-validated (recalibrated without the held-out fold): "
            f"**{100 * result.frr_cv:.1f}%**.",
            "",
            *(rejected_list or ["_No H&E image rejected in-sample._"]),
            "",
            "## False-accept rate on non-histology images (offline)",
            "",
            "| category | images | accepted | false-accept rate |",
            "| --- | --- | --- | --- |",
            *rows,
            f"| **all** | **{total}** | **{accepted}** | "
            f"**{100 * accepted / total if total else 0:.1f}%** |",
            "",
            *(accepted_list or ["_No non-histology image accepted._"]),
            "",
            "## Accepted ranges",
            "",
            "| feature | low | high |",
            "| --- | --- | --- |",
            *ranges,
            "",
        ]
    )


def to_json(result: Evaluation) -> str:
    accepted, total = result.far_overall()
    payload = {
        "he_folders": result.he_folders,
        "n_he": result.n_he,
        "frr_in_sample": result.frr_in_sample,
        "frr_cv": result.frr_cv,
        "folds": result.folds,
        "far_overall": accepted / total if total else None,
        "far": result.far,
        "profile_version": result.profile_version,
        "is_sample": result.is_sample,
        "created_at": iso(utc_now()),
    }
    return json.dumps(payload, indent=2) + "\n"


__all__ = [
    "DEFAULT_PROFILE",
    "HE_PROFILE_VERSION",
    "Evaluation",
    "evaluate",
    "he_images",
    "negative_sets",
    "run_calibration",
    "to_json",
    "to_markdown",
]
