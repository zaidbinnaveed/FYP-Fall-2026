"""``oscc-ml evaluate``: per-run test evaluation and cost, written to ``evaluation.json``.

Uses only the saved predictions (``predictions/*_images.csv``): tau is calibrated on validation,
then test metrics are computed at tau with 95% grouped bootstrap CIs, plus per-magnification
metrics and outcome counts for the inconclusive band. Cost is measured on a freshly built
architecture (weights do not change parameter count, FLOPs or latency), so evaluation needs
neither the dataset nor the checkpoint.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import torch

from oscc_ml.catalog import EVALUATION_FILE
from oscc_ml.config import load_protocol
from oscc_ml.cost import count_gflops, measure_latency
from oscc_ml.eval.bootstrap import grouped_bootstrap, point_metrics
from oscc_ml.eval.threshold import calibrate_threshold, outcome_counts
from oscc_ml.models.factory import build_model, parameter_count
from oscc_ml.utils.io import iso, read_json, utc_now, write_json

logger = logging.getLogger("oscc_ml.eval")


def _images(run_dir: Path, split: str) -> pd.DataFrame:
    path = run_dir / "predictions" / f"{split}_images.csv"
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; the run did not finish")
    return pd.read_csv(path, dtype={"image_id": str, "group_id": str, "magnification": str})


def evaluate_run(
    run_dir: Path,
    *,
    n_bootstrap: int = 2000,
    warmup: int = 50,
    latency_runs: int = 200,
    measure_gpu: bool = True,
    config_dir: Path | None = None,
) -> dict[str, Any]:
    info = read_json(run_dir / "run_info.json")
    if info.get("status") != "completed":
        raise ValueError(f"{run_dir.name}: status is {info.get('status')!r}, not completed")
    protocol = load_protocol(config_dir)
    target = protocol.evaluation.target_recall
    margin = protocol.evaluation.inconclusive_margin

    val, test = _images(run_dir, "val"), _images(run_dir, "test")
    tau = calibrate_threshold(val["label"].tolist(), val["oscc_probability"].tolist(), target)
    threshold = float(tau["threshold"])
    test_ci = grouped_bootstrap(test, threshold, n_resamples=n_bootstrap, seed=protocol.seed)

    by_magnification: dict[str, Any] = {}
    if "magnification" in test.columns:
        for mag, frame in test.groupby("magnification"):
            by_magnification[str(mag)] = {
                "n_images": len(frame),
                **point_metrics(
                    frame["label"].to_numpy(dtype=int),
                    frame["oscc_probability"].to_numpy(dtype=float),
                    threshold,
                ),
            }

    model = build_model(info["architecture"], pretrained=False)
    cost: dict[str, Any] = {
        "parameter_count": parameter_count(model),
        "gflops_per_patch": count_gflops(model),
        "gflops_convention": "torch FlopCounterMode, 1x3x224x224 forward, multiply-add = 2 FLOPs",
        "latency_cpu": measure_latency(model, torch.device("cpu"), warmup, latency_runs),
        "latency_gpu": None,
        "peak_gpu_memory_inference_mb": None,
        "peak_gpu_memory_train_mb": info.get("peak_gpu_memory_train_mb"),
        "training_time_seconds": info.get("training_time_seconds"),
    }
    if measure_gpu and torch.cuda.is_available():
        gpu = measure_latency(model, torch.device("cuda"), warmup, latency_runs)
        cost["latency_gpu"] = gpu
        cost["peak_gpu_memory_inference_mb"] = gpu.get("peak_memory_mb")

    evaluation = {
        "run": run_dir.name,
        "architecture": info["architecture"],
        "seed": info["seed"],
        "dataset_version": info["dataset_version"],
        "threshold": tau,
        "inconclusive_margin": margin,
        "test": test_ci,
        "test_by_magnification": by_magnification,
        "test_outcomes": outcome_counts(
            test["label"].tolist(), test["oscc_probability"].tolist(), threshold, margin
        ),
        "cost": cost,
        "evaluated_at": iso(utc_now()),
    }
    write_json(run_dir / EVALUATION_FILE, evaluation)
    return evaluation


def evaluate_all(
    runs_dir: Path, *, force: bool = False, **kwargs: Any
) -> tuple[list[Path], list[str]]:
    """Evaluate every completed training run that has no evaluation.json yet (or all if force)."""
    done: list[Path] = []
    failed: list[str] = []
    for info_path in sorted(runs_dir.glob("*/run_info.json")):
        run_dir = info_path.parent
        info = read_json(info_path)
        if info.get("purpose") != "train" or info.get("status") != "completed":
            continue
        if (run_dir / EVALUATION_FILE).is_file() and not force:
            logger.info("%s: already evaluated, skipping", run_dir.name)
            done.append(run_dir)
            continue
        try:
            logger.info("evaluating %s", run_dir.name)
            evaluate_run(run_dir, **kwargs)
            done.append(run_dir)
        except Exception as exc:
            logger.exception("evaluation of %s failed", run_dir.name)
            failed.append(f"{run_dir.name}: {type(exc).__name__}: {exc}")
    return done, failed
