"""`prepare`, `make-sample` and the leakage test on a synthetic Kaggle-like archive."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image
from typer.testing import CliRunner

from oscc_ml.cli import app
from oscc_ml.data.prepare import PrepareError, PrepareSettings, prepare
from oscc_ml.data.processed import MemmapPatchDataset, read_dataset_info
from oscc_ml.data.sample import SampleError, make_sample
from oscc_ml.data.sources import UnlabelledPathError
from oscc_ml.data.split import LeakageError, check_leakage
from oscc_ml.data.testzip import make_test_zip

PER_CLASS = 24
AUGMENTED = 2
TRAIN_ORIGINALS = sum(1 for i in range(PER_CLASS) if i % 10 < 7) * 2  # both classes


def _identity(x: object) -> object:
    return x


@pytest.fixture(scope="module")
def test_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_test_zip(tmp_path_factory.mktemp("raw") / "kaggle_like.zip", PER_CLASS, AUGMENTED)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory, test_zip: Path) -> Path:
    out = tmp_path_factory.mktemp("processed") / "synthetic-prep"
    return prepare(test_zip, out, PrepareSettings(dataset_version="synthetic-prep"))


def test_augmented_copies_are_removed(prepared: Path) -> None:
    info = read_dataset_info(prepared)
    assert info["n_source_images"] == 2 * PER_CLASS + TRAIN_ORIGINALS * AUGMENTED
    assert info["n_duplicates_removed"] == TRAIN_ORIGINALS * AUGMENTED
    assert info["n_kept_images"] == 2 * PER_CLASS
    manifest = pd.read_csv(prepared / "manifest.csv")
    removed = manifest[manifest["is_augmented_copy"]]
    assert removed["original_path"].str.contains("/aug_").all()
    assert (removed["split"] == "excluded").all()
    kept = manifest[manifest["split"] != "excluded"]
    assert not kept["original_path"].str.contains("/aug_").any()


def test_split_is_grouped_stratified_70_15_15(prepared: Path) -> None:
    images = pd.read_csv(prepared / "images.csv")
    fractions = images["split"].value_counts(normalize=True)
    assert abs(fractions["train"] - 0.70) <= 0.10
    assert abs(fractions["val"] - 0.15) <= 0.10
    assert abs(fractions["test"] - 0.15) <= 0.10
    for _, frame in images.groupby("split"):
        assert set(frame["label"]) == {0, 1}
    assert images.groupby("group_id")["split"].nunique().max() == 1


def test_manifest_has_the_planned_columns(prepared: Path) -> None:
    columns = set(pd.read_csv(prepared / "manifest.csv", nrows=1).columns)
    for name in (
        "image_id",
        "source",
        "original_path",
        "label",
        "group_id",
        "magnification",
        "width",
        "height",
        "sha256",
        "phash",
        "is_augmented_copy",
        "split",
    ):
        assert name in columns
    info = read_dataset_info(prepared)
    assert info["leakage_test"] == "passed"
    assert "pHash similarity" in info["grouping"]
    assert set(pd.read_csv(prepared / "summary.csv")["magnification"]) == {"100x", "400x"}


def test_patches_match_the_index_and_load(prepared: Path) -> None:
    info = read_dataset_info(prepared)
    for split in ("train", "val", "test"):
        index = pd.read_csv(prepared / f"patches_{split}.csv")
        assert len(index) == info["counts"][split]["patches"]
        assert (prepared / f"patches_{split}.u8").stat().st_size == len(index) * 224 * 224 * 3
    dataset = MemmapPatchDataset(prepared, "train", _identity)
    x, _, _ = dataset[0]
    assert x.shape == (3, 224, 224)


def test_rerun_is_skipped_and_changed_settings_are_refused(prepared: Path, test_zip: Path) -> None:
    created = read_dataset_info(prepared)["created_at"]
    prepare(test_zip, prepared, PrepareSettings(dataset_version="synthetic-prep"))
    assert read_dataset_info(prepared)["created_at"] == created
    with pytest.raises(PrepareError, match="different input or settings"):
        prepare(
            test_zip, prepared, PrepareSettings(dataset_version="synthetic-prep", group_threshold=8)
        )


def test_folder_input_gives_the_same_dataset(
    prepared: Path, test_zip: Path, tmp_path: Path
) -> None:
    folder = tmp_path / "extracted"
    with zipfile.ZipFile(test_zip) as archive:
        archive.extractall(folder)
    out = prepare(
        folder, tmp_path / "from_folder", PrepareSettings(dataset_version="synthetic-prep")
    )
    a = pd.read_csv(prepared / "images.csv").sort_values("image_id").reset_index(drop=True)
    b = pd.read_csv(out / "images.csv").sort_values("image_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def _zip_of(path: Path, members: dict[str, Image.Image]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, image in members.items():
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            archive.writestr(name, buffer.getvalue())
    return path


def test_unlabelled_paths_fail_loudly(tmp_path: Path) -> None:
    image = Image.fromarray(np.zeros((50, 50, 3), np.uint8))
    archive = _zip_of(tmp_path / "bad.zip", {"data/train/mystery/a.png": image})
    with pytest.raises(UnlabelledPathError, match="never guessed"):
        prepare(archive, tmp_path / "out")


def test_the_same_image_under_both_labels_is_refused(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    members = {}
    for i in range(25):
        img = Image.fromarray(rng.integers(0, 255, (64, 64, 3), dtype=np.uint8))
        members[f"d/Normal/n{i}.png"] = img
        members[f"d/OSCC/o{i}.png"] = Image.fromarray(
            rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
        )
    members["d/OSCC/copy.png"] = members["d/Normal/n0.png"]
    with pytest.raises(PrepareError, match="both labels"):
        prepare(_zip_of(tmp_path / "conflict.zip", members), tmp_path / "out")


def test_leakage_test_fails_loudly_on_injected_leaks(prepared: Path) -> None:
    manifest = pd.read_csv(prepared / "manifest.csv")
    kept = manifest[manifest["split"] != "excluded"].copy()
    check_leakage(kept)  # the real split is clean
    leaked = kept.copy()
    victim = leaked.index[leaked["split"] == "train"][0]
    other = leaked.index[leaked["split"] == "test"][0]
    leaked.loc[victim, "group_id"] = leaked.loc[other, "group_id"]
    with pytest.raises(LeakageError, match="group_id"):
        check_leakage(leaked)
    duplicated = kept.copy()
    duplicated.loc[victim, "sha256"] = duplicated.loc[other, "sha256"]
    with pytest.raises(LeakageError, match="sha256"):
        check_leakage(duplicated)


def test_make_sample_reads_only_the_chosen_members(test_zip: Path, tmp_path: Path) -> None:
    out = tmp_path / "sample"
    record = make_sample(test_zip, out, per_class=10)
    assert len(record["files"]) == 20
    images = [p for p in out.rglob("*.jpg")]
    assert len(images) == 20
    assert sum("/Normal/" in p.as_posix() for p in images) == 10
    assert json.loads((out / "SAMPLE.json").read_text("utf-8"))["per_class"] == 10
    again = make_sample(test_zip, tmp_path / "sample2", per_class=10)
    assert [f["path"] for f in again["files"]] == [f["path"] for f in record["files"]]


def test_make_sample_refuses_incomplete_downloads(tmp_path: Path) -> None:
    partial = tmp_path / "download.zip"
    partial.write_bytes(b"PK\x03\x04 truncated")
    with pytest.raises(SampleError, match="not a complete zip"):
        make_sample(partial, tmp_path / "s", per_class=5)
    result = CliRunner().invoke(
        app, ["make-sample", "--zip", str(partial), "--out", str(tmp_path / "s")]
    )
    assert result.exit_code == 2
