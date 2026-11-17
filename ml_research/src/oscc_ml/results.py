"""Move results between the university GPU machine and a laptop.

``pack-results`` writes two archives into ``runs/export/``:

* ``results_small.zip``: everything needed to rebuild the report at home (configs, run info,
  environment, logs, metrics, evaluation, predictions, sweep summary, report, uni_run.log);
  no checkpoints. Small enough for email or a USB stick.
* ``checkpoints.zip``: ``checkpoints/best.pt`` of every training run (needed later to register
  models, Phase R5). ``last.pt`` resume files are not exported.

Each archive contains ``MANIFEST.json`` listing every file with its size and SHA-256.
``import-results`` verifies those hashes, refuses unsafe paths, and unpacks into ``runs/``.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from oscc_ml.paths import EXPORT_DIR_NAME, REPORT_DIR_NAME, SWEEP_DIR_NAME
from oscc_ml.runinfo import git_state
from oscc_ml.utils.io import iso, read_json, utc_now

MANIFEST = "MANIFEST.json"
SMALL_ZIP = "results_small.zip"
CHECKPOINTS_ZIP = "checkpoints.zip"
_CHUNK = 1024 * 1024


class ImportRefusedError(RuntimeError):
    """The archive is unsafe, corrupt or conflicts with existing files."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _run_dirs(root: Path) -> list[Path]:
    """Run folders (with run_info.json) directly under ``root``, excluding smoke runs."""
    out = []
    for info_path in sorted(root.glob("*/run_info.json")):
        try:
            info = read_json(info_path)
        except (OSError, ValueError):
            continue
        if info.get("smoke") or info.get("purpose") == "smoke":
            continue
        out.append(info_path.parent)
    return out


def small_files(runs_dir: Path) -> list[Path]:
    files: list[Path] = []
    for run_dir in _run_dirs(runs_dir) + _run_dirs(runs_dir / SWEEP_DIR_NAME):
        files += [
            p
            for p in sorted(run_dir.rglob("*"))
            if p.is_file() and "checkpoints" not in p.relative_to(run_dir).parts
        ]
    for extra in (
        runs_dir / SWEEP_DIR_NAME / "chosen_lr.json",
        *sorted((runs_dir / REPORT_DIR_NAME).glob("*")),
        *sorted(runs_dir.glob("*.log")),
    ):
        if extra.is_file():
            files.append(extra)
    return files


def checkpoint_files(runs_dir: Path) -> list[Path]:
    files = []
    for run_dir in _run_dirs(runs_dir):
        info = read_json(run_dir / "run_info.json")
        best = run_dir / "checkpoints" / "best.pt"
        if info.get("purpose") == "train" and best.is_file():
            files.append(best)
    return files


def _write_zip(target: Path, runs_dir: Path, files: list[Path], kind: str, stored: bool) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".zip.tmp")
    entries: list[dict[str, Any]] = []
    compression = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(tmp, "w", compression=compression, allowZip64=True) as archive:
        for path in files:
            arcname = path.relative_to(runs_dir).as_posix()
            archive.write(path, arcname)
            entries.append(
                {"path": arcname, "size": path.stat().st_size, "sha256": sha256_of(path)}
            )
        manifest = {
            "kind": kind,
            "created_at": iso(utc_now()),
            "files": entries,
            **git_state(runs_dir.parent),
        }
        archive.writestr(MANIFEST, json.dumps(manifest, indent=2) + "\n")
    tmp.replace(target)
    return target


def pack_results(runs_dir: Path, out_dir: Path | None = None) -> dict[str, Path]:
    out_dir = out_dir or runs_dir / EXPORT_DIR_NAME
    small = small_files(runs_dir)
    if not small:
        raise FileNotFoundError(f"no non-smoke run folders found in {runs_dir}")
    return {
        "results_small": _write_zip(out_dir / SMALL_ZIP, runs_dir, small, "results_small", False),
        "checkpoints": _write_zip(
            out_dir / CHECKPOINTS_ZIP, runs_dir, checkpoint_files(runs_dir), "checkpoints", True
        ),
    }


def _safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or ":" in name
        or "\\" in name
        or name.startswith("/")
    ):
        raise ImportRefusedError(f"unsafe path in archive: {name!r}")
    return path


@dataclass
class ImportResult:
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)


def import_results(archive_path: Path, runs_dir: Path, overwrite: bool = False) -> ImportResult:
    result = ImportResult()
    with zipfile.ZipFile(archive_path) as archive:
        try:
            manifest = json.loads(archive.read(MANIFEST))
        except KeyError as exc:
            raise ImportRefusedError(f"{archive_path.name} has no {MANIFEST}") from exc
        expected = {entry["path"]: entry for entry in manifest["files"]}
        members = {info.filename for info in archive.infolist() if not info.is_dir()} - {MANIFEST}
        if members != set(expected):
            raise ImportRefusedError("archive contents do not match its manifest")

        # Validate everything before writing anything.
        for name in expected:
            _safe_relative(name)
        for name, entry in expected.items():
            target = runs_dir.joinpath(*_safe_relative(name).parts)
            if target.is_file():
                if sha256_of(target) == entry["sha256"]:
                    result.unchanged.append(name)
                    continue
                if not overwrite:
                    raise ImportRefusedError(
                        f"{target} already exists with different content (use --overwrite)"
                    )
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".importing")
            digest = hashlib.sha256()
            with archive.open(name) as src, tmp.open("wb") as dst:
                while chunk := src.read(_CHUNK):
                    digest.update(chunk)
                    dst.write(chunk)
            if digest.hexdigest() != entry["sha256"]:
                tmp.unlink()
                raise ImportRefusedError(f"checksum mismatch for {name}; the archive is corrupt")
            tmp.replace(target)
            result.written.append(name)
    return result
