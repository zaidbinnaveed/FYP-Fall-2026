"""Contact sheets of image pairs for the pHash threshold decision (ADR-0005).

Uses the independent verifier's hashing and selection (scripts/audit/verify_dataset_independent.py),
not oscc_ml. Two sheets:

1. ``pairs_at_<low>-<high>.jpg``: every pair of originals whose pHash distance lies in
   [low, high] (default 5-6). These pairs count as duplicates at threshold 6 but not at threshold 4.
   Each row says whether the pair is still in one duplicate cluster at the new threshold through a
   chain of closer links.
2. ``cross_split_d<k>.jpg``: ``--n-random`` randomly chosen (seeded) pairs of kept images in
   different splits at distance exactly ``k`` (default 12), under the new thresholds.

Images are downsized thumbnails. Credit (CC BY 4.0) is printed on every sheet. Read-only on the raw
data. Also writes a CSV per sheet listing the pairs.

    python -I scripts/audit/make_pair_sheets.py --raw data/raw/kaggle_kebede --out <folder> \
        [--old-threshold 6 --new-threshold 4 --group-threshold 10 --distance 12 --n-random 20]
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CREDIT = (
    "Images: T. Y. Rahman, L. B. Mahanta, A. K. Das, J. D. Sarma, "
    "'Histopathological imaging database for Oral Cancer analysis', Mendeley Data v2, "
    "doi:10.17632/ftmp4cvtmb.2, licensed CC BY 4.0 "
    "(creativecommons.org/licenses/by/4.0). Changes: downsized and arranged side by side."
)
THUMB = 360  # longest side of each thumbnail, pixels


def _verifier() -> ModuleType:
    path = Path(__file__).resolve().parent / "verify_dataset_independent.py"
    spec = importlib.util.spec_from_file_location("verify_dataset_independent", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V = _verifier()


def _font(size: int) -> Any:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _thumb(source: Any, path: str) -> Image.Image:
    image = Image.open(io.BytesIO(source.read(path)))
    image = image.convert("RGB")
    image.thumbnail((THUMB, THUMB))
    return image


def _describe(row: dict[str, Any]) -> str:
    cls = "OSCC" if row["label"] == 1 else "Normal"
    split = row.get("split") or "-"
    return (
        f"{row['path']}\n{cls} {row['magnification']}  kaggle:{row['kaggle_folder']}  ours:{split}"
    )


def render(
    source: Any, pairs: list[dict[str, Any]], title: str, out: Path, columns: int = 1
) -> None:
    """One row per pair: [thumb A][thumb B] with captions; title and credit on top."""
    font, small = _font(16), _font(13)
    caption_h, header_h, pad = 44, 26, 10
    cell_w = 2 * THUMB + 3 * pad
    cell_h = header_h + THUMB + caption_h + pad
    rows = (len(pairs) + columns - 1) // columns
    top = 70
    sheet = Image.new("RGB", (columns * cell_w, top + rows * cell_h + pad), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((pad, 8), title, fill="black", font=font)
    draw.text((pad, 34), CREDIT, fill="dimgray", font=small)
    for n, pair in enumerate(pairs):
        x0 = (n % columns) * cell_w
        y0 = top + (n // columns) * cell_h
        draw.text((x0 + pad, y0 + 4), f"#{n + 1}  {pair['note']}", fill="darkred", font=small)
        for k, row in enumerate((pair["a"], pair["b"])):
            image = _thumb(source, row["path"])
            x = x0 + pad + k * (THUMB + pad)
            sheet.paste(image, (x, y0 + header_h))
            draw.text((x, y0 + header_h + THUMB + 2), _describe(row), fill="black", font=small)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=82, optimize=True)


def write_csv(path: Path, pairs: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["n", "distance", "path_a", "label_a", "path_b", "label_b", "note"])
        for n, p in enumerate(pairs, start=1):
            writer.writerow(
                [
                    n,
                    p["distance"],
                    p["a"]["path"],
                    p["a"]["label"],
                    p["b"]["path"],
                    p["b"]["label"],
                    p["note"],
                ]
            )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--old-threshold", type=int, default=6)
    p.add_argument("--new-threshold", type=int, default=4)
    p.add_argument("--group-threshold", type=int, default=10)
    p.add_argument("--distance", type=int, default=12)
    p.add_argument("--n-random", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    source = V.Source(args.raw)
    rows = V.scan(source)
    sel = V.select(
        rows,
        argparse.Namespace(
            duplicate_threshold=args.new_threshold,
            group_threshold=args.group_threshold,
            seed=args.seed,
        ),
    )
    candidates, dist = sel["candidates"], sel["dist"]
    new_clusters = V.partition(dist, args.new_threshold)

    # 1. pairs that stop counting as duplicates
    low = args.new_threshold + 1
    ii, jj = np.nonzero(np.triu((dist >= low) & (dist <= args.old_threshold), k=1))
    dropped = []
    for i, j in zip(ii.tolist(), jj.tolist(), strict=True):
        a, b = candidates[i], candidates[j]
        still = new_clusters[i] == new_clusters[j]
        labels = "SAME label" if a["label"] == b["label"] else "DIFFERENT labels"
        mags = "same mag" if a["magnification"] == b["magnification"] else "CROSS-MAGNIFICATION"
        note = f"pHash distance {int(dist[i, j])}; {labels}; {mags}; " + (
            "still one cluster at the new threshold via closer links"
            if still
            else f"no longer duplicates at threshold {args.new_threshold}"
        )
        dropped.append({"a": a, "b": b, "distance": int(dist[i, j]), "note": note})
    dropped.sort(key=lambda d: (d["a"]["path"], d["b"]["path"]))
    name = f"pairs_at_{low}-{args.old_threshold}"
    render(
        source,
        dropped,
        f"All {len(dropped)} pairs of originals at pHash distance {low}-{args.old_threshold} "
        f"(duplicates at threshold {args.old_threshold}, not at {args.new_threshold})",
        args.out / f"{name}.jpg",
        columns=2,
    )
    write_csv(args.out / f"{name}.csv", dropped)

    # 2. random cross-split pairs at distance k among kept images (new thresholds)
    kept, sub = sel["kept"], sel["sub"]
    splits = np.array([r["split"] for r in kept])
    ii, jj = np.nonzero(np.triu((sub == args.distance) & (splits[:, None] != splits[None, :]), k=1))
    rng = np.random.default_rng(args.seed)
    chosen = sorted(rng.choice(len(ii), size=min(args.n_random, len(ii)), replace=False).tolist())
    cross = []
    for c in chosen:
        a, b = kept[int(ii[c])], kept[int(jj[c])]
        labels = "same label" if a["label"] == b["label"] else "different labels"
        cross.append(
            {
                "a": a,
                "b": b,
                "distance": args.distance,
                "note": f"pHash distance {args.distance}; {a['split']} vs {b['split']}; {labels}",
            }
        )
    name = f"cross_split_d{args.distance}"
    render(
        source,
        cross,
        f"{len(cross)} random cross-split pairs at pHash distance {args.distance} "
        f"(of {len(ii)}; seed {args.seed}; duplicate threshold {args.new_threshold}, "
        f"group threshold {args.group_threshold})",
        args.out / f"{name}.jpg",
        columns=2,
    )
    write_csv(args.out / f"{name}.csv", cross)
    print(
        f"{len(dropped)} pairs at {low}-{args.old_threshold}; {len(cross)} of {len(ii)} "
        f"cross-split pairs at {args.distance} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
