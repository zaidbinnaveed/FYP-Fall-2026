"""Fast unit tests: synthetic/prepared data format, preprocessing, metrics, seeding, schedule."""

from __future__ import annotations

import itertools
import math
import pickle
import random
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from oscc_ml.data.processed import (
    MemmapPatchDataset,
    PatchMeta,
    PatchWriter,
    open_patches,
    read_dataset_info,
    read_patch_index,
)
from oscc_ml.data.synthetic import is_synthetic, write_synthetic_dataset
from oscc_ml.eval.metrics import aggregate_to_images, auc_or_none, binary_metrics
from oscc_ml.preprocess import IMAGENET_MEAN, IMAGENET_STD, normalize, to_float_tensor
from oscc_ml.train.trainer import epoch_generator, lr_lambda, pos_weight_from
from oscc_ml.utils.seeding import make_generator, seed_everything, worker_init_fn


def _identity(x: torch.Tensor) -> torch.Tensor:
    return x


def test_synthetic_dataset_is_deterministic_and_balanced(tmp_path: Path) -> None:
    a = write_synthetic_dataset(tmp_path / "a", (8, 4, 4), seed=7, patches_per_image=(1, 3))
    b = write_synthetic_dataset(tmp_path / "b", (8, 4, 4), seed=7, patches_per_image=(1, 3))
    for split in ("train", "val", "test"):
        assert (a / f"patches_{split}.u8").read_bytes() == (b / f"patches_{split}.u8").read_bytes()
        images = read_patch_index(a, split).drop_duplicates("image_id")
        assert images["label"].sum() * 2 == len(images)
    info = read_dataset_info(a)
    assert is_synthetic(info["dataset_version"])
    assert info["patch_size"] == 224


def test_groups_never_cross_splits(tmp_path: Path) -> None:
    root = write_synthetic_dataset(tmp_path, (8, 4, 4), seed=1)
    groups = [set(read_patch_index(root, s)["group_id"]) for s in ("train", "val", "test")]
    for x, y in itertools.combinations(groups, 2):
        assert not x & y


def test_patch_writer_roundtrip_and_size_check(tmp_path: Path) -> None:
    pixels = np.arange(4 * 4 * 3, dtype=np.uint8).reshape(4, 4, 3)
    with PatchWriter(tmp_path, "train", 4) as writer:
        writer.add(pixels, PatchMeta("img", 0, 1, "g", "src", "100x"))
        writer.add(pixels[::-1].copy(), PatchMeta("img", 1, 1, "g", "src", "100x"))
    array = open_patches(tmp_path, "train", 2, 4)
    assert np.array_equal(array[0], pixels)
    del array
    with pytest.raises(ValueError, match="expected"):
        open_patches(tmp_path, "train", 3, 4)
    with PatchWriter(tmp_path, "val", 4) as writer, pytest.raises(ValueError, match="uint8"):
        writer.add(np.zeros((5, 5, 3), dtype=np.uint8), PatchMeta("x", 0, 0, "g", "s", "m"))


def test_memmap_dataset_pickles_without_the_array(tmp_path: Path) -> None:
    root = write_synthetic_dataset(tmp_path, (4, 4, 4), seed=3)
    ds = MemmapPatchDataset(root, "train", _identity)
    x, y, _ = ds[1]
    assert x.shape == (3, 224, 224)
    assert float(y) == float(ds.index.at[1, "label"])
    clone = pickle.loads(pickle.dumps(ds))  # noqa: S301 - our own object
    assert clone._array is None
    assert torch.equal(clone[1][0], x)


def test_normalize_uses_imagenet_statistics() -> None:
    pixel = np.full((2, 2, 3), 255, dtype=np.uint8)
    out = normalize(to_float_tensor(pixel))
    expected = [(1.0 - m) / s for m, s in zip(IMAGENET_MEAN, IMAGENET_STD, strict=True)]
    assert torch.allclose(out[:, 0, 0], torch.tensor(expected))


def test_to_float_tensor_rejects_wrong_input() -> None:
    with pytest.raises(ValueError, match="uint8"):
        to_float_tensor(np.zeros((4, 4, 3), dtype=np.float32))  # type: ignore[arg-type]


def test_aggregation_is_mean_of_patch_probabilities() -> None:
    patches = pd.DataFrame(
        {
            "image_id": ["a", "a", "b"],
            "patch_index": [0, 1, 0],
            "label": [1, 1, 0],
            "group_id": ["g1", "g1", "g2"],
            "oscc_probability": [0.2, 0.8, 0.1],
        }
    )
    images = aggregate_to_images(patches).set_index("image_id")
    assert images.loc["a", "oscc_probability"] == pytest.approx(0.5)
    assert images.loc["a", "n_patches"] == 2
    assert images.loc["a", "group_id"] == "g1"
    assert images.loc["b", "oscc_probability"] == pytest.approx(0.1)


def test_aggregation_rejects_mixed_labels() -> None:
    patches = pd.DataFrame(
        {"image_id": ["a", "a"], "patch_index": [0, 1], "label": [0, 1], "oscc_probability": [0, 1]}
    )
    with pytest.raises(ValueError, match="different labels"):
        aggregate_to_images(patches)


def test_binary_metrics_known_values() -> None:
    labels = [1, 1, 1, 0, 0]
    probs = [0.9, 0.6, 0.3, 0.4, 0.1]
    m = binary_metrics(labels, probs, threshold=0.5)
    assert m["confusion_matrix"] == {"tn": 2, "fp": 0, "fn": 1, "tp": 2}
    assert m["accuracy"] == pytest.approx(0.8)
    assert m["precision"] == pytest.approx(1.0)
    assert m["recall"] == pytest.approx(2 / 3)
    assert m["f1"] == pytest.approx(0.8)
    assert m["auc_roc"] == pytest.approx(5 / 6)  # one mis-ordered pair out of six


def test_auc_is_none_for_single_class() -> None:
    assert auc_or_none([1, 1], [0.2, 0.9]) is None


def test_pos_weight_is_negative_over_positive() -> None:
    assert pos_weight_from([0, 0, 0, 1]) == pytest.approx(3.0)
    with pytest.raises(ValueError, match="both classes"):
        pos_weight_from([1, 1])


def test_lr_schedule_warms_up_then_decays_to_zero() -> None:
    f = lr_lambda(warmup_epochs=2, total_epochs=10)
    assert f(0) == pytest.approx(0.5)
    assert f(1) == pytest.approx(1.0)
    assert f(2) == pytest.approx(1.0)
    assert f(10) == pytest.approx(0.0, abs=1e-12)
    values = [f(e) for e in range(2, 11)]
    assert all(a >= b for a, b in itertools.pairwise(values))
    assert not any(math.isnan(v) for v in values)


def test_seeding_makes_all_rngs_repeatable() -> None:
    def draw() -> tuple[float, float, float]:
        seed_everything(123, "strict")
        return random.random(), float(np.random.rand()), float(torch.rand(1))  # noqa: NPY002

    assert draw() == draw()
    assert torch.are_deterministic_algorithms_enabled()


def test_worker_init_fn_seeds_python_and_numpy_from_torch() -> None:
    torch.manual_seed(7)
    worker_init_fn(0)
    first = (random.random(), float(np.random.rand()))  # noqa: NPY002
    torch.manual_seed(7)
    worker_init_fn(0)
    assert first == (random.random(), float(np.random.rand()))  # noqa: NPY002


def test_generators_are_seeded_and_differ_per_epoch() -> None:
    assert torch.equal(
        torch.randperm(10, generator=make_generator(5)),
        torch.randperm(10, generator=make_generator(5)),
    )
    assert torch.equal(
        torch.randperm(50, generator=epoch_generator(42, 3)),
        torch.randperm(50, generator=epoch_generator(42, 3)),
    )
    assert not torch.equal(
        torch.randperm(50, generator=epoch_generator(42, 3)),
        torch.randperm(50, generator=epoch_generator(42, 4)),
    )
