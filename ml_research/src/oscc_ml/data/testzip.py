"""``oscc-ml make-test-zip``: a small synthetic archive laid out like the Kaggle release.

For CI and for a dry run of ``uni_run`` before the real data is used. Not histology; any dataset
built from it must be given a ``dataset_version`` starting with ``synthetic``.

Layout: ``Oral Cancer Dataset/{train,val,test}/{Normal,OSCC}/<name>_<mag>x.jpg``. The train folder
also holds augmented copies (flips, 90-degree rotations, brightness changes) of its originals, as
in the Kaggle release, so deduplication is exercised. Images are 900 x 700 with a white margin, so
tiling and the tissue filter are exercised too.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

from oscc_ml.data.synthetic import synthetic_patch

ROOT = "Oral Cancer Dataset"


def _image(rng: np.random.Generator, label: int, width: int, height: int) -> Image.Image:
    """Irregular tissue on white glass. The tissue outline comes from a smooth random field, so
    every original has its own large-scale shape (as real slides do) and distinct pHashes."""
    tile = 224
    rows, cols = -(-height // tile), -(-width // tile)
    texture = np.concatenate(
        [
            np.concatenate([synthetic_patch(rng, label, tile) for _ in range(cols)], axis=1)
            for _ in range(rows)
        ],
        axis=0,
    )[:height, :width]
    field = Image.fromarray((rng.random((6, 8)) * 255).astype(np.uint8)).resize(
        (width, height), Image.Resampling.BICUBIC
    )
    mask = np.asarray(field) > 100  # roughly 60% tissue
    canvas = np.full((height, width, 3), 245, dtype=np.uint8)  # white glass background
    canvas[mask] = texture[mask]
    return Image.fromarray(canvas)


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def make_test_zip(
    out: Path,
    originals_per_class: int = 30,
    augmented_per_original: int = 2,
    seed: int = 42,
    size: tuple[int, int] = (900, 700),
) -> Path:
    rng = np.random.default_rng(seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    augmentations: list[Callable[[Image.Image], Image.Image]] = [
        lambda im: im.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
        lambda im: im.transpose(Image.Transpose.ROTATE_90),
        lambda im: ImageEnhance.Brightness(im).enhance(1.08),
        lambda im: im.transpose(Image.Transpose.FLIP_TOP_BOTTOM),
    ]
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        for label, cls in ((0, "Normal"), (1, "OSCC")):
            for i in range(originals_per_class):
                split = "train" if i % 10 < 7 else ("val" if i % 10 < 9 else "test")
                mag = "100x" if i % 2 == 0 else "400x"
                image = _image(rng, label, width, height)
                name = f"{ROOT}/{split}/{cls}/{cls.lower()}_{i:03d}_{mag}.jpg"
                archive.writestr(name, _jpeg(image))
                if split == "train":
                    for k in range(augmented_per_original):
                        aug = augmentations[(i + k) % len(augmentations)](image)
                        archive.writestr(
                            f"{ROOT}/{split}/{cls}/aug_{k}_{cls.lower()}_{i:03d}_{mag}.jpg",
                            _jpeg(aug),
                        )
        archive.writestr(f"{ROOT}/README.txt", b"synthetic test archive; not histology\n")
    return out
