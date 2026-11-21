"""``oscc-ml make-sample``: copy N images per class out of the raw zip or folder for local work.

Only the listing (zip central directory or folder tree) is read to choose files; then only the
chosen files are read. Folder structure is preserved, so ``prepare`` infers labels from the
sample exactly as it does from the full dataset. The choice is deterministic (seed 42) and
recorded in ``SAMPLE.json``.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from oscc_ml.data.sources import ImageSource, infer_label
from oscc_ml.utils.io import iso, utc_now, write_json


class SampleError(RuntimeError):
    pass


def _check_output(raw: Path, out: Path) -> None:
    """Never write into, or delete, the raw data; only replace an earlier sample."""
    raw_r, out_r = raw.resolve(), out.resolve()
    if out_r == raw_r or raw_r in out_r.parents or out_r in raw_r.parents:
        raise SampleError(f"--out {out} overlaps the raw data {raw}; choose data/sample/")
    if out.exists() and any(out.iterdir()) and not (out / "SAMPLE.json").is_file():
        raise SampleError(f"{out} is not empty and holds no SAMPLE.json; refusing to replace it")


def make_sample(
    raw: Path,
    out: Path,
    per_class: int,
    seed: int = 42,
    augmented_per_class: int = 5,
    augmented_name_regex: str | None = r"^aug_",
) -> dict[str, Any]:
    """``per_class`` originals per class plus ``augmented_per_class`` publisher-augmented files
    (so the name-based exclusion in ``prepare`` is exercised). Works on a zip or a folder; the
    raw data are only read."""
    if raw.is_file() and not zipfile.is_zipfile(raw):
        raise SampleError(f"{raw} is not a complete zip archive (still downloading, or corrupt?)")
    if not raw.exists():
        raise SampleError(f"{raw} not found")
    _check_output(raw, out)
    pattern = re.compile(augmented_name_regex) if augmented_name_regex else None
    with ImageSource(raw) as source:
        entries = source.list_images()
        pools: dict[tuple[int, bool], list[str]] = {}
        for entry in entries:
            label = infer_label(entry.path)
            if label is None:
                continue
            augmented = bool(pattern and pattern.search(PurePosixPath(entry.path).name))
            pools.setdefault((label, augmented), []).append(entry.path)
        rng = np.random.default_rng(seed)
        chosen: list[str] = []
        for label in (0, 1):
            for augmented, wanted in ((False, per_class), (True, augmented_per_class)):
                paths = pools.get((label, augmented), [])
                if augmented and not paths:
                    continue  # sources without publisher-augmented files
                if len(paths) < wanted:
                    kind = "augmented" if augmented else "original"
                    raise SampleError(
                        f"only {len(paths)} {kind} images with label {label}; asked for {wanted}"
                    )
                picks = rng.choice(len(paths), size=wanted, replace=False)
                chosen += [paths[i] for i in sorted(picks)]

        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        files = []
        for member in chosen:
            rel = PurePosixPath(member)
            if rel.is_absolute() or ".." in rel.parts:
                raise SampleError(f"unsafe path in archive: {member!r}")
            target = out.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            data = source.read(member)
            target.write_bytes(data)
            files.append({"path": member, "sha256": hashlib.sha256(data).hexdigest()})
    record = {
        "source": raw.name,
        "source_kind": "zip" if raw.is_file() else "folder",
        "per_class": per_class,
        "augmented_per_class": augmented_per_class,
        "seed": seed,
        "n_images_in_source": len(entries),
        "n_by_pool_in_source": {
            f"{'oscc' if k[0] else 'non_oscc'}{'_augmented' if k[1] else ''}": len(v)
            for k, v in sorted(pools.items())
        },
        "files": files,
        "created_at": iso(utc_now()),
        "note": "development sample only; never used for reported results",
    }
    write_json(out / "SAMPLE.json", record)
    return record
