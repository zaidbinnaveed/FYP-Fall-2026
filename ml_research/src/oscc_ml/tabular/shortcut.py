"""Non-pathology cues for the shortcut check (Phase T step 6).

If a classifier can tell OSCC from normal using only how the file was made (size, JPEG settings,
metadata) or the whole-frame colour distribution (background and illumination included), the
dataset carries a shortcut that image models could also exploit. These cues are written to a
separate table and are **never** used by the main tabular models.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

HIST_BINS = 8


def _quant_table_stats(image: Image.Image) -> dict[str, float]:
    tables = getattr(image, "quantization", None) or {}
    luma = np.asarray(tables.get(0, []), dtype=np.float64)
    chroma = np.asarray(tables.get(1, []), dtype=np.float64)
    return {
        "jpeg_n_quant_tables": float(len(tables)),
        "jpeg_qtable_luma_mean": float(luma.mean()) if luma.size else -1.0,
        "jpeg_qtable_chroma_mean": float(chroma.mean()) if chroma.size else -1.0,
    }


def _subsampling(image: Image.Image) -> float:
    try:
        from PIL import JpegImagePlugin

        return float(JpegImagePlugin.get_sampling(image))
    except Exception:  # not a JPEG or unknown layout
        return -1.0


def file_cues(image: Image.Image, size_bytes: int) -> dict[str, Any]:
    width, height = image.size
    info = image.info
    dpi = info.get("dpi") or (0, 0)
    out: dict[str, Any] = {
        "file_size_bytes": float(size_bytes),
        "img_width_px": float(width),
        "img_height_px": float(height),
        "img_aspect_ratio": float(width / height) if height else 0.0,
        "bytes_per_pixel": float(size_bytes / (width * height)) if width * height else 0.0,
        "jpeg_progressive": float(bool(info.get("progressive") or info.get("progression"))),
        "jpeg_subsampling": _subsampling(image),
        "has_exif": float(bool(info.get("exif"))),
        "has_icc_profile": float(bool(info.get("icc_profile"))),
        "dpi_x": float(dpi[0]) if dpi else 0.0,
        "is_rgb_mode": float(image.mode == "RGB"),
    }
    out.update(_quant_table_stats(image))
    return out


def global_colour_histogram(rgb_small: np.ndarray) -> dict[str, float]:
    """Whole-frame (tissue AND background) normalised histogram, HIST_BINS bins per RGB channel."""
    out: dict[str, float] = {}
    pixels = rgb_small.reshape(-1, 3).astype(np.int64)
    for i, name in enumerate(("r", "g", "b")):
        hist = np.bincount(pixels[:, i] * HIST_BINS // 256, minlength=HIST_BINS).astype(np.float64)
        hist /= hist.sum()
        for k in range(HIST_BINS):
            out[f"ghist_{name}_bin{k}"] = float(hist[k])
    return out
