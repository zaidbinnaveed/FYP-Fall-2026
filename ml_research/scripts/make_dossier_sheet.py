"""One downsized contact sheet of 4 dataset images for the data dossier (Normal/OSCC x 100x/400x).

Selection is deterministic: for each (class, magnification), the kept TRAINING image with the
smallest ``image_id`` in the prepare manifest. Captions state only class, magnification and file
ID. The CC BY 4.0 credit is printed on the sheet. Read-only on the raw data.

    python -I scripts/make_dossier_sheet.py --manifest <prepare manifest.csv> \
        --raw data/raw/kaggle_kebede --out ../docs/figures/dossier/he_examples.jpg
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CREDIT = (
    "Images: T. Y. Rahman, L. B. Mahanta, A. K. Das, J. D. Sarma, 'Histopathological imaging "
    "database for Oral Cancer analysis', Mendeley Data, doi:10.17632/ftmp4cvtmb.2, CC BY 4.0 "
    "(creativecommons.org/licenses/by/4.0). Changes: downsized and arranged in a grid."
)
THUMB = 480
CELLS = [("Normal", "100x"), ("OSCC", "100x"), ("Normal", "400x"), ("OSCC", "400x")]


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def choose(manifest: Path) -> list[tuple[str, str, dict[str, str]]]:
    with manifest.open(encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["status"] == "ok" and r["split"] == "train"]
    out = []
    for cls, mag in CELLS:
        label = "1" if cls == "OSCC" else "0"
        cell = sorted(
            (r for r in rows if r["label"] == label and r["magnification"] == mag),
            key=lambda r: r["image_id"],
        )
        out.append((cls, mag, cell[0]))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    chosen = choose(args.manifest)
    pad, caption_h, credit_h = 12, 26, 44
    cell_h = int(THUMB * 0.75) + caption_h
    sheet = Image.new("RGB", (2 * THUMB + 3 * pad, 2 * cell_h + 3 * pad + credit_h), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (cls, mag, row) in enumerate(chosen):
        with Image.open(args.raw / row["original_path"]) as image:
            thumb = image.convert("RGB")
            thumb.thumbnail((THUMB, int(THUMB * 0.75)))
        x = pad + (i % 2) * (THUMB + pad)
        y = pad + (i // 2) * (cell_h + pad)
        sheet.paste(thumb, (x + (THUMB - thumb.width) // 2, y))
        name = Path(row["original_path"]).name
        draw.text(
            (x, y + int(THUMB * 0.75) + 4), f"{cls}, {mag}, {name}", fill="black", font=_font(15)
        )
    words, line, lines = CREDIT.split(), "", []
    for word in words:
        if len(line) + len(word) > 125:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    lines.append(line)
    for k, text in enumerate(lines):
        draw.text((pad, 2 * cell_h + 2 * pad + 4 + k * 14), text, fill="black", font=_font(11))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out, quality=85)
    for cls, mag, row in chosen:
        print(f"{cls} {mag}: {row['original_path']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
