"""Threshold calibration, outcome mapping, grouped bootstrap and cost measurement."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from oscc_ml.cost import count_gflops, measure_latency
from oscc_ml.eval.bootstrap import grouped_bootstrap, point_metrics
from oscc_ml.eval.threshold import calibrate_threshold, outcome, outcome_counts
from oscc_ml.models.factory import build_model


def test_threshold_reaches_target_recall_with_best_f1() -> None:
    labels = [1, 1, 1, 1, 0, 0, 0, 0]
    probs = [0.95, 0.9, 0.6, 0.35, 0.5, 0.3, 0.2, 0.1]
    tau = calibrate_threshold(labels, probs, target_recall=0.75)
    # Thresholds reaching recall >= 0.75: 0.6 (P=1.0, R=0.75, F1=0.857) beats 0.5, 0.35, ...
    assert tau["threshold"] == pytest.approx(0.6)
    assert tau["validation_recall"] == pytest.approx(0.75)
    assert tau["validation_f1"] == pytest.approx(6 / 7)


def test_threshold_ties_go_to_the_lower_value() -> None:
    labels = [1, 1, 0]
    probs = [0.8, 0.7, 0.2]
    # 0.7 and 0.8 cannot both reach recall 1.0; only 0.7 and 0.2 do: F1 1.0 at 0.7.
    assert calibrate_threshold(labels, probs, 1.0)["threshold"] == pytest.approx(0.7)
    tie_labels, tie_probs = [1, 0, 1, 0], [0.9, 0.9, 0.5, 0.5]
    # 0.5 gives recall 1.0 with F1 0.667; 0.9 gives recall 0.5 (below target 1.0).
    assert calibrate_threshold(tie_labels, tie_probs, 1.0)["threshold"] == pytest.approx(0.5)


def test_threshold_needs_both_classes() -> None:
    with pytest.raises(ValueError, match="both classes"):
        calibrate_threshold([1, 1], [0.2, 0.4], 0.95)


@pytest.mark.parametrize(
    ("p", "expected"),
    [
        (0.55, "oscc_suspected"),  # p >= tau + m
        (0.549, "inconclusive"),
        (0.45, "inconclusive"),  # tau - m <= p
        (0.449, "non_oscc"),
    ],
)
def test_outcome_bands_match_srs_appendix_b(p: float, expected: str) -> None:
    assert outcome(p, threshold=0.5, margin=0.05) == expected


def test_outcome_counts_by_true_label() -> None:
    counts = outcome_counts([1, 1, 0], [0.9, 0.5, 0.1], threshold=0.5, margin=0.05)
    assert counts["oscc"] == {"oscc_suspected": 1, "inconclusive": 1, "non_oscc": 0}
    assert counts["non_oscc"]["non_oscc"] == 1


def _images(n_groups: int = 20, per_group: int = 3, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_groups):
        label = g % 2
        for i in range(per_group):
            p = float(np.clip(rng.normal(0.7 if label else 0.3, 0.15), 0, 1))
            rows.append(
                {
                    "image_id": f"g{g}-{i}",
                    "group_id": f"g{g}",
                    "label": label,
                    "oscc_probability": p,
                }
            )
    return pd.DataFrame(rows)


def test_bootstrap_ci_brackets_the_estimate_and_is_reproducible() -> None:
    images = _images()
    a = grouped_bootstrap(images, threshold=0.5, n_resamples=300, seed=42)
    b = grouped_bootstrap(images, threshold=0.5, n_resamples=300, seed=42)
    assert a == b
    for metric in ("accuracy", "recall", "f1", "auc_roc"):
        entry = a[metric]
        assert entry["ci_low"] <= entry["estimate"] <= entry["ci_high"]
    assert a["_meta"]["n_groups"] == 20
    assert a["_meta"]["resampled_unit"] == "group_id"
    estimate = point_metrics(
        images["label"].to_numpy(), images["oscc_probability"].to_numpy(), 0.5
    )["accuracy"]
    assert a["accuracy"]["estimate"] == pytest.approx(estimate)


def test_bootstrap_resamples_groups_not_images() -> None:
    # One group of 30 identical images: any resample is that group, so the CI collapses.
    images = pd.DataFrame(
        {
            "image_id": [f"i{i}" for i in range(31)],
            "group_id": ["big"] * 30 + ["small"],
            "label": [1] * 30 + [0],
            "oscc_probability": [0.9] * 30 + [0.2],
        }
    )
    result = grouped_bootstrap(images, threshold=0.5, n_resamples=200, seed=1)
    # AUC is undefined whenever a resample holds only one group's class.
    assert result["auc_roc"]["n_valid"] < 200


def test_gflops_match_the_published_resnet50_cost() -> None:
    gflops = count_gflops(build_model("resnet50", pretrained=False))
    assert 7.5 <= gflops <= 8.8  # ~4.1 GMACs x 2


def test_latency_measurement_shape() -> None:
    model = build_model("efficientnet_b0", pretrained=False)
    result = measure_latency(model, torch.device("cpu"), warmup=1, runs=3)
    assert result["runs"] == 3
    assert result["mean_ms"] > 0
    assert result["p95_ms"] >= result["mean_ms"] * 0.5
    assert result["batch_size"] == 1
