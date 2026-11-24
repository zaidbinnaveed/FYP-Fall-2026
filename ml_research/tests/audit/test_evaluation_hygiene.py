"""Evaluation hygiene verified in code (FYP-I audit, Phase 1 section C5).

* augmentation is applied to the training split only;
* the LR sweep never builds the test split; a training run builds it only after training ends
  (best checkpoint already fixed by validation AUC);
* tau depends on validation predictions only;
* the metrics agree with an independent implementation (scikit-learn);
* pre-D2 preprocessing parity: the patches stored by `prepare` equal the shared
  `oscc_ml.preprocess` rule applied to the raw image (the inference-service half of the parity
  test is Phase D2; the service does not use `oscc_ml.preprocess` yet).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import torch
import yaml
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from oscc_ml.config import DEFAULT_CONFIG_DIR, load_protocol
from oscc_ml.data.datasets import EvalTransform, TrainTransform
from oscc_ml.data.prepare import PrepareSettings, prepare
from oscc_ml.data.processed import MemmapPatchDataset, open_patches, read_patch_index
from oscc_ml.data.sources import ImageSource, decode
from oscc_ml.data.synthetic import write_synthetic_dataset
from oscc_ml.data.testzip import make_test_zip
from oscc_ml.eval.bootstrap import grouped_bootstrap, point_metrics
from oscc_ml.eval.evaluate import evaluate_run
from oscc_ml.eval.metrics import binary_metrics
from oscc_ml.preprocess import load_rgb, normalize, tile_image, to_float_tensor
from oscc_ml.train import runner
from oscc_ml.utils.io import write_json

# ----------------------------------------------------------------------------- augmentation


def test_eval_transform_is_deterministic_and_train_transform_is_random() -> None:
    protocol = load_protocol()
    norm = protocol.data.normalization
    x = torch.rand(3, 224, 224, generator=torch.Generator().manual_seed(0))
    evaluate = EvalTransform(norm)
    assert torch.equal(evaluate(x), evaluate(x))
    assert torch.equal(evaluate(x), normalize(x, norm.mean, norm.std))
    train = TrainTransform(protocol.augmentation, norm)
    torch.manual_seed(1)
    outputs = [train(x) for _ in range(8)]
    assert any(not torch.equal(outputs[0], o) for o in outputs[1:])


# ----------------------------------------------------------------------------- split access


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
        tmp_path_factory.mktemp("data"), (4, 4, 4), seed=5, dataset_version="synthetic-hygiene"
    )


def _record_split_access(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """Log (event, split, transform) for every dataset built and every training call."""
    log: list[tuple[str, str, str]] = []
    real_dataset, real_train = runner.MemmapPatchDataset, runner.train

    def dataset(root: Path, split: str, transform: Any) -> MemmapPatchDataset:
        log.append(("dataset", split, type(transform).__name__))
        return real_dataset(root, split, transform)

    def train(*args: Any, **kwargs: Any) -> Any:
        log.append(("train-start", "", ""))
        result = real_train(*args, **kwargs)
        log.append(("train-end", "", ""))
        return result

    monkeypatch.setattr(runner, "MemmapPatchDataset", dataset)
    monkeypatch.setattr(runner, "train", train)
    return log


@pytest.mark.parametrize("purpose", ["train", "sweep"])
def test_test_split_is_built_only_after_training_and_never_by_the_sweep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config_dir: Path, data_root: Path, purpose: str
) -> None:
    log = _record_split_access(monkeypatch)
    runner.run_training(
        "efficientnet_b0",
        smoke=False,
        runs_dir=tmp_path,
        data_root=data_root,
        device="cpu",
        config_dir=config_dir,
        purpose=purpose,  # type: ignore[arg-type]
        lr=1e-4,
        lr_source="test",
        epochs=1,
        pretrained=False,
    )
    built = [(split, transform) for event, split, transform in log if event == "dataset"]
    assert ("train", "TrainTransform") in built
    assert all(t == "TrainTransform" for s, t in built if s == "train")
    assert all(t == "EvalTransform" for s, t in built if s in {"val", "test"})
    end = log.index(("train-end", "", ""))
    test_events = [i for i, (e, s, _) in enumerate(log) if e == "dataset" and s == "test"]
    if purpose == "sweep":
        assert not test_events
    else:
        assert test_events
        assert all(i > end for i in test_events)


# ----------------------------------------------------------------------------- tau


def _fake_run(folder: Path, val: pd.DataFrame, test: pd.DataFrame) -> Path:
    (folder / "predictions").mkdir(parents=True)
    val.to_csv(folder / "predictions" / "val_images.csv", index=False)
    test.to_csv(folder / "predictions" / "test_images.csv", index=False)
    write_json(
        folder / "run_info.json",
        {
            "status": "completed",
            "architecture": "efficientnet_b0",
            "seed": 42,
            "dataset_version": "synthetic-hygiene",
        },
    )
    return folder


def _images(seed: int, n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, 2, n)
    labels[:2] = [0, 1]
    probs = np.clip(0.35 * labels + rng.random(n) * 0.65, 0, 1)
    return pd.DataFrame(
        {
            "image_id": [f"i{i}" for i in range(n)],
            "label": labels,
            "oscc_probability": probs,
            "group_id": [f"g{i // 2}" for i in range(n)],
            "magnification": ["100x", "400x"] * (n // 2),
        }
    )


def test_tau_depends_on_validation_only(tmp_path: Path) -> None:
    kwargs = {"n_bootstrap": 20, "warmup": 1, "latency_runs": 1, "measure_gpu": False}
    val, test, other_test = _images(1), _images(2), _images(3)
    a = evaluate_run(_fake_run(tmp_path / "a", val, test), **kwargs)
    b = evaluate_run(_fake_run(tmp_path / "b", val, other_test), **kwargs)
    c = evaluate_run(_fake_run(tmp_path / "c", _images(4), test), **kwargs)
    assert a["threshold"] == b["threshold"]
    assert a["threshold"] != c["threshold"]
    assert a["test"] != b["test"]


# ----------------------------------------------------------------------------- metrics


def test_metrics_agree_with_scikit_learn() -> None:
    rng = np.random.default_rng(7)
    for _ in range(20):
        y = rng.integers(0, 2, 101)
        p = rng.random(101)
        t = float(rng.choice(p))
        pred = (p >= t).astype(int)
        tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
        expected = {
            "accuracy": accuracy_score(y, pred),
            "precision": precision_score(y, pred, zero_division=0),
            "recall": recall_score(y, pred, zero_division=0),
            "specificity": tn / (tn + fp),
            "f1": f1_score(y, pred, zero_division=0),
            "auc_roc": roc_auc_score(y, p),
        }
        ours = point_metrics(y, p, t)
        for key, value in expected.items():
            assert ours[key] == pytest.approx(value, abs=1e-12), key
        binary = binary_metrics(y.tolist(), p.tolist(), t)
        assert binary["confusion_matrix"] == {"tn": tn, "fp": fp, "fn": fn, "tp": tp}
        for key in ("accuracy", "precision", "recall", "f1", "auc_roc"):
            assert binary[key] == pytest.approx(expected[key], abs=1e-12), key


def test_grouped_bootstrap_matches_an_independent_resampler() -> None:
    frame = _images(9, 80)
    threshold = 0.5
    ours = grouped_bootstrap(frame, threshold, n_resamples=200, seed=42)
    # Independent re-implementation of the documented scheme: resample groups with replacement
    # (numpy default_rng(seed).integers), percentile 2.5 / 97.5 of each metric over resamples.
    groups = frame["group_id"].astype(str).to_numpy()
    unique = np.unique(groups)
    members = [np.flatnonzero(groups == g) for g in unique]
    rng = np.random.default_rng(42)
    aucs = []
    for _ in range(200):
        idx = np.concatenate([members[i] for i in rng.integers(0, len(members), len(members))])
        y, p = frame["label"].to_numpy()[idx], frame["oscc_probability"].to_numpy()[idx]
        if 0 < y.sum() < len(y):
            aucs.append(roc_auc_score(y, p))
    assert ours["auc_roc"]["estimate"] == pytest.approx(
        roc_auc_score(frame["label"], frame["oscc_probability"])
    )
    low, high = np.percentile(aucs, [2.5, 97.5])
    assert ours["auc_roc"]["ci_low"] == pytest.approx(low)
    assert ours["auc_roc"]["ci_high"] == pytest.approx(high)


# ----------------------------------------------------------------------------- parity (pre-D2)


def test_stored_patches_equal_the_shared_preprocessing_rule(tmp_path: Path) -> None:
    raw = make_test_zip(tmp_path / "raw.zip", 20, 0, size=(600, 500), duplicate_originals=False)
    root = prepare(raw, tmp_path / "prep", PrepareSettings(dataset_version="synthetic-parity"))
    manifest = pd.read_csv(root / "manifest.csv")
    kept = manifest[manifest["split"] != "excluded"]
    protocol = load_protocol()
    norm = protocol.data.normalization
    checked = 0
    with ImageSource(raw) as source:
        for split in ("train", "val", "test"):
            index = read_patch_index(root, split)
            stored = open_patches(root, split, len(index), 224)
            dataset = MemmapPatchDataset(root, split, EvalTransform(norm))
            for _, row in kept[kept["split"] == split].iterrows():
                rows = index.index[index["image_id"] == row["image_id"]].tolist()
                expected = tile_image(
                    load_rgb(decode(source.read(row["original_path"]))),
                    _tiling(root),
                ).patches
                assert len(rows) == len(expected)
                for i, patch in zip(rows, expected, strict=True):
                    assert np.array_equal(stored[i], patch)
                    direct = normalize(to_float_tensor(patch), norm.mean, norm.std)
                    assert torch.equal(dataset[i][0], direct)
                    checked += 1
    assert checked > 0


def _tiling(root: Path) -> Any:
    import json

    from oscc_ml.preprocess import TilingParams

    settings = json.loads((root / "dataset.json").read_text("utf-8"))["settings"]["tiling"]
    return TilingParams(**settings)
