"""Independent verification of the dataset pipeline (FYP-I audit, Phase 1 section C).

This script deliberately does NOT import ``oscc_ml`` (or pandas). It re-derives, from the raw
files and the rules written in the docs, every number that ``oscc-ml prepare`` reports, and
compares them with prepare's own ``manifest.csv`` / ``manifest_only.json``:

* C1 provenance: SHA-256 of every original vs the Mendeley Data per-file listing (metadata JSON
  saved beforehand; no images are downloaded).
* C2 raw untouched: SHA-256 of every file in the raw folder vs every member of the export zip,
  plus the SHA-256 of the zip itself.
* C3 recount: counts per class / magnification / Kaggle folder, ``aug_`` exclusions, byte-identical
  clusters, pHash duplicate clusters, label-conflict exclusions (with the reason per file), the kept
  images; compared row by row with prepare's manifest.
* C4 split hygiene: SHA-256 / cluster / group / near-duplicate leakage, class ratio per split,
  the seed-42 split rebuilt twice.

pHash is re-implemented here with a hand-written DCT-II (no ``imagehash`` / ``scipy.fftpack``),
following the definition in ``docs/adr`` / ``oscc_ml.data.dedup`` docstrings: greyscale ->
thumbnail to 512 px -> each of the 8 flips/90-degree rotations -> 32x32 Lanczos -> DCT -> top-left
8x8 -> bit = coefficient > median. Distance = min Hamming distance between image A's plain hash and
any of B's 8 hashes, symmetrised with min(d(A,B), d(B,A)).

Streams one file at a time; peak memory is one decoded image plus an n x n uint8 matrix
(n = number of originals). Read-only on every input.

Usage (from ml_research/):
    python -I scripts/audit/verify_dataset_independent.py --raw data/raw/kaggle_kebede \
        --manifest-dir data/processed/<manifest-only folder> --out <output folder> \
        [--zip data/export/oscc_kaggle_kebede_v1.zip --zip-root kaggle_kebede \
         --expected-zip-sha256 <hex>] [--mendeley-dir <folder with the saved listing JSON>]
Exit code 0 if every check passed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

import numpy as np
import yaml
from PIL import Image
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from sklearn.model_selection import StratifiedGroupKFold

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
SPLIT_FOLDERS = {"train", "val", "test"}
CLASS_FOLDERS = {"Normal": 0, "OSCC": 1}
ORIGINAL_NAME = re.compile(r"^(Normal|OSCC)_(\d+)x_(\d+)\.(jpg|jpeg|png|tif|tiff|bmp)$", re.I)
AUGMENTED_NAME = re.compile(r"^aug_")  # the publisher's augmented copies (plan section 3)
SPLITS = ("train", "val", "test")
N_FOLDS = 20
FOLD_TO_SPLIT = {f: ("train" if f < 14 else "val" if f < 17 else "test") for f in range(N_FOLDS)}
CHUNK = 1 << 20

# ----------------------------------------------------------------------------- reading


class Source:
    """A folder or a zip archive; lists every file and streams one at a time."""

    def __init__(self, location: Path) -> None:
        self.location = location
        self.zip = zipfile.ZipFile(location) if location.is_file() else None

    def files(self) -> list[tuple[str, int]]:
        if self.zip is not None:
            out = [(i.filename, i.file_size) for i in self.zip.infolist() if not i.is_dir()]
        else:
            out = [
                (p.relative_to(self.location).as_posix(), p.stat().st_size)
                for p in self.location.rglob("*")
                if p.is_file()
            ]
        return sorted(out)

    def open(self, rel: str) -> BinaryIO:
        if self.zip is not None:
            return self.zip.open(rel)  # type: ignore[return-value]
        return (self.location / rel).open("rb")

    def read(self, rel: str) -> bytes:
        with self.open(rel) as handle:
            return handle.read()


def sha256_stream(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    while block := handle.read(CHUNK):
        digest.update(block)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return sha256_stream(handle)


def is_hidden(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return any(p.startswith(".") or p == "__MACOSX" for p in parts) or parts[-1].lower() in {
        "thumbs.db",
        "desktop.ini",
    }


def parse_path(rel: str) -> dict[str, Any]:
    """Label from the class folder (exact names Normal / OSCC), Kaggle folder from the split
    folder, magnification from the original's file name. Independent of oscc_ml.data.sources."""
    parts = PurePosixPath(rel).parts
    name = parts[-1]
    kaggle_folder = next((p for p in parts[:-1] if p in SPLIT_FOLDERS), "none")
    class_folders = [p for p in parts[:-1] if p in CLASS_FOLDERS]
    label = CLASS_FOLDERS[class_folders[-1]] if class_folders else None
    augmented = bool(AUGMENTED_NAME.search(name))
    match = ORIGINAL_NAME.match(name)
    magnification = f"{match.group(2)}x" if match else "unknown"
    name_label = None if match is None else (1 if match.group(1).lower() == "oscc" else 0)
    name_agrees = None if name_label is None else name_label == label
    return {
        "path": rel,
        "name": name,
        "kaggle_folder": kaggle_folder,
        "label": label,
        "augmented": augmented,
        "original_name": match is not None,
        "magnification": magnification,
        "name_class_agrees_with_folder": name_agrees,
    }


# ----------------------------------------------------------------------------- pHash

_N = 32
_DCT = np.cos(np.pi * (2 * np.arange(_N)[None, :] + 1) * np.arange(_N)[:, None] / (2 * _N))
_TRANSPOSES = (
    None,
    Image.Transpose.ROTATE_90,
    Image.Transpose.ROTATE_180,
    Image.Transpose.ROTATE_270,
)
_POPCOUNT8 = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def phash64(grey: Image.Image) -> int:
    """64-bit pHash with a hand-written 2-D DCT-II (uniform scaling does not change the bits)."""
    small = np.asarray(grey.resize((_N, _N), Image.Resampling.LANCZOS), dtype=np.float64)
    coeffs = _DCT @ small @ _DCT.T
    low = coeffs[:8, :8]
    value = 0
    for bit in (low > np.median(low)).ravel():
        value = (value << 1) | int(bit)
    return value


def dihedral_hashes(image: Image.Image) -> list[int]:
    grey = image.convert("L")
    grey.thumbnail((512, 512))
    out = []
    for flip in (False, True):
        base = grey.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if flip else grey
        for op in _TRANSPOSES:
            out.append(phash64(base if op is None else base.transpose(op)))
    return out


def popcount64(values: np.ndarray) -> np.ndarray:
    """Bit count of uint64 values via a byte lookup table (independent of np.bitwise_count)."""
    as_bytes = values.astype(np.uint64).view(np.uint8).reshape(*values.shape, 8)
    return _POPCOUNT8[as_bytes].sum(axis=-1, dtype=np.int64)


def distance_matrix(hashes: np.ndarray) -> np.ndarray:
    """Symmetrised transform-invariant Hamming distance, shape (n, n), int64 -> uint8."""
    n = hashes.shape[0]
    plain = hashes[:, 0]
    out = np.empty((n, n), dtype=np.uint8)
    for start in range(0, n, 256):
        stop = min(n, start + 256)
        xor = plain[start:stop, None, None] ^ hashes[None, :, :]
        out[start:stop] = popcount64(xor).min(axis=2)
    return np.minimum(out, out.T)


def query_distances(queries: np.ndarray, references: np.ndarray) -> np.ndarray:
    """For each query: min over references and their 8 transforms of d(query plain, ref)."""
    best = np.full(len(queries), 64, dtype=np.int64)
    if len(references) == 0:
        return best
    for start in range(0, len(queries), 256):
        stop = min(len(queries), start + 256)
        xor = queries[start:stop, 0][:, None, None] ^ references[None, :, :]
        best[start:stop] = popcount64(xor).min(axis=(1, 2))
    return best


def partition(
    distances: np.ndarray, threshold: int, extra: list[tuple[int, int]] | None = None
) -> list[int]:
    """Connected components of 'distance <= threshold' plus ``extra`` links (scipy csgraph),
    renumbered 0..k-1 in the order of each component's first (lowest-index) member."""
    n = distances.shape[0]
    rows, cols = np.nonzero(distances <= threshold)
    if extra:
        rows = np.concatenate([rows, [a for a, _ in extra]])
        cols = np.concatenate([cols, [b for _, b in extra]])
    graph = coo_matrix((np.ones(len(rows), dtype=np.int8), (rows, cols)), shape=(n, n))
    _, raw = connected_components(graph, directed=False)
    renumber: dict[int, int] = {}
    return [renumber.setdefault(int(r), len(renumber)) for r in raw]


def as_blocks(keys: list[str], labels: list[Any]) -> set[frozenset[str]]:
    blocks: dict[Any, set[str]] = defaultdict(set)
    for key, label in zip(keys, labels, strict=True):
        blocks[label].add(key)
    return {frozenset(b) for b in blocks.values()}


# ----------------------------------------------------------------------------- split


def grouped_split(labels: list[int], groups: list[str], seed: int) -> list[str]:
    folds = np.full(len(labels), -1)
    splitter = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=seed)
    for fold, (_, idx) in enumerate(splitter.split(np.zeros(len(labels)), labels, groups)):
        folds[idx] = fold
    if (folds < 0).any():
        raise RuntimeError("some images were not assigned to a fold")
    return [FOLD_TO_SPLIT[int(f)] for f in folds]


# ----------------------------------------------------------------------------- checks


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: Any = None) -> bool:
        self.checks.append({"check": name, "passed": bool(ok), "detail": detail})
        print(
            f"[{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail is not None else "")
        )
        return ok

    @property
    def all_passed(self) -> bool:
        return all(c["passed"] for c in self.checks)


def scan(source: Source, log_every: int = 250) -> list[dict[str, Any]]:
    """Hash every file; decode and pHash every image."""
    entries = source.files()
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for i, (rel, size) in enumerate(entries, start=1):
        row = parse_path(rel)
        row["size_bytes"] = size
        row["hidden"] = is_hidden(rel)
        row["is_image"] = PurePosixPath(rel).suffix.lower() in IMAGE_SUFFIXES and not row["hidden"]
        data = source.read(rel)
        row["sha256"] = hashlib.sha256(data).hexdigest()
        row["hashes"] = None
        row["width"] = row["height"] = None
        row["readable"] = False
        if row["is_image"]:
            try:
                image = Image.open(io.BytesIO(data))
                image.load()
                row["width"], row["height"] = image.size
                row["hashes"] = dihedral_hashes(image)
                row["readable"] = True
            except Exception as exc:  # recorded and counted, never fatal
                row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        if i % log_every == 0 or i == len(entries):
            print(f"  scanned {i}/{len(entries)} files ({time.perf_counter() - started:.0f} s)")
    return rows


def load_reviewed(path: Path | None) -> dict[str, Any] | None:
    """The reviewed same-field list (ADR-0005), parsed here without oscc_ml."""
    if path is None:
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "count": int(data["source_original_count"]),
        "pairs": [
            ((p["a"]["name"], p["a"]["sha256"].lower()), (p["b"]["name"], p["b"]["sha256"].lower()))
            for p in data["pairs"]
        ],
    }


def reviewed_pairs(
    candidates: list[dict[str, Any]], reviewed: dict[str, Any] | None
) -> tuple[list[tuple[int, int]], str]:
    """Indices of the reviewed pairs among the candidates. Required (missing file or conflicting
    labels -> SystemExit) when the source has exactly the listed number of originals."""
    if reviewed is None:
        return [], "disabled"
    if len(candidates) != reviewed["count"]:
        return [], f"not applicable ({len(candidates)} originals, list is for {reviewed['count']})"
    where = {(r["name"], r["sha256"]): i for i, r in enumerate(candidates)}
    links = []
    for a, b in reviewed["pairs"]:
        if a not in where or b not in where:
            raise SystemExit(f"reviewed pair {a[0]} / {b[0]}: file missing from the source")
        i, j = where[a], where[b]
        if candidates[i]["label"] != candidates[j]["label"]:
            raise SystemExit(f"reviewed pair {a[0]} / {b[0]}: conflicting labels")
        links.append((i, j))
    return links, f"applied: {len(links)} pair(s)"


def select(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    """Re-derive candidates, duplicate clusters, conflicts, kept images, groups and the split."""
    images = [r for r in rows if r["is_image"]]
    candidates = [r for r in images if r["readable"] and not r["augmented"]]
    hashes = np.array([r["hashes"] for r in candidates], dtype=np.uint64).reshape(-1, 8)
    dist = distance_matrix(hashes)
    reviewed_links, reviewed_status = reviewed_pairs(candidates, getattr(args, "reviewed", None))
    dup = partition(dist, args.duplicate_threshold, reviewed_links)
    for r, c in zip(candidates, dup, strict=True):
        r["dup_cluster"] = c

    by_cluster: dict[int, list[int]] = defaultdict(list)
    for i, c in enumerate(dup):
        by_cluster[c].append(i)

    conflicts: list[dict[str, Any]] = []
    kept_idx: list[int] = []
    removed: list[dict[str, Any]] = []
    for cluster, members in sorted(by_cluster.items()):
        labels = {candidates[i]["label"] for i in members}
        if len(labels) > 1:
            by_sha: dict[str, set[int]] = defaultdict(set)
            for i in members:
                by_sha[candidates[i]["sha256"]].add(candidates[i]["label"])
            identical = any(len(v) > 1 for v in by_sha.values())
            for i in members:
                me = candidates[i]
                opposite = [j for j in members if candidates[j]["label"] != me["label"]]
                same_bytes = [j for j in opposite if candidates[j]["sha256"] == me["sha256"]]
                nearest = min(opposite, key=lambda j: (int(dist[i, j]), candidates[j]["path"]))
                if same_bytes:
                    reason = (
                        "byte-identical (same SHA-256) to an opposite-label file: "
                        + ", ".join(candidates[j]["path"] for j in same_bytes)
                    )
                elif dist[i, nearest] <= args.duplicate_threshold:
                    reason = (
                        f"pHash distance {int(dist[i, nearest])} (<= {args.duplicate_threshold}) "
                        f"to opposite-label file {candidates[nearest]['path']}"
                    )
                else:
                    reason = (
                        "same-label near-duplicate chain links it to an opposite-label file; "
                        f"nearest opposite-label file {candidates[nearest]['path']} at pHash "
                        f"distance {int(dist[i, nearest])}"
                    )
                conflicts.append(
                    {
                        "cluster": cluster,
                        "cluster_byte_identical": identical,
                        "path": me["path"],
                        "label": me["label"],
                        "sha256": me["sha256"],
                        "reason": reason,
                    }
                )
            continue

        def rank(i: int) -> tuple[int, int, int, str]:
            r = candidates[i]
            return (
                0 if r["kaggle_folder"] in {"val", "test"} else 1,
                -(r["width"] * r["height"]),
                len(r["path"]),
                r["path"],
            )

        ordered = sorted(members, key=rank)
        kept_idx.append(ordered[0])
        for j in ordered[1:]:
            removed.append(
                {
                    "path": candidates[j]["path"],
                    "kept_instead": candidates[ordered[0]]["path"],
                    "pHash_distance": int(dist[j, ordered[0]]),
                    "byte_identical": candidates[j]["sha256"] == candidates[ordered[0]]["sha256"],
                }
            )

    kept_idx.sort()
    kept = [candidates[i] for i in kept_idx]
    sub = dist[np.ix_(kept_idx, kept_idx)]
    groups = partition(sub, args.group_threshold)
    group_names = [f"g{g:05d}" for g in groups]
    labels = [int(r["label"]) for r in kept]
    split_a = grouped_split(labels, group_names, args.seed)
    split_b = grouped_split(labels, group_names, args.seed)
    for r, g, s in zip(kept, group_names, split_a, strict=True):
        r["group"], r["split"] = g, s

    augmented = [r for r in images if r["readable"] and r["augmented"]]
    aug_hashes = np.array([r["hashes"] for r in augmented], dtype=np.uint64).reshape(-1, 8)
    kept_hashes = hashes[kept_idx]
    aug_near = query_distances(aug_hashes, kept_hashes)
    for r, d in zip(augmented, aug_near, strict=True):
        r["nearest_original_distance"] = int(d)
    return {
        "images": images,
        "candidates": candidates,
        "dist": dist,
        "dup": dup,
        "conflicts": conflicts,
        "removed": removed,
        "kept": kept,
        "kept_idx": kept_idx,
        "sub": sub,
        "split_a": split_a,
        "split_b": split_b,
        "augmented": augmented,
        "reviewed_status": reviewed_status,
    }


def check_split_hygiene(sel: dict[str, Any], args: argparse.Namespace, rep: Report) -> dict:
    kept, sub = sel["kept"], sel["sub"]
    splits = np.array([r["split"] for r in kept])
    rep.check("C4 seed-42 split rebuilt twice is identical", sel["split_a"] == sel["split_b"])
    for key in ("sha256", "dup_cluster", "group"):
        spans: dict[Any, set[str]] = defaultdict(set)
        for r in kept:
            spans[r[key]].add(r["split"])
        leaking = [k for k, v in spans.items() if len(v) > 1]
        rep.check(f"C4 no {key} value in two splits (kept images)", not leaking, len(leaking))
    cross = np.triu(splits[:, None] != splits[None, :], k=1)
    cumulative = {k: int(((sub <= k) & cross).sum()) for k in range(0, 17)}
    min_cross = int(sub[cross].min()) if cross.any() else None
    rep.check(
        f"C4 no near-duplicate pair (pHash <= {args.group_threshold}) across splits",
        cumulative[args.group_threshold] == 0,
        {"min_cross_split_distance": min_cross, "pairs_at_or_below": cumulative},
    )
    mixed_groups = []
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in kept:
        by_group[r["group"]].append(r)
    for members in by_group.values():
        if len({m["label"] for m in members}) > 1:
            mixed_groups.append(sorted(m["path"] for m in members))
    ratios = {}
    for s in SPLITS:
        lab = [r["label"] for r in kept if r["split"] == s]
        ratios[s] = {
            "images": len(lab),
            "non_oscc": lab.count(0),
            "oscc": lab.count(1),
            "oscc_fraction": round(lab.count(1) / len(lab), 4) if lab else None,
            "fraction_of_kept": round(len(lab) / len(kept), 4),
        }
    rep.check(
        "C4 both classes in every split",
        all(ratios[s]["non_oscc"] and ratios[s]["oscc"] for s in SPLITS),
    )
    return {
        "class_ratio_per_split": ratios,
        "n_groups": len(by_group),
        "largest_group": max(len(v) for v in by_group.values()),
        "mixed_label_groups_at_group_threshold": mixed_groups,
        "cross_split_pairs_at_or_below_distance": cumulative,
        "min_cross_split_distance": min_cross,
    }


def counts(
    sel: dict[str, Any], rows: list[dict[str, Any]], duplicate_threshold: int
) -> dict[str, Any]:
    images = sel["images"]
    originals = [r for r in images if not r["augmented"]]
    table: Counter[tuple[str, str, str]] = Counter()
    for r in originals:
        table[
            (r["kaggle_folder"], "OSCC" if r["label"] == 1 else "Normal", r["magnification"])
        ] += 1
    kept_table: Counter[tuple[str, str, str]] = Counter()
    for r in sel["kept"]:
        kept_table[(r["split"], "oscc" if r["label"] == 1 else "non_oscc", r["magnification"])] += 1
    aug_by_folder = Counter((r["kaggle_folder"], r["label"]) for r in images if r["augmented"])
    sha_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in originals:
        sha_groups[r["sha256"]].append(r)
    identical = [g for g in sha_groups.values() if len(g) > 1]
    dup_sizes = Counter(Counter(sel["dup"]).values())
    return {
        "n_files": len(rows),
        "n_non_image_or_hidden_files": sum(1 for r in rows if not r["is_image"]),
        "n_images": len(images),
        "n_unreadable": sum(1 for r in images if not r["readable"]),
        "n_publisher_augmented": sum(1 for r in images if r["augmented"]),
        "publisher_augmented_by_folder_and_label": {
            f"{f}/{'OSCC' if lab == 1 else 'Normal'}": n
            for (f, lab), n in sorted(aug_by_folder.items())
        },
        "n_publisher_augmented_matching_a_kept_original": sum(
            1 for r in sel["augmented"] if r["nearest_original_distance"] <= duplicate_threshold
        ),
        "n_originals": len(originals),
        "originals_by_class": dict(
            Counter("OSCC" if r["label"] == 1 else "Normal" for r in originals)
        ),
        "originals_by_class_and_magnification": {
            f"{c}/{m}": n
            for (c, m), n in sorted(
                Counter(
                    ("OSCC" if r["label"] == 1 else "Normal", r["magnification"]) for r in originals
                ).items()
            )
        },
        "originals_by_kaggle_folder_class_magnification": {
            "/".join(k): n for k, n in sorted(table.items())
        },
        "originals_whose_name_class_disagrees_with_folder": [
            r["path"] for r in originals if r["name_class_agrees_with_folder"] is False
        ],
        "originals_with_unrecognised_name": [
            r["path"] for r in originals if not r["original_name"]
        ],
        "n_byte_identical_groups_among_originals": len(identical),
        "n_byte_identical_groups_with_both_labels": sum(
            1 for g in identical if len({r["label"] for r in g}) > 1
        ),
        "n_files_in_byte_identical_groups": sum(len(g) for g in identical),
        "n_duplicate_clusters": len(set(sel["dup"])),
        "duplicate_cluster_size_histogram": {str(k): v for k, v in sorted(dup_sizes.items())},
        "n_label_conflict_clusters": len({c["cluster"] for c in sel["conflicts"]}),
        "n_label_conflict_clusters_byte_identical": len(
            {c["cluster"] for c in sel["conflicts"] if c["cluster_byte_identical"]}
        ),
        "n_label_conflict_images_excluded": len(sel["conflicts"]),
        "n_duplicates_removed": len(sel["removed"]),
        "n_kept": len(sel["kept"]),
        "kept_by_split_class_magnification": {
            "/".join(k): n for k, n in sorted(kept_table.items())
        },
        "kept_dimensions": dict(
            Counter(f"{r['width']}x{r['height']}" for r in sel["kept"]).most_common()
        ),
    }


# ----------------------------------------------------------------------------- comparisons


def _bool(text: str) -> bool:
    return text.strip().lower() == "true"


def compare_manifest(
    sel: dict[str, Any], manifest_dir: Path, threshold: int, rep: Report
) -> dict[str, Any]:
    with (manifest_dir / "manifest.csv").open(newline="", encoding="utf-8") as handle:
        manifest = {row["original_path"]: row for row in csv.DictReader(handle)}
    info = json.loads((manifest_dir / "manifest_only.json").read_text(encoding="utf-8"))
    images = {r["path"]: r for r in sel["images"]}
    kept_paths = {r["path"] for r in sel["kept"]}
    conflict_paths = {c["path"] for c in sel["conflicts"]}
    rep.check(
        "C3 manifest lists exactly the same image paths",
        set(manifest) == set(images),
        {
            "only_in_manifest": sorted(set(manifest) - set(images))[:10],
            "only_here": sorted(set(images) - set(manifest))[:10],
        },
    )
    mismatches: dict[str, list[str]] = defaultdict(list)
    for path, r in images.items():
        m = manifest.get(path)
        if m is None:
            continue
        expected = {
            "sha256": r["sha256"],
            "label": str(r["label"]),
            "magnification": r["magnification"] if not r["augmented"] else m["magnification"],
            "original_split": r["kaggle_folder"],
            "width": str(r["width"]),
            "height": str(r["height"]),
            "size_bytes": str(r["size_bytes"]),
            "phash": f"{r['hashes'][0]:016x}" if r["hashes"] else "",
            "publisher_augmented": str(r["augmented"]),
        }
        for field, value in expected.items():
            if m[field] != value:
                mismatches[field].append(f"{path}: manifest={m[field]!r} here={value!r}")
        kept_here = path in kept_paths
        if (m["split"] != "excluded") != kept_here:
            mismatches["kept"].append(f"{path}: manifest split={m['split']}")
        if kept_here and m["split"] != r["split"]:
            mismatches["split"].append(f"{path}: manifest={m['split']} here={r['split']}")
        conflict_here = path in conflict_paths
        if (m["status"] == "label_conflict") != conflict_here:
            mismatches["label_conflict"].append(f"{path}: manifest status={m['status']}")
        if (
            r["augmented"]
            and r["readable"]
            and m["nearest_original_distance"] != str(r["nearest_original_distance"])
        ):
            mismatches["nearest_original_distance"].append(
                f"{path}: manifest={m['nearest_original_distance']} "
                f"here={r['nearest_original_distance']}"
            )
    for field in (
        "sha256",
        "label",
        "magnification",
        "original_split",
        "width",
        "height",
        "size_bytes",
        "phash",
        "publisher_augmented",
        "kept",
        "split",
        "label_conflict",
        "nearest_original_distance",
    ):
        rep.check(
            f"C3 manifest column '{field}' matches per row",
            not mismatches[field],
            {"n_mismatches": len(mismatches[field]), "examples": mismatches[field][:5]},
        )

    candidates = sel["candidates"]
    here_dup = as_blocks([r["path"] for r in candidates], [r["dup_cluster"] for r in candidates])
    there_dup = as_blocks(
        [r["path"] for r in candidates],
        [manifest[r["path"]]["duplicate_cluster"] for r in candidates],
    )
    rep.check(
        "C3 pHash duplicate clusters (threshold) identical as partitions",
        here_dup == there_dup,
        {"blocks_here": len(here_dup), "blocks_manifest": len(there_dup)},
    )
    kept = sel["kept"]
    here_grp = as_blocks([r["path"] for r in kept], [r["group"] for r in kept])
    there_grp = as_blocks(
        [r["path"] for r in kept], [manifest[r["path"]]["group_id"] for r in kept]
    )
    rep.check(
        "C4 split groups (group threshold) identical as partitions",
        here_grp == there_grp,
        {"groups_here": len(here_grp), "groups_manifest": len(there_grp)},
    )

    here_status, there_status = sel["reviewed_status"], str(info.get("reviewed_duplicates_status"))
    rep.check(
        "C3 reviewed same-field list (ADR-0005) applied identically",
        here_status == there_status
        if here_status.startswith("applied")
        else there_status.split(":")[0] == here_status.split(" (")[0],
        {"manifest_only.json": there_status, "recomputed": here_status},
    )
    c = counts(sel, [], threshold)
    expected_info = {
        "n_source_images": len(images),
        "n_unreadable": c["n_unreadable"],
        "n_publisher_augmented_excluded": c["n_publisher_augmented"],
        "n_publisher_augmented_matching_an_original": c[
            "n_publisher_augmented_matching_a_kept_original"
        ],
        "n_duplicates_removed": c["n_duplicates_removed"],
        "n_kept_images": c["n_kept"],
        "n_groups": len(here_grp),
        "n_label_conflict_images_excluded": c["n_label_conflict_images_excluded"],
        "n_label_conflict_clusters": {
            "byte_identical": c["n_label_conflict_clusters_byte_identical"],
            "near_duplicate": c["n_label_conflict_clusters"]
            - c["n_label_conflict_clusters_byte_identical"],
        },
    }
    for key, value in expected_info.items():
        rep.check(
            f"C3 manifest_only.json '{key}' matches",
            info.get(key) == value,
            {"manifest_only.json": info.get(key), "recomputed": value},
        )
    for s in SPLITS:
        here = {
            "images": sum(1 for r in kept if r["split"] == s),
            "by_class": {
                "non_oscc": sum(1 for r in kept if r["split"] == s and r["label"] == 0),
                "oscc": sum(1 for r in kept if r["split"] == s and r["label"] == 1),
            },
        }
        rep.check(
            f"C4 manifest_only.json counts for {s} match",
            info["counts"][s] == here,
            {"manifest_only.json": info["counts"][s], "recomputed": here},
        )
    there_conflicts = sorted(p for item in info.get("label_conflicts", []) for p in item["paths"])
    here_conflicts = sorted(c_["path"] for c_ in sel["conflicts"])
    rep.check(
        "C3 the label-conflict file list matches manifest_only.json",
        there_conflicts == here_conflicts,
        {"n_manifest": len(there_conflicts), "n_here": len(here_conflicts)},
    )
    return {
        "manifest_settings": info.get("settings"),
        "manifest_created_at": info.get("created_at"),
    }


def compare_mendeley(sel: dict[str, Any], mendeley_dir: Path, rep: Report) -> dict[str, Any]:
    folders = json.loads((mendeley_dir / "folders_v2.json").read_text(encoding="utf-8"))
    leaf: dict[str, dict[str, Any]] = {}
    for f in folders:
        name = f["name"]
        m = re.match(r"(\d+)x (Normal|OSCC)", name)
        if m:
            leaf[f["id"]] = {
                "name": name,
                "magnification": f"{m.group(1)}x",
                "label": 1 if m.group(2) == "OSCC" else 0,
                "description": f.get("description"),
            }
    files: list[dict[str, Any]] = []
    for folder_id, meta in leaf.items():
        listing = json.loads((mendeley_dir / f"files_{folder_id}.json").read_text(encoding="utf-8"))
        meta["n_listed"] = len(listing)
        for item in listing:
            files.append(
                {
                    "filename": item["filename"],
                    "sha256": item["content_details"]["sha256_hash"],
                    "size": int(item["size"]),
                    "label": meta["label"],
                    "magnification": meta["magnification"],
                }
            )
    originals = [r for r in sel["images"] if not r["augmented"]]
    mend_by_sha: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in files:
        mend_by_sha[f["sha256"]].append(f)
    mend_by_name = {(f["filename"], f["label"]): f for f in files}
    kaggle_sha = {r["sha256"] for r in originals}
    matched = [r for r in originals if r["sha256"] in mend_by_sha]
    missing_in_mendeley = [r["path"] for r in originals if r["sha256"] not in mend_by_sha]
    mendeley_not_in_kaggle = [f["filename"] for f in files if f["sha256"] not in kaggle_sha]
    name_and_hash = 0
    name_mismatch: list[str] = []
    label_mismatch: list[str] = []
    for r in originals:
        f = mend_by_name.get((r["name"], r["label"]))
        if f is None:
            name_mismatch.append(
                f"{r['path']}: no Mendeley file with this name in a {r['label']} folder"
            )
            continue
        if f["sha256"] == r["sha256"] and f["size"] == r["size_bytes"]:
            name_and_hash += 1
        else:
            name_mismatch.append(f"{r['path']}: same name, different bytes")
        if f["magnification"] != r["magnification"]:
            label_mismatch.append(
                f"{r['path']}: magnification {r['magnification']} vs {f['magnification']}"
            )
    mend_identical = [g for g in mend_by_sha.values() if len(g) > 1]
    rep.check(
        "C1 every Kaggle original's SHA-256 is in the Mendeley listing",
        not missing_in_mendeley,
        {
            "matched": len(matched),
            "missing": len(missing_in_mendeley),
            "examples": missing_in_mendeley[:5],
        },
    )
    rep.check(
        "C1 every Mendeley file's SHA-256 is in the Kaggle originals",
        not mendeley_not_in_kaggle,
        {
            "missing_from_kaggle": len(mendeley_not_in_kaggle),
            "examples": mendeley_not_in_kaggle[:5],
        },
    )
    rep.check(
        "C1 same file name + class folder has the same bytes in both releases",
        not name_mismatch and name_and_hash == len(originals),
        {"name_class_and_sha256_and_size_match": name_and_hash, "problems": name_mismatch[:5]},
    )
    rep.check(
        "C1 magnification agrees with the Mendeley folder", not label_mismatch, label_mismatch[:5]
    )
    return {
        "mendeley_files": len(files),
        "mendeley_folders": {
            m["name"]: {"listed": m["n_listed"], "description": m["description"]}
            for m in leaf.values()
        },
        "mendeley_byte_identical_groups": len(mend_identical),
        "mendeley_byte_identical_groups_with_both_labels": sum(
            1 for g in mend_identical if len({f["label"] for f in g}) > 1
        ),
        "kaggle_originals_matched_by_sha256": len(matched),
    }


def compare_zip(
    raw_rows: list[dict[str, Any]],
    zip_path: Path,
    zip_root: str,
    expected_sha: str | None,
    rep: Report,
) -> dict[str, Any]:
    raw = {r["path"]: (r["sha256"], r["size_bytes"]) for r in raw_rows}
    members: dict[str, tuple[str, int]] = {}
    prefix = zip_root.rstrip("/") + "/" if zip_root else ""
    outside_root: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if prefix and not info.filename.startswith(prefix):
                outside_root.append(info.filename)
                continue
            with archive.open(info) as handle:
                members[info.filename[len(prefix) :]] = (sha256_stream(handle), info.file_size)
    differing = [p for p in raw if p in members and members[p] != raw[p]]
    rep.check(
        "C2 zip and raw folder hold the same file paths",
        set(raw) == set(members) and not outside_root,
        {
            "raw_files": len(raw),
            "zip_members": len(members),
            "only_raw": sorted(set(raw) - set(members))[:5],
            "only_zip": sorted(set(members) - set(raw))[:5],
            "outside_root": outside_root[:5],
        },
    )
    rep.check(
        "C2 every zip member is byte-identical (SHA-256, size) to the raw file",
        not differing,
        {"n_differing": len(differing), "examples": differing[:5]},
    )
    zip_sha = sha256_file(zip_path)
    result = {
        "zip_sha256": zip_sha,
        "zip_size_bytes": zip_path.stat().st_size,
        "zip_members": len(members),
    }
    if expected_sha:
        rep.check(
            "C2 zip SHA-256 equals the published value",
            zip_sha == expected_sha.lower(),
            {"computed": zip_sha, "expected": expected_sha.lower()},
        )
    return result


# ----------------------------------------------------------------------------- output


def write_outputs(
    out: Path, sel: dict[str, Any], rows: list[dict[str, Any]], summary: dict
) -> None:
    out.mkdir(parents=True, exist_ok=True)

    def write_csv(name: str, records: list[dict[str, Any]], fields: list[str]) -> None:
        with (out / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(records)

    write_csv(
        "files.csv",
        rows,
        [
            "path",
            "size_bytes",
            "sha256",
            "is_image",
            "readable",
            "augmented",
            "label",
            "magnification",
            "kaggle_folder",
            "width",
            "height",
        ],
    )
    write_csv(
        "label_conflicts.csv",
        sel["conflicts"],
        ["cluster", "cluster_byte_identical", "path", "label", "sha256", "reason"],
    )
    write_csv(
        "duplicates_removed.csv",
        sel["removed"],
        ["path", "kept_instead", "pHash_distance", "byte_identical"],
    )
    write_csv(
        "kept.csv",
        sel["kept"],
        [
            "path",
            "label",
            "magnification",
            "kaggle_folder",
            "width",
            "height",
            "sha256",
            "group",
            "split",
        ],
    )
    (out / "verify_results.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def run(args: argparse.Namespace) -> int:
    rep = Report()
    started = time.perf_counter()
    source = Source(args.raw)
    print(f"scanning {args.raw} ...")
    rows = scan(source)
    sel = select(rows, args)
    summary: dict[str, Any] = {
        "script": "scripts/audit/verify_dataset_independent.py",
        "inputs": {
            "raw": str(args.raw),
            "manifest_dir": str(args.manifest_dir) if args.manifest_dir else None,
            "zip": str(args.zip) if args.zip else None,
            "mendeley_dir": str(args.mendeley_dir) if args.mendeley_dir else None,
        },
        "settings": {
            "duplicate_threshold": args.duplicate_threshold,
            "group_threshold": args.group_threshold,
            "seed": args.seed,
            "reviewed_duplicates": str(args.reviewed_duplicates),
        },
        "reviewed_duplicates_status": sel["reviewed_status"],
        "counts": counts(sel, rows, args.duplicate_threshold),
    }
    rep.check("C3 no unreadable images", summary["counts"]["n_unreadable"] == 0)
    rep.check(
        "C3 every original's file-name class agrees with its folder",
        not summary["counts"]["originals_whose_name_class_disagrees_with_folder"],
    )
    rep.check(
        "C3 publisher augmented copies only in the Kaggle train folder",
        all(
            k.startswith("train/")
            for k in summary["counts"]["publisher_augmented_by_folder_and_label"]
        ),
    )
    summary["split_hygiene"] = check_split_hygiene(sel, args, rep)
    if args.manifest_dir:
        summary["manifest_comparison"] = compare_manifest(
            sel, args.manifest_dir, args.duplicate_threshold, rep
        )
    if args.mendeley_dir:
        summary["mendeley"] = compare_mendeley(sel, args.mendeley_dir, rep)
    if args.zip:
        summary["zip"] = compare_zip(rows, args.zip, args.zip_root, args.expected_zip_sha256, rep)
    summary["checks"] = rep.checks
    summary["all_passed"] = rep.all_passed
    write_outputs(args.out, sel, rows, summary)
    print(
        f"done in {time.perf_counter() - started:.0f} s; "
        f"{sum(c['passed'] for c in rep.checks)}/{len(rep.checks)} checks passed -> {args.out}"
    )
    return 0 if rep.all_passed else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--raw", type=Path, required=True, help="raw folder or zip (read-only)")
    p.add_argument(
        "--manifest-dir", type=Path, help="prepare --manifest-only output to compare with"
    )
    p.add_argument("--zip", type=Path, help="export zip to compare with the raw folder (C2)")
    p.add_argument("--zip-root", default="kaggle_kebede", help="top folder inside the zip")
    p.add_argument("--expected-zip-sha256", help="published SHA-256 of the zip")
    p.add_argument("--mendeley-dir", type=Path, help="saved Mendeley listing JSON (C1)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--duplicate-threshold", type=int, default=4)  # ADR-0005
    p.add_argument(
        "--reviewed-duplicates",
        default=str(Path(__file__).resolve().parents[2] / "configs/data/reviewed_duplicates.yaml"),
        help="reviewed same-field list (ADR-0005); 'none' to disable",
    )
    p.add_argument("--group-threshold", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)
    args.reviewed = (
        None
        if str(args.reviewed_duplicates).lower() == "none"
        else load_reviewed(Path(args.reviewed_duplicates))
    )
    return args


if __name__ == "__main__":
    sys.exit(run(parse_args()))
