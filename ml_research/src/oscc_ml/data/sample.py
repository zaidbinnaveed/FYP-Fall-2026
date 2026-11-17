"""``oscc-ml make-sample``: copy N images per class out of the raw zip for local development.

Only the zip's central directory is read to choose members; then only the chosen members are
decompressed. Folder structure is preserved, so ``prepare`` infers labels from the sample exactly
as it does from the full archive. The choice is deterministic (seed 42) and recorded in
``SAMPLE.json``.
"""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from oscc_ml.data.sources import ImageSource, infer_label
from oscc_ml.utils.io import iso, utc_now, write_json


class SampleError(RuntimeError):
    pass


def make_sample(zip_path: Path, out: Path, per_class: int, seed: int = 42) -> dict[str, Any]:
    if not zipfile.is_zipfile(zip_path):
        raise SampleError(
            f"{zip_path} is not a complete zip archive (still downloading, or corrupt?)"
        )
    with ImageSource(zip_path) as source:
        entries = source.list_images()
        by_label: dict[int, list[str]] = {0: [], 1: []}
        for entry in entries:
            label = infer_label(entry.path)
            if label is not None:
                by_label[label].append(entry.path)
        rng = np.random.default_rng(seed)
        chosen: list[str] = []
        for label, paths in sorted(by_label.items()):
            if len(paths) < per_class:
                raise SampleError(
                    f"only {len(paths)} images with label {label} in the archive; "
                    f"asked for {per_class}"
                )
            picks = rng.choice(len(paths), size=per_class, replace=False)
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
        "source_zip": zip_path.name,
        "per_class": per_class,
        "seed": seed,
        "n_images_in_archive": len(entries),
        "n_by_label_in_archive": {str(k): len(v) for k, v in by_label.items()},
        "files": files,
        "created_at": iso(utc_now()),
        "note": "development sample only; never used for reported results",
    }
    write_json(out / "SAMPLE.json", record)
    return record
