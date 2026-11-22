"""Reviewed same-field pairs (ADR-0005): loading, applicability and the loud failures."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pandas as pd
import pytest
import yaml

from oscc_ml.data.prepare import PrepareError, PrepareSettings, prepare
from oscc_ml.data.reviewed import (
    DEFAULT_REVIEWED_DUPLICATES,
    ReviewedDuplicatesError,
    load_reviewed_duplicates,
)
from oscc_ml.data.testzip import make_test_zip


@pytest.fixture(scope="module")
def raw(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_test_zip(tmp_path_factory.mktemp("raw") / "k.zip", 24, 1, size=(300, 260))


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory, raw: Path) -> pd.DataFrame:
    out = tmp_path_factory.mktemp("p") / "base"
    prepare(
        raw,
        out,
        PrepareSettings(dataset_version="synthetic-r", reviewed_duplicates=None),
        manifest_only=True,
    )
    return pd.read_csv(out / "manifest.csv")


def _originals(manifest: pd.DataFrame) -> pd.DataFrame:
    return manifest[~manifest["publisher_augmented"]]


def _write(tmp: Path, count: int, pairs: list[tuple[pd.Series, pd.Series]]) -> Path:
    def entry(row: pd.Series) -> dict[str, str]:
        return {"name": PurePosixPath(row["original_path"]).name, "sha256": row["sha256"]}

    data = {
        "version": 1,
        "source_name": "synthetic",
        "source_original_count": count,
        "pairs": [
            {
                "a": entry(a),
                "b": entry(b),
                "reason": "test",
                "evidence": "test",
                "reviewer": "test",
                "date": "2026-11-22",
            }
            for a, b in pairs
        ],
    }
    path = tmp / "reviewed.yaml"
    path.write_text(yaml.safe_dump(data), "utf-8")
    return path


def _run(raw: Path, tmp: Path, yaml_path: Path) -> tuple[pd.DataFrame, dict]:
    import json

    out = tmp / "out"
    prepare(
        raw,
        out,
        PrepareSettings(
            dataset_version="synthetic-r",
            reviewed_duplicates=load_reviewed_duplicates(yaml_path),
        ),
        manifest_only=True,
    )
    return pd.read_csv(out / "manifest.csv"), json.loads(
        (out / "manifest_only.json").read_text("utf-8")
    )


def _singleton_pair(manifest: pd.DataFrame, label: int) -> tuple[pd.Series, pd.Series]:
    """Two kept originals with the same label, in different groups, at least one in val/test."""
    kept = manifest[(manifest["split"] != "excluded") & (manifest["label"] == label)]
    sizes = manifest["duplicate_cluster"].value_counts()
    alone = kept[kept["duplicate_cluster"].map(sizes) == 1]
    a = alone[alone["original_split"] == "train"].iloc[0]
    b = alone[alone["original_split"].isin(["val", "test"])].iloc[0]
    return a, b


def test_the_shipped_list_is_valid_and_names_the_two_reviewed_pairs() -> None:
    reviewed = load_reviewed_duplicates(DEFAULT_REVIEWED_DUPLICATES)
    assert reviewed.source_original_count == 1224
    names = {(p.a.name, p.b.name) for p in reviewed.pairs}
    assert names == {
        ("OSCC_100x_81.jpg", "OSCC_100x_82.jpg"),
        ("OSCC_400x_417.jpg", "OSCC_400x_423.jpg"),
    }
    for pair in reviewed.pairs:
        assert pair.reviewer == "Claude Code, pending Zaid confirmation"
        assert "pairs_at_5-6.jpg" in pair.evidence


def test_default_settings_load_the_list_and_threshold_4() -> None:
    settings = PrepareSettings()
    assert settings.duplicate_threshold == 4
    assert settings.group_threshold == 10
    assert settings.reviewed_duplicates == load_reviewed_duplicates()


def test_not_applicable_to_another_release(raw: Path, tmp_path: Path) -> None:
    _, info = _run(raw, tmp_path, DEFAULT_REVIEWED_DUPLICATES)
    assert info["reviewed_duplicates_status"].startswith("not applicable: the source has")


def test_a_reviewed_pair_is_merged_with_the_duplicate_rules(
    raw: Path, baseline: pd.DataFrame, tmp_path: Path
) -> None:
    a, b = _singleton_pair(baseline, 1)
    count = int((~baseline["publisher_augmented"]).sum())
    manifest, info = _run(raw, tmp_path, _write(tmp_path, count, [(a, b)]))
    assert info["reviewed_duplicates_status"] == "applied: 1 pair(s)"
    rows = manifest.set_index("original_path").loc[[a["original_path"], b["original_path"]]]
    assert rows["duplicate_cluster"].nunique() == 1
    # representative rule: the val/test member is kept, the train member points to it
    assert rows.loc[b["original_path"], "split"] != "excluded"
    assert rows.loc[a["original_path"], "split"] == "excluded"
    assert rows.loc[a["original_path"], "duplicate_of"] == rows.loc[b["original_path"], "image_id"]
    assert info["n_duplicates_removed"] == 1 + int(
        (baseline["is_augmented_copy"] & ~baseline["publisher_augmented"]).sum()
    )
    # every other original is still a candidate (the split itself may shift: groups changed)
    others = baseline[~baseline["original_path"].isin([a["original_path"], b["original_path"]])]
    merged = others.merge(manifest, on="original_path", suffixes=("", "_new"))
    assert len(merged) == len(others)
    assert (merged["duplicate_cluster"].notna() == merged["duplicate_cluster_new"].notna()).all()


def test_missing_listed_file_fails_loudly(
    raw: Path, baseline: pd.DataFrame, tmp_path: Path
) -> None:
    a, b = _singleton_pair(baseline, 1)
    b = b.copy()
    b["sha256"] = "0" * 64
    count = int((~baseline["publisher_augmented"]).sum())
    with pytest.raises(PrepareError, match="is not in the source"):
        _run(raw, tmp_path, _write(tmp_path, count, [(a, b)]))


def test_conflicting_labels_fail_loudly(raw: Path, baseline: pd.DataFrame, tmp_path: Path) -> None:
    a, _ = _singleton_pair(baseline, 0)
    _, b = _singleton_pair(baseline, 1)
    count = int((~baseline["publisher_augmented"]).sum())
    with pytest.raises(PrepareError, match="label conflict"):
        _run(raw, tmp_path, _write(tmp_path, count, [(a, b)]))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["pairs"][0]["a"].update(name="train/OSCC/x.jpg"), "file name"),
        (lambda d: d["pairs"][0]["a"].update(sha256="abc"), "64 hex"),
        (
            lambda d: d["pairs"][0]["b"].update(sha256=d["pairs"][0]["a"]["sha256"]),
            "byte-identical",
        ),
        (lambda d: d["pairs"][0].pop("reviewer"), "needs exactly"),
        (lambda d: d.pop("source_original_count"), "missing keys"),
    ],
)
def test_malformed_lists_are_rejected(tmp_path: Path, mutate: object, message: str) -> None:
    data = yaml.safe_load(DEFAULT_REVIEWED_DUPLICATES.read_text("utf-8"))
    mutate(data)  # type: ignore[operator]
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data), "utf-8")
    with pytest.raises(ReviewedDuplicatesError, match=message):
        load_reviewed_duplicates(path)
