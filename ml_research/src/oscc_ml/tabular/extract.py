"""Streamed extraction of the tabular dataset from the kept images (Phase T).

Input: the manifest written by ``oscc-ml prepare`` (or ``prepare --manifest-only``) and the raw
folder it was built from. Rows with ``status == "ok"`` and a split in train/val/test are the kept
images; their split, label, magnification and group come **only** from the manifest (no new
split). Each image is read once, its SHA-256 is checked against the manifest, then it is decoded,
downsized and measured. Rows are written one by one, in ``image_id`` order, to ``*.partial`` files
renamed at the end, so memory stays flat and an interrupted run never leaves a half table.

Floats are written with 10 significant digits so two extractions produce byte-identical CSVs.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import Image

from oscc_ml.tabular import (
    CUES_FILE,
    EXTRACTION_INFO_FILE,
    FEATURES_FILE,
    ID_COLUMNS,
    METADATA_COLUMNS,
    TABULAR_FEATURES_VERSION,
    shortcut,
)
from oscc_ml.tabular import features as feat
from oscc_ml.utils.io import iso, utc_now

logger = logging.getLogger("oscc_ml.tabular")
SPLITS = ("train", "val", "test")


class ExtractionError(RuntimeError):
    """The inputs disagree with the manifest (hash, size, count) or a value is not finite."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def kept_rows(manifest: pd.DataFrame) -> pd.DataFrame:
    kept = manifest[(manifest["status"] == "ok") & manifest["split"].isin(SPLITS)].copy()
    return kept.sort_values("image_id").reset_index(drop=True)


def read_manifest(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        dtype={"image_id": str, "group_id": str, "magnification": str, "split": str, "sha256": str},
        keep_default_na=False,
    )


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ExtractionError(f"non-finite value {value!r}")
        text = f"{value:.10g}"
        return "0" if text == "-0" else text
    return str(value)


def measure(data: bytes) -> tuple[dict[str, Any], dict[str, Any], tuple[int, int]]:
    """Features and shortcut cues of one encoded image."""
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        cues = shortcut.file_cues(image, len(data))
        small = feat.downsize(image)
        features = feat.features_of_downsized(small)
        size = image.size
    cues.update(shortcut.global_colour_histogram(small))
    return features, cues, size


def extract(
    manifest_path: Path,
    raw_root: Path,
    out_dir: Path,
    *,
    limit: int | None = None,
    progress_every: int = 50,
) -> dict[str, Any]:
    manifest = read_manifest(manifest_path)
    kept = kept_rows(manifest)
    if limit is not None:
        kept = kept.iloc[:limit]
    if kept.empty:
        raise ExtractionError(f"no kept images in {manifest_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    feat_path, cues_path = out_dir / FEATURES_FILE, out_dir / CUES_FILE
    feat_tmp = feat_path.with_suffix(".csv.partial")
    cues_tmp = cues_path.with_suffix(".csv.partial")

    started = time.perf_counter()
    feature_columns: list[str] | None = None
    cue_columns: list[str] | None = None
    n_fallback = 0
    with (
        feat_tmp.open("w", newline="", encoding="utf-8") as fh,
        cues_tmp.open("w", newline="", encoding="utf-8") as ch,
    ):
        fw = csv.writer(fh, lineterminator="\n")
        cw = csv.writer(ch, lineterminator="\n")
        for n, row in enumerate(kept.itertuples(index=False), start=1):
            path = raw_root / str(row.original_path)
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != row.sha256:
                raise ExtractionError(f"{row.original_path}: SHA-256 differs from the manifest")
            features, cues, size = measure(data)
            if size != (int(row.width), int(row.height)):
                raise ExtractionError(f"{row.original_path}: size {size} differs from the manifest")
            n_fallback += int(features["tissue_mask_fallback"])
            ids = [row.image_id, row.split, int(row.label), row.magnification, row.group_id]
            meta = [int(row.width), int(row.height), row.original_path]
            if feature_columns is None:
                feature_columns = list(features)
                cue_columns = list(cues)
                fw.writerow([*ID_COLUMNS, *METADATA_COLUMNS, *feature_columns])
                cw.writerow([*ID_COLUMNS, *cue_columns])
            if list(features) != feature_columns or list(cues) != cue_columns:
                raise ExtractionError(f"{row.original_path}: feature columns changed")
            fw.writerow([*ids, *meta, *(_fmt(features[c]) for c in feature_columns)])
            cw.writerow([*ids, *(_fmt(cues[c]) for c in cue_columns or [])])
            if n % progress_every == 0 or n == len(kept):
                rate = (time.perf_counter() - started) / n
                logger.info(
                    "tabular features: %d/%d images (%.2f s/image, about %.0f s left)",
                    n,
                    len(kept),
                    rate,
                    rate * (len(kept) - n),
                )
    feat_tmp.replace(feat_path)
    cues_tmp.replace(cues_path)
    seconds = time.perf_counter() - started

    check = check_table(feat_path, manifest_path, limit=limit)
    info: dict[str, Any] = {
        "tabular_features_version": TABULAR_FEATURES_VERSION,
        "features_file": FEATURES_FILE,
        "features_sha256": sha256_file(feat_path),
        "cues_file": CUES_FILE,
        "cues_sha256": sha256_file(cues_path),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "raw_root": str(raw_root),
        "n_images": len(kept),
        "n_feature_columns": len(feature_columns or []),
        "n_cue_columns": len(cue_columns or []),
        "n_tissue_mask_fallback": n_fallback,
        "counts": check["counts"],
        "checks": check,
        "settings": {
            "downsample": f"PIL Image.reduce({feat.DOWNSAMPLE}) (4x4 box average)",
            "tissue_rule": f"saturation > min(Otsu, {feat.MAX_TISSUE_THRESHOLD}) (ADR-0002)",
            "min_tissue_pixels": feat.MIN_TISSUE_PIXELS,
            "glcm_levels": feat.GLCM_LEVELS,
            "glcm_distances": list(feat.GLCM_DISTANCES),
            "glcm_angles_deg": list(feat.GLCM_ANGLES),
            "lbp": "riu2, 8 square neighbours, radius 1",
            "stain_vectors": "Ruifrok & Johnston 2001 (H, E, residual), rows normalised",
            "min_blob_pixels": feat.MIN_BLOB_PIXELS,
        },
        "limit": limit,
        "seconds": round(seconds, 1),
        "seconds_per_image": round(seconds / len(kept), 4),
        "created_at": iso(utc_now()),
    }
    (out_dir / EXTRACTION_INFO_FILE).write_text(
        json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return info


def check_table(
    table_path: Path, manifest_path: Path, *, limit: int | None = None
) -> dict[str, Any]:
    """Rows = kept images, no missing or non-finite value, and image_id/split/label/magnification/
    group exactly equal to the manifest. Raises ExtractionError on any failure."""
    table = pd.read_csv(table_path, dtype={"image_id": str, "group_id": str, "magnification": str})
    kept = kept_rows(read_manifest(manifest_path))
    if limit is not None:
        kept = kept.iloc[:limit]
    problems: list[str] = []
    if len(table) != len(kept):
        problems.append(f"{len(table)} rows but {len(kept)} kept images")
    if table["image_id"].duplicated().any():
        problems.append("duplicate image_id")
    numeric = table.drop(columns=[*ID_COLUMNS, "original_path"])
    if numeric.isna().any().any():
        problems.append(f"missing values in {sorted(numeric.columns[numeric.isna().any()])}")
    if not numeric.map(lambda v: math.isfinite(float(v))).all().all():
        problems.append("non-finite values")
    merged = table.merge(kept, on="image_id", how="outer", suffixes=("", "_m"), indicator=True)
    if (merged["_merge"] != "both").any():
        problems.append("image_id sets differ from the manifest")
    else:
        for col in ("split", "label", "magnification", "group_id"):
            if (merged[col].astype(str) != merged[f"{col}_m"].astype(str)).any():
                problems.append(f"{col} differs from the manifest")
    if problems:
        raise ExtractionError("tabular table check failed: " + "; ".join(problems))
    counts = {
        split: {
            "images": int((table["split"] == split).sum()),
            "non_oscc": int(((table["split"] == split) & (table["label"] == 0)).sum()),
            "oscc": int(((table["split"] == split) & (table["label"] == 1)).sum()),
        }
        for split in SPLITS
    }
    return {
        "rows_equal_kept_images": True,
        "no_missing_or_non_finite": True,
        "ids_split_label_magnification_group_equal_manifest": True,
        "counts": counts,
    }
