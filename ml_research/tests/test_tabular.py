"""Phase T: tabular features (known answers on synthetic images), streamed extraction
(byte-identical re-runs, manifest equality, integrity failures) and the classifiers end to end."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from oscc_ml.tabular import CUES_FILE, FEATURES_FILE
from oscc_ml.tabular import features as feat
from oscc_ml.tabular.extract import ExtractionError, check_table, extract


def _uniform(rgb: tuple[int, int, int], size: int = 64) -> np.ndarray:
    return np.full((size, size, 3), rgb, dtype=np.uint8)


def _from_od(concentrations: tuple[float, float, float], size: int = 32) -> np.ndarray:
    """RGB pixels whose optical density is the given (H, E, residual) mix of the stain vectors."""
    od = np.asarray(concentrations) @ feat.RGB_FROM_HED
    rgb = np.clip(np.round(256.0 * 10.0 ** (-od) - 1.0), 0, 255)
    return np.full((size, size, 3), rgb, dtype=np.uint8)


# ---------------------------------------------------------------- known answers ----------------


def test_colour_of_a_uniform_image() -> None:
    pixels = _uniform((200, 100, 150)).reshape(-1, 3)
    out = feat.colour_features(pixels)
    assert out["rgb_r_mean"] == 200
    assert out["rgb_g_mean"] == 100
    assert out["rgb_b_mean"] == 150
    assert out["rgb_r_std"] == 0
    assert out["hsv_v_mean"] == 200  # V = max channel
    assert out["hsv_s_mean"] == pytest.approx(127.5, abs=1)  # (200-100)/200 * 255
    assert out["hsv_h_resultant_length"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("rgb", "lab"),
    [
        ((255, 255, 255), (100.0, 0.0, 0.0)),
        ((0, 0, 0), (0.0, 0.0, 0.0)),
        ((255, 0, 0), (53.24, 80.09, 67.20)),  # standard sRGB red, D65
    ],
)
def test_lab_reference_colours(rgb: tuple[int, int, int], lab: tuple[float, float, float]) -> None:
    got = feat.srgb_to_lab(np.asarray([rgb], dtype=np.uint8))[0]
    assert got == pytest.approx(lab, abs=0.05)


def test_pure_hematoxylin_and_pure_eosin_unmix() -> None:
    h = feat.stain_concentrations(_from_od((0.6, 0.0, 0.0)).reshape(-1, 3)).mean(axis=0)
    e = feat.stain_concentrations(_from_od((0.0, 0.5, 0.0)).reshape(-1, 3)).mean(axis=0)
    assert h[0] == pytest.approx(0.6, abs=0.02)
    assert abs(h[1]) < 0.02
    assert e[1] == pytest.approx(0.5, abs=0.02)
    assert abs(e[0]) < 0.02
    share = feat.stain_features(_from_od((0.6, 0.2, 0.0)).reshape(-1, 3))["he_h_share"]
    assert share == pytest.approx(0.75, abs=0.03)


def test_glcm_of_vertical_stripes() -> None:
    stripes = np.zeros((40, 40, 3), dtype=np.uint8)
    stripes[:, 1::2] = 255  # columns alternate black / white -> levels 0 / 31
    out = feat.texture_features(stripes, np.ones((40, 40), dtype=bool))
    # d=1: 0, 45 and 135 degrees cross a column boundary (31^2 = 961), 90 degrees does not
    assert out["glcm_contrast_d1"] == pytest.approx(961 * 3 / 4)
    # d=2 always lands on the same column parity
    assert out["glcm_contrast_d2"] == pytest.approx(0.0)
    assert out["glcm_homogeneity_d2"] == pytest.approx(1.0)


def test_lbp_of_a_constant_image_is_all_bin_8() -> None:
    grey = np.full((20, 20), 77, dtype=np.int64)
    out = feat.lbp_features(grey, np.ones((20, 20), dtype=bool))
    assert out["lbp_riu2_bin8"] == pytest.approx(1.0)
    assert sum(out.values()) == pytest.approx(1.0)


def test_blob_count_of_drawn_nuclei() -> None:
    image = _from_od((0.05, 0.4, 0.0), size=120)  # pink, eosin-rich background
    dark = _from_od((1.2, 0.1, 0.0), size=1)[0, 0]
    centres = [(15 + 30 * i, 15 + 30 * j) for i in range(4) for j in range(3)]  # 12 nuclei
    yy, xx = np.mgrid[:120, :120]
    for cy, cx in centres:
        image[(yy - cy) ** 2 + (xx - cx) ** 2 <= 9] = dark
    out = feat.nuclei_features(image, np.ones((120, 120), dtype=bool))
    assert out["nuc_blob_count"] == 12
    assert out["nuc_blob_area_median_px"] == 29  # a radius-3 digital disc has 29 pixels


def test_white_image_uses_the_mask_fallback() -> None:
    out = feat.features_of_downsized(_uniform((255, 255, 255)))
    assert out["tissue_mask_fallback"] == 1
    assert out["tissue_fraction"] == 0.0
    assert all(np.isfinite(v) for v in out.values())


# ---------------------------------------------------------------- extraction -------------------


def _fake_release(root: Path, n: int = 8) -> Path:
    """A raw folder of JPEGs and a prepare-style manifest (kept rows + one excluded)."""
    rng = np.random.default_rng(0)
    rows = []
    for i in range(n):
        label = i % 2
        split = ("train", "val", "test")[i % 3]
        base = (150, 80, 170) if label else (220, 150, 200)
        arr = np.clip(rng.normal(base, 25, size=(96, 128, 3)), 0, 255).astype(np.uint8)
        rel = f"{split}/{'OSCC' if label else 'Normal'}/img_{i}.jpg"
        path = root / "raw" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(arr).save(path, quality=90)
        rows.append(
            {
                "image_id": f"src-{i:04d}",
                "original_path": rel,
                "label": label,
                "group_id": f"g{i // 2}",
                "magnification": "100x" if i % 4 < 2 else "400x",
                "width": 128,
                "height": 96,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "split": split,
                "status": "ok",
            }
        )
    rows.append(
        {**rows[0], "image_id": "src-9999", "split": "excluded", "status": "label_conflict"}
    )
    manifest = root / "manifest.csv"
    pd.DataFrame(rows).to_csv(manifest, index=False)
    return manifest


def test_extraction_is_byte_identical_and_matches_the_manifest(tmp_path: Path) -> None:
    manifest = _fake_release(tmp_path)
    a = extract(manifest, tmp_path / "raw", tmp_path / "a")
    b = extract(manifest, tmp_path / "raw", tmp_path / "b")
    assert a["n_images"] == 8  # the excluded row is not a kept image
    assert a["features_sha256"] == b["features_sha256"]
    assert a["cues_sha256"] == b["cues_sha256"]
    assert (tmp_path / "a" / FEATURES_FILE).read_bytes() == (
        tmp_path / "b" / FEATURES_FILE
    ).read_bytes()
    table = pd.read_csv(tmp_path / "a" / FEATURES_FILE)
    assert list(table["image_id"]) == sorted(table["image_id"])
    assert not table.isna().any().any()
    assert {"split", "label", "magnification", "group_id"} <= set(table.columns)
    cues = pd.read_csv(tmp_path / "a" / CUES_FILE)
    assert len(cues) == 8
    assert not set(cues.columns) & {"he_h_od_mean", "glcm_contrast_d1"}  # cues never mix in
    info = json.loads((tmp_path / "a" / "extraction.json").read_text("utf-8"))
    assert info["checks"]["ids_split_label_magnification_group_equal_manifest"] is True


def test_check_table_catches_a_label_or_split_mismatch(tmp_path: Path) -> None:
    manifest = _fake_release(tmp_path)
    extract(manifest, tmp_path / "raw", tmp_path / "t")
    frame = pd.read_csv(manifest)
    frame.loc[1, "label"] = 1 - frame.loc[1, "label"]
    frame.to_csv(tmp_path / "bad.csv", index=False)
    with pytest.raises(ExtractionError, match="label differs"):
        check_table(tmp_path / "t" / FEATURES_FILE, tmp_path / "bad.csv")
    frame = pd.read_csv(manifest)
    frame.loc[2, "split"] = "train" if frame.loc[2, "split"] != "train" else "val"
    frame.to_csv(tmp_path / "bad2.csv", index=False)
    with pytest.raises(ExtractionError, match="split differs"):
        check_table(tmp_path / "t" / FEATURES_FILE, tmp_path / "bad2.csv")


def test_a_changed_file_stops_the_extraction(tmp_path: Path) -> None:
    manifest = _fake_release(tmp_path)
    victim = tmp_path / "raw" / pd.read_csv(manifest).loc[3, "original_path"]
    victim.write_bytes(victim.read_bytes() + b"\0")
    with pytest.raises(ExtractionError, match="SHA-256"):
        extract(manifest, tmp_path / "raw", tmp_path / "t")
    assert not (tmp_path / "t" / FEATURES_FILE).exists()  # no half table is left behind


# ---------------------------------------------------------------- models -----------------------


def test_classifiers_end_to_end_in_the_image_run_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from oscc_ml.tabular import models

    # a small, learnable table: 4 informative + 4 noise features, groups of 2
    rng = np.random.default_rng(1)
    n = 120
    label = rng.integers(0, 2, n)
    frame = pd.DataFrame(
        {
            "image_id": [f"i{k:04d}" for k in range(n)],
            "split": np.array(["train"] * 72 + ["val"] * 24 + ["test"] * 24),
            "label": label,
            "magnification": np.where(rng.random(n) < 0.5, "100x", "400x"),
            "group_id": [f"g{k // 2}" for k in range(n)],
            "width": 2048,
            "height": 1536,
            "original_path": [f"x/{k}.jpg" for k in range(n)],
            "tissue_threshold": 40.0,
            "tissue_mask_fallback": 0,
        }
    )
    for j in range(4):
        frame[f"signal_{j}"] = label * 1.5 + rng.normal(0, 1, n)
        frame[f"noise_{j}"] = rng.normal(0, 1, n)
    features_dir = tmp_path / "tab"
    features_dir.mkdir()
    frame.to_csv(features_dir / FEATURES_FILE, index=False)
    (features_dir / "extraction.json").write_text(
        json.dumps({"features_sha256": "x", "seconds_per_image": 0.4, "manifest": "none"}), "utf-8"
    )
    small = {
        "tab_logreg": models.ModelSpec("tab_logreg", models._logreg, {"model__C": [0.1, 1.0]}),
        "tab_random_forest": models.ModelSpec(
            "tab_random_forest", models._forest, {"model__max_depth": [4]}
        ),
        "tab_gradient_boosting": models.ModelSpec(
            "tab_gradient_boosting", models._boosting, {"model__max_iter": [50]}
        ),
    }
    monkeypatch.setattr(models, "MODELS", small)
    runs = tmp_path / "runs"
    done = models.train_tabular(features_dir, runs, models=tuple(small), n_bootstrap=50)
    assert len(done) == 6  # 3 models + 3 magnification ablations
    for run in done:
        info = json.loads((run / "run_info.json").read_text("utf-8"))
        ev = json.loads((run / "evaluation.json").read_text("utf-8"))
        assert info["status"] == "completed"
        assert info["family"] == "Tabular"
        assert ev["test"]["auc_roc"]["estimate"] > 0.7  # the signal is learnable
        assert {"100x", "400x"} == set(ev["test_by_magnification"])
        assert "ece" in ev["calibration"]["test"]
        test = pd.read_csv(run / "predictions" / "test_images.csv")
        assert len(test) == 24
        assert {"image_id", "label", "oscc_probability", "group_id", "magnification"} <= set(test)
        assert (run / "permutation_importance_val.csv").is_file()
        assert "Chosen setting" in (run / "TRAINING_JOURNAL.md").read_text("utf-8")
        if info["purpose"] == "train":
            assert (
                "is_400x" not in json.loads((run / "metrics.json").read_text("utf-8"))["features"]
            )
        else:
            assert info["purpose"] == "ablation"
            assert "is_400x" in json.loads((run / "metrics.json").read_text("utf-8"))["features"]
    # importance is computed on validation; signal features rank above noise for the forest
    forest = next(r for r in done if "random_forest" in r.name and not r.name.endswith("_mag"))
    imp = pd.read_csv(forest / "permutation_importance_val.csv")
    assert imp.iloc[0]["feature"].startswith("signal_")


def test_shortcut_check_reports_every_baseline(tmp_path: Path) -> None:
    from oscc_ml.tabular.checks import shortcut_check

    manifest = _fake_release(tmp_path, n=24)
    extract(manifest, tmp_path / "raw", tmp_path / "t")
    result = shortcut_check(tmp_path / "t", tmp_path / "out", n_bootstrap=50)
    assert set(result["baselines"]) == {
        "file_and_jpeg",
        "global_colour_histogram",
        "all_non_pathology_cues",
        "image_size_only",
        "magnification_only",
    }
    assert (tmp_path / "out" / "shortcut_check.md").is_file()


def test_data_dictionary_documents_every_column(tmp_path: Path) -> None:
    import re

    manifest = _fake_release(tmp_path, n=6)
    extract(manifest, tmp_path / "raw", tmp_path / "t")
    doc = (
        Path(__file__).resolve().parents[2] / "docs" / "results" / "TABULAR_DATA_DICTIONARY.md"
    ).read_text("utf-8")
    documented = set(re.findall(r"^\| `([a-z0-9_]+)` \|", doc, re.MULTILINE))
    for name in (FEATURES_FILE, CUES_FILE):
        columns = set(pd.read_csv(tmp_path / "t" / name, nrows=0).columns)
        assert columns <= documented | {"image_id", "split", "label", "magnification", "group_id"}
    features = set(pd.read_csv(tmp_path / "t" / FEATURES_FILE, nrows=0).columns)
    cues = set(pd.read_csv(tmp_path / "t" / CUES_FILE, nrows=0).columns)
    assert documented == features | cues  # nothing documented that does not exist


def test_tabular_report_is_built_from_files_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from oscc_ml.tabular import models
    from oscc_ml.tabular.checks import shortcut_check
    from oscc_ml.tabular.report import write_report

    manifest = _fake_release(tmp_path, n=36)
    extract(manifest, tmp_path / "raw", tmp_path / "t")
    small = {"tab_logreg": models.ModelSpec("tab_logreg", models._logreg, {"model__C": [1.0]})}
    monkeypatch.setattr(models, "MODELS", small)
    runs = tmp_path / "runs"
    models.train_tabular(tmp_path / "t", runs, models=("tab_logreg",), n_bootstrap=30)
    shortcut_check(tmp_path / "t", tmp_path / "checks", n_bootstrap=30)
    text = write_report(runs, tmp_path / "t", tmp_path / "checks", tmp_path / "R.md").read_text(
        "utf-8"
    )
    for heading in (
        "## Dataset",
        "## Test results",
        "## Per magnification",
        "## Permutation importance",
        "## Ablation",
        "## Class-level image statistics",
        "## Shortcut check",
    ):
        assert heading in text
    assert "Random forest (tabular) | not yet run" in text
    info = json.loads((tmp_path / "t" / "extraction.json").read_text("utf-8"))
    assert info["features_sha256"] in text
