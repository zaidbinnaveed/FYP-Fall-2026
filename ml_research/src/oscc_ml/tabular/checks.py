"""Shortcut check (Phase T step 6): can OSCC be predicted from cues that are NOT pathology?

Baselines, each fitted on train only and scored once on test (AUC with the grouped 95% bootstrap
CI, the same resampling as every other model):

* ``file_and_jpeg``: file size, image size, JPEG quantisation tables, subsampling, EXIF/ICC/DPI;
* ``global_colour_histogram``: whole-frame RGB histograms (background and illumination included);
* ``all_non_pathology_cues``: both of the above;
* ``image_size_only``: width, height, aspect ratio;
* ``magnification_only``: P(OSCC | magnification) estimated on train.

Each cue model is a gradient-boosting classifier with default settings (no tuning, so no test or
validation information leaks into it). The rule fixed **before** looking at the numbers: a test AUC
point estimate >= 0.80 for any non-pathology baseline is reported as a MAJOR finding; 0.65-0.80 as
a moderate one. The numbers are published whatever they are.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from oscc_ml.eval.bootstrap import grouped_bootstrap
from oscc_ml.tabular import CUES_FILE, ID_COLUMNS
from oscc_ml.utils.io import iso, read_json, utc_now, write_json

CHECK_FILE = "shortcut_check.json"
MAJOR_AUC = 0.80
MODERATE_AUC = 0.65
SIZE_COLUMNS = ("img_width_px", "img_height_px", "img_aspect_ratio")


def _auc_ci(
    test: pd.DataFrame, probabilities: np.ndarray, n_bootstrap: int, seed: int
) -> dict[str, Any]:
    frame = test[["image_id", "label", "group_id"]].copy()
    frame["oscc_probability"] = probabilities
    ci = grouped_bootstrap(frame, 0.5, n_resamples=n_bootstrap, seed=seed)["auc_roc"]
    return {"estimate": ci["estimate"], "ci_low": ci["ci_low"], "ci_high": ci["ci_high"]}


def _verdict(auc: float | None) -> str:
    if auc is None:
        return "undefined"
    if auc >= MAJOR_AUC:
        return "MAJOR finding: non-pathology cues predict the label well"
    if auc >= MODERATE_AUC:
        return "moderate: some label information in non-pathology cues"
    return "no strong shortcut found"


def _cue_model(
    train: pd.DataFrame, test: pd.DataFrame, columns: list[str], seed: int
) -> np.ndarray:
    model = HistGradientBoostingClassifier(random_state=seed, early_stopping=False)
    model.fit(train[columns].astype(float), train["label"].to_numpy(int))
    return np.asarray(model.predict_proba(test[columns].astype(float))[:, 1], dtype=float)


def shortcut_check(
    features_dir: Path, out_dir: Path, *, seed: int = 42, n_bootstrap: int = 2000
) -> dict[str, Any]:
    cues = pd.read_csv(
        features_dir / CUES_FILE, dtype={"image_id": str, "group_id": str, "magnification": str}
    )
    train = cues[cues["split"] == "train"].reset_index(drop=True)
    test = cues[cues["split"] == "test"].reset_index(drop=True)
    cue_columns = [c for c in cues.columns if c not in ID_COLUMNS]
    file_cols = [c for c in cue_columns if not c.startswith("ghist_")]
    hist_cols = [c for c in cue_columns if c.startswith("ghist_")]
    baselines: dict[str, Any] = {}
    for name, cols in (
        ("file_and_jpeg", file_cols),
        ("global_colour_histogram", hist_cols),
        ("all_non_pathology_cues", cue_columns),
        ("image_size_only", list(SIZE_COLUMNS)),
    ):
        auc = _auc_ci(test, _cue_model(train, test, cols, seed), n_bootstrap, seed)
        constant = [c for c in cols if train[c].nunique() <= 1]
        baselines[name] = {
            "n_columns": len(cols),
            "columns_constant_in_train": constant,
            "test_auc": auc,
            "verdict": _verdict(auc["estimate"]),
        }
    rate = train.groupby("magnification")["label"].mean()
    mag_prob = test["magnification"].map(rate).fillna(float(train["label"].mean())).to_numpy()
    auc = _auc_ci(test, mag_prob, n_bootstrap, seed)
    baselines["magnification_only"] = {
        "train_oscc_rate_by_magnification": {str(k): float(v) for k, v in rate.items()},
        "test_auc": auc,
        "verdict": _verdict(auc["estimate"]),
    }
    worst = max(
        (
            b["test_auc"]["estimate"]
            for b in baselines.values()
            if b["test_auc"]["estimate"] is not None
        ),
        default=None,
    )
    extraction = read_json(features_dir / "extraction.json")
    result = {
        "rule": f"MAJOR if any test AUC point estimate >= {MAJOR_AUC}; "
        f"moderate if >= {MODERATE_AUC}",
        "model": "HistGradientBoostingClassifier, default settings, fitted on train only",
        "ci": f"95% grouped bootstrap over group_id, {n_bootstrap} resamples, seed {seed}",
        "n_train": len(train),
        "n_test": len(test),
        "baselines": baselines,
        "highest_test_auc": worst,
        "overall_verdict": _verdict(worst),
        "cues_sha256": extraction.get("cues_sha256"),
        "created_at": iso(utc_now()),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / CHECK_FILE, result)
    (out_dir / "shortcut_check.md").write_text(render(result), encoding="utf-8")
    return result


def render(result: dict[str, Any]) -> str:
    def fmt(v: Any) -> str:
        return "n/a" if v is None else f"{v:.3f}"

    lines = [
        "# Shortcut check: non-pathology cues",
        "",
        "_Generated by `oscc-ml tabular-shortcut` from `shortcut_check.json`; "
        "do not edit by hand._",
        "",
        f"Rule (fixed before the run): {result['rule']}. Model: {result['model']}. "
        f"CIs: {result['ci']}.",
        f"Train {result['n_train']} images, test {result['n_test']} images.",
        "",
        "| Baseline | Test AUC (95% CI) | Verdict |",
        "| --- | --- | --- |",
    ]
    for name, b in result["baselines"].items():
        auc = b["test_auc"]
        lines.append(
            f"| {name} | {fmt(auc['estimate'])} [{fmt(auc['ci_low'])}, {fmt(auc['ci_high'])}] | "
            f"{b['verdict']} |"
        )
    lines += [
        "",
        f"**Overall:** {result['overall_verdict']} "
        f"(highest AUC {fmt(result['highest_test_auc'])}).",
        "",
    ]
    return "\n".join(lines)
