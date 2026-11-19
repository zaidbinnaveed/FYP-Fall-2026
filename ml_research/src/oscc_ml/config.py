"""Protocol loading and validation.

``configs/protocol.yaml`` holds every shared setting; ``configs/<model>.yaml`` may contain only
``architecture``. The merged, validated result is written to each run directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # .../ml_research
DEFAULT_CONFIG_DIR = PACKAGE_ROOT / "configs"
DEFAULT_RUNS_DIR = PACKAGE_ROOT / "runs"
PROTOCOL_FILE = "protocol.yaml"
ALLOWED_MODEL_KEYS = frozenset({"architecture"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Normalization(_Strict):
    mean: tuple[float, float, float]
    std: tuple[float, float, float]


class Tiling(_Strict):
    resize_if_both_sides_below: int = Field(gt=0)
    patch_size: int = Field(gt=0)
    min_tissue_fraction: float = Field(ge=0, le=1)
    max_patches_per_image: int = Field(gt=0)
    max_tissue_threshold: int = Field(ge=0, le=255)  # ADR-0002 (O5 amendment)


class DataSettings(_Strict):
    input_size: int = Field(gt=0)
    normalization: Normalization
    stain_normalization: Literal["none", "macenko"]
    tiling: Tiling
    num_workers: int = Field(ge=0)


class ColorJitter(_Strict):
    brightness: float = Field(ge=0)
    contrast: float = Field(ge=0)
    saturation: float = Field(ge=0)
    hue: float = Field(ge=0, le=0.5)


class Augmentation(_Strict):
    horizontal_flip: bool
    vertical_flip: bool
    rotate_90: bool
    color_jitter: ColorJitter


class ModelSettings(_Strict):
    pretrained: Literal["imagenet"]
    num_logits: Literal[1]


class Optimizer(_Strict):
    name: Literal["adamw"]
    weight_decay: float = Field(ge=0)
    betas: tuple[float, float]
    lr: float = Field(gt=0)
    lr_grid: tuple[float, ...]


class Scheduler(_Strict):
    name: Literal["cosine"]
    warmup_epochs: int = Field(ge=0)


class EarlyStopping(_Strict):
    monitor: Literal["val_auc"]
    patience: int = Field(gt=0)


class Training(_Strict):
    batch_size: int = Field(gt=0)
    max_epochs: int = Field(gt=0)
    early_stopping: EarlyStopping
    amp: bool
    loss: Literal["bce_with_logits_pos_weight"]
    deterministic: Literal["strict", "warn"]


class Evaluation(_Strict):
    aggregation: Literal["mean_patch_probability"]
    target_recall: float = Field(gt=0, le=1)
    inconclusive_margin: float = Field(ge=0, lt=0.5)


class Smoke(_Strict):
    num_images: int = Field(gt=0)
    split: tuple[int, int, int]
    epochs: int = Field(gt=0)
    batch_size: int = Field(gt=0)
    num_workers: int = Field(ge=0)
    pretrained: bool
    deterministic: Literal["strict", "warn"]

    @model_validator(mode="after")
    def _split_matches(self) -> Smoke:
        if sum(self.split) != self.num_images:
            raise ValueError("smoke.split must add up to smoke.num_images")
        if any(n < 2 or n % 2 for n in self.split):
            raise ValueError("each smoke split needs an even count >= 2 (balanced classes)")
        return self


class Protocol(_Strict):
    protocol_version: str
    seed: int
    data: DataSettings
    augmentation: Augmentation
    model: ModelSettings
    optimizer: Optimizer
    scheduler: Scheduler
    training: Training
    evaluation: Evaluation
    smoke: Smoke


class RunSettings(_Strict):
    """What this particular run actually used.

    ``deviations`` lists every way the run differs from the protocol (smoke mode, random
    initialization, shortened epochs, manual LR, ...). ``protocol_compliant`` is True only when
    there are none; reports refuse non-compliant runs.
    """

    purpose: Literal["smoke", "sweep", "train"]
    smoke: bool
    seed: int
    epochs: int
    batch_size: int
    num_workers: int
    pretrained: bool
    deterministic: Literal["strict", "warn"]
    device: str
    dataset_version: str
    lr: float
    lr_source: str
    deviations: tuple[str, ...] = ()

    @property
    def protocol_compliant(self) -> bool:
        return not self.deviations


class ResolvedConfig(_Strict):
    architecture: str
    protocol: Protocol
    run: RunSettings


class ModelConfigError(ValueError):
    """A per-model config tried to change something other than the architecture."""


def config_dir() -> Path:
    override = os.environ.get("OSCC_ML_CONFIG_DIR")
    return Path(override) if override else DEFAULT_CONFIG_DIR


def _read_yaml(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def load_protocol(directory: Path | None = None) -> Protocol:
    return Protocol.model_validate(_read_yaml((directory or config_dir()) / PROTOCOL_FILE))


def load_model_config(name: str, directory: Path | None = None) -> str:
    """Return the architecture named by ``configs/<name>.yaml``; reject any other key."""
    path = (directory or config_dir()) / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"no model config {path.name} in {path.parent}")
    data = _read_yaml(path)
    extra = set(data) - ALLOWED_MODEL_KEYS
    if extra:
        raise ModelConfigError(
            f"{path.name} may only set 'architecture' (identical protocol, FR-7.6); "
            f"found {sorted(extra)}"
        )
    architecture = data.get("architecture")
    if not isinstance(architecture, str) or not architecture:
        raise ModelConfigError(f"{path.name} must set a non-empty 'architecture'")
    return architecture


def model_config_names(directory: Path | None = None) -> list[str]:
    root = directory or config_dir()
    return sorted(p.stem for p in root.glob("*.yaml") if p.name != PROTOCOL_FILE)


def resolve(
    model: str,
    *,
    smoke: bool,
    seed: int | None,
    device: str,
    dataset_version: str,
    directory: Path | None = None,
    purpose: Literal["smoke", "sweep", "train"] | None = None,
    lr: float | None = None,
    lr_source: str | None = None,
    epochs: int | None = None,
    batch_size: int | None = None,
    pretrained: bool | None = None,
) -> ResolvedConfig:
    """Merge protocol + model config + run options; record every deviation from the protocol."""
    protocol = load_protocol(directory)
    architecture = load_model_config(model, directory)
    deviations: list[str] = []
    if smoke:
        run = RunSettings(
            purpose="smoke",
            smoke=True,
            seed=protocol.seed if seed is None else seed,
            epochs=protocol.smoke.epochs,
            batch_size=protocol.smoke.batch_size,
            num_workers=protocol.smoke.num_workers,
            pretrained=protocol.smoke.pretrained,
            deterministic=protocol.smoke.deterministic,
            device=device,
            dataset_version=dataset_version,
            lr=protocol.optimizer.lr,
            lr_source="protocol placeholder",
            deviations=("smoke run (ADR-0001 G-e)",),
        )
        return ResolvedConfig(architecture=architecture, protocol=protocol, run=run)

    purpose = purpose or "train"
    run_epochs = protocol.training.max_epochs if epochs is None else epochs
    run_batch = protocol.training.batch_size if batch_size is None else batch_size
    run_pretrained = True if pretrained is None else pretrained
    run_lr = protocol.optimizer.lr if lr is None else lr
    run_lr_source = lr_source or ("protocol placeholder" if lr is None else "manual")
    if dataset_version.startswith("synthetic"):
        deviations.append("synthetic dataset")
    if not run_pretrained:
        deviations.append("random initialization instead of ImageNet weights")
    if purpose == "train":
        if run_epochs != protocol.training.max_epochs:
            deviations.append(f"max epochs {run_epochs} instead of {protocol.training.max_epochs}")
        if run_lr_source != "sweep":
            deviations.append(f"learning rate from {run_lr_source}, not from the shared sweep")
    if run_batch > protocol.training.batch_size:
        deviations.append(f"batch size {run_batch} above protocol {protocol.training.batch_size}")
    run = RunSettings(
        purpose=purpose,
        smoke=False,
        seed=protocol.seed if seed is None else seed,
        epochs=run_epochs,
        batch_size=run_batch,
        num_workers=protocol.data.num_workers,
        pretrained=run_pretrained,
        deterministic=protocol.training.deterministic,
        device=device,
        dataset_version=dataset_version,
        lr=run_lr,
        lr_source=run_lr_source,
        deviations=tuple(deviations),
    )
    return ResolvedConfig(architecture=architecture, protocol=protocol, run=run)
