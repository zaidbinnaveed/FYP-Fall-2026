"""Training loop under the shared protocol (SDS Appendix A).

AdamW, BCEWithLogits with ``pos_weight`` from the training class ratio, cosine schedule with
linear warm-up, AMP on CUDA, early stopping on validation image-level AUC (patience from the
protocol) keeping the best checkpoint.

Resumable: ``checkpoints/last.pt`` is written after every epoch with model, optimizer, scheduler,
AMP scaler, early-stopping state, history and RNG states. Shuffling is reseeded per epoch from
(seed, epoch), so a resumed run continues on the same data order.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader

from oscc_ml import observe
from oscc_ml.config import ResolvedConfig
from oscc_ml.data.processed import MemmapPatchDataset
from oscc_ml.eval.metrics import aggregate_to_images, auc_or_none
from oscc_ml.utils.seeding import worker_init_fn

LOG_COLUMNS = ["epoch", "lr", "train_loss", "val_loss", "val_auc", "epoch_seconds"]
logger = logging.getLogger("oscc_ml.train")

Loader = DataLoader[tuple[torch.Tensor, torch.Tensor, int]]


@dataclass
class TrainResult:
    best_epoch: int
    best_val_auc: float | None
    epochs_run: int
    stopped_early: bool
    training_seconds: float
    peak_gpu_memory_mb: float | None
    resumed_from_epoch: int | None = None
    history: list[dict[str, Any]] = field(default_factory=list)


def pos_weight_from(labels: list[int]) -> float:
    """``n_negative / n_positive`` over the training patches (class-weighted loss)."""
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        raise ValueError("training split must contain both classes")
    return negatives / positives


def lr_lambda(warmup_epochs: int, total_epochs: int) -> Callable[[int], float]:
    """Per-epoch multiplier: linear warm-up, then cosine decay to zero."""

    def factor(epoch: int) -> float:
        if warmup_epochs and epoch < warmup_epochs:
            return (epoch + 1) / warmup_epochs
        span = max(1, total_epochs - warmup_epochs)
        progress = min(1.0, (epoch - warmup_epochs) / span)
        return 0.5 * (1.0 + math.cos(math.pi * progress))

    return factor


def epoch_generator(seed: int, epoch: int) -> torch.Generator:
    generator = torch.Generator()
    generator.manual_seed(seed * 1_000 + epoch)
    return generator


def make_loader(
    dataset: MemmapPatchDataset,
    batch_size: int,
    shuffle: bool,
    num_workers: int,
    generator: torch.Generator,
    pin_memory: bool = False,
) -> Loader:
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        generator=generator,
        worker_init_fn=worker_init_fn,
        persistent_workers=False,
        pin_memory=pin_memory,
        drop_last=False,
    )


@torch.no_grad()
def predict(
    model: nn.Module,
    loader: Loader,
    dataset: MemmapPatchDataset,
    device: torch.device,
    use_amp: bool,
    loss_fn: nn.Module | None = None,
) -> tuple[pd.DataFrame, float | None]:
    """Per-patch probabilities (and mean loss if ``loss_fn`` is given)."""
    model.eval()
    rows: list[dict[str, Any]] = []
    total_loss, total_n = 0.0, 0
    index = dataset.index
    for x, y, idx in loader:
        x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
        with torch.autocast(device_type=device.type, enabled=use_amp):
            logits = model(x).squeeze(1)
        logits = logits.float()
        if loss_fn is not None:
            total_loss += float(loss_fn(logits, y)) * len(y)
            total_n += len(y)
        probs = torch.sigmoid(logits).cpu().tolist()
        for i, p in zip(idx.tolist(), probs, strict=True):
            rows.append(
                {
                    "image_id": index.at[i, "image_id"],
                    "patch_index": int(index.at[i, "patch_index"]),
                    "label": int(index.at[i, "label"]),
                    "group_id": index.at[i, "group_id"],
                    "magnification": index.at[i, "magnification"],
                    "oscc_probability": p,
                }
            )
    frame = pd.DataFrame(rows).sort_values(["image_id", "patch_index"]).reset_index(drop=True)
    return frame, (total_loss / total_n if total_n else None)


def _rng_state() -> dict[str, Any]:
    state: dict[str, Any] = {
        "python": random.getstate(),
        "numpy": np.random.get_state(),  # noqa: NPY002
        "torch": torch.get_rng_state(),
    }
    if torch.cuda.is_available():
        state["cuda"] = torch.cuda.get_rng_state_all()
    return state


def _set_rng_state(state: dict[str, Any]) -> None:
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])  # noqa: NPY002
    torch.set_rng_state(state["torch"])
    if "cuda" in state and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["cuda"])


def _fmt(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m{seconds % 60:02d}s"


def train(
    model: nn.Module,
    cfg: ResolvedConfig,
    train_ds: MemmapPatchDataset,
    val_ds: MemmapPatchDataset,
    device: torch.device,
    run_dir: Path,
    checkpoint_meta: dict[str, Any],
    resume: bool = False,
) -> TrainResult:
    protocol, run = cfg.protocol, cfg.run
    use_amp = protocol.training.amp and device.type == "cuda"
    pin = device.type == "cuda"
    ckpt_dir = run_dir / "checkpoints"
    ckpt_dir.mkdir(exist_ok=True)
    best_path, last_path = ckpt_dir / "best.pt", ckpt_dir / "last.pt"
    log_path = run_dir / "train_log.csv"

    model.to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=run.lr,
        weight_decay=protocol.optimizer.weight_decay,
        betas=protocol.optimizer.betas,
    )
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lr_lambda(protocol.scheduler.warmup_epochs, run.epochs)
    )
    pos_weight = torch.tensor([pos_weight_from(train_ds.labels())], device=device)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    scaler = torch.amp.GradScaler(device.type, enabled=use_amp)

    patience = protocol.training.early_stopping.patience
    best_auc: float | None = None
    best_epoch = 0
    stale_epochs = 0
    history: list[dict[str, Any]] = []
    start_epoch = 1
    elapsed_before = 0.0
    resumed_from: int | None = None

    if resume and last_path.is_file():
        state = torch.load(last_path, map_location=device, weights_only=False)
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        scaler.load_state_dict(state["scaler"])
        best_auc, best_epoch = state["best_auc"], state["best_epoch"]
        stale_epochs, history = state["stale_epochs"], state["history"]
        elapsed_before = state["elapsed_seconds"]
        _set_rng_state(state["rng"])
        start_epoch = state["epoch"] + 1
        resumed_from = state["epoch"]
        logger.info("resuming %s from epoch %d", cfg.architecture, resumed_from)
        if state.get("finished"):
            start_epoch = run.epochs + 1  # nothing left to train

    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    val_loader = make_loader(
        val_ds, run.batch_size, False, run.num_workers, epoch_generator(run.seed, 0), pin
    )
    started = time.perf_counter()
    stopped_early = bool(history) and stale_epochs >= patience
    # Observation record (Phase 2A): read-only hooks, switched off entirely by observe.ENABLED.
    obs_dir = run_dir / observe.OBSERVATIONS_DIR
    tracker = observe.GradNormTracker()

    with log_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS)
        writer.writeheader()
        for row in history:  # rewrite rows from a resumed run
            writer.writerow(row)
        handle.flush()

        epoch = start_epoch
        while epoch <= run.epochs and not stopped_early:
            epoch_start = time.perf_counter()
            non_finite, n_batches = 0, 0
            with observe.capture_warnings(observe.ENABLED) as messages:
                lr = optimizer.param_groups[0]["lr"]
                train_loader = make_loader(
                    train_ds,
                    run.batch_size,
                    True,
                    run.num_workers,
                    epoch_generator(run.seed, epoch),
                    pin,
                )
                model.train()
                running, seen = 0.0, 0
                for x, y, _ in train_loader:
                    x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
                    optimizer.zero_grad(set_to_none=True)
                    with torch.autocast(device_type=device.type, enabled=use_amp):
                        logits = model(x).squeeze(1)
                    loss = loss_fn(logits.float(), y)
                    scaler.scale(loss).backward()
                    if observe.ENABLED:
                        tracker.add(model, scaler.get_scale() if scaler.is_enabled() else 1.0)
                    scaler.step(optimizer)
                    scaler.update()
                    loss_value = float(loss.detach())
                    running += loss_value * len(y)
                    seen += len(y)
                    n_batches += 1
                    non_finite += 0 if math.isfinite(loss_value) else 1
                scheduler.step()

                val_patches, val_loss = predict(model, val_loader, val_ds, device, use_amp, loss_fn)
                val_images = aggregate_to_images(val_patches)
                val_auc = auc_or_none(
                    val_images["label"].tolist(), val_images["oscc_probability"].tolist()
                )
                improved = val_auc is not None and (best_auc is None or val_auc > best_auc)
                if improved or not best_path.is_file():
                    # The first epoch always writes best.pt so a run never ends without one.
                    if improved:
                        best_auc = val_auc
                    best_epoch = epoch
                    torch.save(
                        {
                            "state_dict": model.state_dict(),
                            "epoch": epoch,
                            "val_auc": val_auc,
                            **checkpoint_meta,
                        },
                        best_path,
                    )
                stale_epochs = 0 if improved else stale_epochs + 1

                seconds = time.perf_counter() - epoch_start
                row = {
                    "epoch": epoch,
                    "lr": lr,
                    "train_loss": running / max(seen, 1),
                    "val_loss": val_loss,
                    "val_auc": val_auc,
                    "epoch_seconds": round(seconds, 3),
                }
                writer.writerow(row)
                handle.flush()
                history.append(row)
                stopped_early = stale_epochs >= patience
                finished = stopped_early or epoch == run.epochs
                torch.save(
                    {
                        "model": model.state_dict(),
                        "optimizer": optimizer.state_dict(),
                        "scheduler": scheduler.state_dict(),
                        "scaler": scaler.state_dict(),
                        "epoch": epoch,
                        "best_auc": best_auc,
                        "best_epoch": best_epoch,
                        "stale_epochs": stale_epochs,
                        "history": history,
                        "elapsed_seconds": elapsed_before + time.perf_counter() - started,
                        "rng": _rng_state(),
                        "finished": finished,
                    },
                    last_path,
                )
            if observe.ENABLED:
                for message in messages:
                    logger.warning("%s epoch %d: %s", cfg.architecture, epoch, message)
                observe.append_jsonl(
                    obs_dir / observe.EPOCHS_FILE,
                    {
                        **row,
                        **observe.validation_metrics(
                            val_images["label"].tolist(), val_images["oscc_probability"].tolist()
                        ),
                        "val_n_images": len(val_images),
                        "improved": improved,
                        "stale_epochs": stale_epochs,
                        "best_epoch_so_far": best_epoch,
                        "best_val_auc_so_far": best_auc,
                        "n_batches": n_batches,
                        "non_finite_loss_batches": non_finite,
                        "grad_norm": tracker.summary(),
                        "peak_gpu_memory_mb_so_far": observe.peak_gpu_memory_mb(device),
                        "warnings": messages,
                        "first_epoch_after_resume": resumed_from is not None
                        and epoch == start_epoch,
                    },
                )
            remaining = (run.epochs - epoch) * seconds
            logger.info(
                "%s seed %d | epoch %d/%d | loss %.4f | val AUC %s | %.1f s/epoch | ETA <= %s",
                cfg.architecture,
                run.seed,
                epoch,
                run.epochs,
                row["train_loss"],
                "n/a" if val_auc is None else f"{val_auc:.4f}",
                seconds,
                _fmt(remaining),
            )
            epoch += 1

    peak = torch.cuda.max_memory_allocated(device) / 2**20 if device.type == "cuda" else None
    if observe.ENABLED:
        # Totals come from epochs.jsonl (appended after every saved epoch), so epochs from before
        # an interruption are counted too.
        epochs_path = obs_dir / observe.EPOCHS_FILE
        lines = (
            [json.loads(x) for x in epochs_path.read_text("utf-8").splitlines() if x.strip()]
            if epochs_path.is_file()
            else []
        )
        observe.write_json_file(
            obs_dir / observe.SUMMARY_FILE,
            {
                "architecture": cfg.architecture,
                "seed": run.seed,
                "lr": run.lr,
                "max_epochs": run.epochs,
                "patience": patience,
                "epochs_run": len(history),
                "best_epoch": best_epoch,
                "best_val_auc": best_auc,
                "stop_epoch": history[-1]["epoch"] if history else None,
                "stopped_early": stopped_early,
                "stop_reason": observe.stop_reason(
                    stopped_early, patience, len(history), run.epochs
                ),
                "resumed_at_epochs": [x["epoch"] for x in lines if x["first_epoch_after_resume"]],
                "warnings": sum(len(x["warnings"]) for x in lines),
                "non_finite_loss_batches": sum(x["non_finite_loss_batches"] for x in lines),
                "peak_gpu_memory_mb": peak,
                "epoch_metrics_threshold": observe.UNCALIBRATED,
                "checkpoint_rule": "best.pt = epoch with the highest validation image-level AUC",
            },
        )
    return TrainResult(
        best_epoch=best_epoch,
        best_val_auc=best_auc,
        epochs_run=len(history),
        stopped_early=stopped_early,
        training_seconds=elapsed_before + time.perf_counter() - started,
        peak_gpu_memory_mb=peak,
        resumed_from_epoch=resumed_from,
        history=history,
    )
