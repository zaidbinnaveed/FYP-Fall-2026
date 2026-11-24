"""``oscc-ml evaluate``: per-run test evaluation and cost, written to ``evaluation.json``.

Evaluation is the only step that opens the test split (audit M2). For each completed training run
it predicts the test split from ``checkpoints/best.pt`` with the same model build, loader, AMP and
deterministic settings as training (``predictions/test_*.csv``). If a run folder has no checkpoint
(results imported at home), its existing test predictions are used and the evaluation says so.

Then: tau is calibrated on validation and the whole validation curve is saved; test metrics at tau
with 95% grouped bootstrap CIs; per-magnification metrics; the confusion matrix at tau and the
lists of false positives / false negatives; calibration (reliability bins, ECE) on validation and
test; outcome counts for the inconclusive band; cost on a freshly built architecture (weights do
not change parameter count, FLOPs or latency). After all runs: paired comparisons between models
(``comparisons.json``), the decision log (``decisions.jsonl``) and an environment snapshot.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import torch
import yaml

from oscc_ml import journal, observe
from oscc_ml.catalog import EVALUATION_FILE
from oscc_ml.config import ResolvedConfig, load_protocol
from oscc_ml.cost import count_gflops, measure_latency
from oscc_ml.eval.bootstrap import grouped_bootstrap, point_metrics
from oscc_ml.eval.calibration import reliability
from oscc_ml.eval.compare import compare_runs
from oscc_ml.eval.threshold import calibrate_threshold, outcome_counts, threshold_curve
from oscc_ml.models.factory import build_model, parameter_count
from oscc_ml.utils.io import iso, read_json, utc_now, write_json

logger = logging.getLogger("oscc_ml.eval")
CURVE_FILE = "val_threshold_curve.csv"


def _images(run_dir: Path, split: str) -> pd.DataFrame:
    path = run_dir / "predictions" / f"{split}_images.csv"
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; the run did not finish")
    return pd.read_csv(path, dtype={"image_id": str, "group_id": str, "magnification": str})


def predict_test(
    run_dir: Path, info: dict[str, Any], *, data_root: Path | None = None, device: str = "auto"
) -> dict[str, Any]:
    """Write ``predictions/test_{patches,images}.csv`` from ``checkpoints/best.pt``.

    Reproduces the prediction step that training ran before audit M2: the model is built exactly
    as in training, the best checkpoint is loaded, and the test split is read with the evaluation
    transform and the run's batch size, workers, AMP setting and deterministic mode."""
    from oscc_ml.data.datasets import EvalTransform
    from oscc_ml.data.processed import MemmapPatchDataset, read_dataset_info
    from oscc_ml.eval.metrics import aggregate_to_images
    from oscc_ml.train.runner import resolve_device
    from oscc_ml.train.trainer import epoch_generator, make_loader, predict
    from oscc_ml.utils.seeding import seed_everything

    best = run_dir / "checkpoints" / "best.pt"
    predictions = run_dir / "predictions"
    if not best.is_file():
        if (predictions / "test_images.csv").is_file():
            return {"source": "existing predictions/test_*.csv (no checkpoint in this folder)"}
        raise FileNotFoundError(f"{run_dir.name}: neither checkpoints/best.pt nor test predictions")
    cfg = ResolvedConfig.model_validate(
        yaml.safe_load((run_dir / "config.resolved.yaml").read_text("utf-8"))
    )
    root = Path(data_root) if data_root is not None else Path(str(info.get("data_root")))
    if not (root / "dataset.json").is_file():
        raise FileNotFoundError(
            f"{run_dir.name}: prepared dataset not found at {root}; pass --data-root"
        )
    version = read_dataset_info(root)["dataset_version"]
    if version != info["dataset_version"]:
        raise ValueError(
            f"{run_dir.name}: trained on {info['dataset_version']!r}, but the dataset at {root} "
            f"is {version!r}"
        )
    torch_device = resolve_device(device, smoke=bool(info.get("smoke")))
    seed_everything(cfg.run.seed, cfg.run.deterministic)
    model = build_model(cfg.architecture, pretrained=cfg.run.pretrained)
    state = torch.load(best, map_location=torch_device, weights_only=True)
    model.load_state_dict(state["state_dict"])
    model.to(torch_device)
    use_amp = bool(info.get("amp_active")) and torch_device.type == "cuda"
    dataset = MemmapPatchDataset(root, "test", EvalTransform(cfg.protocol.data.normalization))
    loader = make_loader(
        dataset, cfg.run.batch_size, False, cfg.run.num_workers, epoch_generator(cfg.run.seed, 0)
    )
    patches, _ = predict(model, loader, dataset, torch_device, use_amp)
    images = aggregate_to_images(patches)
    predictions.mkdir(exist_ok=True)
    patches.to_csv(predictions / "test_patches.csv", index=False)
    images.to_csv(predictions / "test_images.csv", index=False)
    return {
        "source": "checkpoints/best.pt",
        "checkpoint_epoch": state.get("epoch"),
        "device": str(torch_device),
        "amp": use_amp,
        "data_root": str(root),
        "n_images": len(images),
        "n_patches": len(patches),
    }


def errors_at(frame: pd.DataFrame, threshold: float) -> dict[str, Any]:
    """Confusion matrix at ``threshold`` and the false positives / negatives (image IDs)."""
    pred = frame["oscc_probability"].to_numpy(dtype=float) >= threshold
    label = frame["label"].to_numpy(dtype=int)
    keep = [c for c in ("image_id", "label", "oscc_probability", "magnification") if c in frame]
    fp = frame.loc[pred & (label == 0), keep].sort_values("oscc_probability", ascending=False)
    fn = frame.loc[~pred & (label == 1), keep].sort_values("oscc_probability")
    return {
        "threshold": threshold,
        "confusion_matrix": {
            "tn": int((~pred & (label == 0)).sum()),
            "fp": int((pred & (label == 0)).sum()),
            "fn": int((~pred & (label == 1)).sum()),
            "tp": int((pred & (label == 1)).sum()),
        },
        "false_positives": fp.to_dict(orient="records"),
        "false_negatives": fn.to_dict(orient="records"),
    }


def evaluate_run(
    run_dir: Path,
    *,
    n_bootstrap: int = 2000,
    warmup: int = 50,
    latency_runs: int = 200,
    measure_gpu: bool = True,
    config_dir: Path | None = None,
    data_root: Path | None = None,
    device: str = "auto",
) -> dict[str, Any]:
    info = read_json(run_dir / "run_info.json")
    if info.get("status") != "completed":
        raise ValueError(f"{run_dir.name}: status is {info.get('status')!r}, not completed")
    protocol = load_protocol(config_dir)
    target = protocol.evaluation.target_recall
    margin = protocol.evaluation.inconclusive_margin

    test_source = predict_test(run_dir, info, data_root=data_root, device=device)
    val, test = _images(run_dir, "val"), _images(run_dir, "test")
    tau = calibrate_threshold(val["label"].tolist(), val["oscc_probability"].tolist(), target)
    threshold = float(tau["threshold"])
    curve = threshold_curve(val["label"].tolist(), val["oscc_probability"].tolist(), target)
    pd.DataFrame(curve).to_csv(run_dir / CURVE_FILE, index=False)
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
        "test_at_tau": errors_at(test, threshold),
        "calibration": {
            "validation": reliability(val["label"].tolist(), val["oscc_probability"].tolist()),
            "test": reliability(test["label"].tolist(), test["oscc_probability"].tolist()),
        },
        "validation_threshold_curve": CURVE_FILE,
        "test_predictions": test_source,
        "cost": cost,
        "evaluated_at": iso(utc_now()),
    }
    write_json(run_dir / EVALUATION_FILE, evaluation)
    return evaluation


def evaluate_all(
    runs_dir: Path,
    *,
    force: bool = False,
    data_root: Path | None = None,
    device: str = "auto",
    **kwargs: Any,
) -> tuple[list[Path], list[str]]:
    """Evaluate every completed training run that has no evaluation.json yet (or all if force),
    then compare the models pairwise and record the decisions."""
    done: list[Path] = []
    failed: list[str] = []
    newly_evaluated = 0
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
            evaluation = evaluate_run(run_dir, data_root=data_root, device=device, **kwargs)
            tau = evaluation["threshold"]
            observe.record_decision(
                runs_dir,
                "evaluate",
                f"tau for {info['architecture']} seed {info['seed']}: {tau['threshold']:.6f}",
                run=run_dir.name,
                architecture=info["architecture"],
                rule=tau["rule"],
                target_recall=tau["target_recall"],
                validation_recall=tau["validation_recall"],
                validation_f1=tau["validation_f1"],
                evidence=f"{run_dir.name}/{CURVE_FILE}",
            )
            journal.safely(journal.write_run_journal, run_dir)
            done.append(run_dir)
            newly_evaluated += 1
        except Exception as exc:
            logger.exception("evaluation of %s failed", run_dir.name)
            failed.append(f"{run_dir.name}: {type(exc).__name__}: {exc}")
    if done and not failed:
        comparisons = compare_runs(
            runs_dir,
            n_resamples=int(kwargs.get("n_bootstrap", 2000)),
            seed=load_protocol(kwargs.get("config_dir")).seed,
        )
        if comparisons is not None and newly_evaluated:
            for run_seed, pairs in comparisons["seeds"].items():
                for pair in pairs:
                    observe.record_decision(
                        runs_dir,
                        "compare",
                        f"{pair['a']} vs {pair['b']} (seed {run_seed}): "
                        f"dAUC {pair['delta_auc']['estimate']:+.4f}, "
                        f"Holm p {pair['delta_auc']['p_holm']:.4g}; McNemar Holm p "
                        f"{pair['mcnemar']['p_holm']:.4g}",
                        evidence="comparisons.json",
                    )
        observe.snapshot_environment(runs_dir, device)
    journal.safely(journal.write_pipeline_journal, runs_dir)
    return done, failed
