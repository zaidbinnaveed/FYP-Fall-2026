"""``oscc-ml audit``: the dataset audit report (plan R1 step 3), generated from a prepared dataset.

Sources: ``manifest.csv`` and ``dataset.json`` of one prepared dataset, nothing else. That folder
is either the output of ``oscc-ml prepare`` or ``runs/dataset/<dataset_version>/`` after
``oscc-ml import-results results_small.zip`` (pack-results carries both files), so the audit can be
regenerated at home from the university run.

The report is labelled by what it describes: the full benchmark dataset (``oscc-unified-v1``
prepared from the complete source), a SAMPLE (anything else), or SYNTHETIC test data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from oscc_ml.catalog import is_synthetic
from oscc_ml.data.processed import LABEL_NAMES, SPLITS
from oscc_ml.data.split import LeakageError, check_leakage
from oscc_ml.paths import DEFAULT_DATASET_VERSION, ML_ROOT
from oscc_ml.utils.io import read_json

DEFAULT_AUDIT_PATH = ML_ROOT.parent / "docs" / "results" / "dataset_audit.md"
SAMPLE_BANNER = "SAMPLE ONLY — not the full dataset"
SYNTHETIC_BANNER = "SYNTHETIC TEST DATA — not histology, not the dataset"
FULL_BANNER = "Full benchmark dataset"
PATCH_BINS = [(1, 1), (2, 8), (9, 16), (17, 32), (33, 63), (64, 64)]
BOOL_COLUMNS = ("is_augmented_copy", "publisher_augmented")


class AuditError(RuntimeError):
    """The folder is not a prepared dataset (or misses one of the two source files)."""


def classify(info: dict[str, Any]) -> str:
    """``full`` | ``sample`` | ``synthetic`` (decides the banner)."""
    version = str(info.get("dataset_version", ""))
    if is_synthetic(version):
        return "synthetic"
    source = info.get("source") or {}
    if version == DEFAULT_DATASET_VERSION and source.get("name") != "sample":
        return "full"
    return "sample"


def load(prepared: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    info_path, manifest_path = prepared / "dataset.json", prepared / "manifest.csv"
    missing = [p.name for p in (info_path, manifest_path) if not p.is_file()]
    if missing:
        raise AuditError(
            f"{prepared} is missing {missing}; pass a folder made by `oscc-ml prepare` or "
            "runs/dataset/<dataset_version>/ after `oscc-ml import-results`"
        )
    manifest = pd.read_csv(manifest_path, dtype={"phash": str, "sha256": str})
    for column in BOOL_COLUMNS:
        manifest[column] = manifest[column].astype(str).str.lower().eq("true")
    return read_json(info_path), manifest


def _table(frame: pd.DataFrame) -> str:
    """Markdown table (no external dependency)."""
    if frame.empty:
        return "_(none)_"
    head = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    rule = "| " + " | ".join("---" for _ in frame.columns) + " |"
    rows = [
        "| " + " | ".join(_cell(v) for v in row) + " |" for row in frame.itertuples(index=False)
    ]
    return "\n".join([head, rule, *rows])


def _cell(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.1f}" if not value.is_integer() else f"{int(value):,}"
    if isinstance(value, int | np.integer):
        return f"{int(value):,}"
    return str(value).replace("|", "\\|")


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def _class(label: Any) -> str:
    return LABEL_NAMES.get(int(label), str(label))


def _counts_section(kept: pd.DataFrame) -> list[str]:
    frame = kept.assign(**{"class": kept["label"].map(_class)})
    table = (
        frame.groupby(["source", "class", "magnification", "split"])
        .agg(images=("image_id", "count"), patches=("n_patches", "sum"))
        .reset_index()
    )
    order = {s: i for i, s in enumerate(SPLITS)}
    table = table.sort_values(
        ["source", "class", "magnification", "split"],
        key=lambda c: c.map(order) if c.name == "split" else c,
    )
    wide = (
        frame.pivot_table(
            index=["source", "class", "magnification"],
            columns="split",
            values="image_id",
            aggfunc="count",
            fill_value=0,
        )
        .reindex(columns=list(SPLITS), fill_value=0)
        .reset_index()
    )
    wide["total"] = wide[list(SPLITS)].sum(axis=1)
    totals = frame.groupby(["split", "class"])["image_id"].count().unstack(fill_value=0)
    totals = totals.reindex(index=list(SPLITS), fill_value=0).reset_index()
    totals["images"] = totals.drop(columns="split").sum(axis=1)
    totals["share of kept"] = [_pct(n, len(kept)) for n in totals["images"]]
    return [
        "## 1. Counts per source x class x magnification x split (kept images)",
        "",
        _table(wide),
        "",
        "Images and patches:",
        "",
        _table(table),
        "",
        "Per split:",
        "",
        _table(totals),
        "",
    ]


def _sources_section(info: dict[str, Any], manifest: pd.DataFrame) -> list[str]:
    publisher = manifest[manifest["publisher_augmented"]]
    originals = manifest[~manifest["publisher_augmented"]]
    by_folder = (
        originals.assign(**{"class": originals["label"].map(_class)})
        .groupby(["original_split", "class"])["image_id"]
        .count()
        .unstack(fill_value=0)
        .reset_index()
    )
    aug_by = (
        publisher.assign(**{"class": publisher["label"].map(_class)})
        .groupby(["original_split", "class"])["image_id"]
        .count()
        .reset_index(name="aug_ files")
    )
    matched = pd.to_numeric(publisher["nearest_original_distance"], errors="coerce")
    threshold = info.get("settings", {}).get("duplicate_threshold")
    unreadable = manifest["status"].astype(str).str.startswith("unreadable")
    return [
        "## 2. Source files and publisher `aug_` copies",
        "",
        f"- Files read: **{len(manifest):,}**; unreadable: **{int(unreadable.sum())}**.",
        f"- Original images (not `aug_`): **{len(originals):,}**.",
        f"- Publisher augmented copies (`aug_*`, excluded by name): **{len(publisher):,}**; "
        f"of these, **{int((matched <= threshold).sum()) if threshold is not None else 'n/a'}** "
        f"are within pHash distance {threshold} of a kept original; the others are not linked "
        "by pHash (for example crops). All are excluded by name.",
        "",
        "Originals per publisher folder (before deduplication):",
        "",
        _table(by_folder),
        "",
        "`aug_` files per publisher folder:",
        "",
        _table(aug_by),
        "",
    ]


def _sizes_section(manifest: pd.DataFrame) -> list[str]:
    readable = manifest[manifest["status"] == "ok"].copy()
    readable["size"] = (
        readable["width"].astype("Int64").astype(str)
        + " x "
        + readable["height"].astype("Int64").astype(str)
    )
    readable["kind"] = np.where(readable["publisher_augmented"], "aug_ copy", "original")
    table = (
        readable.groupby(["kind", "size"])["image_id"].count().reset_index(name="images")
    ).sort_values(["kind", "images"], ascending=[True, False])
    return ["## 3. Image sizes (width x height, pixels)", "", _table(table), ""]


def _duplicates_section(info: dict[str, Any], manifest: pd.DataFrame) -> list[str]:
    originals = manifest[~manifest["publisher_augmented"] & manifest["duplicate_cluster"].notna()]
    sizes = originals.groupby("duplicate_cluster")["image_id"].count()
    multi = sizes[sizes > 1]
    removed = manifest[manifest["is_augmented_copy"] & ~manifest["publisher_augmented"]]
    by_id = manifest.set_index("image_id")["original_path"]
    removed_rows = pd.DataFrame(
        {
            "removed": removed["original_path"],
            "kept twin": [by_id.get(d, "?") for d in removed["duplicate_of"]],
            "byte-identical": [
                bool((manifest.loc[manifest["image_id"] == d, "sha256"] == s).any())
                for d, s in zip(removed["duplicate_of"], removed["sha256"], strict=True)
            ],
        }
    )
    settings = info.get("settings", {})
    lines = [
        "## 4. Duplicate clusters",
        "",
        f"Rule: originals within pHash Hamming distance **{settings.get('duplicate_threshold')}** "
        "(minimum over the 8 rotations/flips) or with the same SHA-256 form one cluster; each "
        "cluster keeps one image (prefers the publisher's val/test folders, then the largest).",
        "",
        f"- Clusters with more than one original: **{len(multi)}** "
        f"(sizes: {dict(sorted(multi.value_counts().items()))}).",
        f"- Same-label duplicates removed: **{len(removed)}**.",
        "",
        _table(removed_rows),
        "",
        "### Label conflicts (ADR-0003)",
        "",
    ]
    if "n_label_conflict_clusters" not in info:
        lines += ["_Not recorded: this dataset was prepared before ADR-0003._", ""]
        return lines
    counts = info["n_label_conflict_clusters"]
    lines += [
        f"Clusters whose images carry both labels are excluded as a whole: "
        f"**{counts['byte_identical']}** byte-identical and **{counts['near_duplicate']}** "
        f"near-duplicate clusters, **{info['n_label_conflict_images_excluded']}** images.",
        "",
    ]
    conflicts = pd.DataFrame(
        [
            {
                "cluster": c["duplicate_cluster"],
                "kind": "byte-identical" if c["byte_identical"] else "near-duplicate",
                "images": " · ".join(c["paths"]),
            }
            for c in info.get("label_conflicts", [])
        ]
    )
    lines += [_table(conflicts), ""]
    return lines


def _cross_split_near_pairs(kept: pd.DataFrame, threshold: int) -> int:
    """Pairs of kept images in different splits within ``threshold`` of each other, on the stored
    (identity-transform) pHash. prepare's own test also checks the 8 rotations/flips."""
    hashes = np.array([int(h, 16) for h in kept["phash"]], dtype=np.uint64)
    splits = kept["split"].to_numpy()
    count = 0
    for i in range(len(hashes) - 1):
        xor = np.bitwise_xor(hashes[i], hashes[i + 1 :])
        dist = np.array([bin(int(v)).count("1") for v in xor])
        count += int(((dist <= threshold) & (splits[i + 1 :] != splits[i])).sum())
    return count


def _leakage_section(info: dict[str, Any], kept: pd.DataFrame) -> list[str]:
    spans = {
        column: int((kept.groupby(column)["split"].nunique() > 1).sum())
        for column in ("sha256", "duplicate_cluster", "group_id")
    }
    try:
        check_leakage(kept)
        recheck = "passed"
    except LeakageError as exc:
        recheck = f"FAILED: {exc}"
    threshold = int(info.get("settings", {}).get("group_threshold", 10))
    near = _cross_split_near_pairs(kept, threshold)
    group_sizes = kept.groupby("group_id")["image_id"].count()
    return [
        "## 5. Grouping and leakage test",
        "",
        f"- Grouping: **{info.get('grouping')}**. Groups: **{group_sizes.size:,}**; "
        f"group size min {group_sizes.min()}, median {int(group_sizes.median())}, "
        f"max {group_sizes.max()}.",
        f"- Leakage test recorded by prepare: **{info.get('leakage_test')}**.",
        f"- Re-checked here from the manifest: **{recheck}** — values spanning two splits: "
        f"SHA-256 {spans['sha256']}, duplicate cluster {spans['duplicate_cluster']}, "
        f"group {spans['group_id']}; cross-split pairs within pHash distance {threshold}: "
        f"**{near}**.",
        "",
    ]


def _tissue_section(info: dict[str, Any], kept: pd.DataFrame) -> list[str]:
    tiling = info.get("settings", {}).get("tiling", {})
    modes = kept["tiling_mode"].value_counts().to_dict()
    gridded = kept[kept["tiling_mode"].isin(["grid", "grid_fallback"])]
    tiles, patches = int(gridded["n_grid_tiles"].sum()), int(gridded["n_patches"].sum())
    capped = gridded[gridded["n_patches"] >= int(tiling.get("max_patches_per_image", 64))]
    frame = kept.assign(**{"class": kept["label"].map(_class)})
    per = (
        frame[frame["tiling_mode"].isin(["grid", "grid_fallback"])]
        .groupby(["class", "magnification"])
        .agg(
            images=("image_id", "count"),
            grid_tiles=("n_grid_tiles", "sum"),
            kept_patches=("n_patches", "sum"),
            one_tile=("n_patches", lambda s: int((s == 1).sum())),
        )
        .reset_index()
    )
    per["kept share"] = [
        _pct(k, t) for k, t in zip(per["kept_patches"], per["grid_tiles"], strict=True)
    ]
    return [
        "## 6. Tissue filter (O5 + ADR-0002)",
        "",
        f"Settings: patch {tiling.get('patch_size')} px; resize when both sides < "
        f"{tiling.get('resize_if_both_sides_below')} px; tissue = saturation > min(Otsu, "
        f"{tiling.get('max_tissue_threshold')}); keep tiles with ≥ "
        f"{tiling.get('min_tissue_fraction')} tissue; at most "
        f"{tiling.get('max_patches_per_image')} patches per image; preprocess "
        f"`{info.get('preprocess_version')}`.",
        "",
        f"- Tiling modes: {dict(sorted(modes.items()))}.",
        f"- Grid tiles kept: **{patches:,} / {tiles:,} = {_pct(patches, tiles)}**; images "
        f"limited by the {tiling.get('max_patches_per_image')}-patch cap: **{len(capped)}**.",
        f"- Images reduced to one tile: **{int((gridded['n_patches'] == 1).sum())}** "
        f"(of which no tile reached the tissue threshold, `grid_fallback`: "
        f"**{modes.get('grid_fallback', 0)}**).",
        "",
        _table(per),
        "",
    ]


def _patches_section(kept: pd.DataFrame) -> list[str]:
    frame = kept.assign(**{"class": kept["label"].map(_class)})
    stats = (
        frame.groupby(["class", "magnification"])["n_patches"]
        .describe(percentiles=[0.25, 0.5, 0.75])
        .reset_index()
        .rename(columns={"count": "images", "25%": "p25", "50%": "median", "75%": "p75"})
    )
    stats = stats[
        ["class", "magnification", "images", "min", "p25", "median", "p75", "max", "mean"]
    ]
    bins = pd.DataFrame(
        [
            {
                "patches per image": f"{lo}" if lo == hi else f"{lo}-{hi}",
                **{
                    s: int(((kept["split"] == s) & kept["n_patches"].between(lo, hi)).sum())
                    for s in SPLITS
                },
            }
            for lo, hi in PATCH_BINS
        ]
    )
    return [
        "## 7. Patches per image",
        "",
        _table(stats),
        "",
        "Images per patch-count bin and split:",
        "",
        _table(bins),
        "",
    ]


def build_audit(prepared: Path) -> tuple[str, str]:
    """(markdown, kind). ``kind`` is full | sample | synthetic."""
    info, manifest = load(prepared)
    kind = classify(info)
    kept = manifest[manifest["split"].isin(SPLITS)].copy()
    banner = {"full": FULL_BANNER, "sample": SAMPLE_BANNER, "synthetic": SYNTHETIC_BANNER}[kind]
    source = info.get("source") or {}
    lines = [
        f"# Dataset audit: `{info.get('dataset_version')}`",
        "",
        f"> **{banner}.**"
        + (
            " Numbers below describe a small development sample; the reportable audit is "
            "regenerated from the university run (`oscc-ml audit --prepared "
            "runs/dataset/oscc-unified-v1` after `import-results`)."
            if kind != "full"
            else ""
        ),
        "",
        "Generated by `oscc-ml audit` from `manifest.csv` and `dataset.json` only.",
        "",
        f"- Prepared: {info.get('created_at')} · preprocess `{info.get('preprocess_version')}` · "
        f"seed {info.get('seed')}",
        f"- Source: {source.get('kind')} `{source.get('name')}` · {source.get('n_images')} "
        f"image files · listing SHA-256 `{str(source.get('listing_sha256', ''))[:16]}…`",
        f"- Kept images: **{len(kept):,}** · patches: **{int(kept['n_patches'].sum()):,}** · "
        "patient IDs: "
        + ("yes (regex)" if "regex" in str(info.get("grouping")) else "**none** (limitation L1)"),
        "",
    ]
    lines += _counts_section(kept)
    lines += _sources_section(info, manifest)
    lines += _sizes_section(manifest)
    lines += _duplicates_section(info, manifest)
    lines += _leakage_section(info, kept)
    lines += _tissue_section(info, kept)
    lines += _patches_section(kept)
    return "\n".join(lines).rstrip() + "\n", kind


def write_audit(prepared: Path, out: Path = DEFAULT_AUDIT_PATH) -> tuple[Path, str]:
    markdown, kind = build_audit(prepared)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown, "utf-8")
    return out, kind
