"""Train every architecture with the shared LR chosen by the sweep (plan R2 baseline: seed 42).

With ``resume=True`` completed runs are skipped and interrupted ones continue from
``checkpoints/last.pt``. A failure in one model does not stop the others; all failures are
reported at the end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from oscc_ml.data.processed import read_dataset_info
from oscc_ml.models.factory import ALL_ARCHITECTURES
from oscc_ml.train.runner import run_training
from oscc_ml.train.sweep import chosen_lr_path
from oscc_ml.utils.io import read_json

logger = logging.getLogger("oscc_ml.train")


class NoChosenLearningRateError(RuntimeError):
    """train-all needs the sweep result (or an explicit --lr)."""


@dataclass
class TrainAllResult:
    completed: list[Path] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def learning_rate_for(
    runs_dir: Path, dataset_version: str, pretrained: bool, lr: float | None
) -> tuple[float, str]:
    """The LR to use and its provenance (``sweep`` only for a protocol-compliant sweep)."""
    if lr is not None:
        return lr, "manual"
    path = chosen_lr_path(runs_dir)
    if not path.is_file():
        raise NoChosenLearningRateError(
            f"{path} not found. Run `oscc-ml sweep` first (or pass --lr, which makes the runs "
            "non-reportable)."
        )
    sweep = read_json(path)
    if sweep.get("dataset_version") != dataset_version:
        raise NoChosenLearningRateError(
            f"the sweep in {path} used dataset {sweep.get('dataset_version')!r}, but training "
            f"uses {dataset_version!r}; run the sweep again for this dataset"
        )
    compliant = bool(sweep.get("protocol_sweep")) and pretrained
    return float(sweep["chosen_lr"]), "sweep" if compliant else "sweep (non-protocol)"


def train_all(
    data_root: Path,
    runs_dir: Path,
    *,
    models: tuple[str, ...] = ALL_ARCHITECTURES,
    seeds: tuple[int, ...] = (42,),
    resume: bool = False,
    device: str = "auto",
    config_dir: Path | None = None,
    lr: float | None = None,
    epochs: int | None = None,
    batch_size: int | None = None,
    pretrained: bool = True,
) -> TrainAllResult:
    dataset_version = str(read_dataset_info(data_root)["dataset_version"])
    chosen_lr, source = learning_rate_for(runs_dir, dataset_version, pretrained, lr)
    logger.info("train-all: LR %g (%s), models %s, seeds %s", chosen_lr, source, models, seeds)
    result = TrainAllResult()
    for seed in seeds:
        for model in models:
            try:
                run_dir = run_training(
                    model,
                    smoke=False,
                    runs_dir=runs_dir,
                    data_root=data_root,
                    seed=seed,
                    device=device,
                    config_dir=config_dir,
                    purpose="train",
                    lr=chosen_lr,
                    lr_source=source,
                    epochs=epochs,
                    batch_size=batch_size,
                    pretrained=pretrained,
                    resume=resume,
                )
                result.completed.append(run_dir)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                logger.exception("training %s seed %d failed", model, seed)
                result.failed.append(f"{model} seed {seed}: {type(exc).__name__}: {exc}")
    return result
