"""One training run, end to end, written to ``runs/<UTC timestamp>_<model>_<seed>/``.

Run folder contents (plan section 6, R0):

    config.resolved.yaml     protocol + architecture + the settings this run actually used
    run_info.json            status, git commit/dirty flag, dataset_version, timings, command
    environment.json         python/torch/torchvision/transformers/CUDA versions, GPU names
    train_log.csv            one row per epoch
    checkpoints/best.pt      best checkpoint by validation image-level AUC
    predictions/{val,test}_{patches,images}.csv
    metrics.json             validation and test metrics, image level (primary) and patch level
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
import yaml

from oscc_ml import __version__
from oscc_ml.config import PACKAGE_ROOT, ResolvedConfig, resolve
from oscc_ml.data.datasets import PatchDataset, eval_transform, train_transform
from oscc_ml.data.synthetic import SYNTHETIC_DATASET_VERSION, make_split
from oscc_ml.eval.metrics import aggregate_to_images, binary_metrics
from oscc_ml.models.factory import FAMILY, build_model, parameter_count
from oscc_ml.preprocess import PREPROCESS_VERSION
from oscc_ml.runinfo import environment_info, git_state
from oscc_ml.train.trainer import make_loader, predict, train
from oscc_ml.utils.seeding import seed_everything

# Threshold calibration on validation (tau, O2) is Phase R3. Until then metrics at a decision
# threshold use this fixed value, and every metrics file says so.
UNCALIBRATED_THRESHOLD = 0.5


class DatasetUnavailableError(RuntimeError):
    """Raised for a real (non-smoke) run before the Phase R1 dataset exists."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", "utf-8")


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


def new_run_dir(runs_dir: Path, architecture: str, seed: int, now: datetime) -> Path:
    base = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{architecture}_{seed}"
    candidate, n = runs_dir / base, 1
    while candidate.exists():  # two runs in the same second never share a folder
        candidate = runs_dir / f"{base}-{n}"
        n += 1
    candidate.mkdir(parents=True)
    return candidate


def run_training(
    model_name: str,
    *,
    smoke: bool,
    seed: int | None = None,
    runs_dir: Path,
    device: str = "auto",
    config_dir: Path | None = None,
) -> Path:
    """Execute one run and return its folder. Raises on failure (after recording it)."""
    if not smoke:
        raise DatasetUnavailableError(
            "Real training needs the oscc-unified-v1 dataset built in Phase R1, which does not "
            "exist yet. Use --smoke for the pipeline check."
        )
    torch_device = resolve_device(device, smoke)
    cfg: ResolvedConfig = resolve(
        model_name,
        smoke=smoke,
        seed=seed,
        device=str(torch_device),
        dataset_version=SYNTHETIC_DATASET_VERSION,
        directory=config_dir,
    )
    protocol, run = cfg.protocol, cfg.run

    started = _utc_now()
    run_dir = new_run_dir(runs_dir, cfg.architecture, run.seed, started)
    info: dict[str, Any] = {
        "status": "running",
        "architecture": cfg.architecture,
        "family": FAMILY.get(cfg.architecture),
        "seed": run.seed,
        "smoke": run.smoke,
        "reportable": not run.smoke,  # the report generator refuses smoke runs (G-e)
        "dataset_version": run.dataset_version,
        "protocol_version": protocol.protocol_version,
        "preprocess_version": PREPROCESS_VERSION,
        "oscc_ml_version": __version__,
        "amp_active": protocol.training.amp and torch_device.type == "cuda",
        "started_at": _iso(started),
        "command": sys.argv,
        **git_state(PACKAGE_ROOT),
    }
    (run_dir / "config.resolved.yaml").write_text(
        yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False), "utf-8"
    )
    _write_json(run_dir / "environment.json", environment_info(torch_device))
    _write_json(run_dir / "run_info.json", info)

    try:
        seed_everything(run.seed, run.deterministic)
        n_train, n_val, n_test = protocol.smoke.split
        size = protocol.data.input_size
        splits = {
            "train": make_split("train", n_train, run.seed, size),
            "val": make_split("val", n_val, run.seed, size),
            "test": make_split("test", n_test, run.seed, size),
        }
        norm = protocol.data.normalization
        train_ds = PatchDataset(splits["train"], train_transform(protocol.augmentation, norm))
        val_ds = PatchDataset(splits["val"], eval_transform(norm))
        test_ds = PatchDataset(splits["test"], eval_transform(norm))
        loaders = {
            "train": make_loader(train_ds, run.batch_size, True, run.num_workers, run.seed),
            "val": make_loader(val_ds, run.batch_size, False, run.num_workers, run.seed),
            "test": make_loader(test_ds, run.batch_size, False, run.num_workers, run.seed),
        }

        model = build_model(cfg.architecture, pretrained=run.pretrained)
        checkpoint = run_dir / "checkpoints" / "best.pt"
        checkpoint.parent.mkdir()
        result = train(
            model,
            cfg,
            splits["train"],
            loaders["train"],
            splits["val"],
            loaders["val"],
            torch_device,
            checkpoint,
            run_dir / "train_log.csv",
            {
                "architecture": cfg.architecture,
                "preprocess_version": PREPROCESS_VERSION,
                "protocol_version": protocol.protocol_version,
                "dataset_version": run.dataset_version,
            },
        )

        state = torch.load(checkpoint, map_location=torch_device, weights_only=True)
        model.load_state_dict(state["state_dict"])
        predictions_dir = run_dir / "predictions"
        predictions_dir.mkdir()
        metrics: dict[str, Any] = {
            "architecture": cfg.architecture,
            "seed": run.seed,
            "smoke": run.smoke,
            "dataset_version": run.dataset_version,
            "parameter_count": parameter_count(model),
            "best_epoch": result.best_epoch,
            "best_val_auc_image": result.best_val_auc,
            "epochs_run": result.epochs_run,
            "stopped_early": result.stopped_early,
            "training_time_seconds": round(result.training_seconds, 3),
            "decision_threshold": UNCALIBRATED_THRESHOLD,
            "threshold_note": "fixed 0.5, uncalibrated; tau calibration on validation is Phase R3",
            "primary_unit": "image (mean of patch probabilities)",
        }
        for split in ("val", "test"):
            patches, _ = predict(
                model, loaders[split], splits[split], torch_device, info["amp_active"]
            )
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
        _write_json(run_dir / "metrics.json", metrics)
        info.update(status="completed", finished_at=_iso(_utc_now()))
        _write_json(run_dir / "run_info.json", info)
    except BaseException as exc:
        info.update(
            status="failed",
            finished_at=_iso(_utc_now()),
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
        )
        _write_json(run_dir / "run_info.json", info)
        raise
    return run_dir
