"""Per-image handcrafted features (Phase T, proposed FR-7.11). NumPy/SciPy/Pillow only.

Every feature is computed on a **downsized copy** of the original image and only over its
**tissue pixels**:

* downsizing: ``PIL.Image.reduce(DOWNSAMPLE)``, a 4x4 box average (one downsized pixel = 4x4
  original pixels; a 2048x1536 image becomes 512x384);
* tissue mask: the training rule of ADR-0002 applied to the downsized copy, i.e. HSV saturation
  (``oscc_ml.preprocess.saturation``) > min(Otsu threshold, 40). If fewer than
  ``MIN_TISSUE_PIXELS`` pixels pass, every pixel is used and ``tissue_mask_fallback`` = 1.

Families (names, units and formulas: ``docs/results/TABULAR_DATA_DICTIONARY.md``):

* colour: RGB, HSV and CIE L*a*b* statistics;
* stain: H&E colour deconvolution (Ruifrok & Johnston 2001 stain vectors), optical density;
* texture: grey-level co-occurrence matrix (GLCM) at distances 1, 2, 4 averaged over 0°, 45°, 90°,
  135°; uniform rotation-invariant local binary patterns (LBP, 8 neighbours, radius 1);
* nuclei-density proxies: connected "dark blobs" of hematoxylin-positive tissue pixels.

Magnification and image size are metadata, not features (``extract.py``).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from scipy import ndimage

DOWNSAMPLE = 4
MAX_TISSUE_THRESHOLD = 40  # ADR-0002 (same value as protocol.yaml data.tiling.max_tissue_threshold)
MIN_TISSUE_PIXELS = 500
GLCM_LEVELS = 32
GLCM_DISTANCES = (1, 2, 4)
GLCM_ANGLES = (0, 45, 90, 135)
MIN_BLOB_PIXELS = 2

# Ruifrok & Johnston (2001) stain vectors (rows: hematoxylin, eosin, residual/DAB), as used by
# scikit-image's ``rgb_from_hed``; each row is normalised to unit length below.
_STAINS = np.array([[0.65, 0.70, 0.29], [0.07, 0.99, 0.11], [0.27, 0.57, 0.78]], dtype=np.float64)
RGB_FROM_HED = _STAINS / np.linalg.norm(_STAINS, axis=1, keepdims=True)
HED_FROM_RGB = np.linalg.inv(RGB_FROM_HED)

# sRGB (D65) -> XYZ, and the D65 white point
_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)
_WHITE_D65 = np.array([0.95047, 1.0, 1.08883])


def downsize(image: Image.Image) -> NDArray[np.uint8]:
    rgb = image.convert("RGB")
    if DOWNSAMPLE > 1:
        rgb = rgb.reduce(DOWNSAMPLE)
    return np.asarray(rgb, dtype=np.uint8)


def tissue_mask(rgb: NDArray[np.uint8]) -> tuple[NDArray[np.bool_], int, bool, float]:
    """ADR-0002 rule on the given pixels -> (mask, threshold used, fallback flag, tissue fraction).
    The fraction is that of the rule itself, also when the fallback uses every pixel."""
    from oscc_ml.preprocess import otsu_threshold, saturation

    sat = saturation(rgb)
    threshold = min(otsu_threshold(sat), MAX_TISSUE_THRESHOLD)
    mask = sat > threshold
    fraction = float(mask.mean())
    if int(mask.sum()) < MIN_TISSUE_PIXELS:
        return np.ones(mask.shape, dtype=bool), threshold, True, fraction
    return mask, threshold, False, fraction


def _stats(prefix: str, values: NDArray[np.float64]) -> dict[str, float]:
    return {
        f"{prefix}_mean": float(values.mean()),
        f"{prefix}_std": float(values.std()),
        f"{prefix}_p10": float(np.percentile(values, 10)),
        f"{prefix}_p50": float(np.percentile(values, 50)),
        f"{prefix}_p90": float(np.percentile(values, 90)),
    }


def srgb_to_lab(rgb: NDArray[np.uint8]) -> NDArray[np.float64]:
    """Nx3 uint8 sRGB -> Nx3 CIE L*a*b* (D65)."""
    c = rgb.astype(np.float64) / 255.0
    linear = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = linear @ _RGB_TO_XYZ.T / _WHITE_D65
    delta = 6.0 / 29.0
    f = np.where(xyz > delta**3, np.cbrt(xyz), xyz / (3 * delta**2) + 4.0 / 29.0)
    lab = np.empty_like(f)
    lab[:, 0] = 116.0 * f[:, 1] - 16.0
    lab[:, 1] = 500.0 * (f[:, 0] - f[:, 1])
    lab[:, 2] = 200.0 * (f[:, 1] - f[:, 2])
    return np.asarray(lab, dtype=np.float64)


def optical_density(rgb: NDArray[np.uint8]) -> NDArray[np.float64]:
    """OD = -log10((I + 1) / 256) per channel; 0 for white, about 2.4 for black."""
    return -np.log10((rgb.astype(np.float64) + 1.0) / 256.0)


def stain_concentrations(rgb: NDArray[np.uint8]) -> NDArray[np.float64]:
    """Nx3 uint8 RGB -> Nx3 (hematoxylin, eosin, residual) optical-density concentrations."""
    return optical_density(rgb) @ HED_FROM_RGB


def colour_features(pixels: NDArray[np.uint8]) -> dict[str, float]:
    out: dict[str, float] = {}
    for i, name in enumerate(("r", "g", "b")):
        values = pixels[:, i].astype(np.float64)
        out[f"rgb_{name}_mean"] = float(values.mean())
        out[f"rgb_{name}_std"] = float(values.std())
    hsv = np.asarray(Image.fromarray(pixels.reshape(1, -1, 3)).convert("HSV"), dtype=np.float64)
    hsv = hsv.reshape(-1, 3)
    angle = hsv[:, 0] / 256.0 * 2.0 * np.pi
    sin_m, cos_m = float(np.sin(angle).mean()), float(np.cos(angle).mean())
    out["hsv_h_circular_mean_deg"] = float(np.degrees(np.arctan2(sin_m, cos_m)) % 360.0)
    out["hsv_h_resultant_length"] = float(np.hypot(sin_m, cos_m))
    for i, name in ((1, "s"), (2, "v")):
        out[f"hsv_{name}_mean"] = float(hsv[:, i].mean())
        out[f"hsv_{name}_std"] = float(hsv[:, i].std())
    lab = srgb_to_lab(pixels)
    for i, name in enumerate(("l", "a", "b")):
        out[f"lab_{name}_mean"] = float(lab[:, i].mean())
        out[f"lab_{name}_std"] = float(lab[:, i].std())
    return out


def stain_features(pixels: NDArray[np.uint8]) -> dict[str, float]:
    hed = stain_concentrations(pixels)
    out = {**_stats("he_h_od", hed[:, 0]), **_stats("he_e_od", hed[:, 1])}
    # bounded hematoxylin share: mean(max(H, 0)) / (mean(max(H, 0)) + mean(max(E, 0))), in [0, 1]
    h_pos = float(np.clip(hed[:, 0], 0, None).mean())
    e_pos = float(np.clip(hed[:, 1], 0, None).mean())
    out["he_h_share"] = h_pos / (h_pos + e_pos) if h_pos + e_pos > 0 else 0.5
    out["od_total_mean"] = float(optical_density(pixels).sum(axis=1).mean())
    return out


def _glcm(
    levels: NDArray[np.int64], mask: NDArray[np.bool_], dy: int, dx: int
) -> NDArray[np.float64]:
    """Symmetric, normalised co-occurrence matrix for offset (dy, dx) over pairs with both pixels in
    the mask."""
    h, w = levels.shape
    y0, y1 = max(0, -dy), min(h, h - dy)
    x0, x1 = max(0, -dx), min(w, w - dx)
    a = levels[y0:y1, x0:x1]
    b = levels[y0 + dy : y1 + dy, x0 + dx : x1 + dx]
    both = mask[y0:y1, x0:x1] & mask[y0 + dy : y1 + dy, x0 + dx : x1 + dx]
    n = GLCM_LEVELS
    counts = np.bincount((a[both] * n + b[both]).ravel(), minlength=n * n).reshape(n, n)
    counts = counts + counts.T
    total = counts.sum()
    return counts / total if total else counts.astype(np.float64)


def glcm_properties(p: NDArray[np.float64]) -> dict[str, float]:
    n = p.shape[0]
    i, j = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    diff = (i - j).astype(np.float64)
    mu_i, mu_j = float((i * p).sum()), float((j * p).sum())
    sd_i = float(np.sqrt(((i - mu_i) ** 2 * p).sum()))
    sd_j = float(np.sqrt(((j - mu_j) ** 2 * p).sum()))
    asm = float((p**2).sum())
    corr = float(((i - mu_i) * (j - mu_j) * p).sum() / (sd_i * sd_j)) if sd_i * sd_j > 0 else 1.0
    return {
        "contrast": float((p * diff**2).sum()),
        "dissimilarity": float((p * np.abs(diff)).sum()),
        "homogeneity": float((p / (1.0 + diff**2)).sum()),
        "asm": asm,
        "energy": float(np.sqrt(asm)),
        "correlation": corr,
    }


def _offset(distance: int, angle: int) -> tuple[int, int]:
    # (dy, dx), image rows pointing down; same convention as scikit-image graycomatrix
    return {
        0: (0, distance),
        45: (-distance, distance),
        90: (-distance, 0),
        135: (-distance, -distance),
    }[angle]


def grey_levels(rgb: NDArray[np.uint8]) -> NDArray[np.int64]:
    """ITU-R 601 luma (Pillow "L") quantised to GLCM_LEVELS levels."""
    grey = np.asarray(Image.fromarray(rgb).convert("L"), dtype=np.int64)
    return grey * GLCM_LEVELS // 256


def texture_features(rgb: NDArray[np.uint8], mask: NDArray[np.bool_]) -> dict[str, float]:
    levels = grey_levels(rgb)
    out: dict[str, float] = {}
    for d in GLCM_DISTANCES:
        per_angle = [glcm_properties(_glcm(levels, mask, *_offset(d, a))) for a in GLCM_ANGLES]
        for prop in per_angle[0]:
            out[f"glcm_{prop}_d{d}"] = float(np.mean([x[prop] for x in per_angle]))
    out.update(lbp_features(np.asarray(Image.fromarray(rgb).convert("L"), dtype=np.int64), mask))
    return out


# neighbours in circular order (dy, dx)
_LBP_NEIGHBOURS = ((0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0), (1, 1))


def lbp_codes(grey: NDArray[np.int64]) -> NDArray[np.int64]:
    """Uniform rotation-invariant LBP (riu2), 8 square neighbours at radius 1, for interior pixels:
    code = number of neighbours >= centre if the circular pattern has <= 2 transitions, else 9."""
    centre = grey[1:-1, 1:-1]
    h, w = grey.shape
    bits = np.stack(
        [grey[1 + dy : h - 1 + dy, 1 + dx : w - 1 + dx] >= centre for dy, dx in _LBP_NEIGHBOURS]
    ).astype(np.int64)
    transitions = np.abs(bits - np.roll(bits, -1, axis=0)).sum(axis=0)
    return np.where(transitions <= 2, bits.sum(axis=0), 9)


def lbp_features(grey: NDArray[np.int64], mask: NDArray[np.bool_]) -> dict[str, float]:
    codes = lbp_codes(grey)
    inner = mask[1:-1, 1:-1]
    hist = np.bincount(codes[inner].ravel(), minlength=10).astype(np.float64)
    hist = hist / hist.sum() if hist.sum() else hist
    return {f"lbp_riu2_bin{k}": float(hist[k]) for k in range(10)}


def _otsu_float(values: NDArray[np.float64], bins: int = 256) -> float:
    """Otsu threshold for real values (histogram over [min, max])."""
    low, high = float(values.min()), float(values.max())
    if high <= low:
        return high
    hist, edges = np.histogram(values, bins=bins, range=(low, high))
    centres = (edges[:-1] + edges[1:]) / 2.0
    w0 = np.cumsum(hist).astype(np.float64)
    w1 = w0[-1] - w0
    m = np.cumsum(hist * centres)
    with np.errstate(divide="ignore", invalid="ignore"):
        mu0 = m / w0
        mu1 = (m[-1] - m) / w1
        between = np.nan_to_num(w0 * w1 * (mu0 - mu1) ** 2)
    return float(centres[int(np.argmax(between))])


def nuclei_features(rgb: NDArray[np.uint8], mask: NDArray[np.bool_]) -> dict[str, float]:
    """Dark-blob proxies for nuclei: tissue pixels whose hematoxylin OD is above the Otsu threshold
    of hematoxylin OD within the tissue, grouped into 8-connected blobs of >= MIN_BLOB_PIXELS."""
    h_od = stain_concentrations(rgb.reshape(-1, 3))[:, 0].reshape(rgb.shape[:2])
    tissue_values = h_od[mask]
    threshold = _otsu_float(tissue_values)
    positive = mask & (h_od > threshold)
    labels, n = ndimage.label(positive, structure=np.ones((3, 3), dtype=bool))
    areas = np.bincount(labels.ravel())[1:] if n else np.zeros(0, dtype=np.int64)
    areas = areas[areas >= MIN_BLOB_PIXELS]
    tissue_px = int(mask.sum())
    out = {
        "nuc_h_threshold_od": threshold,
        "nuc_h_positive_fraction": float(positive.sum() / tissue_px) if tissue_px else 0.0,
        "nuc_blob_count": float(len(areas)),
        "nuc_blob_density_per_10k_tissue_px": float(len(areas) / tissue_px * 1e4)
        if tissue_px
        else 0.0,
        "nuc_blob_area_mean_px": float(areas.mean()) if len(areas) else 0.0,
        "nuc_blob_area_median_px": float(np.median(areas)) if len(areas) else 0.0,
        "nuc_blob_area_std_px": float(areas.std()) if len(areas) else 0.0,
        "nuc_blob_area_p90_px": float(np.percentile(areas, 90)) if len(areas) else 0.0,
    }
    return out


def image_features(image: Image.Image) -> dict[str, Any]:
    """All features of one image (dict of floats, plus two mask diagnostics)."""
    return features_of_downsized(downsize(image))


def features_of_downsized(rgb: NDArray[np.uint8]) -> dict[str, Any]:
    mask, threshold, fallback, fraction = tissue_mask(rgb)
    pixels = rgb[mask]
    out: dict[str, Any] = {
        "tissue_fraction": fraction,
        "tissue_threshold": float(threshold),
        "tissue_mask_fallback": int(fallback),
    }
    out.update(colour_features(pixels))
    out.update(stain_features(pixels))
    out.update(texture_features(rgb, mask))
    out.update(nuclei_features(rgb, mask))
    return out
