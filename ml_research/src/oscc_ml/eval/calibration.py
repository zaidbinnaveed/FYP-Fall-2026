"""Calibration of the image-level OSCC probability: reliability bins and expected calibration error.

Equal-width bins on [0, 1] (bin k holds 0.1*k <= p < 0.1*(k+1); p = 1.0 goes to the last bin). For
each bin: count, mean predicted probability and observed fraction of OSCC images. ECE is the
count-weighted mean absolute gap between the two; MCE the largest gap over non-empty bins.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np


def reliability(
    labels: Sequence[int], probabilities: Sequence[float], n_bins: int = 10
) -> dict[str, Any]:
    y = np.asarray(labels, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    if len(y) == 0:
        raise ValueError("calibration needs at least one image")
    if ((p < 0) | (p > 1)).any():
        raise ValueError("probabilities must lie in [0, 1]")
    index = np.minimum((p * n_bins).astype(int), n_bins - 1)
    bins: list[dict[str, Any]] = []
    ece, mce = 0.0, 0.0
    for k in range(n_bins):
        mask = index == k
        n = int(mask.sum())
        row: dict[str, Any] = {"lower": k / n_bins, "upper": (k + 1) / n_bins, "n": n}
        if n:
            confidence, observed = float(p[mask].mean()), float(y[mask].mean())
            gap = abs(observed - confidence)
            row.update(mean_probability=confidence, fraction_oscc=observed, gap=gap)
            ece += n / len(y) * gap
            mce = max(mce, gap)
        bins.append(row)
    return {"n_bins": n_bins, "n_images": len(y), "ece": ece, "mce": mce, "bins": bins}
