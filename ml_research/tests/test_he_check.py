"""FR-2.2 H&E colour-profile check: validator, profile file, calibration and offline evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from oscc_ml.cli import app
from oscc_ml.data.synthetic import synthetic_patch
from oscc_ml.preprocess.he_check import (
    FEATURES,
    HE_PROFILE_VERSION,
    NO_STAIN,
    HEProfile,
    calibrate,
    check_he,
    he_features,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "oscc_ml"


def he_like(seed: int, label: int = 1, size: tuple[int, int] = (672, 448)) -> np.ndarray:
    """Pink/purple stained texture (the synthetic histology stand-in used across the tests)."""
    rng = np.random.default_rng(seed)
    width, height = size
    rows = [
        np.concatenate([synthetic_patch(rng, label, 224) for _ in range(width // 224)], axis=1)
        for _ in range(height // 224)
    ]
    return np.concatenate(rows, axis=0)


@pytest.fixture(scope="module")
def profile() -> HEProfile:
    return calibrate([he_features(he_like(s, s % 2)) for s in range(12)])


def test_features_are_defined_and_bounded() -> None:
    feats = he_features(he_like(0))
    assert set(feats) == set(FEATURES)
    assert all(np.isfinite(v) for v in feats.values())
    assert 0.9 <= feats["stained_fraction"] <= 1.0
    assert 250 <= feats["hue_mean"] <= 370  # pink-purple, unwrapped
    assert feats["flat_fraction"] < 0.2  # synthetic blobs clip; real micrographs are ~0


def test_he_like_images_pass(profile: HEProfile) -> None:
    for seed in range(100, 106):
        result = check_he(he_like(seed, seed % 2), profile)
        assert result.passed, result.failed


@pytest.mark.parametrize(
    ("name", "image", "expected"),
    [
        ("white", np.full((300, 400, 3), 255, np.uint8), NO_STAIN),
        ("black solid", np.zeros((300, 400, 3), np.uint8), "flat_fraction"),
        ("pink solid", np.full((300, 400, 3), (200, 120, 200), np.uint8), "flat_fraction"),
        ("green", np.full((300, 400, 3), (40, 160, 60), np.uint8), "hue_mean"),
    ],
)
def test_obvious_non_he_images_fail(
    profile: HEProfile, name: str, image: np.ndarray, expected: str
) -> None:
    result = check_he(image, profile)
    assert not result.passed, name
    assert expected in result.failed


def test_greyscale_copy_of_an_he_image_fails(profile: HEProfile) -> None:
    grey = np.asarray(Image.fromarray(he_like(3)).convert("L").convert("RGB"))
    result = check_he(grey, profile)
    assert not result.passed
    assert "saturation_mean" in result.failed or "hue_concentration" in result.failed


def test_input_validation() -> None:
    with pytest.raises(ValueError, match="uint8"):
        he_features(np.zeros((10, 10), np.uint8))
    with pytest.raises(ValueError, match="at least 5"):
        calibrate([he_features(he_like(0))])


def test_profile_roundtrip_and_version_check(profile: HEProfile, tmp_path: Path) -> None:
    path = tmp_path / "he_profile.json"
    profile.save(path)
    loaded = HEProfile.load(path)
    assert loaded.ranges == profile.ranges
    data = json.loads(path.read_text("utf-8"))
    data["version"] = "he-0.0.1"
    path.write_text(json.dumps(data), "utf-8")
    with pytest.raises(ValueError, match="he-calibrate"):
        HEProfile.load(path)


def test_committed_profile_is_valid() -> None:
    committed = SRC.parents[1] / "configs" / "he_profile.json"
    profile = HEProfile.load(committed)
    assert profile.version == HE_PROFILE_VERSION
    for low, high in profile.ranges.values():
        assert low <= high


def test_prepare_and_training_never_use_the_he_check() -> None:
    """FR-2.2 screens uploads only; the dataset pipeline must not depend on it."""
    for folder in ("data", "train", "models", "eval"):
        for path in (SRC / folder).rglob("*.py"):
            assert "he_check" not in path.read_text("utf-8"), path
    for name in ("pipeline.py", "preprocess/__init__.py"):
        assert "he_check" not in (SRC / name).read_text("utf-8")


def _write_he_folder(root: Path, n: int) -> Path:
    for i in range(n):
        folder = root / ("train" if i % 2 else "test") / ("OSCC" if i % 2 else "Normal")
        folder.mkdir(parents=True, exist_ok=True)
        Image.fromarray(he_like(i, i % 2)).save(folder / f"img_{i}.png")
    Image.fromarray(he_like(99)).save(root / "train" / "OSCC" / "aug_1_1.png")  # skipped
    return root


def test_negative_sets_are_offline_and_sized() -> None:
    pytest.importorskip("skimage")
    from oscc_ml.he_eval import negative_sets

    sets = negative_sets([], seed=42)
    counts = {name: sum(1 for _ in items) for name, items in sets.items()}
    assert counts["solid colours"] == 24
    assert counts["gradients"] == 24
    assert counts["noise"] == 24
    assert counts["screenshots"] == 40
    assert counts["greyscale H&E"] == 0
    assert counts["scikit-image samples"] >= 10


def test_cli_calibrate_and_evaluate(tmp_path: Path) -> None:
    pytest.importorskip("skimage")
    images = _write_he_folder(tmp_path / "he", 12)
    profile = tmp_path / "he_profile.json"
    runner = CliRunner()
    cal = runner.invoke(app, ["he-calibrate", "--images", str(images), "--out", str(profile)])
    assert cal.exit_code == 0, cal.output
    assert json.loads(profile.read_text("utf-8"))["n_calibration_images"] == 12  # aug_ skipped
    out = tmp_path / "report" / "he.md"
    ev = runner.invoke(
        app,
        ["he-evaluate", "--images", str(images), "--profile", str(profile), "--out", str(out),
         "--folds", "3"],
    )  # fmt: skip
    assert ev.exit_code == 0, ev.output
    report = json.loads(out.with_suffix(".json").read_text("utf-8"))
    assert report["n_he"] == 12
    assert report["frr_in_sample"] == 0.0
    assert report["far"]["greyscale H&E"]["n"] == 12
    assert report["far"]["greyscale H&E"]["accepted"] == 0
    assert report["far"]["solid colours"]["accepted"] == 0
    assert "False-accept rate" in out.read_text("utf-8")


def test_cli_evaluate_without_profile_is_refused(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["he-evaluate", "--images", str(tmp_path), "--profile", str(tmp_path / "none.json")],
    )
    assert result.exit_code == 2
    assert "he-calibrate" in result.output
