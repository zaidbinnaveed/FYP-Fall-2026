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
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from oscc_ml.data.dedup import N_TRANSFORMS, clusters, dihedral_phashes, min_distances
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
from oscc_ml.utils.io import iso, read_json, utc_now

logger = logging.getLogger("oscc_ml.data")
TARGET_FRACTIONS = {"train": 0.70, "val": 0.15, "test": 0.15}
MAX_FRACTION_DEVIATION = 0.10


class PrepareError(RuntimeError):
    """The input cannot be turned into a valid dataset; the message says why."""


@dataclass(frozen=True)
class PrepareSettings:
    dataset_version: str = "oscc-unified-v1"
    source_name: str = "kaggle_kebede"
    seed: int = 42
    duplicate_threshold: int = 6
    group_threshold: int = 10
    group_regex: str | None = None
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


def settings_record(settings: PrepareSettings) -> dict[str, Any]:
    record = asdict(settings)
    record["tiling"] = asdict(settings.tiling)
    return record


def prepare(
    raw: Path, out: Path, settings: PrepareSettings | None = None, force: bool = False
) -> Path:
    settings = settings or PrepareSettings()
    with ImageSource(raw) as source:
        fingerprint = source.fingerprint()
        existing = out / "dataset.json"
        if existing.is_file():
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
        readable = manifest["status"].eq("ok").to_numpy()
        manifest["image_id"] = [f"{settings.source_name}-{s[:16]}" for s in manifest["sha256"]]

        # Exact duplicates share an image_id; keep the first occurrence only.
        positions = np.flatnonzero(readable)
        distances = min_distances(hashes[positions])
        dup_labels = clusters(distances, settings.duplicate_threshold)
        manifest["duplicate_cluster"] = None
        manifest.loc[positions, "duplicate_cluster"] = [f"dup-{int(c):05d}" for c in dup_labels]
        conflicting = manifest.loc[positions].groupby("duplicate_cluster")["label"].nunique()
        if (conflicting > 1).any():
            examples = list(conflicting[conflicting > 1].index[:3])
            raise PrepareError(
                f"{int((conflicting > 1).sum())} duplicate cluster(s) contain both labels "
                f"(e.g. {examples}); inspect manifest.csv in {partial} and lower "
                "--duplicate-threshold"
            )

        manifest["is_augmented_copy"] = False
        manifest["duplicate_of"] = None
        manifest["kept"] = False
        for _, frame in manifest.loc[positions].groupby("duplicate_cluster"):
            ordered = _representative_order(frame)
            keep_index = ordered.index[0]
            manifest.loc[keep_index, "kept"] = True
            others = ordered.index[1:]
            manifest.loc[others, "is_augmented_copy"] = True
            manifest.loc[others, "duplicate_of"] = manifest.loc[keep_index, "image_id"]

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
        columns = [
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
            "original_split",
            "split",
            "n_patches",
            "n_grid_tiles",
            "tiling_mode",
            "size_bytes",
            "status",
        ]
        manifest["source"] = settings.source_name
        manifest[columns].to_csv(partial / "manifest.csv", index=False)
        summary = summarize(manifest)
        summary.to_csv(partial / "summary.csv", index=False)

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
                "n_unreadable": int((manifest["status"] != "ok").sum()),
                "n_duplicates_removed": int(manifest["is_augmented_copy"].sum()),
                "n_kept_images": len(kept_final),
                "n_groups": int(kept_final["group_id"].nunique()),
                "tiling_fallbacks": int((manifest["tiling_mode"] == "grid_fallback").sum()),
                # Share of full 224 px grid tiles that passed the tissue filter (gridded images);
                # a low value means the O5 tissue filter is discarding much of the image.
                "grid_tile_keep_rate": _keep_rate(kept_final),
                "created_at": iso(utc_now()),
                "seconds": round(time.perf_counter() - started, 1),
                "leakage_test": "passed",
            },
        )
    if out.exists():
        shutil.rmtree(out)
    partial.rename(out)
    print_summary(read_json(out / "dataset.json"), pd.read_csv(out / "summary.csv"))
    return out


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
        f"duplicates/augmented copies removed: {info['n_duplicates_removed']}  "
        f"kept: {info['n_kept_images']}  groups: {info['n_groups']}  "
        f"tiling fallbacks: {info['tiling_fallbacks']}  "
        f"grid tiles kept: {info['grid_tile_keep_rate']}"
    )
    print(summary.to_string(index=False))
    for split in SPLITS:
        counts = info["counts"][split]
        print(f"  {split:>5}: {counts['images']} images, {counts['patches']} patches")
    print(f"  leakage test: {info['leakage_test']}")
