"""One training run, end to end, written to a run folder.

Folder name: ``<UTC timestamp>_<model>_<seed>`` (sweep runs add ``_lr<value>`` and live in
``runs/sweep/``). Contents:

    config.resolved.yaml     protocol + architecture + the settings this run actually used
    run_info.json            status, purpose, protocol compliance and deviations, git state,
                             dataset_version, timings, peak GPU memory, command
    environment.json         python/torch/torchvision/transformers/CUDA versions, GPU names
    run.log                  console log of the run
    train_log.csv            one row per epoch, including seconds per epoch
    checkpoints/best.pt      best checkpoint by validation image-level AUC
    checkpoints/last.pt      full training state after the latest epoch (for --resume)
    predictions/val_*.csv    validation predictions per patch and per image
    predictions/test_*.csv   test predictions (not for sweep runs: the sweep never sees test)
    metrics.json             metrics at the uncalibrated 0.5 threshold; ``evaluate`` adds the
                             calibrated threshold, bootstrap CIs and cost (evaluation.json)
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import torch
import yaml

from oscc_ml import __version__
from oscc_ml.config import ResolvedConfig, resolve
from oscc_ml.data.datasets import EvalTransform, TrainTransform
from oscc_ml.data.processed import MemmapPatchDataset, read_dataset_info
from oscc_ml.data.synthetic import SYNTHETIC_DATASET_VERSION, write_synthetic_dataset
from oscc_ml.eval.metrics import aggregate_to_images, binary_metrics
from oscc_ml.models.factory import (
    DISPLAY_NAME,
    FAMILY,
    WEIGHTS_SOURCE,
    attention_implementation,
    build_model,
    parameter_count,
)
from oscc_ml.paths import ML_ROOT
from oscc_ml.preprocess import PREPROCESS_VERSION
from oscc_ml.runinfo import environment_info, git_state
from oscc_ml.train.trainer import epoch_generator, make_loader, predict, train
from oscc_ml.utils.io import iso, read_json, utc_now, write_json
from oscc_ml.utils.seeding import seed_everything

# Calibration of tau on validation happens in `oscc-ml evaluate`. metrics.json uses this fixed
# value and says so.
UNCALIBRATED_THRESHOLD = 0.5
Purpose = Literal["smoke", "sweep", "train"]
logger = logging.getLogger("oscc_ml.train")


class DatasetUnavailableError(RuntimeError):
    """Raised when a non-smoke run has no prepared dataset to read."""


def resolve_device(requested: str, smoke: bool) -> torch.device:
    if smoke:
        if requested not in {"auto", "cpu"}:
            raise ValueError("smoke runs are CPU-only (ADR-0001 G-e); use --device cpu or auto")
        return torch.device("cpu")
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise ValueError("--device cuda requested but CUDA is not available")
    return torch.device(requested)


def lr_tag(lr: float) -> str:
    return f"{lr:.0e}".replace("e-0", "e-")


def new_run_dir(runs_dir: Path, name: str, now: datetime) -> Path:
    base = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{name}"
    candidate, n = runs_dir / base, 1
    while candidate.exists():  # two runs in the same second never share a folder
        candidate = runs_dir / f"{base}-{n}"
        n += 1
    candidate.mkdir(parents=True)
    return candidate


def find_run(
    runs_dir: Path,
    *,
    architecture: str,
    seed: int,
    dataset_version: str,
    purpose: Purpose,
    lr: float,
    epochs: int,
) -> tuple[Path | None, str | None]:
    """Latest run folder matching these settings and its status, or (None, None)."""
    if not runs_dir.is_dir():
        return None, None
    matches = []
    for info_path in runs_dir.glob("*/run_info.json"):
        try:
            info = read_json(info_path)
        except (OSError, json.JSONDecodeError):
            continue
        if (
            info.get("architecture") == architecture
            and info.get("seed") == seed
            and info.get("dataset_version") == dataset_version
            and info.get("purpose") == purpose
            and info.get("lr") == lr
            and info.get("epochs") == epochs
        ):
            matches.append((info_path.parent.name, info_path.parent, info.get("status")))
    if not matches:
        return None, None
    _, path, status = max(matches)
    return path, status


class _RunLog:
    """Mirror log records into ``run_dir/run.log`` for the duration of a run."""

    def __init__(self, run_dir: Path) -> None:
        self.handler = logging.FileHandler(run_dir / "run.log", encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    def __enter__(self) -> None:
        logging.getLogger("oscc_ml").addHandler(self.handler)

    def __exit__(self, *exc: object) -> None:
        logging.getLogger("oscc_ml").removeHandler(self.handler)
        self.handler.close()


def run_training(
    model_name: str,
    *,
    smoke: bool,
    runs_dir: Path,
    data_root: Path | None = None,
    seed: int | None = None,
    device: str = "auto",
    config_dir: Path | None = None,
    purpose: Purpose | None = None,
    lr: float | None = None,
    lr_source: str | None = None,
    epochs: int | None = None,
    batch_size: int | None = None,
    pretrained: bool | None = None,
    resume: bool = False,
) -> Path:
    """Execute (or resume) one run and return its folder. Failures are recorded, then raised."""
    torch_device = resolve_device(device, smoke)
    # ignore_cleanup_errors: on Windows a memmap may still be open when the folder is removed.
    with tempfile.TemporaryDirectory(prefix="oscc-smoke-", ignore_cleanup_errors=True) as tmp:
        if smoke:
            from oscc_ml.config import load_protocol

            smoke_cfg = load_protocol(config_dir).smoke
            data_root = write_synthetic_dataset(
                Path(tmp),
                smoke_cfg.split,
                seed=42 if seed is None else seed,
                dataset_version=SYNTHETIC_DATASET_VERSION,
            )
        if data_root is None or not (data_root / "dataset.json").is_file():
            raise DatasetUnavailableError(
                f"No prepared dataset at {data_root}. Run `oscc-ml prepare` (Phase R1) or pass "
                "--data-root; use --smoke for the pipeline check."
            )
        dataset_info = read_dataset_info(data_root)
        cfg = resolve(
            model_name,
            smoke=smoke,
            seed=seed,
            device=str(torch_device),
            dataset_version=str(dataset_info["dataset_version"]),
            directory=config_dir,
            purpose=purpose,
            lr=lr,
            lr_source=lr_source,
            epochs=epochs,
            batch_size=batch_size,
            pretrained=pretrained,
        )
        return _execute(cfg, data_root, runs_dir, torch_device, resume)


def _execute(
    cfg: ResolvedConfig, data_root: Path, runs_dir: Path, device: torch.device, resume: bool
) -> Path:
    protocol, run = cfg.protocol, cfg.run
    existing, status = (None, None)
    if resume:
        existing, status = find_run(
            runs_dir,
            architecture=cfg.architecture,
            seed=run.seed,
            dataset_version=run.dataset_version,
            purpose=run.purpose,
            lr=run.lr,
            epochs=run.epochs,
        )
        if existing is not None and status == "completed":
            logger.info("%s: already completed in %s, skipping", cfg.architecture, existing.name)
            return existing
        if existing is not None and not (existing / "checkpoints" / "last.pt").is_file():
            existing = None  # nothing to resume from; start a fresh run

    started = utc_now()
    if existing is not None:
        run_dir = existing
        info = read_json(run_dir / "run_info.json")
        info["resumed_at"] = [*info.get("resumed_at", []), iso(started)]
    else:
        name = f"{cfg.architecture}_{run.seed}"
        if run.purpose == "sweep":
            name += f"_lr{lr_tag(run.lr)}"
        run_dir = new_run_dir(runs_dir, name, started)
        info = {
            "architecture": cfg.architecture,
            "display_name": DISPLAY_NAME.get(cfg.architecture),
            "family": FAMILY.get(cfg.architecture),
            "weights": WEIGHTS_SOURCE.get(cfg.architecture) if run.pretrained else "random",
            "seed": run.seed,
            "purpose": run.purpose,
            "smoke": run.smoke,
            "lr": run.lr,
            "lr_source": run.lr_source,
            "epochs": run.epochs,
            "batch_size": run.batch_size,
            "protocol_compliant": run.protocol_compliant,
            "deviations": list(run.deviations),
            "reportable": run.purpose == "train" and run.protocol_compliant,
            "dataset_version": run.dataset_version,
            "data_root": str(data_root) if not run.smoke else "temporary synthetic data",
            "protocol_version": protocol.protocol_version,
            "preprocess_version": PREPROCESS_VERSION,
            "oscc_ml_version": __version__,
            "amp_active": protocol.training.amp and device.type == "cuda",
            "started_at": iso(started),
            "command": sys.argv,
            **git_state(ML_ROOT),
        }
        (run_dir / "config.resolved.yaml").write_text(
            yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False), "utf-8"
        )
        write_json(run_dir / "environment.json", environment_info(device))
    info["status"] = "running"
    write_json(run_dir / "run_info.json", info)

    with _RunLog(run_dir):
        try:
            _train_and_predict(cfg, data_root, run_dir, device, info, resume=existing is not None)
        except KeyboardInterrupt:
            info.update(status="interrupted", stopped_at=iso(utc_now()))
            write_json(run_dir / "run_info.json", info)
            raise
        except BaseException as exc:
            info.update(
                status="failed",
                stopped_at=iso(utc_now()),
                error=f"{type(exc).__name__}: {exc}",
                traceback=traceback.format_exc(),
            )
            write_json(run_dir / "run_info.json", info)
            logger.exception("%s failed", cfg.architecture)
            raise
    return run_dir


def _train_and_predict(
    cfg: ResolvedConfig,
    data_root: Path,
    run_dir: Path,
    device: torch.device,
    info: dict[str, Any],
    resume: bool,
) -> None:
    protocol, run = cfg.protocol, cfg.run
    seed_everything(run.seed, run.deterministic)
    norm = protocol.data.normalization
    train_ds = MemmapPatchDataset(data_root, "train", TrainTransform(protocol.augmentation, norm))
    val_ds = MemmapPatchDataset(data_root, "val", EvalTransform(norm))

    model = build_model(cfg.architecture, pretrained=run.pretrained)
    info["attention_implementation"] = attention_implementation(model)
    result = train(
        model,
        cfg,
        train_ds,
        val_ds,
        device,
        run_dir,
        {
            "architecture": cfg.architecture,
            "preprocess_version": PREPROCESS_VERSION,
            "protocol_version": protocol.protocol_version,
            "dataset_version": run.dataset_version,
        },
        resume=resume,
    )

    state = torch.load(run_dir / "checkpoints" / "best.pt", map_location=device, weights_only=True)
    model.load_state_dict(state["state_dict"])
    use_amp = bool(info["amp_active"])
    predictions_dir = run_dir / "predictions"
    predictions_dir.mkdir(exist_ok=True)
    metrics: dict[str, Any] = {
        "architecture": cfg.architecture,
        "seed": run.seed,
        "purpose": run.purpose,
        "smoke": run.smoke,
        "dataset_version": run.dataset_version,
        "parameter_count": parameter_count(model),
        "best_epoch": result.best_epoch,
        "best_val_auc_image": result.best_val_auc,
        "epochs_run": result.epochs_run,
        "stopped_early": result.stopped_early,
        "training_time_seconds": round(result.training_seconds, 3),
        "mean_epoch_seconds": (
            round(sum(r["epoch_seconds"] for r in result.history) / len(result.history), 3)
            if result.history
            else None
        ),
        "peak_gpu_memory_train_mb": result.peak_gpu_memory_mb,
        "decision_threshold": UNCALIBRATED_THRESHOLD,
        "threshold_note": "fixed 0.5, uncalibrated; see evaluation.json for tau from validation",
        "primary_unit": "image (mean of patch probabilities)",
    }
    # The LR sweep selects on validation only; it never computes test predictions.
    splits = ("val",) if run.purpose == "sweep" else ("val", "test")
    for split in splits:
        dataset = (
            val_ds if split == "val" else MemmapPatchDataset(data_root, split, val_ds.transform)
        )
        loader = make_loader(
            dataset, run.batch_size, False, run.num_workers, epoch_generator(run.seed, 0)
        )
        patches, _ = predict(model, loader, dataset, device, use_amp)
        images = aggregate_to_images(patches)
        patches.to_csv(predictions_dir / f"{split}_patches.csv", index=False)
        images.to_csv(predictions_dir / f"{split}_images.csv", index=False)
        metrics[split] = {
            "image": binary_metrics(
                images["label"].tolist(),
                images["oscc_probability"].tolist(),
                UNCALIBRATED_THRESHOLD,
            ),
            "patch": binary_metrics(
                patches["label"].tolist(),
                patches["oscc_probability"].tolist(),
                UNCALIBRATED_THRESHOLD,
            ),
        }
    write_json(run_dir / "metrics.json", metrics)
    info.update(
        status="completed",
        finished_at=iso(utc_now()),
        peak_gpu_memory_train_mb=result.peak_gpu_memory_mb,
        training_time_seconds=round(result.training_seconds, 3),
    )
    write_json(run_dir / "run_info.json", info)
