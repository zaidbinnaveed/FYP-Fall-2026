"""Training loop under the shared protocol (SDS Appendix A).

AdamW, BCEWithLogits with ``pos_weight`` from the training class ratio, cosine schedule with
linear warm-up, AMP on CUDA, early stopping on validation image-level AUC with the best checkpoint
kept. The same loop serves smoke runs and real runs; only the resolved run settings differ.
"""

from __future__ import annotations

import csv
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader

from oscc_ml.config import ResolvedConfig
from oscc_ml.data.datasets import PatchDataset
from oscc_ml.data.synthetic import PatchRecord
from oscc_ml.eval.metrics import aggregate_to_images, auc_or_none
from oscc_ml.utils.seeding import make_generator, worker_init_fn

LOG_COLUMNS = ["epoch", "lr", "train_loss", "val_loss", "val_auc", "epoch_seconds"]


@dataclass
class TrainResult:
    best_epoch: int
    best_val_auc: float | None
    epochs_run: int
    stopped_early: bool
    training_seconds: float
    history: list[dict[str, Any]] = field(default_factory=list)


def pos_weight_from(records: Sequence[PatchRecord]) -> float:
    """``n_negative / n_positive`` over the training patches (class-weighted loss)."""
    positives = sum(r.label for r in records)
    negatives = len(records) - positives
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


def make_loader(
    dataset: PatchDataset, batch_size: int, shuffle: bool, num_workers: int, seed: int
) -> DataLoader[tuple[torch.Tensor, torch.Tensor, int]]:
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        generator=make_generator(seed),
        worker_init_fn=worker_init_fn,
        persistent_workers=False,
        drop_last=False,
    )


@torch.no_grad()
def predict(
    model: nn.Module,
    loader: DataLoader[tuple[torch.Tensor, torch.Tensor, int]],
    records: Sequence[PatchRecord],
    device: torch.device,
    use_amp: bool,
    loss_fn: nn.Module | None = None,
) -> tuple[pd.DataFrame, float | None]:
    """Per-patch probabilities (and mean loss if ``loss_fn`` is given)."""
    model.eval()
    rows: list[dict[str, Any]] = []
    total_loss, total_n = 0.0, 0
    for x, y, idx in loader:
        x, y = x.to(device), y.to(device)
        with torch.autocast(device_type=device.type, enabled=use_amp):
            logits = model(x).squeeze(1)
        logits = logits.float()
        if loss_fn is not None:
            total_loss += float(loss_fn(logits, y)) * len(y)
            total_n += len(y)
        probs = torch.sigmoid(logits).cpu().tolist()
        for i, p in zip(idx.tolist(), probs, strict=True):
            rec = records[i]
            rows.append(
                {
                    "image_id": rec.image_id,
                    "patch_index": rec.patch_index,
                    "label": rec.label,
                    "oscc_probability": p,
                }
            )
    frame = pd.DataFrame(rows).sort_values(["image_id", "patch_index"]).reset_index(drop=True)
    return frame, (total_loss / total_n if total_n else None)


def train(
    model: nn.Module,
    cfg: ResolvedConfig,
    train_records: Sequence[PatchRecord],
    train_loader: DataLoader[tuple[torch.Tensor, torch.Tensor, int]],
    val_records: Sequence[PatchRecord],
    val_loader: DataLoader[tuple[torch.Tensor, torch.Tensor, int]],
    device: torch.device,
    checkpoint_path: Path,
    log_path: Path,
    checkpoint_meta: dict[str, Any],
) -> TrainResult:
    protocol, run = cfg.protocol, cfg.run
    use_amp = protocol.training.amp and device.type == "cuda"

    model.to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=protocol.optimizer.lr,
        weight_decay=protocol.optimizer.weight_decay,
        betas=protocol.optimizer.betas,
    )
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lr_lambda(protocol.scheduler.warmup_epochs, run.epochs)
    )
    pos_weight = torch.tensor([pos_weight_from(train_records)], device=device)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    scaler = torch.amp.GradScaler(device.type, enabled=use_amp)

    patience = protocol.training.early_stopping.patience
    best_auc: float | None = None
    best_epoch = 0
    epochs_without_improvement = 0
    history: list[dict[str, Any]] = []
    started = time.perf_counter()

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS)
        writer.writeheader()

        for epoch in range(1, run.epochs + 1):
            epoch_start = time.perf_counter()
            lr = optimizer.param_groups[0]["lr"]
            model.train()
            running, seen = 0.0, 0
            for x, y, _ in train_loader:
                x, y = x.to(device), y.to(device)
                optimizer.zero_grad(set_to_none=True)
                with torch.autocast(device_type=device.type, enabled=use_amp):
                    logits = model(x).squeeze(1)
                loss = loss_fn(logits.float(), y)
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
                running += float(loss.detach()) * len(y)
                seen += len(y)
            scheduler.step()

            val_patches, val_loss = predict(
                model, val_loader, val_records, device, use_amp, loss_fn
            )
            val_images = aggregate_to_images(val_patches)
            val_auc = auc_or_none(
                val_images["label"].tolist(), val_images["oscc_probability"].tolist()
            )

            improved = val_auc is not None and (best_auc is None or val_auc > best_auc)
            if improved or epoch == 1:
                # Epoch 1 always writes a checkpoint so a run never ends without one.
                if improved:
                    best_auc = val_auc
                    epochs_without_improvement = 0
                best_epoch = epoch
                torch.save(
                    {
                        "state_dict": model.state_dict(),
                        "epoch": epoch,
                        "val_auc": val_auc,
                        **checkpoint_meta,
                    },
                    checkpoint_path,
                )
            if not improved:
                epochs_without_improvement += 1

            row = {
                "epoch": epoch,
                "lr": lr,
                "train_loss": running / max(seen, 1),
                "val_loss": val_loss,
                "val_auc": val_auc,
                "epoch_seconds": round(time.perf_counter() - epoch_start, 3),
            }
            writer.writerow(row)
            handle.flush()
            history.append(row)

            if epochs_without_improvement >= patience:
                return TrainResult(
                    best_epoch, best_auc, epoch, True, time.perf_counter() - started, history
                )

    return TrainResult(
        best_epoch, best_auc, run.epochs, False, time.perf_counter() - started, history
    )
