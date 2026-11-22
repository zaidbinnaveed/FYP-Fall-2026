"""Reviewed same-field pairs (ADR-0005): visually confirmed duplicates that pHash misses at the
duplicate threshold.

``configs/data/reviewed_duplicates.yaml`` lists pairs of originals (file name + SHA-256) that a
reviewer confirmed show the same tissue field. ``prepare`` adds each pair as an extra link to the
duplicate graph, so the pair falls in one duplicate cluster and is then handled by exactly the same
rules as hash duplicates (one representative kept; a cluster with both labels is a label conflict).

The list belongs to one release, identified by its number of readable originals
(``source_original_count``):

* same count -> the list is **required**: a listed file that is missing (name + SHA-256) or a
  listed pair whose two files carry different labels stops ``prepare`` with an error;
* different count (synthetic data, the local sample) -> not applicable; recorded as such.

The file lives in ``configs/data/`` because every ``configs/*.yaml`` is a model config.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from oscc_ml.paths import ML_ROOT

DEFAULT_REVIEWED_DUPLICATES = ML_ROOT / "configs" / "data" / "reviewed_duplicates.yaml"


class ReviewedDuplicatesError(ValueError):
    """The reviewed list is malformed, or does not match the release it is meant for."""


@dataclass(frozen=True)
class ReviewedFile:
    name: str  # file name only, e.g. OSCC_100x_81.jpg
    sha256: str


@dataclass(frozen=True)
class ReviewedPair:
    a: ReviewedFile
    b: ReviewedFile
    reason: str
    evidence: str
    reviewer: str
    date: str


@dataclass(frozen=True)
class ReviewedDuplicates:
    version: int
    source_name: str
    source_original_count: int
    pairs: tuple[ReviewedPair, ...]


_PAIR_KEYS = {"a", "b", "reason", "evidence", "reviewer", "date"}
_FILE_KEYS = {"name", "sha256"}


def _file(raw: object, where: str) -> ReviewedFile:
    if not isinstance(raw, dict) or set(raw) != _FILE_KEYS:
        raise ReviewedDuplicatesError(f"{where}: needs exactly {sorted(_FILE_KEYS)}")
    name, sha = str(raw["name"]), str(raw["sha256"]).lower()
    if PurePosixPath(name).name != name:
        raise ReviewedDuplicatesError(f"{where}: name must be a file name, not a path ({name!r})")
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ReviewedDuplicatesError(f"{where}: sha256 must be 64 hex characters")
    return ReviewedFile(name, sha)


def load_reviewed_duplicates(path: Path = DEFAULT_REVIEWED_DUPLICATES) -> ReviewedDuplicates:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ReviewedDuplicatesError(f"{path}: expected a mapping")
    missing = {"version", "source_name", "source_original_count", "pairs"} - set(data)
    if missing:
        raise ReviewedDuplicatesError(f"{path}: missing keys {sorted(missing)}")
    pairs: list[ReviewedPair] = []
    for i, raw in enumerate(data["pairs"] or []):
        where = f"{path.name} pair {i + 1}"
        if not isinstance(raw, dict) or set(raw) != _PAIR_KEYS:
            raise ReviewedDuplicatesError(f"{where}: needs exactly {sorted(_PAIR_KEYS)}")
        a, b = _file(raw["a"], f"{where} a"), _file(raw["b"], f"{where} b")
        if a.sha256 == b.sha256:
            raise ReviewedDuplicatesError(f"{where}: byte-identical files need no review")
        pairs.append(
            ReviewedPair(
                a,
                b,
                str(raw["reason"]),
                str(raw["evidence"]),
                str(raw["reviewer"]),
                str(raw["date"]),
            )
        )
    return ReviewedDuplicates(
        int(data["version"]),
        str(data["source_name"]),
        int(data["source_original_count"]),
        tuple(pairs),
    )


def resolve_pairs(
    reviewed: ReviewedDuplicates,
    paths: list[str],
    sha256s: list[str],
    labels: list[int],
) -> tuple[list[tuple[int, int]], str]:
    """Map the reviewed pairs onto candidate rows (``paths``/``sha256s``/``labels`` of the readable
    originals, in candidate order). Returns the index pairs and a status string. Raises
    :class:`ReviewedDuplicatesError` if the list is required but does not match."""
    if len(paths) != reviewed.source_original_count:
        return [], (
            f"not applicable: the source has {len(paths)} originals, the list is for the "
            f"{reviewed.source_original_count}-original {reviewed.source_name} release"
        )
    index = {
        (PurePosixPath(p).name, s): i for i, (p, s) in enumerate(zip(paths, sha256s, strict=True))
    }
    edges: list[tuple[int, int]] = []
    for n, pair in enumerate(reviewed.pairs, start=1):
        found = []
        for f in (pair.a, pair.b):
            i = index.get((f.name, f.sha256))
            if i is None:
                raise ReviewedDuplicatesError(
                    f"reviewed duplicate pair {n}: {f.name} (sha256 {f.sha256[:12]}...) is not in "
                    "the source; the list does not match this release"
                )
            found.append(i)
        if labels[found[0]] != labels[found[1]]:
            raise ReviewedDuplicatesError(
                f"reviewed duplicate pair {n} ({pair.a.name} / {pair.b.name}) carries both labels; "
                "a same-field pair with conflicting labels is a label conflict (ADR-0003), not a "
                "reviewed duplicate: remove it from the list and record it as a conflict"
            )
        edges.append((found[0], found[1]))
    return edges, f"applied: {len(edges)} pair(s)"
