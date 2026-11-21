"""Shared learning-rate sweep (SDS Appendix A; plan decision O1, primary analysis).

Every model is trained briefly with every LR in ``protocol.optimizer.lr_grid``. The chosen LR is
the one with the highest *mean over models* of each short run's best validation image-level AUC
(ties -> the lower LR), and it is applied to every model. Each model's own best LR is recorded too,
for the O1 secondary analysis. The sweep uses validation data only; test data are never read.

Output: ``runs/sweep/chosen_lr.json`` (plus one run folder per trial in ``runs/sweep/``).
Completed trials are skipped, so an interrupted sweep continues where it stopped.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from oscc_ml.catalog import ALL_ARCHITECTURES, is_synthetic
from oscc_ml.config import load_protocol
from oscc_ml.data.processed import read_dataset_info
from oscc_ml.paths import SWEEP_DIR_NAME
from oscc_ml.train.runner import run_training
from oscc_ml.utils.io import iso, read_json, utc_now, write_json

DEFAULT_SWEEP_EPOCHS = 5
CHOSEN_LR_FILE = "chosen_lr.json"
SELECTION_RULE = (
    "highest mean over models of the best validation image-level AUC within each short run; "
    "ties -> lower learning rate"
)
logger = logging.getLogger("oscc_ml.train")


class SweepIncompleteError(RuntimeError):
    """A trial failed or produced no validation AUC, so no LR can be chosen."""


def chosen_lr_path(runs_dir: Path) -> Path:
    return runs_dir / SWEEP_DIR_NAME / CHOSEN_LR_FILE


def select_lr(table: dict[float, dict[str, float]]) -> tuple[float, dict[float, float]]:
    means = {lr: sum(aucs.values()) / len(aucs) for lr, aucs in table.items()}
    best = max(means.values())
    chosen = min(lr for lr, m in means.items() if math.isclose(m, best, abs_tol=1e-12))
    return chosen, means


def run_sweep(
    data_root: Path,
    runs_dir: Path,
    *,
    epochs: int = DEFAULT_SWEEP_EPOCHS,
    models: tuple[str, ...] = ALL_ARCHITECTURES,
    seed: int | None = None,
    device: str = "auto",
    config_dir: Path | None = None,
    pretrained: bool = True,
) -> dict[str, Any]:
    protocol = load_protocol(config_dir)
    dataset_version = str(read_dataset_info(data_root)["dataset_version"])
    sweep_dir = runs_dir / SWEEP_DIR_NAME
    table: dict[float, dict[str, float]] = {}
    trials: list[dict[str, Any]] = []
    failures: list[str] = []
    for lr in protocol.optimizer.lr_grid:
        for model in models:
            label = f"{model} lr={lr:g}"
            try:
                run_dir = run_training(
                    model,
                    smoke=False,
                    runs_dir=sweep_dir,
                    data_root=data_root,
                    seed=seed,
                    device=device,
                    config_dir=config_dir,
                    purpose="sweep",
                    lr=lr,
                    lr_source="sweep grid",
                    epochs=epochs,
                    pretrained=pretrained,
                    resume=True,
                )
            except Exception as exc:  # keep going; report every failed trial at the end
                logger.exception("sweep trial %s failed", label)
                failures.append(f"{label}: {type(exc).__name__}: {exc}")
                continue
            auc = read_json(run_dir / "metrics.json").get("best_val_auc_image")
            trials.append({"model": model, "lr": lr, "best_val_auc": auc, "run": run_dir.name})
            if auc is None:
                failures.append(f"{label}: no validation AUC (single-class validation split?)")
            else:
                table.setdefault(lr, {})[model] = float(auc)

    if failures:
        raise SweepIncompleteError("sweep incomplete:\n  " + "\n  ".join(failures))

    chosen, means = select_lr(table)

    def best_lr(model: str) -> float:
        # highest validation AUC for this model; ties -> lower LR
        return max(protocol.optimizer.lr_grid, key=lambda lr: (table[lr][model], -lr))

    per_model_best = {model: best_lr(model) for model in models}
    protocol_sweep = pretrained and not is_synthetic(dataset_version)
    result: dict[str, Any] = {
        "chosen_lr": chosen,
        "selection_rule": SELECTION_RULE,
        "lr_grid": list(protocol.optimizer.lr_grid),
        "epochs_per_trial": epochs,
        "models": list(models),
        "seed": protocol.seed if seed is None else seed,
        "dataset_version": dataset_version,
        "pretrained": pretrained,
        "protocol_sweep": protocol_sweep,
        "mean_val_auc_by_lr": {f"{lr:g}": means[lr] for lr in sorted(means)},
        "val_auc_table": {f"{lr:g}": table[lr] for lr in sorted(table)},
        "best_lr_per_model": {m: lr for m, lr in per_model_best.items()},
        "trials": trials,
        "created_at": iso(utc_now()),
    }
    write_json(chosen_lr_path(runs_dir), result)
    logger.info("sweep complete: chosen LR %g (mean val AUC %.4f)", chosen, means[chosen])
    return result
