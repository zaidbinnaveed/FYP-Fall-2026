"""95% bootstrap confidence intervals that resample *groups* (patients or duplicate clusters),
not images, so correlated images from one patient never inflate precision (plan R3 step 4)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.metrics import roc_auc_score

METRICS = ("accuracy", "precision", "recall", "specificity", "f1", "auc_roc")


def point_metrics(
    y: NDArray[np.int_], p: NDArray[np.float64], threshold: float
) -> dict[str, float | None]:
    pred = p >= threshold
    tp = float((pred & (y == 1)).sum())
    tn = float((~pred & (y == 0)).sum())
    fp = float((pred & (y == 0)).sum())
    fn = float((~pred & (y == 1)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if recall is not None and precision + recall
        else (0.0 if recall is not None else None)
    )
    both = 0 < y.sum() < len(y)
    return {
        "accuracy": (tp + tn) / len(y) if len(y) else None,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "f1": f1,
        "auc_roc": float(roc_auc_score(y, p)) if both else None,
    }


def grouped_bootstrap(
    images: pd.DataFrame,
    threshold: float,
    n_resamples: int = 2000,
    seed: int = 42,
    confidence: float = 0.95,
) -> dict[str, dict[str, Any]]:
    """Point estimate and percentile CI per metric.

    ``images`` needs ``label``, ``oscc_probability`` and ``group_id``. Resamples where a metric is
    undefined (e.g. AUC with one class) are skipped for that metric; ``n_valid`` says how many
    resamples contributed.
    """
    y_all = images["label"].to_numpy(dtype=int)
    p_all = images["oscc_probability"].to_numpy(dtype=float)
    groups = images["group_id"].astype(str).to_numpy()
    unique_groups = np.unique(groups)
    members = [np.flatnonzero(groups == g) for g in unique_groups]
    rng = np.random.default_rng(seed)

    point = point_metrics(y_all, p_all, threshold)
    samples: dict[str, list[float]] = {m: [] for m in METRICS}
    for _ in range(n_resamples):
        chosen = rng.integers(0, len(members), len(members))
        idx = np.concatenate([members[i] for i in chosen])
        values = point_metrics(y_all[idx], p_all[idx], threshold)
        for metric in METRICS:
            value = values[metric]
            if value is not None:
                samples[metric].append(value)

    alpha = (1.0 - confidence) / 2.0
    result: dict[str, dict[str, Any]] = {}
    for metric in METRICS:
        values = np.asarray(samples[metric])
        result[metric] = {
            "estimate": point[metric],
            "ci_low": float(np.quantile(values, alpha)) if len(values) else None,
            "ci_high": float(np.quantile(values, 1 - alpha)) if len(values) else None,
            "n_valid": len(values),
        }
    result["_meta"] = {
        "n_resamples": n_resamples,
        "confidence": confidence,
        "unit": "image",
        "resampled_unit": "group_id",
        "n_groups": len(unique_groups),
        "n_images": len(images),
        "seed": seed,
    }
    return result
