"""``oscc-ml prepare``: raw zip/folder -> prepared dataset (manifest, dedup, split, patches).

Two streaming passes over the source; at most one image is in memory at a time:

1. Hash pass: SHA-256 and the eight dihedral pHashes of every image, plus width/height, label,
   magnification and original split from the path.
2. Patch pass: kept images only, tiled with the shared ``oscc_ml.preprocess`` rule (O5) and
   appended to ``patches_<split>.u8``.

In between: duplicate clusters (augmented copies and re-saves) keep one representative; groups
(patient IDs if ``--group-regex`` is given, else pHash similarity clusters, a documented
deviation); grouped stratified 70:15:15 split with seed 42; the leakage test.

Output (atomic: written to ``<out>.partial`` and renamed when complete):
    dataset.json, manifest.csv (every image, kept or not), images.csv, summary.csv,
    patches_<split>.u8 + patches_<split>.csv
If ``<out>`` already holds a dataset built from the same input with the same settings, the step is
skipped.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pandas as pd

from oscc_ml.data.dedup import N_TRANSFORMS, clusters, dihedral_phashes, min_distances, nearest
from oscc_ml.data.processed import (
    SPLITS,
    PatchMeta,
    PatchWriter,
    write_dataset_info,
    write_images_table,
)
from oscc_ml.data.sources import (
    ImageSource,
    UnlabelledPathError,
    decode,
    infer_label,
    infer_magnification,
    infer_original_split,
)
from oscc_ml.data.split import check_leakage, grouped_split
from oscc_ml.preprocess import PREPROCESS_VERSION, TilingParams, load_rgb, tile_image
from oscc_ml.utils.io import iso, read_json, utc_now, write_json

logger = logging.getLogger("oscc_ml.data")
TARGET_FRACTIONS = {"train": 0.70, "val": 0.15, "test": 0.15}
MAX_FRACTION_DEVIATION = 0.10


LABEL_CONFLICT = "label_conflict"
MANIFEST_ONLY_INFO = "manifest_only.json"
MANIFEST_COLUMNS = [
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
    "duplicate_of",
    "duplicate_cluster",
    "publisher_augmented",
    "nearest_original_distance",
    "original_split",
    "split",
    "n_patches",
    "n_grid_tiles",
    "tiling_mode",
    "size_bytes",
    "status",
]


class PrepareError(RuntimeError):
    """The input cannot be turned into a valid dataset; the message says why."""


def label_conflicts(candidates: pd.DataFrame) -> pd.DataFrame:
    """Duplicate clusters whose members carry both labels (ADR-0003). One row per cluster:
    ``duplicate_cluster``, ``n_images``, ``byte_identical`` (True if two members with different
    labels have the same SHA-256; False means a pHash near-duplicate conflict) and ``paths``."""
    rows: list[dict[str, Any]] = []
    for cluster, frame in candidates.groupby("duplicate_cluster"):
        if frame["label"].nunique() < 2:
            continue
        identical = bool((frame.groupby("sha256")["label"].nunique() > 1).any())
        rows.append(
            {
                "duplicate_cluster": cluster,
                "n_images": len(frame),
                "byte_identical": identical,
                "paths": " | ".join(sorted(frame["original_path"])),
            }
        )
    frame = pd.DataFrame(rows, columns=["duplicate_cluster", "n_images", "byte_identical", "paths"])
    return frame.astype({"n_images": int, "byte_identical": bool})


@dataclass(frozen=True)
class PrepareSettings:
    dataset_version: str = "oscc-unified-v1"
    source_name: str = "kaggle_kebede"
    seed: int = 42
    duplicate_threshold: int = 6
    group_threshold: int = 10
    group_regex: str | None = None
    # File names the publisher uses for augmented copies (Kaggle release: train/*/aug_<n>_<n>.jpg,
    # 224 x 224 crops/resizes). They are excluded by name before deduplication; pHash alone
    # cannot be trusted to link a 224 px crop to its 2048 px original.
    augmented_name_regex: str | None = r"^aug_"
    tiling: TilingParams = field(default_factory=TilingParams)


def _progress(done: int, total: int, started: float, what: str) -> None:
    if done == total or done % 100 == 0:
        elapsed = time.perf_counter() - started
        eta = elapsed / max(done, 1) * (total - done)
        logger.info(
            "%s: %d/%d images (%.0f s elapsed, ~%.0f s left)", what, done, total, elapsed, eta
        )


def _hash_pass(source: ImageSource, settings: PrepareSettings) -> tuple[pd.DataFrame, np.ndarray]:
    entries = source.list_images()
    if not entries:
        raise PrepareError(f"no images (.jpg/.png/.tif/.bmp) found in {source.location}")
    unlabelled = [e.path for e in entries if infer_label(e.path) is None]
    if unlabelled:
        raise UnlabelledPathError(
            f"{len(unlabelled)} image path(s) name no class folder (normal/OSCC), e.g. "
            f"{unlabelled[:3]}; labels are never guessed. Check the archive layout."
        )
    rows: list[dict[str, Any]] = []
    hashes: list[np.ndarray] = []
    started = time.perf_counter()
    for i, entry in enumerate(entries, start=1):
        data = source.read(entry.path)
        row: dict[str, Any] = {
            "original_path": entry.path,
            "label": infer_label(entry.path),
            "magnification": infer_magnification(entry.path),
            "original_split": infer_original_split(entry.path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": entry.size_bytes,
            "status": "ok",
        }
        try:
            image = decode(data)
            row["width"], row["height"] = image.size
            variants = dihedral_phashes(image)
            row["phash"] = f"{int(variants[0]):016x}"
        except Exception as exc:  # unreadable image: recorded, excluded, never fatal
            row.update(
                status=f"unreadable: {type(exc).__name__}", width=None, height=None, phash=None
            )
            variants = np.zeros(N_TRANSFORMS, dtype=np.uint64)
        rows.append(row)
        hashes.append(variants)
        _progress(i, len(entries), started, "hashing")
    return pd.DataFrame(rows), np.stack(hashes)


def _representative_order(frame: pd.DataFrame) -> pd.DataFrame:
    """Within a duplicate cluster prefer: an image from the publisher's val/test folders (not
    augmented, plan section 3), then the largest image, then the shortest path, then path order."""
    rank = frame["original_split"].map({"val": 0, "test": 0}).fillna(1)
    pixels = (frame["width"].fillna(0) * frame["height"].fillna(0)).astype(float)
    return frame.assign(_rank=rank, _px=-pixels, _len=frame["original_path"].str.len()).sort_values(
        ["_rank", "_px", "_len", "original_path"]
    )


def _assign_groups(
    kept: pd.DataFrame, sub_distances: np.ndarray, settings: PrepareSettings
) -> list[str]:
    if settings.group_regex:
        pattern = re.compile(settings.group_regex)
        groups = []
        for path in kept["original_path"]:
            match = pattern.search(path)
            if not match:
                raise PrepareError(
                    f"--group-regex {settings.group_regex!r} does not match {path!r}"
                )
            groups.append("patient-" + (match.group(1) if match.groups() else match.group(0)))
        return groups
    labels = clusters(sub_distances, settings.group_threshold)
    return [f"simgroup-{int(label):05d}" for label in labels]


def protocol_tiling(max_tissue_threshold: int | None = None) -> TilingParams:
    """Tiling parameters from configs/protocol.yaml (O5 + ADR-0002). ``max_tissue_threshold``
    overrides the protocol's cap (ablations only; 255 = plain Otsu)."""
    from oscc_ml.config import load_protocol

    cfg = load_protocol().data.tiling
    return TilingParams(
        patch_size=cfg.patch_size,
        resize_if_both_sides_below=cfg.resize_if_both_sides_below,
        min_tissue_fraction=cfg.min_tissue_fraction,
        max_patches_per_image=cfg.max_patches_per_image,
        max_tissue_threshold=(
            cfg.max_tissue_threshold if max_tissue_threshold is None else max_tissue_threshold
        ),
    )


def settings_record(settings: PrepareSettings) -> dict[str, Any]:
    record = asdict(settings)
    record["tiling"] = asdict(settings.tiling)
    return record


def prepare(
    raw: Path,
    out: Path,
    settings: PrepareSettings | None = None,
    force: bool = False,
    manifest_only: bool = False,
) -> Path:
    """Build a prepared dataset. With ``manifest_only`` the patch pass is skipped: ``out`` gets
    manifest.csv, summary.csv (patch counts 0) and manifest_only.json, never dataset.json, so it
    can never be mistaken for (or used as) a training dataset. A dry run of everything up to and
    including the split and the leakage test, streaming one image at a time."""
    settings = settings or PrepareSettings()
    if manifest_only and out.exists() and not (out / MANIFEST_ONLY_INFO).is_file():
        raise PrepareError(
            f"{out} exists and is not a manifest-only folder; choose a new --out for a dry run"
        )
    with ImageSource(raw) as source:
        fingerprint = source.fingerprint()
        existing = out / "dataset.json"
        if existing.is_file() and not manifest_only:
            info = read_json(existing)
            if info.get("source") == fingerprint and info.get("settings") == settings_record(
                settings
            ):
                logger.info("prepare: %s already built from this input, skipping", out)
                return out
            if not force:
                raise PrepareError(
                    f"{out} already holds a dataset built from different input or settings; "
                    "use --force to rebuild it or choose another --out"
                )
        partial = out.with_name(out.name + ".partial")
        if partial.exists():
            shutil.rmtree(partial)
        partial.mkdir(parents=True)
        started = time.perf_counter()

        manifest, hashes = _hash_pass(source, settings)
        manifest["image_id"] = [f"{settings.source_name}-{s[:16]}" for s in manifest["sha256"]]
        name_pattern = (
            re.compile(settings.augmented_name_regex) if settings.augmented_name_regex else None
        )
        manifest["publisher_augmented"] = [
            bool(name_pattern and name_pattern.search(PurePosixPath(p).name))
            for p in manifest["original_path"]
        ]
        readable = manifest["status"].eq("ok").to_numpy()
        candidates = readable & ~manifest["publisher_augmented"].to_numpy(dtype=bool)
        if not candidates.any():
            raise PrepareError("no readable original images left after excluding augmented copies")

        # Duplicate clusters among the originals (exact copies have distance 0).
        positions = np.flatnonzero(candidates)
        distances = min_distances(hashes[positions])
        dup_labels = clusters(distances, settings.duplicate_threshold)
        manifest["duplicate_cluster"] = None
        manifest.loc[positions, "duplicate_cluster"] = [f"dup-{int(c):05d}" for c in dup_labels]
        # ADR-0003: a duplicate cluster whose members carry both labels has no trustworthy label
        # (the Rahman release holds 14 byte-identical Normal/OSCC pairs). Every member is
        # excluded (status "label_conflict"); none of them is used for training or testing.
        conflicts = label_conflicts(manifest.loc[positions])
        conflict_clusters = set(conflicts["duplicate_cluster"])
        if conflict_clusters:
            members = manifest["duplicate_cluster"].isin(conflict_clusters)
            manifest.loc[members, "status"] = LABEL_CONFLICT
            logger.warning(
                "%d duplicate cluster(s) carry both labels (%d byte-identical, %d near-duplicate);"
                " all %d member images are excluded (ADR-0003)",
                len(conflicts),
                int(conflicts["byte_identical"].sum()),
                int((~conflicts["byte_identical"]).sum()),
                int(members.sum()),
            )

        manifest["is_augmented_copy"] = False
        manifest["duplicate_of"] = None
        manifest["kept"] = False
        for cluster, frame in manifest.loc[positions].groupby("duplicate_cluster"):
            if cluster in conflict_clusters:
                continue
            ordered = _representative_order(frame)
            keep_index = ordered.index[0]
            manifest.loc[keep_index, "kept"] = True
            others = ordered.index[1:]
            manifest.loc[others, "is_augmented_copy"] = True
            manifest.loc[others, "duplicate_of"] = manifest.loc[keep_index, "image_id"]

        # Byte-identical files share a SHA-256-derived id; make ids unique per manifest row.
        # The kept image keeps the base id (so duplicate_of stays valid); copies get -copyN.
        for _, same in manifest.groupby("image_id"):
            if len(same) < 2:
                continue
            copies = same.index[~same["kept"].to_numpy(dtype=bool)]
            for n, idx in enumerate(copies, start=1):
                manifest.loc[idx, "image_id"] = f"{manifest.loc[idx, 'image_id']}-copy{n}"

        # Publisher-named augmented copies: excluded. For the audit, record how close each one is
        # to its nearest kept original (<= duplicate_threshold means pHash would also catch it).
        aug_positions = np.flatnonzero(
            readable & manifest["publisher_augmented"].to_numpy(dtype=bool)
        )
        manifest["nearest_original_distance"] = None
        if len(aug_positions):
            kept_now = np.flatnonzero(manifest["kept"].to_numpy(dtype=bool))
            near_dist, near_idx = nearest(hashes[aug_positions], hashes[kept_now])
            manifest.loc[aug_positions, "nearest_original_distance"] = near_dist
            manifest.loc[aug_positions, "is_augmented_copy"] = True
            close = near_dist <= settings.duplicate_threshold
            manifest.loc[aug_positions[close], "duplicate_of"] = manifest.loc[
                kept_now[near_idx[close]], "image_id"
            ].to_numpy()

        kept_mask = manifest["kept"].to_numpy(dtype=bool)
        kept_positions = np.flatnonzero(kept_mask)
        index_in_readable = {int(p): i for i, p in enumerate(positions)}
        sub_idx = np.array([index_in_readable[int(p)] for p in kept_positions])
        sub_distances = distances[np.ix_(sub_idx, sub_idx)]
        kept = manifest.loc[kept_positions].copy()
        kept["group_id"] = _assign_groups(kept, sub_distances, settings)
        kept["split"] = grouped_split(
            kept["label"].astype(int).tolist(), kept["group_id"].tolist(), settings.seed
        )

        fractions = kept["split"].value_counts(normalize=True)
        off = {
            s: float(fractions.get(s, 0.0))
            for s in SPLITS
            if abs(float(fractions.get(s, 0.0)) - TARGET_FRACTIONS[s]) > MAX_FRACTION_DEVIATION
        }
        if off:
            largest = int(kept["group_id"].value_counts().iloc[0])
            raise PrepareError(
                f"split proportions {off} are more than {MAX_FRACTION_DEVIATION:.0%} "
                "from 70:15:15; "
                f"the largest group has {largest} images. Lower --group-threshold (similar images "
                "are being chained into very large groups) and run prepare again."
            )
        check_leakage(
            kept,
            distances=sub_distances,
            positions={iid: i for i, iid in enumerate(kept["image_id"])},
            near_threshold=settings.group_threshold,
        )
        logger.info(
            "leakage test passed: no SHA-256, duplicate cluster, group or near-duplicate "
            "spans two splits"
        )

        manifest["group_id"] = None
        manifest["split"] = "excluded"
        manifest.loc[kept.index, "group_id"] = kept["group_id"]
        manifest.loc[kept.index, "split"] = kept["split"]
        manifest["n_patches"] = 0
        manifest["n_grid_tiles"] = 0
        manifest["tiling_mode"] = None

        if manifest_only:
            _write_manifest(partial, manifest, settings)
            write_json(
                partial / MANIFEST_ONLY_INFO,
                {
                    "manifest_only": True,
                    "note": "dry run: no patches were extracted; not a training dataset",
                    "dataset_version": settings.dataset_version,
                    "preprocess_version": PREPROCESS_VERSION,
                    "seed": settings.seed,
                    "source": fingerprint,
                    "settings": settings_record(settings),
                    **_selection_counts(manifest, conflicts, settings),
                    "created_at": iso(utc_now()),
                    "seconds": round(time.perf_counter() - started, 1),
                    "leakage_test": "passed",
                },
            )
            if out.exists():
                shutil.rmtree(out)
            partial.rename(out)
            print_manifest_only(read_json(out / MANIFEST_ONLY_INFO))
            return out

        # Pass 2: patches for kept images, split by split.
        tiling = settings.tiling
        image_rows: list[dict[str, Any]] = []
        done, total, patch_started = 0, len(kept), time.perf_counter()
        for split in SPLITS:
            subset = kept[kept["split"] == split].sort_values("image_id")
            with PatchWriter(partial, split, tiling.patch_size) as writer:
                for idx, row in subset.iterrows():
                    rgb = load_rgb(decode(source.read(row["original_path"])))
                    result = tile_image(rgb, tiling)
                    for p, patch in enumerate(result.patches):
                        writer.add(
                            patch,
                            PatchMeta(
                                row["image_id"],
                                p,
                                int(row["label"]),
                                row["group_id"],
                                settings.source_name,
                                row["magnification"],
                            ),
                        )
                    manifest.loc[idx, "n_patches"] = len(result.patches)
                    manifest.loc[idx, "n_grid_tiles"] = result.grid_candidates
                    manifest.loc[idx, "tiling_mode"] = result.mode
                    image_rows.append(
                        {
                            "image_id": row["image_id"],
                            "split": split,
                            "label": int(row["label"]),
                            "group_id": row["group_id"],
                            "source": settings.source_name,
                            "magnification": row["magnification"],
                            "n_patches": len(result.patches),
                        }
                    )
                    done += 1
                    _progress(done, total, patch_started, "patching")

        write_images_table(partial, image_rows)
        _write_manifest(partial, manifest, settings)

        kept_final = manifest[manifest["kept"]]
        write_dataset_info(
            partial,
            {
                "dataset_version": settings.dataset_version,
                "preprocess_version": PREPROCESS_VERSION,
                "patch_size": tiling.patch_size,
                "seed": settings.seed,
                "source": fingerprint,
                "settings": settings_record(settings),
                "grouping": "regex patient id"
                if settings.group_regex
                else "pHash similarity cluster (no patient IDs; documented deviation)",
                "counts": {
                    split: {
                        "images": int((kept_final["split"] == split).sum()),
                        "patches": int(
                            kept_final.loc[kept_final["split"] == split, "n_patches"].sum()
                        ),
                    }
                    for split in SPLITS
                },
                "n_source_images": len(manifest),
                "n_unreadable": _n_unreadable(manifest),
                "n_publisher_augmented_excluded": int(manifest["publisher_augmented"].sum()),
                "n_publisher_augmented_matching_an_original": int(
                    (
                        pd.to_numeric(manifest["nearest_original_distance"], errors="coerce")
                        <= settings.duplicate_threshold
                    ).sum()
                ),
                "n_duplicates_removed": int(
                    (manifest["is_augmented_copy"] & ~manifest["publisher_augmented"]).sum()
                ),
                "n_kept_images": len(kept_final),
                "n_groups": int(kept_final["group_id"].nunique()),
                "tiling_fallbacks": int((manifest["tiling_mode"] == "grid_fallback").sum()),
                # Share of full 224 px grid tiles that passed the tissue filter (gridded images);
                # a low value means the O5 tissue filter is discarding much of the image.
                "grid_tile_keep_rate": _keep_rate(kept_final),
                "created_at": iso(utc_now()),
                "seconds": round(time.perf_counter() - started, 1),
                "leakage_test": "passed",
                **_conflict_counts(conflicts),
            },
        )
    if out.exists():
        shutil.rmtree(out)
    partial.rename(out)
    print_summary(read_json(out / "dataset.json"), pd.read_csv(out / "summary.csv"))
    return out


def _write_manifest(folder: Path, manifest: pd.DataFrame, settings: PrepareSettings) -> None:
    manifest["source"] = settings.source_name
    manifest[MANIFEST_COLUMNS].to_csv(folder / "manifest.csv", index=False)
    summarize(manifest).to_csv(folder / "summary.csv", index=False)


def _n_unreadable(manifest: pd.DataFrame) -> int:
    return int(manifest["status"].astype(str).str.startswith("unreadable").sum())


def _conflict_counts(conflicts: pd.DataFrame) -> dict[str, Any]:
    """ADR-0003 counts recorded in dataset.json (and manifest_only.json)."""
    return {
        "n_label_conflict_clusters": {
            "byte_identical": int(conflicts["byte_identical"].sum()),
            "near_duplicate": int((~conflicts["byte_identical"].astype(bool)).sum()),
        },
        "n_label_conflict_images_excluded": int(conflicts["n_images"].sum()),
        "label_conflicts": [
            {
                "duplicate_cluster": str(row.duplicate_cluster),
                "byte_identical": bool(row.byte_identical),
                "paths": str(row.paths).split(" | "),
            }
            for row in conflicts.itertuples()
        ],
    }


def _selection_counts(
    manifest: pd.DataFrame, conflicts: pd.DataFrame, settings: PrepareSettings
) -> dict[str, Any]:
    kept = manifest[manifest["kept"]]
    per_split = {
        split: {
            "images": int((kept["split"] == split).sum()),
            "by_class": {
                name: int(((kept["split"] == split) & (kept["label"] == label)).sum())
                for label, name in ((0, "non_oscc"), (1, "oscc"))
            },
        }
        for split in SPLITS
    }
    return {
        "counts": per_split,
        "n_source_images": len(manifest),
        "n_unreadable": _n_unreadable(manifest),
        "n_publisher_augmented_excluded": int(manifest["publisher_augmented"].sum()),
        "n_publisher_augmented_matching_an_original": int(
            (
                pd.to_numeric(manifest["nearest_original_distance"], errors="coerce")
                <= settings.duplicate_threshold
            ).sum()
        ),
        "n_duplicates_removed": int(
            (manifest["is_augmented_copy"] & ~manifest["publisher_augmented"]).sum()
        ),
        "n_kept_images": len(kept),
        "n_groups": int(kept["group_id"].nunique()),
        "largest_group": int(kept["group_id"].value_counts().iloc[0]) if len(kept) else 0,
        **_conflict_counts(conflicts),
    }


def print_manifest_only(info: dict[str, Any]) -> None:
    print("")
    print(f"MANIFEST-ONLY dry run of {info['dataset_version']} (no patches extracted)")
    for key in (
        "n_source_images",
        "n_unreadable",
        "n_publisher_augmented_excluded",
        "n_publisher_augmented_matching_an_original",
        "n_duplicates_removed",
        "n_label_conflict_clusters",
        "n_label_conflict_images_excluded",
        "n_kept_images",
        "n_groups",
        "largest_group",
    ):
        print(f"  {key}: {info[key]}")
    for split in SPLITS:
        counts = info["counts"][split]
        print(f"  {split:>5}: {counts['images']} images {counts['by_class']}")
    print(f"  leakage test: {info['leakage_test']}")


def _keep_rate(kept: pd.DataFrame) -> float | None:
    gridded = kept[kept["tiling_mode"].isin(["grid", "grid_fallback"])]
    tiles = int(gridded["n_grid_tiles"].sum())
    return round(int(gridded["n_patches"].sum()) / tiles, 4) if tiles else None


def summarize(manifest: pd.DataFrame) -> pd.DataFrame:
    """Counts per split x class x magnification (kept images and their patches)."""
    kept = manifest[manifest["kept"]].copy()
    kept["class"] = kept["label"].map({0: "non_oscc", 1: "oscc"})
    table = (
        kept.groupby(["split", "class", "magnification"])
        .agg(images=("image_id", "count"), patches=("n_patches", "sum"))
        .reset_index()
    )
    order = {s: i for i, s in enumerate(SPLITS)}
    return table.sort_values(
        ["split", "class", "magnification"], key=lambda c: c.map(order) if c.name == "split" else c
    )


def print_summary(info: dict[str, Any], summary: pd.DataFrame) -> None:
    print("")
    print(f"Dataset {info['dataset_version']} ({info['grouping']})")
    print(
        f"  source images: {info['n_source_images']}  unreadable: {info['n_unreadable']}  "
        f"publisher augmented copies excluded: {info['n_publisher_augmented_excluded']} "
        f"(pHash-matched to an original: {info['n_publisher_augmented_matching_an_original']})  "
        f"pHash duplicates removed: {info['n_duplicates_removed']}  "
        f"kept: {info['n_kept_images']}  groups: {info['n_groups']}  "
        f"tiling fallbacks: {info['tiling_fallbacks']}  "
        f"grid tiles kept: {info['grid_tile_keep_rate']}"
    )
    print(summary.to_string(index=False))
    for split in SPLITS:
        counts = info["counts"][split]
        print(f"  {split:>5}: {counts['images']} images, {counts['patches']} patches")
    print(f"  leakage test: {info['leakage_test']}")
