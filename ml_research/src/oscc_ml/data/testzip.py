"""``oscc-ml make-test-zip``: a small synthetic archive laid out like the Kaggle release.

For CI and for a dry run of ``uni_run`` before the real data is used. Not histology; any dataset
built from it must be given a ``dataset_version`` starting with ``synthetic``.

Layout: ``Oral Cancer Dataset/{train,val,test}/{Normal,OSCC}/<Class>_<mag>_<n>.jpg`` plus
publisher-style augmented copies ``train/<Class>/aug_<n>_<k>.jpg`` (224 x 224), as in the real
release. Originals are 900 x 700 with white glass around the tissue, so tiling and the tissue
filter are exercised too.
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
    duplicate_originals: bool = True,
) -> Path:
    """Write the archive. Mirrors the real release (checked Nov 2026): originals named
    ``<Class>_<mag>_<n>.jpg`` in train/val/test; augmented copies only in train, named
    ``aug_<n>_<k>.jpg``, 224 x 224, no magnification in the name. Half the copies are whole-image
    resizes (pHash finds them), half are random crops (pHash cannot). With
    ``duplicate_originals`` the first original of each class is also saved in test/ under another
    name, so prepare's pHash deduplication must remove a cross-split duplicate."""
    rng = np.random.default_rng(seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    transforms: list[Callable[[Image.Image], Image.Image]] = [
        lambda im: im.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
        lambda im: im.transpose(Image.Transpose.ROTATE_90),
        lambda im: ImageEnhance.Brightness(im).enhance(1.08),
        lambda im: im.transpose(Image.Transpose.FLIP_TOP_BOTTOM),
    ]
    aug_counter = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        for label, cls in ((0, "Normal"), (1, "OSCC")):
            for i in range(originals_per_class):
                split = "train" if i % 10 < 7 else ("val" if i % 10 < 9 else "test")
                mag = "100x" if i % 2 == 0 else "400x"
                image = _image(rng, label, width, height)
                data = _jpeg(image)
                archive.writestr(f"{ROOT}/{split}/{cls}/{cls}_{mag}_{i + 1}.jpg", data)
                if duplicate_originals and i == 0:
                    archive.writestr(f"{ROOT}/test/{cls}/{cls}_{mag}_{1000 + i}.jpg", data)
                if split != "train":
                    continue
                for k in range(augmented_per_original):
                    aug = transforms[(i + k) % len(transforms)](image)
                    if k % 2 == 0:  # whole image, downscaled
                        aug = aug.resize((224, 224), Image.Resampling.BILINEAR)
                    else:  # random 224 crop
                        left = int(rng.integers(0, aug.width - 224 + 1))
                        top = int(rng.integers(0, aug.height - 224 + 1))
                        aug = aug.crop((left, top, left + 224, top + 224))
                    aug_counter += 1
                    archive.writestr(f"{ROOT}/{split}/{cls}/aug_{aug_counter}_{k}.jpg", _jpeg(aug))
        archive.writestr(f"{ROOT}/README.txt", b"synthetic test archive; not histology")
    return out
