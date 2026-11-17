"""Grouped, stratified 70:15:15 split (seed 42) and the leakage test (plan R1 step 5).

``StratifiedGroupKFold`` with 20 folds; folds 0-13 -> train, 14-16 -> val, 17-19 -> test (70:15:15
by group count, stratified by label). The leakage test fails loudly if any SHA-256, duplicate
cluster, group (patient or similarity cluster) or near-duplicate pair spans two splits.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

N_FOLDS = 20
FOLD_TO_SPLIT = {
    **dict.fromkeys(range(14), "train"),
    **dict.fromkeys(range(14, 17), "val"),
    **dict.fromkeys(range(17, 20), "test"),
}


class LeakageError(AssertionError):
    """The split leaks information between train, validation and test."""


class SplitError(ValueError):
    """The data cannot be split as the protocol requires."""


def grouped_split(labels: list[int], groups: list[str], seed: int) -> list[str]:
    n_groups = len(set(groups))
    if n_groups < N_FOLDS:
        raise SplitError(
            f"only {n_groups} groups; a grouped 70:15:15 split needs at least {N_FOLDS}"
        )
    if len(set(labels)) < 2:
        raise SplitError("both classes are needed for a stratified split")
    smallest = min(labels.count(0), labels.count(1))
    if smallest < N_FOLDS:
        raise SplitError(
            f"the smaller class has only {smallest} images; a stratified 70:15:15 split with "
            f"{N_FOLDS} folds needs at least {N_FOLDS} per class"
        )
    folds = np.full(len(labels), -1)
    splitter = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=seed)
    dummy = np.zeros(len(labels))
    for fold, (_, test_idx) in enumerate(splitter.split(dummy, labels, groups)):
        folds[test_idx] = fold
    return [FOLD_TO_SPLIT[int(f)] for f in folds]


def check_leakage(
    kept: pd.DataFrame,
    distances: Any | None = None,
    positions: dict[str, int] | None = None,
    near_threshold: int | None = None,
) -> None:
    """Raise :class:`LeakageError` if anything identifying spans two splits.

    ``kept`` needs ``image_id, split, label, sha256, duplicate_cluster, group_id``. With
    ``distances`` (full pairwise matrix), ``positions`` (image_id -> row) and ``near_threshold``
    it also rejects any cross-split pair of kept images that are near-duplicates.
    """
    problems: list[str] = []
    for column in ("sha256", "duplicate_cluster", "group_id"):
        spans = kept.groupby(column)["split"].nunique()
        leaking = spans[spans > 1]
        if len(leaking):
            examples = ", ".join(map(str, leaking.index[:5]))
            problems.append(
                f"{len(leaking)} {column} value(s) appear in more than one split: {examples}"
            )
    for split, frame in kept.groupby("split"):
        if frame["label"].nunique() < 2:
            problems.append(f"split {split!r} does not contain both classes")
    if distances is not None and positions is not None and near_threshold is not None:
        idx = np.array([positions[i] for i in kept["image_id"]])
        splits = kept["split"].to_numpy()
        sub = distances[np.ix_(idx, idx)]
        rows, cols = np.nonzero(np.triu(sub <= near_threshold, k=1))
        crossing = [(r, c) for r, c in zip(rows, cols, strict=True) if splits[r] != splits[c]]
        if crossing:
            r, c = crossing[0]
            problems.append(
                f"{len(crossing)} near-duplicate pair(s) span splits, e.g. "
                f"{kept['image_id'].iloc[r]} ({splits[r]}) ~ "
                f"{kept['image_id'].iloc[c]} ({splits[c]})"
            )
    if problems:
        raise LeakageError("LEAKAGE TEST FAILED:\n  " + "\n  ".join(problems))
