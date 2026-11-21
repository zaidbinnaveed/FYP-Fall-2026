"""Regression lock on ``oscc-ml prepare`` (Phase C must not change the dataset pipeline).

The expected hashes were recorded with the ``main`` code at commit 0b45abe (Phase B merged,
before any Phase C change). If any of these tests fail, the manifest, the split, the tiling or
the patch bytes have changed: do not update the hashes without a new PREPROCESS_VERSION and an ADR.

* ``test_synthetic_png_dataset_is_unchanged`` runs everywhere (CI included). Its input is a small
  lossless PNG folder generated from a fixed seed, so no JPEG encoder differences between
  platforms can change it.
ADR-0003 (label-conflict exclusion) adds three keys to dataset.json; they are excluded from the
hash and checked to be zero, because neither input contains a conflicting pair.

* ``test_local_sample_is_unchanged`` runs on the team laptop where the real-image sample
  ``data/sample/`` exists (``oscc-ml make-sample``); it is skipped elsewhere (the data are
  gitignored). It must be identical to the recorded sample fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from oscc_ml.data.prepare import PrepareSettings, prepare, protocol_tiling
from oscc_ml.data.synthetic import synthetic_patch
from oscc_ml.paths import SAMPLE_DIR
from oscc_ml.preprocess import PREPROCESS_VERSION

VOLATILE_KEYS = {"created_at", "seconds"}
# Keys ADR-0003 added to dataset.json (label-conflict exclusion). They are stripped before hashing
# so that every key that existed at 0b45abe must still be byte-identical, and they are checked
# separately (no conflicts in these inputs).
ADR_0003_KEYS = {"n_label_conflict_clusters", "n_label_conflict_images_excluded", "label_conflicts"}


def prepared_fingerprint(root: Path) -> dict[str, str]:
    """SHA-256 of every file of a prepared dataset. CSV line endings are normalized (pandas writes
    the OS line separator); ``dataset.json`` is hashed without its timestamp and duration."""
    out: dict[str, str] = {}
    for path in sorted(root.iterdir()):
        data = path.read_bytes()
        if path.name == "dataset.json":
            info = {
                k: v for k, v in json.loads(data).items() if k not in VOLATILE_KEYS | ADR_0003_KEYS
            }
            data = json.dumps(info, sort_keys=True).encode()
        elif path.suffix == ".csv":
            data = data.replace(b"\r\n", b"\n")
        out[path.name] = hashlib.sha256(data).hexdigest()
    return out


def _tissue_on_glass(rng: np.random.Generator, label: int, width: int, height: int) -> Image.Image:
    tile = 224
    rows, cols = -(-height // tile), -(-width // tile)
    texture = np.concatenate(
        [
            np.concatenate([synthetic_patch(rng, label, tile) for _ in range(cols)], axis=1)
            for _ in range(rows)
        ],
        axis=0,
    )[:height, :width]
    field = rng.random((height // 100 + 2, width // 100 + 2))
    mask = np.kron(field, np.ones((100, 100)))[:height, :width] > 0.4
    canvas = np.full((height, width, 3), 245, dtype=np.uint8)
    canvas[mask] = texture[mask]
    return Image.fromarray(canvas)


def write_png_dataset(root: Path, per_class: int = 20, seed: int = 7) -> Path:
    """Kaggle-like folder (train/val/test x Normal/OSCC) of lossless PNGs, with two publisher-style
    ``aug_`` copies per class and one re-saved original in test/ (a cross-split duplicate)."""
    rng = np.random.default_rng(seed)
    for label, cls in ((0, "Normal"), (1, "OSCC")):
        for i in range(per_class):
            split = "train" if i % 10 < 7 else ("val" if i % 10 < 9 else "test")
            mag = "100x" if i % 2 == 0 else "400x"
            width, height = (600, 460) if i % 3 else (300, 260)  # grid tiling and resize
            image = _tissue_on_glass(rng, label, width, height)
            folder = root / split / cls
            folder.mkdir(parents=True, exist_ok=True)
            image.save(folder / f"{cls}_{mag}_{i + 1}.png")
            if i == 0:
                (root / "test" / cls).mkdir(parents=True, exist_ok=True)
                image.save(root / "test" / cls / f"{cls}_{mag}_{900 + i}.png")
            if i < 2:
                aug = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT).resize((224, 224))
                aug.save(root / "train" / cls / f"aug_{i + 1}_{label}.png")
    return root


# Recorded at 0b45abe with the code on main (see the module docstring).
EXPECTED_SYNTHETIC: dict[str, str] = {
    "images.csv": "f45d10119d68bfdf3099bb288f2460e61f3cdcb2911fac5791ac54951ecfbcd9",
    "manifest.csv": "3fffadfe1114e9107df8268d0df3a2cd289ff44511f193b4fd9f7af0eaf3a236",
    "patches_test.csv": "eeb5b9349c9f136b3117d31c7c2c6def4e1774bce1406d6519b53f2cca055d00",
    "patches_test.u8": "c0d44d054aa2e6e72f559594b15418f6fa5a93ac33263d534614d700519ff02e",
    "patches_train.csv": "8cf79dfd83f89942cc83372f2c56aaec62585dd6272cecae2ae2b3972059d4d9",
    "patches_train.u8": "cda9343869272fdbe854cea09dea38d4160b8fbe4fcc67c66b9cbaaf35378e17",
    "patches_val.csv": "af8a10dd75ab91b5b2009aa21d6a8f623c69c04b532751778fad10cfdcf15f4a",
    "patches_val.u8": "5eb26aefda019bc346897728e20dcb4df1bd08d96d86789985575537abf4b90c",
    "summary.csv": "932ed35e16fad629a898a7a72fae59a27d4f07d6844feaf6883a53732dd508de",
}
# data/sample/ as made on 2026-11-17 (SAMPLE.json listing; 70 files, 60 kept, 2,641 patches).
EXPECTED_SAMPLE: dict[str, str] = {
    "dataset.json": "1b78502d8f4b03f190f4c489d4bf76deaa1abd47ab465207dcebab7ab4964c7b",
    "images.csv": "c4118c5d36d6810fee3ebf0d0b06adb4417cad241c771f29dad54d66c68c157d",
    "manifest.csv": "f9b3eac7b39215ccdcbba7346a9697e721883c4c7449ab0ae8605ecf2ae14b34",
    "patches_test.csv": "87fca4a977240c249c90eedcf2ad869fd5d6824cfd73dd932030d98682b53cc0",
    "patches_test.u8": "af7bf6bfac2cbdf1a3ecd27098dcd549dcd6981eeceb639ca627c5568c5e7b56",
    "patches_train.csv": "b15fcc2d16470c71be8e21475f7aebbc29df2086e85c28c9a5690b03aefafaf0",
    "patches_train.u8": "3f8deeb6d70a1bc1d9995c71936c91b819160e2a8fa340fed4fda7d8f7c51f75",
    "patches_val.csv": "b47be4226dc8451707008a331c48032225cc936fd772faab4578781faf368ea7",
    "patches_val.u8": "014fbb0f1356ec3985e7f4b94c4f75d7c81d7a708b2686b6c20f236ffefba613",
    "summary.csv": "4745fa8c3d86bc90d09c0a6fb5f87b58dd534537eb56f88e8910f144db109c85",
}


def _assert_no_conflicts(root: Path) -> None:
    info = json.loads((root / "dataset.json").read_text("utf-8"))
    assert info["n_label_conflict_clusters"] == {"byte_identical": 0, "near_duplicate": 0}
    assert info["n_label_conflict_images_excluded"] == 0
    assert info["label_conflicts"] == []


def test_preprocess_version_is_unchanged() -> None:
    assert PREPROCESS_VERSION == "pp-0.3.0"


def test_synthetic_png_dataset_is_unchanged(tmp_path: Path) -> None:
    raw = write_png_dataset(tmp_path / "raw")
    out = prepare(
        raw,
        tmp_path / "prepared",
        PrepareSettings(dataset_version="synthetic-regression", tiling=protocol_tiling()),
    )
    _assert_no_conflicts(out)
    fingerprint = prepared_fingerprint(out)
    fingerprint.pop("dataset.json")  # records tmp folder name; manifest + patches carry the data
    assert fingerprint == EXPECTED_SYNTHETIC


@pytest.mark.skipif(
    not (SAMPLE_DIR / "SAMPLE.json").is_file(),
    reason="local real-image sample (data/sample/) not present",
)
def test_local_sample_is_unchanged(tmp_path: Path) -> None:
    out = prepare(
        SAMPLE_DIR,
        tmp_path / "sample",
        PrepareSettings(dataset_version="sample-golden", tiling=protocol_tiling()),
    )
    _assert_no_conflicts(out)
    assert prepared_fingerprint(out) == EXPECTED_SAMPLE
