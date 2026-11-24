"""Perceptual-hash deduplication and grouping (plan section 3 and R1 steps 3-4).

Each image gets eight 64-bit pHashes: one per flip/90-degree rotation (the dihedral group). The
distance between two images is the smallest Hamming distance between image A's plain hash and
any of image B's eight hashes, so flipped or rotated augmented copies are recognised exactly.

Two thresholds (both recorded in dataset.json; tune at gate G1 by inspecting clusters):
* ``duplicate_threshold`` (default 4, ADR-0005; plan R1 proposed 6): images this close are copies
  of one another (re-saves, flips/rotations). One representative per duplicate cluster is kept.
  Visually confirmed same-field pairs above the threshold are added as extra links (ADR-0005,
  ``configs/data/reviewed_duplicates.yaml``).
* pHash distances are always even (every 64-bit pHash has exactly 32 one-bits: the bits are
  "above the median of 64 values"), so thresholds 4/5, 6/7 and 10/11 behave identically.
* ``group_threshold`` (default 10): kept images this close are probably neighbouring fields of the
  same slide/patient, so they are grouped and always land in the same split.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from PIL import Image

N_TRANSFORMS = 8


def dihedral_phashes(image: Image.Image) -> NDArray[np.uint64]:
    """pHash of each of the 8 flips/rotations, as uint64 (index 0 = the image as is)."""
    import imagehash

    grey = image.convert("L")
    grey.thumbnail((512, 512))  # pHash works on 32x32; shrinking first only saves time
    variants = []
    for flip in (False, True):
        base = grey.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if flip else grey
        for k in range(4):
            rotated = base.rotate(90 * k, expand=True) if k else base
            bits = imagehash.phash(rotated).hash.flatten()
            variants.append(int("".join("1" if b else "0" for b in bits), 2))
    return np.asarray(variants, dtype=np.uint64)


def min_distances(hashes: NDArray[np.uint64], chunk: int = 512) -> NDArray[np.uint8]:
    """Pairwise transform-invariant Hamming distance, shape (n, n), uint8. Memory: n*n bytes."""
    n = hashes.shape[0]
    plain = hashes[:, 0]
    out = np.full((n, n), 64, dtype=np.uint8)
    for start in range(0, n, chunk):
        stop = min(n, start + chunk)
        xor = plain[start:stop, None, None] ^ hashes[None, :, :]  # (chunk, n, 8)
        dist = np.bitwise_count(xor).min(axis=2).astype(np.uint8)
        out[start:stop] = dist
    return np.minimum(out, out.T)


def clusters(
    distances: NDArray[np.uint8],
    threshold: int,
    extra_edges: Sequence[tuple[int, int]] = (),
) -> NDArray[np.int64]:
    """Connected components of the graph 'distance <= threshold' plus ``extra_edges`` (reviewed
    same-field pairs, ADR-0005), by union-find. Labels 0..k-1, numbered by their first member so the
    result is deterministic."""
    n = distances.shape[0]
    parent = np.arange(n)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = int(parent[i])
        return i

    rows, cols = np.nonzero(np.triu(distances <= threshold, k=1))
    edges = list(zip(rows.tolist(), cols.tolist(), strict=True)) + [
        (int(a), int(b)) for a, b in extra_edges
    ]
    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([find(i) for i in range(n)])
    _, labels = np.unique(roots, return_inverse=True)
    return labels.astype(np.int64)


def nearest(
    queries: NDArray[np.uint64], references: NDArray[np.uint64], chunk: int = 512
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """For each query (8 hashes), the transform-invariant distance to the closest reference and
    that reference's row index."""
    if len(references) == 0:
        return np.full(len(queries), 64, dtype=np.int64), np.zeros(len(queries), dtype=np.int64)
    best_d = np.empty(len(queries), dtype=np.int64)
    best_i = np.empty(len(queries), dtype=np.int64)
    plain = queries[:, 0]
    for start in range(0, len(queries), chunk):
        stop = min(len(queries), start + chunk)
        xor = plain[start:stop, None, None] ^ references[None, :, :]
        dist = np.bitwise_count(xor).min(axis=2)
        best_i[start:stop] = dist.argmin(axis=1)
        best_d[start:stop] = dist.min(axis=1)
    return best_d, best_i
