"""Classical classifiers on the tabular dataset (Phase T; proposed FR-7.11).

Protocol, the same as the image models wherever it applies:

* fitted on **train only**, every step inside a scikit-learn ``Pipeline`` (scaling is learnt on the
  training folds only);
* hyper-parameters tuned by **grouped** 5-fold cross-validation on train
  (``StratifiedGroupKFold`` over the manifest ``group_id``, scoring ROC AUC); the best setting is
  refitted on all of train;
* tau from **validation** (target recall 0.95, max F1, ties -> lower), as ``oscc-ml evaluate``;
* **test used once**, after tau is fixed: 95% CIs by the grouped bootstrap, per-magnification
  metrics, ECE, confusion matrix, FP/FN lists;
* permutation importance on **validation** (never test);
* results written as run folders in the image-run format (``run_info.json``, ``metrics.json``,
  ``predictions/{val,test}_images.csv``, ``evaluation.json``, ``TRAINING_JOURNAL.md``), so
  ``report`` and the paired comparisons treat tabular, CNN and ViT runs alike.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV, StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from oscc_ml import __version__, journal, observe
from oscc_ml.catalog import DISPLAY_NAME, EVALUATION_FILE, FAMILY
from oscc_ml.config import load_protocol
from oscc_ml.eval.bootstrap import grouped_bootstrap, point_metrics
from oscc_ml.eval.calibration import reliability
from oscc_ml.eval.threshold import calibrate_threshold, outcome_counts, threshold_curve
from oscc_ml.paths import ML_ROOT
from oscc_ml.tabular import (
    EXTRACTION_INFO_FILE,
    FEATURES_FILE,
    ID_COLUMNS,
    METADATA_COLUMNS,
    TABULAR_FEATURES_VERSION,
)
from oscc_ml.utils.gitinfo import git_state
from oscc_ml.utils.io import iso, read_json, utc_now, write_json

logger = logging.getLogger("oscc_ml.tabular")

CURVE_FILE = "val_threshold_curve.csv"
IMPORTANCE_FILE = "permutation_importance_val.csv"
DIAGNOSTIC_COLUMNS = ("tissue_threshold", "tissue_mask_fallback")  # mask diagnostics, not features
CV_FOLDS = 5
PROTOCOL_NAME = "tabular-v1"


@dataclass(frozen=True)
class ModelSpec:
    architecture: str
    build: Callable[[int], Pipeline]
    grid: dict[str, list[Any]]


def _logreg(seed: int) -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(class_weight="balanced", max_iter=5000, random_state=seed),
            ),
        ]
    )


def _forest(seed: int) -> Pipeline:
    return Pipeline(
        [
            (
                "model",
                RandomForestClassifier(
                    n_estimators=500, class_weight="balanced", random_state=seed, n_jobs=1
                ),
            )
        ]
    )


def _boosting(seed: int) -> Pipeline:
    return Pipeline(
        [
            (
                "model",
                HistGradientBoostingClassifier(
                    class_weight="balanced", early_stopping=False, random_state=seed
                ),
            )
        ]
    )


MODELS: dict[str, ModelSpec] = {
    "tab_logreg": ModelSpec("tab_logreg", _logreg, {"model__C": [0.01, 0.1, 1.0, 10.0]}),
    "tab_random_forest": ModelSpec(
        "tab_random_forest",
        _forest,
        {
            "model__max_depth": [None, 8],
            "model__min_samples_leaf": [1, 5],
            "model__max_features": ["sqrt", 0.3],
        },
    ),
    "tab_gradient_boosting": ModelSpec(
        "tab_gradient_boosting",
        _boosting,
        {
            "model__learning_rate": [0.05, 0.1],
            "model__max_leaf_nodes": [15, 31],
            "model__max_iter": [100, 300],
        },
    ),
}


# --------------------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------------------


def load_table(features_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    table = pd.read_csv(
        features_dir / FEATURES_FILE,
        dtype={"image_id": str, "group_id": str, "magnification": str, "split": str},
    )
    info = read_json(features_dir / EXTRACTION_INFO_FILE)
    return table, info


def feature_columns(table: pd.DataFrame, *, with_magnification: bool = False) -> list[str]:
    skip = {*ID_COLUMNS, *METADATA_COLUMNS, *DIAGNOSTIC_COLUMNS}
    cols = [c for c in table.columns if c not in skip]
    if with_magnification:
        cols.append("is_400x")
    return cols


def design(table: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    frame = table.copy()
    frame["is_400x"] = (frame["magnification"] == "400x").astype(float)
    return frame[columns].astype(float)


def dataset_version_for(info: dict[str, Any]) -> str:
    """dataset_version from the prepare output next to the manifest the table was built from."""
    manifest_dir = Path(str(info.get("manifest", ""))).parent
    for name in ("dataset.json", "manifest_only.json"):
        path = manifest_dir / name
        if path.is_file():
            return str(read_json(path).get("dataset_version", "unknown"))
    return "unknown"


# --------------------------------------------------------------------------------------------------
# Cost
# --------------------------------------------------------------------------------------------------


def parameter_count(estimator: Pipeline) -> int:
    """Learnt numbers: coefficients + intercept (LR); tree nodes (forest, boosting)."""
    model = estimator.named_steps["model"]
    if isinstance(model, LogisticRegression):
        return int(model.coef_.size + model.intercept_.size)
    if isinstance(model, RandomForestClassifier):
        return int(sum(t.tree_.node_count for t in model.estimators_))
    if isinstance(model, HistGradientBoostingClassifier):
        return int(sum(p.nodes.shape[0] for it in model._predictors for p in it))
    return -1


def latency_ms(
    estimator: BaseEstimator, row: pd.DataFrame, warmup: int, runs: int
) -> dict[str, Any]:
    for _ in range(warmup):
        estimator.predict_proba(row)
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        estimator.predict_proba(row)
        times.append((time.perf_counter() - start) * 1000.0)
    arr = np.asarray(times)
    return {
        "device": "cpu",
        "device_name": "cpu",
        "mean_ms": float(arr.mean()),
        "p95_ms": float(np.percentile(arr, 95)),
        "warmup": warmup,
        "runs": runs,
        "batch_size": 1,
        "scope": "classifier only (one feature row); feature extraction is reported separately",
    }


# --------------------------------------------------------------------------------------------------
# Training + evaluation of one model
# --------------------------------------------------------------------------------------------------


def _predictions(frame: pd.DataFrame, probabilities: np.ndarray) -> pd.DataFrame:
    out = frame[["image_id", "label", "group_id", "magnification"]].copy()
    out["oscc_probability"] = probabilities
    out["n_patches"] = 1  # one feature row per image (keeps the image-run columns)
    return out.sort_values("image_id").reset_index(drop=True)


def errors_at(frame: pd.DataFrame, threshold: float) -> dict[str, Any]:
    from oscc_ml.eval.evaluate import errors_at as image_errors_at

    return image_errors_at(frame, threshold)


def _new_run_dir(runs_dir: Path, name: str) -> Path:
    base = f"{utc_now().strftime('%Y%m%dT%H%M%SZ')}_{name}"
    candidate, n = runs_dir / base, 1
    while candidate.exists():
        candidate = runs_dir / f"{base}-{n}"
        n += 1
    candidate.mkdir(parents=True)
    return candidate


def train_one(
    spec: ModelSpec,
    table: pd.DataFrame,
    extraction: dict[str, Any],
    runs_dir: Path,
    *,
    seed: int = 42,
    with_magnification: bool = False,
    n_bootstrap: int = 2000,
    n_repeats: int = 20,
    latency_runs: int = 200,
    config_dir: Path | None = None,
) -> Path:
    protocol = load_protocol(config_dir)
    target, margin = protocol.evaluation.target_recall, protocol.evaluation.inconclusive_margin
    columns = feature_columns(table, with_magnification=with_magnification)
    splits = {
        s: table[table["split"] == s].reset_index(drop=True) for s in ("train", "val", "test")
    }
    x_train, y_train = design(splits["train"], columns), splits["train"]["label"].to_numpy(int)
    groups = splits["train"]["group_id"].to_numpy()
    purpose = "ablation" if with_magnification else "train"
    name = f"{spec.architecture}_{seed}" + ("_mag" if with_magnification else "")
    run_dir = _new_run_dir(runs_dir, name)
    started = utc_now()
    info: dict[str, Any] = {
        "architecture": spec.architecture,
        "display_name": DISPLAY_NAME[spec.architecture],
        "family": FAMILY[spec.architecture],
        "model_type": "tabular",
        "weights": "fitted on the train split only (scikit-learn)",
        "seed": seed,
        "purpose": purpose,
        "smoke": False,
        "lr": None,
        "lr_source": "not applicable (tabular)",
        "epochs": None,
        "batch_size": None,
        "protocol_compliant": True,
        "deviations": [],
        "reportable": purpose == "train",
        "feature_set": "features + magnification (ablation)" if with_magnification else "features",
        "n_features": len(columns),
        "dataset_version": dataset_version_for(extraction),
        "tabular_features_version": TABULAR_FEATURES_VERSION,
        "features_sha256": extraction.get("features_sha256"),
        "protocol_version": PROTOCOL_NAME,
        "preprocess_version": None,
        "oscc_ml_version": __version__,
        "amp_active": False,
        "status": "running",
        "started_at": iso(started),
        **git_state(ML_ROOT),
    }
    write_json(run_dir / "run_info.json", info)

    tic = time.perf_counter()
    search = GridSearchCV(
        spec.build(seed),
        spec.grid,
        scoring="roc_auc",
        cv=StratifiedGroupKFold(n_splits=CV_FOLDS, shuffle=True, random_state=seed),
        refit=True,
        n_jobs=1,
    )
    search.fit(x_train, y_train, groups=groups)
    fit_seconds = time.perf_counter() - tic
    model = search.best_estimator_

    cv_rows: list[dict[str, Any]] = [
        {
            "params": {k.removeprefix("model__"): v for k, v in params.items()},
            "mean_cv_auc": float(mean),
            "std_cv_auc": float(std),
            "rank": int(rank),
        }
        for params, mean, std, rank in zip(
            search.cv_results_["params"],
            search.cv_results_["mean_test_score"],
            search.cv_results_["std_test_score"],
            search.cv_results_["rank_test_score"],
            strict=True,
        )
    ]
    best_params = {k.removeprefix("model__"): v for k, v in search.best_params_.items()}

    preds_dir = run_dir / "predictions"
    preds_dir.mkdir()
    val = _predictions(splits["val"], model.predict_proba(design(splits["val"], columns))[:, 1])
    val.to_csv(preds_dir / "val_images.csv", index=False)
    val_at_half = point_metrics(val["label"].to_numpy(int), val["oscc_probability"].to_numpy(), 0.5)
    metrics = {
        "architecture": spec.architecture,
        "seed": seed,
        "purpose": purpose,
        "smoke": False,
        "dataset_version": info["dataset_version"],
        "parameter_count": parameter_count(model),
        "n_features": len(columns),
        "features": columns,
        "tuning": {
            "method": f"GridSearchCV, StratifiedGroupKFold({CV_FOLDS}, shuffle, seed {seed}) on "
            "train, groups = manifest group_id, scoring ROC AUC, refit on all of train",
            "grid": {k.removeprefix("model__"): v for k, v in spec.grid.items()},
            "best_params": best_params,
            "best_mean_cv_auc": float(search.best_score_),
            "cv_results": cv_rows,
        },
        "training_time_seconds": round(fit_seconds, 3),
        "val": {"image": val_at_half},
        "decision_threshold": 0.5,
        "threshold_note": "fixed 0.5, uncalibrated; see evaluation.json for tau from validation",
        "primary_unit": "image (one feature row per image)",
        "test_predictions": "made after tau is fixed, in the same call (test used once)",
    }
    write_json(run_dir / "metrics.json", metrics)

    # tau from validation, then test once
    tau = calibrate_threshold(val["label"].tolist(), val["oscc_probability"].tolist(), target)
    threshold = float(tau["threshold"])
    pd.DataFrame(
        threshold_curve(val["label"].tolist(), val["oscc_probability"].tolist(), target)
    ).to_csv(run_dir / CURVE_FILE, index=False)
    test = _predictions(splits["test"], model.predict_proba(design(splits["test"], columns))[:, 1])
    test.to_csv(preds_dir / "test_images.csv", index=False)
    test_ci = grouped_bootstrap(test, threshold, n_resamples=n_bootstrap, seed=protocol.seed)
    by_mag = {
        str(mag): {
            "n_images": len(frame),
            **point_metrics(
                frame["label"].to_numpy(int), frame["oscc_probability"].to_numpy(), threshold
            ),
        }
        for mag, frame in test.groupby("magnification")
    }

    importance = permutation_importance(
        model,
        design(splits["val"], columns),
        splits["val"]["label"].to_numpy(int),
        scoring="roc_auc",
        n_repeats=n_repeats,
        random_state=seed,
        n_jobs=1,
    )
    imp = (
        pd.DataFrame(
            {
                "feature": columns,
                "importance_mean": importance.importances_mean,
                "importance_std": importance.importances_std,
            }
        )
        .sort_values(["importance_mean", "feature"], ascending=[False, True])
        .reset_index(drop=True)
    )
    imp.to_csv(run_dir / IMPORTANCE_FILE, index=False)

    row = design(splits["test"].iloc[[0]], columns)
    cost = {
        "parameter_count": parameter_count(model),
        "parameter_count_meaning": "LR: coefficients + intercept; trees: total node count",
        "gflops_per_patch": None,
        "gflops_convention": "not applicable (no neural network)",
        "latency_cpu": latency_ms(model, row, warmup=10, runs=latency_runs),
        "latency_gpu": None,
        "feature_extraction_seconds_per_image": extraction.get("seconds_per_image"),
        "peak_gpu_memory_inference_mb": None,
        "peak_gpu_memory_train_mb": None,
        "training_time_seconds": round(fit_seconds, 3),
    }
    evaluation = {
        "run": run_dir.name,
        "architecture": spec.architecture,
        "seed": seed,
        "dataset_version": info["dataset_version"],
        "threshold": tau,
        "inconclusive_margin": margin,
        "test": test_ci,
        "test_by_magnification": by_mag,
        "test_outcomes": outcome_counts(
            test["label"].tolist(), test["oscc_probability"].tolist(), threshold, margin
        ),
        "test_at_tau": errors_at(test, threshold),
        "calibration": {
            "validation": reliability(val["label"].tolist(), val["oscc_probability"].tolist()),
            "test": reliability(test["label"].tolist(), test["oscc_probability"].tolist()),
        },
        "validation_threshold_curve": CURVE_FILE,
        "permutation_importance_validation": {
            "file": IMPORTANCE_FILE,
            "scoring": "roc_auc",
            "n_repeats": n_repeats,
            "top10": imp.head(10).to_dict(orient="records"),
        },
        "test_predictions": {"source": "fitted pipeline, after tau was fixed on validation"},
        "cost": cost,
        "evaluated_at": iso(utc_now()),
    }
    write_json(run_dir / EVALUATION_FILE, evaluation)
    info.update(
        status="completed",
        finished_at=iso(utc_now()),
        training_time_seconds=round(fit_seconds, 3),
    )
    write_json(run_dir / "run_info.json", info)

    best = max(cv_rows, key=lambda r: float(r["mean_cv_auc"]))
    observe.record_decision(
        runs_dir,
        "tabular",
        f"{spec.architecture} ({info['feature_set']}): chose {best_params}",
        run=run_dir.name,
        reason=f"highest mean grouped-CV AUC on train ({best['mean_cv_auc']:.4f}) of "
        f"{len(cv_rows)} settings",
        evidence=f"{run_dir.name}/metrics.json",
    )
    observe.record_decision(
        runs_dir,
        "evaluate",
        f"tau for {spec.architecture} seed {seed}: {threshold:.6f}",
        run=run_dir.name,
        architecture=spec.architecture,
        rule=tau["rule"],
        target_recall=tau["target_recall"],
        validation_recall=tau["validation_recall"],
        validation_f1=tau["validation_f1"],
        evidence=f"{run_dir.name}/{CURVE_FILE}",
    )
    journal.safely(journal.write_run_journal, run_dir)
    logger.info(
        "%s (%s): CV AUC %.4f, test AUC %s",
        spec.architecture,
        info["feature_set"],
        search.best_score_,
        json.dumps(test_ci["auc_roc"]["estimate"]),
    )
    return run_dir


def train_tabular(
    features_dir: Path,
    runs_dir: Path,
    *,
    models: tuple[str, ...] = tuple(MODELS),
    seed: int = 42,
    magnification_ablation: bool = True,
    n_bootstrap: int = 2000,
    config_dir: Path | None = None,
) -> list[Path]:
    table, extraction = load_table(features_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    done = []
    for name in models:
        done.append(
            train_one(
                MODELS[name],
                table,
                extraction,
                runs_dir,
                seed=seed,
                n_bootstrap=n_bootstrap,
                config_dir=config_dir,
            )
        )
    if magnification_ablation:
        for name in models:
            done.append(
                train_one(
                    MODELS[name],
                    table,
                    extraction,
                    runs_dir,
                    seed=seed,
                    with_magnification=True,
                    n_bootstrap=n_bootstrap,
                    config_dir=config_dir,
                )
            )
    journal.safely(journal.write_pipeline_journal, runs_dir)
    return done
