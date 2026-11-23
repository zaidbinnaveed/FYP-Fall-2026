"""Paired comparisons between models on the same test images (plan R3; recorded from FYP-I on).

For every pair of evaluated training runs with the same seed:

* **paired bootstrap ΔAUC**: groups (``group_id``) are resampled with replacement, and the same
  resample is applied to both models; ΔAUC = AUC(a) - AUC(b). Point estimate on all images,
  95% percentile CI, and a two-sided bootstrap p-value 2·min(P(Δ* ≤ 0), P(Δ* ≥ 0)), capped at 1;
* **McNemar** at each model's own tau: b = images only model a gets right, c = images only model b
  gets right; exact two-sided binomial test on min(b, c) out of b + c (p = 1 when b + c = 0).

Holm's step-down correction is applied separately to the ΔAUC p-values and the McNemar p-values of
all pairs. The models must have predictions for exactly the same images with the same labels.
"""

from __future__ import annotations

import itertools
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import binomtest
from sklearn.metrics import roc_auc_score

from oscc_ml.catalog import EVALUATION_FILE
from oscc_ml.utils.io import iso, read_json, utc_now, write_json

COMPARISONS_FILE = "comparisons.json"
logger = logging.getLogger("oscc_ml.eval")


def holm(p_values: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, in the input order."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted


def mcnemar_exact(correct_a: np.ndarray, correct_b: np.ndarray) -> dict[str, Any]:
    b = int((correct_a & ~correct_b).sum())
    c = int((~correct_a & correct_b).sum())
    p = 1.0 if b + c == 0 else float(binomtest(min(b, c), b + c, 0.5).pvalue)
    return {
        "b_only_a_correct": b,
        "c_only_b_correct": c,
        "p_value": p,
        "test": "McNemar exact (two-sided binomial)",
    }


def paired_delta_auc(
    y: np.ndarray,
    p_a: np.ndarray,
    p_b: np.ndarray,
    groups: np.ndarray,
    n_resamples: int = 2000,
    seed: int = 42,
    confidence: float = 0.95,
) -> dict[str, Any]:
    unique = np.unique(groups)
    members = [np.flatnonzero(groups == g) for g in unique]
    rng = np.random.default_rng(seed)
    deltas: list[float] = []
    for _ in range(n_resamples):
        idx = np.concatenate([members[i] for i in rng.integers(0, len(members), len(members))])
        yy = y[idx]
        if 0 < yy.sum() < len(yy):
            deltas.append(float(roc_auc_score(yy, p_a[idx]) - roc_auc_score(yy, p_b[idx])))
    values = np.asarray(deltas)
    alpha = (1 - confidence) / 2
    estimate = float(roc_auc_score(y, p_a) - roc_auc_score(y, p_b))
    if len(values):
        p = min(1.0, 2 * min(float((values <= 0).mean()), float((values >= 0).mean())))
        low, high = float(np.quantile(values, alpha)), float(np.quantile(values, 1 - alpha))
    else:
        p, low, high = 1.0, None, None
    return {
        "estimate": estimate,
        "ci_low": low,
        "ci_high": high,
        "p_value": p,
        "n_valid": len(values),
        "n_resamples": n_resamples,
        "seed": seed,
        "resampled_unit": "group_id",
    }


def compare_frames(
    frames: dict[str, pd.DataFrame],
    taus: dict[str, float],
    n_resamples: int = 2000,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """``frames``: model -> test image predictions (image_id, label, oscc_probability, group_id)."""
    names = sorted(frames)
    base = frames[names[0]].sort_values("image_id").reset_index(drop=True)
    for name in names[1:]:
        other = frames[name].sort_values("image_id").reset_index(drop=True)
        if list(other["image_id"]) != list(base["image_id"]) or list(other["label"]) != list(
            base["label"]
        ):
            raise ValueError(f"{name} and {names[0]} were not evaluated on the same test images")
    aligned = {
        n: frames[n]
        .sort_values("image_id")
        .reset_index(drop=True)["oscc_probability"]
        .to_numpy(dtype=float)
        for n in names
    }
    y = base["label"].to_numpy(dtype=int)
    groups = base["group_id"].astype(str).to_numpy()
    pairs: list[dict[str, Any]] = []
    for a, b in itertools.combinations(names, 2):
        correct_a = (aligned[a] >= taus[a]).astype(int) == y
        correct_b = (aligned[b] >= taus[b]).astype(int) == y
        pairs.append(
            {
                "a": a,
                "b": b,
                "n_images": len(y),
                "delta_auc": paired_delta_auc(y, aligned[a], aligned[b], groups, n_resamples, seed),
                "mcnemar": {
                    **mcnemar_exact(correct_a, correct_b),
                    "tau_a": taus[a],
                    "tau_b": taus[b],
                },
            }
        )
    for family in ("delta_auc", "mcnemar"):
        adjusted = holm([p[family]["p_value"] for p in pairs])
        for pair, value in zip(pairs, adjusted, strict=True):
            pair[family]["p_holm"] = value
    return pairs


def compare_runs(runs_dir: Path, n_resamples: int = 2000, seed: int = 42) -> dict[str, Any] | None:
    """Compare all evaluated training runs per seed; writes ``<runs_dir>/comparisons.json``."""
    by_seed: dict[int, dict[str, tuple[pd.DataFrame, float]]] = {}
    for info_path in sorted(runs_dir.glob("*/run_info.json")):
        run_dir = info_path.parent
        info = read_json(info_path)
        if info.get("purpose") != "train" or not (run_dir / EVALUATION_FILE).is_file():
            continue
        tau = float(read_json(run_dir / EVALUATION_FILE)["threshold"]["threshold"])
        frame = pd.read_csv(
            run_dir / "predictions" / "test_images.csv",
            dtype={"image_id": str, "group_id": str, "magnification": str},
        )
        by_seed.setdefault(int(info["seed"]), {})[str(info["architecture"])] = (frame, tau)
    result: dict[str, Any] = {"created_at": iso(utc_now()), "seeds": {}}
    for run_seed, models in sorted(by_seed.items()):
        if len(models) < 2:
            continue
        result["seeds"][str(run_seed)] = compare_frames(
            {m: f for m, (f, _) in models.items()},
            {m: t for m, (_, t) in models.items()},
            n_resamples,
            seed,
        )
    if not result["seeds"]:
        return None
    result["method"] = __doc__
    write_json(runs_dir / COMPARISONS_FILE, result)
    logger.info("paired comparisons written to %s", runs_dir / COMPARISONS_FILE)
    return result
