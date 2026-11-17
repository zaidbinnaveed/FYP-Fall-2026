"""Binary classification metrics and patch-to-image aggregation.

Bootstrap confidence intervals, paired tests and threshold calibration are Phase R3.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score


def aggregate_to_images(patches: pd.DataFrame) -> pd.DataFrame:
    """Image probability = mean of its patch probabilities (SDS classification logic).

    Expects columns ``image_id, label, oscc_probability``; a label must be constant per image.
    """
    grouped = patches.groupby("image_id", sort=True)
    if (grouped["label"].nunique() > 1).any():
        raise ValueError("an image has patches with different labels")
    images = grouped.agg(
        label=("label", "first"),
        oscc_probability=("oscc_probability", "mean"),
        n_patches=("oscc_probability", "size"),
    )
    return images.reset_index()


def auc_or_none(labels: Sequence[int], probabilities: Sequence[float]) -> float | None:
    """AUC-ROC, or ``None`` when only one class is present (undefined)."""
    if len(set(labels)) < 2:
        return None
    value = float(roc_auc_score(labels, probabilities))
    return None if math.isnan(value) else value


def binary_metrics(
    labels: Sequence[int], probabilities: Sequence[float], threshold: float
) -> dict[str, Any]:
    y = np.asarray(labels, dtype=int)
    p = np.asarray(probabilities, dtype=float)
    pred = (p >= threshold).astype(int)
    tn, fp, fn, tp = (int(v) for v in confusion_matrix(y, pred, labels=[0, 1]).ravel())
    return {
        "n": len(y),
        "n_positive": int(y.sum()),
        "accuracy": float((pred == y).mean()) if len(y) else None,
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "auc_roc": auc_or_none(y.tolist(), p.tolist()),
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
    }
