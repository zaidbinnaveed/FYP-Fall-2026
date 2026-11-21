"""Read raw images one at a time from a zip archive or a folder, never the whole dataset.

Labels, magnification and the original (publisher's) split are inferred from the path:

* label: the deepest folder (then the file name) that names a class:
  ``normal`` / ``non-oscc`` / ``benign`` -> non_oscc (0);
  ``oscc`` / ``scc`` / ``carcinoma`` -> oscc (1).
  Folder names such as "Oral Cancer" that apply to both classes are deliberately not used.
* magnification: ``100x``, ``400x`` ... anywhere in the path, else ``unknown``.
* original split: a folder named train / val / valid / validation / test, else ``none``.

Paths that cannot be labelled are collected and reported; ``prepare`` fails loudly on them rather
than guessing.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from PIL import Image

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
_NORMAL = re.compile(r"(^|[^a-z])(normal|non[-_ ]?oscc|benign|healthy)([^a-z]|$)", re.I)
_OSCC = re.compile(r"(^|[^a-z])(oscc|scc|carcinoma)([^a-z]|$)", re.I)
_MAGNIFICATION = re.compile(r"(?<!\d)(40|100|200|400|1000)\s*[x\N{MULTIPLICATION SIGN}]", re.I)
_SPLITS = {
    "train": "train",
    "training": "train",
    "val": "val",
    "valid": "val",
    "validation": "val",
    "test": "test",
    "testing": "test",
}


class UnlabelledPathError(ValueError):
    """Some image paths name no class folder; labels must never be guessed."""


def infer_label(path: str) -> int | None:
    parts = PurePosixPath(path).parts
    folders, stem = parts[:-1], PurePosixPath(path).stem
    for component in [*reversed(folders), stem]:
        if _NORMAL.search(component):
            return 0
        if _OSCC.search(component):
            return 1
    return None


def infer_magnification(path: str) -> str:
    match = _MAGNIFICATION.search(path)
    return f"{match.group(1)}x" if match else "unknown"


def infer_original_split(path: str) -> str:
    for component in PurePosixPath(path).parts[:-1]:
        split = _SPLITS.get(component.lower())
        if split:
            return split
    return "none"


@dataclass(frozen=True)
class RawImage:
    path: str  # POSIX-style path inside the zip or relative to the folder
    size_bytes: int


class ImageSource:
    """A zip archive or a folder of images. ``read`` returns one image's bytes."""

    def __init__(self, location: Path) -> None:
        if not location.exists():
            raise FileNotFoundError(f"{location} does not exist")
        self.location = location
        self.is_zip = location.is_file() and zipfile.is_zipfile(location)
        if location.is_file() and not self.is_zip:
            raise ValueError(f"{location} is a file but not a readable zip archive")
        self._zip: zipfile.ZipFile | None = zipfile.ZipFile(location) if self.is_zip else None

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()

    def __enter__(self) -> ImageSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def list_images(self) -> list[RawImage]:
        """Image entries only (by suffix), sorted by path; hidden/system files skipped."""
        entries: list[RawImage] = []
        if self._zip is not None:
            for info in self._zip.infolist():
                name = info.filename
                if info.is_dir() or _hidden(name):
                    continue
                if PurePosixPath(name).suffix.lower() in IMAGE_SUFFIXES:
                    entries.append(RawImage(name, info.file_size))
        else:
            for path in self.location.rglob("*"):
                rel = path.relative_to(self.location).as_posix()
                if path.is_file() and not _hidden(rel) and path.suffix.lower() in IMAGE_SUFFIXES:
                    entries.append(RawImage(rel, path.stat().st_size))
        return sorted(entries, key=lambda e: e.path)

    def read(self, path: str) -> bytes:
        if self._zip is not None:
            return self._zip.read(path)
        return (self.location / path).read_bytes()

    def fingerprint(self) -> dict[str, object]:
        """Cheap identity of the input: name, size, number of images and (for zips) a hash of
        the central directory's CRCs. Used to skip `prepare` when nothing changed."""
        import hashlib

        images = self.list_images()
        digest = hashlib.sha256()
        if self._zip is not None:
            for info in sorted(self._zip.infolist(), key=lambda i: i.filename):
                digest.update(f"{info.filename}:{info.CRC}:{info.file_size}\n".encode())
        else:
            for entry in images:
                digest.update(f"{entry.path}:{entry.size_bytes}\n".encode())
        return {
            "name": self.location.name,
            "kind": "zip" if self.is_zip else "folder",
            "n_images": len(images),
            "total_bytes": sum(e.size_bytes for e in images),
            "listing_sha256": digest.hexdigest(),
        }


def decode(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def _hidden(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return any(p.startswith(".") or p == "__MACOSX" for p in parts) or parts[-1].lower() in {
        "thumbs.db",
        "desktop.ini",
    }


def iter_labelled(images: list[RawImage]) -> Iterator[tuple[RawImage, int | None]]:
    for entry in images:
        yield entry, infer_label(entry.path)
