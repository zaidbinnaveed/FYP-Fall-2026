"""The independent dataset verifier (scripts/audit/verify_dataset_independent.py), FYP-I audit C.

Its pHash, distance, clustering and split must agree with the pipeline on a synthetic Kaggle-like
archive, it must be deterministic, and it must FAIL when the manifest, the zip or the provenance
listing are tampered with.
"""

from __future__ import annotations

import ast
import csv
import importlib.util
import json
import shutil
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
from PIL import Image

from oscc_ml.data.dedup import clusters, dihedral_phashes, min_distances
from oscc_ml.data.prepare import PrepareSettings, prepare
from oscc_ml.data.testzip import make_test_zip

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit" / "verify_dataset_independent.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_dataset_independent", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V = _load()


def test_script_does_not_import_the_pipeline() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"oscc_ml", "pandas", "imagehash"}, imported


@pytest.fixture(scope="module")
def conflict_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_test_zip(
        tmp_path_factory.mktemp("raw") / "kaggle_like.zip",
        24,
        1,
        size=(300, 260),
        label_conflicts=2,
    )


@pytest.fixture(scope="module")
def manifest_dir(tmp_path_factory: pytest.TempPathFactory, conflict_zip: Path) -> Path:
    out = tmp_path_factory.mktemp("processed") / "dry"
    return prepare(
        conflict_zip, out, PrepareSettings(dataset_version="synthetic-audit"), manifest_only=True
    )


@pytest.fixture(scope="module")
def extracted(tmp_path_factory: pytest.TempPathFactory, conflict_zip: Path) -> Path:
    folder = tmp_path_factory.mktemp("extracted")
    with zipfile.ZipFile(conflict_zip) as archive:
        archive.extractall(folder)
    return folder / "Oral Cancer Dataset"


def _run(tmp: Path, *extra: str, raw: Path, manifest: Path | None = None) -> tuple[int, dict]:
    out = tmp / "out"
    if out.exists():
        shutil.rmtree(out)
    argv = ["--raw", str(raw), "--out", str(out), *extra]
    if manifest is not None:
        argv += ["--manifest-dir", str(manifest)]
    code = V.run(V.parse_args(argv))
    return code, json.loads((out / "verify_results.json").read_text("utf-8"))


def _failed(result: dict) -> list[str]:
    return [c["check"] for c in result["checks"] if not c["passed"]]


# ----------------------------------------------------------------------------- building blocks


def test_phash_is_bit_identical_to_imagehash_on_varied_images() -> None:
    rng = np.random.default_rng(0)
    for size in [(300, 260), (2048, 1536), (224, 224), (513, 97)]:
        array = rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
        smooth = Image.fromarray(array).resize((size[0] // 8 + 1, size[1] // 8 + 1)).resize(size)
        for image in (Image.fromarray(array), smooth):
            ours = V.dihedral_hashes(image)
            theirs = [int(v) for v in dihedral_phashes(image)]
            assert ours == theirs


def test_popcount_and_distances_match_numpy() -> None:
    rng = np.random.default_rng(1)
    hashes = rng.integers(0, 2**63, (40, 8), dtype=np.uint64) * np.uint64(2) + np.uint64(1)
    assert np.array_equal(V.popcount64(hashes), np.bitwise_count(hashes).astype(np.int64))
    assert np.array_equal(V.distance_matrix(hashes), min_distances(hashes))


def test_partition_matches_union_find() -> None:
    rng = np.random.default_rng(2)
    base = rng.integers(0, 20, (60, 60))
    distances = np.minimum(base, base.T).astype(np.uint8)
    np.fill_diagonal(distances, 0)
    for threshold in (0, 1, 2, 3):
        keys = [str(i) for i in range(60)]
        ours = V.as_blocks(keys, V.partition(distances, threshold))
        theirs = V.as_blocks(keys, clusters(distances, threshold).tolist())
        assert ours == theirs


# ----------------------------------------------------------------------------- end to end


def test_all_checks_pass_against_prepare(
    tmp_path: Path, conflict_zip: Path, manifest_dir: Path
) -> None:
    code, result = _run(tmp_path, raw=conflict_zip, manifest=manifest_dir)
    assert code == 0, _failed(result)
    counts = result["counts"]
    assert counts["n_label_conflict_clusters"] == 2
    assert counts["n_label_conflict_images_excluded"] == 4
    assert counts["n_byte_identical_groups_with_both_labels"] == 1


def test_output_is_deterministic(tmp_path: Path, conflict_zip: Path, manifest_dir: Path) -> None:
    outputs = []
    for run in ("a", "b"):
        folder = tmp_path / run
        folder.mkdir()
        _run(folder, raw=conflict_zip, manifest=manifest_dir)
        outputs.append({p.name: p.read_bytes() for p in sorted((folder / "out").iterdir())})
    assert outputs[0] == outputs[1]


def test_folder_and_zip_give_the_same_counts(
    tmp_path: Path, conflict_zip: Path, extracted: Path
) -> None:
    (tmp_path / "z").mkdir()
    _, from_zip = _run(tmp_path / "z", raw=conflict_zip)
    _, from_folder = _run(tmp_path, raw=extracted)
    as_folder = json.loads(json.dumps(from_zip["counts"]).replace("Oral Cancer Dataset/", ""))
    assert as_folder == from_folder["counts"]
    assert (
        from_zip["split_hygiene"]["class_ratio_per_split"]
        == (from_folder["split_hygiene"]["class_ratio_per_split"])
    )


def test_tampered_manifest_split_is_detected(
    tmp_path: Path, conflict_zip: Path, manifest_dir: Path
) -> None:
    tampered = tmp_path / "tampered"
    shutil.copytree(manifest_dir, tampered)
    path = tampered / "manifest.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    victim = next(r for r in rows if r["split"] == "test")
    victim["split"] = "train"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    code, result = _run(tmp_path, raw=conflict_zip, manifest=tampered)
    assert code == 1
    assert "C3 manifest column 'split' matches per row" in _failed(result)


def test_zip_with_a_changed_file_is_detected(
    tmp_path: Path, conflict_zip: Path, extracted: Path
) -> None:
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(conflict_zip) as src, zipfile.ZipFile(bad, "w") as dst:
        for i, info in enumerate(src.infolist()):
            data = src.read(info)
            if i == 3 and not info.is_dir():
                data = data[:-1] + bytes([data[-1] ^ 1])
            dst.writestr(info, data)
    code, result = _run(
        tmp_path, "--zip", str(bad), "--zip-root", "Oral Cancer Dataset", raw=extracted
    )
    assert code == 1
    assert "C2 every zip member is byte-identical (SHA-256, size) to the raw file" in _failed(
        result
    )
    code, result = _run(
        tmp_path,
        "--zip",
        str(conflict_zip),
        "--zip-root",
        "Oral Cancer Dataset",
        "--expected-zip-sha256",
        V.sha256_file(conflict_zip),
        raw=extracted,
    )
    assert code == 0, _failed(result)


def _listing(folder: Path, files_csv: Path, corrupt: bool) -> None:
    """A Mendeley-style listing built from the synthetic originals (one folder per class/mag)."""
    folder.mkdir()
    with files_csv.open(newline="", encoding="utf-8") as handle:
        rows = [
            r
            for r in csv.DictReader(handle)
            if r["augmented"] == "False" and r["is_image"] == "True"
        ]
    folders, per_folder = [], {}
    for row in rows:
        cls = "OSCC" if row["label"] == "1" else "Normal"
        key = f"{row['magnification']} {cls} images"
        fid = f"id-{len(per_folder)}" if key not in {f["name"] for f in folders} else None
        if fid:
            folders.append({"id": fid, "name": key, "description": "synthetic"})
            per_folder[fid] = []
        target = next(f["id"] for f in folders if f["name"] == key)
        sha = row["sha256"]
        if corrupt and not per_folder[target] and target == "id-0":
            sha = "0" * 64
        name = row["path"].rsplit("/", 1)[-1]
        if any(e["filename"] == name for e in per_folder[target]):
            continue  # a byte-identical copy saved twice under the same name; list it once
        per_folder[target].append(
            {
                "filename": name,
                "size": int(row["size_bytes"]),
                "content_details": {"sha256_hash": sha},
            }
        )
    (folder / "folders_v2.json").write_text(json.dumps(folders), "utf-8")
    for fid, items in per_folder.items():
        (folder / f"files_{fid}.json").write_text(json.dumps(items), "utf-8")


def test_provenance_listing_match_and_mismatch(tmp_path: Path, extracted: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    _run(base, raw=extracted)
    files_csv = base / "out" / "files.csv"
    good, bad = tmp_path / "good", tmp_path / "bad"
    _listing(good, files_csv, corrupt=False)
    _listing(bad, files_csv, corrupt=True)
    code, result = _run(tmp_path, "--mendeley-dir", str(good), raw=extracted)
    provenance = [c for c in result["checks"] if c["check"].startswith("C1")]
    assert provenance
    assert all(c["passed"] for c in provenance), provenance
    code, result = _run(tmp_path, "--mendeley-dir", str(bad), raw=extracted)
    assert code == 1
    assert "C1 same file name + class folder has the same bytes in both releases" in _failed(result)


def test_reviewed_pairs_are_reproduced_independently(
    tmp_path: Path, conflict_zip: Path, manifest_dir: Path
) -> None:
    """ADR-0005: the verifier parses the same reviewed list itself and must reach prepare's result;
    a listed file that is missing stops it."""
    import pandas as pd
    import yaml

    from oscc_ml.data.reviewed import load_reviewed_duplicates

    manifest = pd.read_csv(manifest_dir / "manifest.csv")
    originals = manifest[~manifest["publisher_augmented"]]
    sizes = manifest["duplicate_cluster"].value_counts()
    alone = originals[
        (originals["split"] != "excluded")
        & (originals["label"] == 1)
        & (originals["duplicate_cluster"].map(sizes) == 1)
    ]
    a, b = alone.iloc[0], alone.iloc[-1]

    def entry(row: pd.Series) -> dict[str, str]:
        return {"name": row["original_path"].rsplit("/", 1)[-1], "sha256": row["sha256"]}

    listing = {
        "version": 1,
        "source_name": "synthetic",
        "source_original_count": len(originals),
        "pairs": [
            {
                "a": entry(a),
                "b": entry(b),
                "reason": "t",
                "evidence": "t",
                "reviewer": "t",
                "date": "2026-11-22",
            }
        ],
    }
    path = tmp_path / "reviewed.yaml"
    path.write_text(yaml.safe_dump(listing), "utf-8")
    reviewed_dir = tmp_path / "dry-reviewed"
    prepare(
        conflict_zip,
        reviewed_dir,
        PrepareSettings(
            dataset_version="synthetic-audit", reviewed_duplicates=load_reviewed_duplicates(path)
        ),
        manifest_only=True,
    )
    code, result = _run(
        tmp_path, "--reviewed-duplicates", str(path), raw=conflict_zip, manifest=reviewed_dir
    )
    assert code == 0, _failed(result)
    assert result["reviewed_duplicates_status"] == "applied: 1 pair(s)"
    # the same list against the manifest made WITHOUT it must disagree
    code, result = _run(
        tmp_path, "--reviewed-duplicates", str(path), raw=conflict_zip, manifest=manifest_dir
    )
    assert code == 1
    listing["pairs"][0]["b"]["sha256"] = "0" * 64
    path.write_text(yaml.safe_dump(listing), "utf-8")
    with pytest.raises(SystemExit, match="file missing"):
        _run(tmp_path, "--reviewed-duplicates", str(path), raw=conflict_zip)
