"""Identical-protocol guard (FR-7.6) and fidelity of protocol.yaml to SDS Appendix A."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from oscc_ml.config import (
    ALLOWED_MODEL_KEYS,
    DEFAULT_CONFIG_DIR,
    ModelConfigError,
    load_model_config,
    load_protocol,
    model_config_names,
    resolve,
)
from oscc_ml.models.factory import available_architectures


def test_every_model_config_sets_only_the_architecture() -> None:
    names = model_config_names()
    assert names, "expected at least one model config"
    for name in names:
        data = yaml.safe_load((DEFAULT_CONFIG_DIR / f"{name}.yaml").read_text("utf-8"))
        assert set(data) == ALLOWED_MODEL_KEYS, f"{name}.yaml sets {sorted(data)}"


def test_every_model_config_names_a_registered_architecture() -> None:
    for name in model_config_names():
        assert load_model_config(name) in available_architectures()


def test_resolved_protocol_is_identical_across_models() -> None:
    resolved = [
        resolve(n, smoke=False, seed=None, device="cpu", dataset_version="x")
        for n in model_config_names()
    ]
    first = resolved[0]
    for other in resolved[1:]:
        assert other.protocol == first.protocol
        assert other.run == first.run


def test_model_config_with_extra_key_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "protocol.yaml").write_text(
        (DEFAULT_CONFIG_DIR / "protocol.yaml").read_text("utf-8"), "utf-8"
    )
    (tmp_path / "cheat.yaml").write_text("architecture: resnet50\nlr: 0.1\n", "utf-8")
    with pytest.raises(ModelConfigError, match="only set 'architecture'"):
        load_model_config("cheat", tmp_path)


def test_protocol_rejects_unknown_fields(tmp_path: Path) -> None:
    data = yaml.safe_load((DEFAULT_CONFIG_DIR / "protocol.yaml").read_text("utf-8"))
    data["training"]["secret_trick"] = True
    (tmp_path / "protocol.yaml").write_text(yaml.safe_dump(data), "utf-8")
    with pytest.raises(ValueError, match="secret_trick"):
        load_protocol(tmp_path)


def test_protocol_matches_sds_appendix_a() -> None:
    p = load_protocol()
    assert p.seed == 42
    assert p.data.input_size == 224
    assert p.data.normalization.mean == (0.485, 0.456, 0.406)
    assert p.data.normalization.std == (0.229, 0.224, 0.225)
    assert p.augmentation.horizontal_flip
    assert p.augmentation.vertical_flip
    assert p.augmentation.rotate_90
    assert p.model.pretrained == "imagenet"
    assert p.model.num_logits == 1
    assert p.optimizer.name == "adamw"
    assert p.optimizer.weight_decay == 0.05
    assert p.optimizer.lr_grid == (1e-5, 3e-5, 1e-4, 3e-4, 1e-3)
    assert min(p.optimizer.lr_grid) >= 1e-5
    assert max(p.optimizer.lr_grid) <= 1e-3
    assert p.training.batch_size == 32
    assert p.training.max_epochs == 50
    assert p.training.early_stopping.monitor == "val_auc"
    assert p.training.early_stopping.patience == 7
    assert p.training.amp is True
    assert p.training.loss == "bce_with_logits_pos_weight"
    assert p.evaluation.aggregation == "mean_patch_probability"
    assert p.evaluation.target_recall == 0.95  # O2
    assert p.evaluation.inconclusive_margin == 0.05  # O3


def test_smoke_overrides_follow_adr_g_e() -> None:
    cfg = resolve(
        "resnet50", smoke=True, seed=None, device="cpu", dataset_version="synthetic-smoke"
    )
    assert cfg.run.smoke is True
    assert cfg.run.pretrained is False
    assert cfg.run.deterministic == "strict"
    assert cfg.run.seed == 42
    assert cfg.protocol.smoke.num_images == 32


def test_report_and_import_work_without_torch() -> None:
    """At home only a light install is needed to rebuild the report (no torch download)."""
    import subprocess
    import sys

    code = (
        "import sys, oscc_ml.cli, oscc_ml.report, oscc_ml.results; "
        "sys.exit(1 if 'torch' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0  # noqa: S603
