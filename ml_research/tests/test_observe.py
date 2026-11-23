"""Phase 2A PR (B): the observation record changes nothing, training never reads the test split,
and evaluate's test predictions equal a direct forward pass of the best checkpoint."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch
import yaml

from oscc_ml import observe
from oscc_ml.config import DEFAULT_CONFIG_DIR
from oscc_ml.data import processed
from oscc_ml.data.synthetic import write_synthetic_dataset
from oscc_ml.eval.evaluate import evaluate_run
from oscc_ml.models.factory import build_model
from oscc_ml.preprocess import IMAGENET_MEAN, IMAGENET_STD, normalize, to_float_tensor
from oscc_ml.train.runner import run_training

ARCH = "efficientnet_b0"


@pytest.fixture(scope="module")
def config_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("configs")
    for path in DEFAULT_CONFIG_DIR.glob("*.yaml"):
        shutil.copy(path, folder / path.name)
    protocol = yaml.safe_load((folder / "protocol.yaml").read_text("utf-8"))
    protocol["data"]["num_workers"] = 0
    (folder / "protocol.yaml").write_text(yaml.safe_dump(protocol), "utf-8")
    return folder


@pytest.fixture(scope="module")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_synthetic_dataset(
        tmp_path_factory.mktemp("data"),
        (8, 8, 8),
        seed=3,
        patches_per_image=(1, 2),
        dataset_version="synthetic-observe",
    )


def _train(runs: Path, config_dir: Path, data_root: Path) -> Path:
    return run_training(
        ARCH,
        smoke=False,
        runs_dir=runs,
        data_root=data_root,
        device="cpu",
        config_dir=config_dir,
        purpose="train",
        lr=1e-3,
        lr_source="test",
        epochs=3,
        pretrained=False,
    )


def _state_digest(path: Path) -> str:
    state = torch.load(path, map_location="cpu", weights_only=True)["state_dict"]
    digest = hashlib.sha256()
    for key in sorted(state):
        digest.update(key.encode() + state[key].numpy().tobytes())
    return digest.hexdigest()


def _log_without_timing(run: Path) -> list[dict[str, str]]:
    with (run / "train_log.csv").open(encoding="utf-8") as handle:
        return [
            {k: v for k, v in r.items() if k != "epoch_seconds"} for r in csv.DictReader(handle)
        ]


@pytest.fixture(scope="module")
def pair(
    tmp_path_factory: pytest.TempPathFactory, config_dir: Path, data_root: Path
) -> tuple[Path, Path]:
    """The same run with the observation record on, then off."""
    on = _train(tmp_path_factory.mktemp("on"), config_dir, data_root)
    observe.ENABLED = False
    try:
        off = _train(tmp_path_factory.mktemp("off"), config_dir, data_root)
    finally:
        observe.ENABLED = True
    return on, off


def test_recording_changes_nothing(pair: tuple[Path, Path]) -> None:
    on, off = pair
    assert (on / "checkpoints/best.pt").read_bytes() == (off / "checkpoints/best.pt").read_bytes()
    assert _state_digest(on / "checkpoints/best.pt") == _state_digest(off / "checkpoints/best.pt")
    for name in ("val_patches.csv", "val_images.csv"):
        assert (on / "predictions" / name).read_bytes() == (off / "predictions" / name).read_bytes()
    assert _log_without_timing(on) == _log_without_timing(off)
    timing = {"training_time_seconds", "mean_epoch_seconds"}
    m_on, m_off = (json.loads((d / "metrics.json").read_text("utf-8")) for d in (on, off))
    assert {k: v for k, v in m_on.items() if k not in timing} == {
        k: v for k, v in m_off.items() if k not in timing
    }
    assert (on / "observations" / "epochs.jsonl").is_file()
    assert not (off / "observations").exists()


def test_epoch_record_is_complete(pair: tuple[Path, Path]) -> None:
    on, _ = pair
    lines = [json.loads(x) for x in (on / "observations/epochs.jsonl").read_text().splitlines()]
    assert [x["epoch"] for x in lines] == [1, 2, 3]
    needed = {
        "lr",
        "train_loss",
        "val_loss",
        "val_auc",
        "val_recall_at_0.5",
        "val_specificity_at_0.5",
        "val_f1_at_0.5",
        "grad_norm",
        "epoch_seconds",
        "peak_gpu_memory_mb_so_far",
        "warnings",
        "non_finite_loss_batches",
        "improved",
    }
    for line in lines:
        assert needed <= set(line)
        assert line["grad_norm"]["n"] == line["n_batches"] > 0
    summary = json.loads((on / "observations/training_summary.json").read_text())
    log = _log_without_timing(on)
    best = max(log, key=lambda r: (float(r["val_auc"]), -int(r["epoch"])))
    assert summary["best_epoch"] == int(best["epoch"])
    assert summary["epochs_run"] == 3
    assert summary["stop_reason"].startswith("reached the maximum number of epochs")


def test_training_never_reads_the_test_split_and_evaluate_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config_dir: Path, data_root: Path
) -> None:
    opened: list[str] = []
    real_index, real_patches = processed.read_patch_index, processed.open_patches

    def index(root: Path, split: str) -> Any:
        opened.append(split)
        return real_index(root, split)

    def patches(root: Path, split: str, n: int, size: int) -> Any:
        opened.append(split)
        return real_patches(root, split, n, size)

    monkeypatch.setattr(processed, "read_patch_index", index)
    monkeypatch.setattr(processed, "open_patches", patches)
    run = _train(tmp_path / "runs", config_dir, data_root)
    assert "test" not in opened
    assert {"train", "val"} <= set(opened)
    assert not (run / "predictions" / "test_images.csv").exists()
    opened.clear()
    evaluate_run(
        run,
        n_bootstrap=20,
        warmup=1,
        latency_runs=1,
        measure_gpu=False,
        config_dir=config_dir,
        device="cpu",
    )
    assert set(opened) == {"test"}


def test_evaluate_predictions_equal_a_direct_forward_pass(
    tmp_path: Path, config_dir: Path, data_root: Path
) -> None:
    run = _train(tmp_path / "runs", config_dir, data_root)
    ev = evaluate_run(
        run,
        n_bootstrap=20,
        warmup=1,
        latency_runs=1,
        measure_gpu=False,
        config_dir=config_dir,
        device="cpu",
    )
    assert ev["test_predictions"]["source"] == "checkpoints/best.pt"
    # independent: no DataLoader, no predict(); one patch at a time
    model = build_model(ARCH, pretrained=False)
    model.load_state_dict(
        torch.load(run / "checkpoints/best.pt", map_location="cpu", weights_only=True)["state_dict"]
    )
    model.eval()
    index = processed.read_patch_index(data_root, "test")
    pixels = processed.open_patches(data_root, "test", len(index), 224)
    probs: dict[str, list[float]] = {}
    with torch.no_grad():
        for i, row in index.iterrows():
            x = normalize(to_float_tensor(np.array(pixels[i])), IMAGENET_MEAN, IMAGENET_STD)
            p = float(torch.sigmoid(model(x.unsqueeze(0)).squeeze()))
            probs.setdefault(str(row["image_id"]), []).append(p)
    with (run / "predictions/test_images.csv").open(encoding="utf-8") as handle:
        saved = {r["image_id"]: float(r["oscc_probability"]) for r in csv.DictReader(handle)}
    assert set(saved) == set(probs)
    for image_id, values in probs.items():
        assert saved[image_id] == pytest.approx(float(np.mean(values)), abs=1e-5)
    # the evaluation's extra records
    assert (run / "val_threshold_curve.csv").is_file()
    cm = ev["test_at_tau"]["confusion_matrix"]
    assert sum(cm.values()) == len(saved)
    assert len(ev["test_at_tau"]["false_positives"]) == cm["fp"]
    assert len(ev["test_at_tau"]["false_negatives"]) == cm["fn"]
    assert 0.0 <= ev["calibration"]["test"]["ece"] <= 1.0


def test_evaluate_refuses_a_different_dataset(
    tmp_path: Path, config_dir: Path, data_root: Path
) -> None:
    run = _train(tmp_path / "runs", config_dir, data_root)
    other = write_synthetic_dataset(
        tmp_path / "other", (4, 4, 4), seed=9, dataset_version="synthetic-other"
    )
    with pytest.raises(ValueError, match="trained on"):
        evaluate_run(
            run,
            n_bootstrap=20,
            warmup=1,
            latency_runs=1,
            measure_gpu=False,
            config_dir=config_dir,
            data_root=other,
            device="cpu",
        )


def test_capture_warnings_collects_and_deduplicates() -> None:
    import warnings

    with observe.capture_warnings() as messages:
        warnings.warn("same", UserWarning, stacklevel=1)
        warnings.warn("same", UserWarning, stacklevel=1)
        warnings.warn("other", RuntimeWarning, stacklevel=1)
    assert messages == ["RuntimeWarning: other", "UserWarning: same"]


def test_capture_warnings_is_exception_safe(caplog: pytest.LogCaptureFixture) -> None:
    """An exception inside the block restores the global warning state, keeps the warnings raised
    before it (and logs them) and propagates unchanged."""
    import warnings

    filters_before = list(warnings.filters)
    show_before = warnings.showwarning
    captured: list[str] = []

    def crash() -> None:
        nonlocal captured
        with observe.capture_warnings() as messages:
            captured = messages
            warnings.warn("before the crash", UserWarning, stacklevel=1)
            _ = 1 / 0

    with caplog.at_level("WARNING", logger="oscc_ml.observe"), pytest.raises(ZeroDivisionError):
        crash()
    assert warnings.filters == filters_before
    assert warnings.showwarning is show_before
    assert captured == ["UserWarning: before the crash"]
    assert "before the crash" in caplog.text


def test_capture_warnings_disabled_touches_nothing() -> None:
    import warnings

    show_before = warnings.showwarning
    with observe.capture_warnings(enabled=False) as messages:
        assert warnings.showwarning is show_before
    assert messages == []
