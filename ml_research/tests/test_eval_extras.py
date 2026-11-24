"""Calibration, paired comparisons and the gradient-norm tracker, each checked against an
independent implementation."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
import torch
from sklearn.metrics import roc_auc_score

from oscc_ml.eval.calibration import reliability
from oscc_ml.eval.compare import compare_frames, holm, mcnemar_exact, paired_delta_auc
from oscc_ml.eval.threshold import threshold_curve
from oscc_ml.observe import GradNormTracker


def test_reliability_and_ece_match_a_direct_computation() -> None:
    rng = np.random.default_rng(3)
    p = rng.random(500)
    y = (rng.random(500) < p).astype(int)
    p[:3] = [0.0, 1.0, 0.1]  # edges: 1.0 goes to the last bin, 0.1 to bin 1
    out = reliability(y.tolist(), p.tolist(), n_bins=10)
    ece = 0.0
    for k in range(10):
        lo, hi = k / 10, (k + 1) / 10
        mask = (p >= lo) & ((p < hi) if k < 9 else (p <= hi))
        if mask.any():
            ece += mask.sum() / len(p) * abs(y[mask].mean() - p[mask].mean())
        assert out["bins"][k]["n"] == int(mask.sum())
    assert out["ece"] == pytest.approx(ece, abs=1e-12)
    assert sum(b["n"] for b in out["bins"]) == 500


def test_perfectly_calibrated_bins_have_zero_gap() -> None:
    out = reliability([0, 1, 0, 1], [0.55, 0.55, 0.55, 0.55])
    assert out["ece"] == pytest.approx(0.05)


def test_holm_matches_the_textbook_procedure() -> None:
    p = [0.01, 0.04, 0.03, 0.005]
    # sorted: 0.005*4=0.02, 0.01*3=0.03, 0.03*2=0.06, 0.04*1=0.04 -> monotone 0.06
    assert holm(p) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert holm([0.5, 0.9]) == pytest.approx([1.0, 1.0])


def test_mcnemar_exact_matches_a_binomial_sum() -> None:
    a = np.array([True] * 30 + [False] * 10 + [True] * 7 + [False] * 3)
    b = np.array([True] * 30 + [False] * 10 + [False] * 7 + [True] * 3)
    out = mcnemar_exact(a, b)
    n, k = 10, 3
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    assert (out["b_only_a_correct"], out["c_only_b_correct"]) == (7, 3)
    assert out["p_value"] == pytest.approx(min(1.0, 2 * tail))
    assert mcnemar_exact(a, a)["p_value"] == 1.0


def test_paired_delta_auc_is_antisymmetric_and_matches_sklearn() -> None:
    rng = np.random.default_rng(5)
    y = rng.integers(0, 2, 120)
    y[:2] = [0, 1]
    pa, pb = rng.random(120) * 0.5 + 0.4 * y, rng.random(120)
    groups = np.array([f"g{i // 3}" for i in range(120)])
    ab = paired_delta_auc(y, pa, pb, groups, n_resamples=300, seed=1)
    ba = paired_delta_auc(y, pb, pa, groups, n_resamples=300, seed=1)
    assert ab["estimate"] == pytest.approx(roc_auc_score(y, pa) - roc_auc_score(y, pb))
    assert ab["estimate"] == pytest.approx(-ba["estimate"])
    assert ab["ci_low"] == pytest.approx(-ba["ci_high"])
    assert ab["p_value"] == pytest.approx(ba["p_value"])
    assert ab["p_value"] < 0.05  # pa is informative, pb is noise


def test_compare_frames_refuses_different_test_sets() -> None:
    f = pd.DataFrame(
        {
            "image_id": ["a", "b", "c", "d"],
            "label": [0, 1, 0, 1],
            "oscc_probability": [0.1, 0.9, 0.2, 0.8],
            "group_id": ["1", "2", "3", "4"],
        }
    )
    g = f.copy()
    g.loc[0, "image_id"] = "z"
    with pytest.raises(ValueError, match="same test images"):
        compare_frames({"m1": f, "m2": g}, {"m1": 0.5, "m2": 0.5}, n_resamples=10)
    pairs = compare_frames(
        {"m1": f, "m2": f.copy(), "m3": f.copy()}, {"m1": 0.5, "m2": 0.5, "m3": 0.5}, n_resamples=10
    )
    assert len(pairs) == 3
    assert all(p["mcnemar"]["p_holm"] == 1.0 for p in pairs)


def test_threshold_curve_matches_direct_counts() -> None:
    y = [0, 0, 1, 1, 1, 0]
    p = [0.1, 0.4, 0.35, 0.8, 0.9, 0.6]
    curve = threshold_curve(y, p, target_recall=0.95)
    assert [r["threshold"] for r in curve] == sorted(set(p))
    for row in curve:
        pred = [int(q >= row["threshold"]) for q in p]
        tp = sum(1 for a, b in zip(y, pred, strict=True) if a == b == 1)
        fp = sum(1 for a, b in zip(y, pred, strict=True) if a == 0 and b == 1)
        assert (row["tp"], row["fp"]) == (tp, fp)
        assert row["recall"] == pytest.approx(tp / 3)
        assert row["meets_target_recall"] == (tp / 3 >= 0.95)


def test_grad_norm_tracker_matches_clip_grad_norm_and_changes_nothing() -> None:
    torch.manual_seed(0)
    model = torch.nn.Sequential(torch.nn.Linear(5, 4), torch.nn.ReLU(), torch.nn.Linear(4, 1))
    model(torch.randn(8, 5)).pow(2).mean().backward()
    before = [p.grad.clone() for p in model.parameters()]
    tracker = GradNormTracker()
    tracker.add(model, scale=1.0)
    tracker.add(model, scale=2.0)  # an AMP scale of 2 halves the reported (unscaled) norm
    reference = float(torch.nn.utils.clip_grad_norm_(model.parameters(), float("inf")))
    for p, g in zip(model.parameters(), before, strict=True):
        assert torch.equal(p.grad, g)
    summary = tracker.summary()
    assert summary["n"] == 2
    assert summary["max"] == pytest.approx(reference, rel=1e-6)
    assert summary["min"] == pytest.approx(reference / 2, rel=1e-6)
