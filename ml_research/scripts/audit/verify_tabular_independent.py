"""Independent re-implementation of key tabular features on a subset (Phase T verification).

Written separately from ``oscc_ml.tabular.features`` and deliberately by different algorithms:

* tissue mask: saturation per pixel, then Otsu by brute force (every threshold's within-class
  variance), capped at 40;
* RGB means/SDs over tissue: plain NumPy on the masked pixels;
* CIE L*a*b*: per-channel scalar formulas applied with ``np.vectorize`` (not the matrix route);
* H&E: per-image least-squares unmixing (``np.linalg.lstsq``) of optical density on the stain
  vectors, instead of multiplying by the inverse matrix;
* GLCM (distance 1, four angles): explicit Python loops over pixel pairs and a dict of counts;
* LBP riu2: a per-pixel Python loop;
* dark blobs: brute-force Otsu on the hematoxylin values within tissue (256 bins) and a
  breadth-first flood fill with 8-connectivity.

It imports nothing from ``oscc_ml``: its inputs are the raw images, the
features CSV and the manifest. The downsized copy is rebuilt with Pillow's ``reduce(4)`` (the
documented preprocessing step) and checked against a NumPy 4x4 block mean (|diff| <= 1).

    python -I scripts/audit/verify_tabular_independent.py --table data/processed/tabular \
        --raw data/raw/kaggle_kebede --per-cell 2 --out <folder>
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

STAINS = [[0.65, 0.70, 0.29], [0.07, 0.99, 0.11], [0.27, 0.57, 0.78]]


def otsu_bruteforce(values: np.ndarray, levels: np.ndarray) -> float:
    """Threshold t (from ``levels``) minimising within-class variance of values <= t / > t."""
    best_t, best = float(levels[0]), math.inf
    total = values.size
    for t in levels:
        low, high = values[values <= t], values[values > t]
        if low.size == 0 or high.size == 0:
            continue
        within = low.size / total * low.var() + high.size / total * high.var()
        if within < best - 1e-12:
            best, best_t = within, float(t)
    return best_t


def lab_scalar(r: float, g: float, b: float) -> tuple[float, float, float]:
    def lin(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = lin(r), lin(g), lin(b)
    x = (0.4124564 * rl + 0.3575761 * gl + 0.1804375 * bl) / 0.95047
    y = 0.2126729 * rl + 0.7151522 * gl + 0.0721750 * bl
    z = (0.0193339 * rl + 0.1191920 * gl + 0.9503041 * bl) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def glcm_d1(grey32: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    h, w = grey32.shape
    offsets = {0: (0, 1), 45: (-1, 1), 90: (-1, 0), 135: (-1, -1)}
    per_angle = []
    for dy, dx in offsets.values():
        counts: collections.Counter[tuple[int, int]] = collections.Counter()
        for y in range(h):
            for x in range(w):
                y2, x2 = y + dy, x + dx
                if 0 <= y2 < h and 0 <= x2 < w and mask[y, x] and mask[y2, x2]:
                    a, b = int(grey32[y, x]), int(grey32[y2, x2])
                    counts[(a, b)] += 1
                    counts[(b, a)] += 1
        total = sum(counts.values())
        contrast = sum(n * (a - b) ** 2 for (a, b), n in counts.items()) / total
        homog = sum(n / (1 + (a - b) ** 2) for (a, b), n in counts.items()) / total
        per_angle.append((contrast, homog))
    return {
        "glcm_contrast_d1": float(np.mean([p[0] for p in per_angle])),
        "glcm_homogeneity_d1": float(np.mean([p[1] for p in per_angle])),
    }


def lbp_hist(grey: np.ndarray, mask: np.ndarray) -> list[float]:
    h, w = grey.shape
    ring = [(0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0), (1, 1)]
    hist = [0] * 10
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if not mask[y, x]:
                continue
            c = grey[y, x]
            bits = [1 if grey[y + dy, x + dx] >= c else 0 for dy, dx in ring]
            transitions = sum(bits[i] != bits[(i + 1) % 8] for i in range(8))
            hist[sum(bits) if transitions <= 2 else 9] += 1
    total = sum(hist)
    return [v / total for v in hist]


def blob_count(h_od: np.ndarray, mask: np.ndarray, min_pixels: int = 2) -> int:
    values = h_od[mask]
    low, high = float(values.min()), float(values.max())
    edges = np.linspace(low, high, 257)
    centres = (edges[:-1] + edges[1:]) / 2
    # histogram-based brute force: assign each value to a bin, evaluate each bin centre as t
    idx = np.clip(np.searchsorted(edges, values, side="right") - 1, 0, 255)
    binned = centres[idx]
    t = otsu_bruteforce(binned, centres)
    positive = mask & (h_od > t)
    seen = np.zeros_like(positive)
    h, w = positive.shape
    count = 0
    for y in range(h):
        for x in range(w):
            if positive[y, x] and not seen[y, x]:
                queue = collections.deque([(y, x)])
                seen[y, x] = True
                size = 0
                while queue:
                    cy, cx = queue.popleft()
                    size += 1
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            inside = 0 <= ny < h and 0 <= nx < w
                            if inside and positive[ny, nx] and not seen[ny, nx]:
                                seen[ny, nx] = True
                                queue.append((ny, nx))
                count += size >= min_pixels
    return count


def verify_image(path: Path, row: dict[str, str]) -> dict[str, object]:
    with Image.open(path) as image:
        rgb_full = np.asarray(image.convert("RGB"), dtype=np.int64)
        small = np.asarray(image.convert("RGB").reduce(4), dtype=np.int64)
    hh, ww = small.shape[:2]
    block = rgb_full[: hh * 4, : ww * 4].reshape(hh, 4, ww, 4, 3).mean(axis=(1, 3))
    reduce_ok = bool(np.abs(block - small).max() <= 1.0)

    high, low = small.max(axis=2), small.min(axis=2)
    sat = np.where(high > 0, (high - low) * 255 // np.maximum(high, 1), 0)
    t = min(otsu_bruteforce(sat.ravel().astype(float), np.arange(256, dtype=float)), 40.0)
    mask = sat > t
    if mask.sum() < 500:
        mask = np.ones_like(mask)
    px = small[mask].astype(float)
    ours: dict[str, float] = {
        "tissue_threshold": t,
        "rgb_r_mean": px[:, 0].mean(),
        "rgb_g_mean": px[:, 1].mean(),
        "rgb_b_mean": px[:, 2].mean(),
        "rgb_r_std": px[:, 0].std(),
    }
    lab = np.array([lab_scalar(*p) for p in px[:: max(1, len(px) // 20000)]])  # subsample
    ours["lab_l_mean~"] = lab[:, 0].mean()
    stains = np.array(STAINS) / np.linalg.norm(STAINS, axis=1, keepdims=True)
    od = -np.log10((px + 1.0) / 256.0)
    conc, *_ = np.linalg.lstsq(stains.T, od.T, rcond=None)
    ours["he_h_od_mean"] = conc[0].mean()
    ours["he_e_od_mean"] = conc[1].mean()
    grey = np.asarray(Image.fromarray(small.astype(np.uint8)).convert("L"), dtype=np.int64)
    ours.update(glcm_d1(grey * 32 // 256, mask))
    for k, v in enumerate(lbp_hist(grey, mask)):
        ours[f"lbp_riu2_bin{k}"] = v
    od_all = -np.log10((small.reshape(-1, 3).astype(float) + 1.0) / 256.0)
    h_map, *_ = np.linalg.lstsq(stains.T, od_all.T, rcond=None)
    ours["nuc_blob_count"] = float(blob_count(h_map[0].reshape(hh, ww), mask))

    tolerances = {"lab_l_mean~": 0.5, "nuc_blob_count": 0.0}
    results = {}
    for key, value in ours.items():
        table_key = key.rstrip("~")
        expected = float(row[table_key])
        tol = tolerances.get(key, 1e-6 * max(1.0, abs(expected)))
        if key == "nuc_blob_count":
            tol = max(2.0, 0.01 * expected)  # Otsu bin edges can differ by one bin
        results[table_key] = {
            "independent": float(value),
            "table": expected,
            "abs_diff": abs(float(value) - expected),
            "tolerance": tol,
            "passed": abs(float(value) - expected) <= tol,
        }
    return {"reduce_matches_block_mean": reduce_ok, "features": results}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--table", type=Path, required=True, help="folder with oscc_features_v1.csv")
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--per-cell", type=int, default=2, help="images per split x label")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    with (args.table / "oscc_features_v1.csv").open(encoding="utf-8") as handle:
        rows = sorted(csv.DictReader(handle), key=lambda r: r["image_id"])
    chosen: list[dict[str, str]] = []
    for split in ("train", "val", "test"):
        for label in ("0", "1"):
            cell = [r for r in rows if r["split"] == split and r["label"] == label]
            chosen += cell[: args.per_cell]
    report = {}
    for row in chosen:
        report[row["image_id"]] = verify_image(args.raw / row["original_path"], row)
        status = all(f["passed"] for f in report[row["image_id"]]["features"].values())
        verdict = "ok" if status else "MISMATCH"
        print(f"{row['image_id']} ({row['split']}, label {row['label']}): {verdict}")
    passed = all(
        r["reduce_matches_block_mean"] and all(f["passed"] for f in r["features"].values())
        for r in report.values()
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "verify_tabular.json").write_text(
        json.dumps({"all_passed": passed, "n_images": len(report), "images": report}, indent=2),
        encoding="utf-8",
    )
    print(f"{'ALL PASSED' if passed else 'FAILED'}: {len(report)} images")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
