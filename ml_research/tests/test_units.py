"""Fast unit tests: synthetic data, preprocessing, metrics, seeding, schedule, factory."""

from __future__ import annotations

import itertools
import math
import random

import numpy as np
import pandas as pd
import pytest
import torch

from oscc_ml.data.synthetic import make_split
from oscc_ml.eval.metrics import aggregate_to_images, auc_or_none, binary_metrics
from oscc_ml.models.factory import build_model, parameter_count
from oscc_ml.preprocess import IMAGENET_MEAN, IMAGENET_STD, normalize, to_float_tensor
from oscc_ml.train.trainer import lr_lambda, pos_weight_from
from oscc_ml.utils.seeding import make_generator, seed_everything, worker_init_fn


def test_synthetic_split_is_deterministic_and_balanced() -> None:
    a = make_split("train", 16, seed=42)
    b = make_split("train", 16, seed=42)
    c = make_split("train", 16, seed=43)
    assert [r.image_id for r in a] == [r.image_id for r in b]
    assert all(np.array_equal(x.pixels, y.pixels) for x, y in zip(a, b, strict=True))
    assert not np.array_equal(a[0].pixels, c[0].pixels)
    assert sum(r.label for r in a) == 8
    assert a[0].pixels.shape == (224, 224, 3)
    assert a[0].pixels.dtype == np.uint8


def test_splits_never_share_image_ids() -> None:
    ids = [{r.image_id for r in make_split(name, 8, seed=42)} for name in ("train", "val", "test")]
    assert not ids[0] & ids[1]
    assert not ids[0] & ids[2]
    assert not ids[1] & ids[2]


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
            "oscc_probability": [0.2, 0.8, 0.1],
        }
    )
    images = aggregate_to_images(patches).set_index("image_id")
    assert images.loc["a", "oscc_probability"] == pytest.approx(0.5)
    assert images.loc["a", "n_patches"] == 2
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
    # AUC: 6 positive/negative pairs; only (0.3, 0.4) is mis-ordered -> 5/6
    assert m["auc_roc"] == pytest.approx(5 / 6)


def test_auc_is_none_for_single_class() -> None:
    assert auc_or_none([1, 1], [0.2, 0.9]) is None


def test_pos_weight_is_negative_over_positive() -> None:
    records = make_split("train", 8, seed=1)[:6]  # labels 0,1,0,1,0,1
    assert pos_weight_from(records) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="both classes"):
        pos_weight_from([r for r in records if r.label == 1])


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


def test_generator_is_seeded() -> None:
    assert torch.equal(
        torch.randperm(10, generator=make_generator(5)),
        torch.randperm(10, generator=make_generator(5)),
    )


def test_factory_builds_single_logit_resnet50() -> None:
    torch.manual_seed(0)
    model = build_model("resnet50", pretrained=False).eval()
    with torch.no_grad():
        out = model(torch.zeros(2, 3, 224, 224))
    assert out.shape == (2, 1)
    assert parameter_count(model) > 20_000_000


def test_factory_rejects_unknown_architecture() -> None:
    with pytest.raises(ValueError, match="unknown architecture"):
        build_model("alexnet", pretrained=False)
