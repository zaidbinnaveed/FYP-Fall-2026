"""`oscc-ml audit`: built only from manifest.csv + dataset.json; labelled by what it shows."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from oscc_ml.audit import (
    SAMPLE_BANNER,
    SYNTHETIC_BANNER,
    AuditError,
    build_audit,
    classify,
)
from oscc_ml.cli import app
from oscc_ml.data.prepare import PrepareSettings, prepare
from oscc_ml.data.testzip import make_test_zip


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("audit")
    raw = make_test_zip(root / "raw.zip", 24, 1, size=(300, 260), label_conflicts=2)
    return prepare(raw, root / "synthetic-audit", PrepareSettings(dataset_version="synthetic-a"))


def _only_sources(prepared: Path, tmp_path: Path) -> Path:
    """A copy holding just the two files the audit may read."""
    folder = tmp_path / "only"
    folder.mkdir()
    for name in ("manifest.csv", "dataset.json"):
        shutil.copy(prepared / name, folder / name)
    return folder


def test_audit_uses_only_manifest_and_dataset_json(prepared: Path, tmp_path: Path) -> None:
    full, kind = build_audit(prepared)
    only, _ = build_audit(_only_sources(prepared, tmp_path))
    assert only == full
    assert kind == "synthetic"
    assert SYNTHETIC_BANNER in full


def test_audit_numbers_match_the_manifest(prepared: Path) -> None:
    markdown, _ = build_audit(prepared)
    manifest = pd.read_csv(prepared / "manifest.csv")
    info = json.loads((prepared / "dataset.json").read_text("utf-8"))
    kept = manifest[manifest["split"] != "excluded"]
    assert f"Kept images: **{len(kept):,}**" in markdown
    assert f"patches: **{int(kept['n_patches'].sum()):,}**" in markdown
    excluded_aug = int(manifest["publisher_augmented"].sum())
    assert f"excluded by name): **{excluded_aug:,}**" in markdown
    assert "**1** byte-identical and **1** near-duplicate clusters, **4** images" in markdown
    assert "Leakage test recorded by prepare: **passed**" in markdown
    assert "Re-checked here from the manifest: **passed**" in markdown
    for title in (
        "## 1. Counts per source x class x magnification x split",
        "## 2. Source files and publisher `aug_` copies",
        "## 3. Image sizes",
        "## 4. Duplicate clusters",
        "## 5. Grouping and leakage test",
        "## 6. Tissue filter",
        "## 7. Patches per image",
    ):
        assert title in markdown
    fallbacks = int((manifest["tiling_mode"] == "grid_fallback").sum())
    assert f"`grid_fallback`: **{fallbacks}**" in markdown
    assert info["dataset_version"] in markdown


def test_audit_detects_a_leak_in_a_tampered_manifest(prepared: Path, tmp_path: Path) -> None:
    folder = _only_sources(prepared, tmp_path)
    manifest = pd.read_csv(folder / "manifest.csv")
    kept = manifest.index[manifest["split"] != "excluded"]
    train = [i for i in kept if manifest.loc[i, "split"] == "train"]
    test = [i for i in kept if manifest.loc[i, "split"] == "test"]
    manifest.loc[train[0], "group_id"] = manifest.loc[test[0], "group_id"]
    manifest.to_csv(folder / "manifest.csv", index=False)
    markdown, _ = build_audit(folder)
    assert "Re-checked here from the manifest: **FAILED" in markdown


def test_labels_sample_full_and_synthetic() -> None:
    assert classify({"dataset_version": "synthetic-x"}) == "synthetic"
    assert classify({"dataset_version": "sample-dev", "source": {"name": "sample"}}) == "sample"
    sample_named_like_full = {"dataset_version": "oscc-unified-v1", "source": {"name": "sample"}}
    assert classify(sample_named_like_full) == "sample"
    full = {"dataset_version": "oscc-unified-v1", "source": {"name": "kaggle_kebede"}}
    assert classify(full) == "full"


def test_sample_banner(prepared: Path, tmp_path: Path) -> None:
    folder = _only_sources(prepared, tmp_path)
    info = json.loads((folder / "dataset.json").read_text("utf-8"))
    info["dataset_version"] = "sample-dev"
    (folder / "dataset.json").write_text(json.dumps(info), "utf-8")
    markdown, kind = build_audit(folder)
    assert kind == "sample"
    assert SAMPLE_BANNER in markdown


def test_missing_sources_are_refused(tmp_path: Path) -> None:
    with pytest.raises(AuditError, match="missing"):
        build_audit(tmp_path)


def test_cli_refuses_synthetic_without_explicit_out(prepared: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    refused = runner.invoke(app, ["audit", "--prepared", str(prepared)])
    assert refused.exit_code == 2
    assert "synthetic" in refused.output
    out = tmp_path / "audit.md"
    ok = runner.invoke(app, ["audit", "--prepared", str(prepared), "--out", str(out)])
    assert ok.exit_code == 0, ok.output
    assert out.read_text("utf-8").startswith("# Dataset audit")
