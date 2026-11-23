"""Decision threshold calibration and the three-way outcome mapping.

tau (SDS Appendix A, plan R3 step 2, decision O2): on the *validation* set, among thresholds whose
recall reaches the target, choose the one with the highest F1; ties -> the lower threshold.

Outcomes (SRS Appendix B / CLAUDE.md): ``oscc_suspected`` if p >= tau + m; ``inconclusive`` if
tau - m <= p < tau + m; ``non_oscc`` if p < tau - m.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

OUTCOMES = ("oscc_suspected", "inconclusive", "non_oscc")


def calibrate_threshold(
    labels: Sequence[int], probabilities: Sequence[float], target_recall: float
) -> dict[str, Any]:
    y = np.asarray(labels, dtype=int)
    p = np.asarray(probabilities, dtype=float)
    if y.sum() == 0 or y.sum() == len(y):
        raise ValueError("threshold calibration needs both classes in the validation set")
    best: tuple[float, float, float] | None = None  # (f1, -threshold, recall)
    for t in np.unique(p):
        pred = p >= t
        tp = int((pred & (y == 1)).sum())
        fp = int((pred & (y == 0)).sum())
        fn = int((~pred & (y == 1)).sum())
        recall = tp / (tp + fn)
        if recall < target_recall:
            continue
        precision = tp / (tp + fp) if tp + fp else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        key = (f1, -float(t), recall)
        if best is None or key > best:
            best = key
    if best is None:  # unreachable: the lowest observed probability gives recall 1.0
        raise ValueError("no threshold reaches the target recall")
    f1, neg_t, recall = best
    return {
        "threshold": -neg_t,
        "target_recall": target_recall,
        "validation_recall": recall,
        "validation_f1": f1,
        "rule": "max F1 among thresholds with validation recall >= target; ties -> lower",
    }


def outcome(probability: float, threshold: float, margin: float) -> str:
    if probability >= threshold + margin:
        return "oscc_suspected"
    if probability >= threshold - margin:
        return "inconclusive"
    return "non_oscc"


def outcome_counts(
    labels: Sequence[int], probabilities: Sequence[float], threshold: float, margin: float
) -> dict[str, dict[str, int]]:
    """Counts of each outcome, split by the true label (non_oscc / oscc)."""
    table = {name: {outcome_name: 0 for outcome_name in OUTCOMES} for name in ("non_oscc", "oscc")}
    for label, prob in zip(labels, probabilities, strict=True):
        table["oscc" if label == 1 else "non_oscc"][outcome(prob, threshold, margin)] += 1
    return table


def threshold_curve(
    labels: Sequence[int], probabilities: Sequence[float], target_recall: float
) -> list[dict[str, Any]]:
    """The validation curve tau is chosen from: one row per candidate threshold (every distinct
    probability, ascending) with its confusion counts, precision, recall, specificity, F1 and
    whether it reaches the target recall. Same candidates and formulas as
    :func:`calibrate_threshold`."""
    y = np.asarray(labels, dtype=int)
    p = np.asarray(probabilities, dtype=float)
    rows: list[dict[str, Any]] = []
    for t in np.unique(p):
        pred = p >= t
        tp = int((pred & (y == 1)).sum())
        fp = int((pred & (y == 0)).sum())
        fn = int((~pred & (y == 1)).sum())
        tn = int((~pred & (y == 0)).sum())
        recall = tp / (tp + fn) if tp + fn else 0.0
        precision = tp / (tp + fp) if tp + fp else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append(
            {
                "threshold": float(t),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
                "precision": precision,
                "recall": recall,
                "specificity": tn / (tn + fp) if tn + fp else None,
                "f1": f1,
                "meets_target_recall": recall >= target_recall,
            }
        )
    return rows
