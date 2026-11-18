"""The shared tiling rule (decision O5) used by prepare and, later, the inference service."""

from __future__ import annotations

import numpy as np
import pytest

from oscc_ml.preprocess import TilingParams, otsu_threshold, saturation, tile_image

TISSUE = np.array([200, 120, 170], dtype=np.uint8)  # pink, saturated
GLASS = np.array([245, 245, 245], dtype=np.uint8)  # white, unsaturated


def _image(height: int, width: int, tissue_box: tuple[int, int, int, int] | None) -> np.ndarray:
    image = np.tile(GLASS, (height, width, 1))
    if tissue_box:
        top, left, bottom, right = tissue_box
        image[top:bottom, left:right] = TISSUE
    return image


def test_otsu_separates_two_levels() -> None:
    values = np.array([10] * 500 + [200] * 500, dtype=np.uint8)
    assert 10 <= otsu_threshold(values) < 200


def test_saturation_of_grey_is_zero() -> None:
    assert int(saturation(np.full((2, 2, 3), 128, np.uint8)).max()) == 0
    assert int(saturation(np.array([[[255, 0, 0]]], np.uint8))[0, 0]) == 255


def test_small_images_are_resized_to_one_patch() -> None:
    result = tile_image(_image(300, 400, (0, 0, 300, 400)))
    assert result.mode == "resize"
    assert len(result.patches) == 1
    assert result.patches[0].shape == (224, 224, 3)


def test_grid_keeps_only_tissue_tiles() -> None:
    # 2 x 3 grid of 224 tiles; tissue covers the left two columns only
    image = _image(448, 672, (0, 0, 448, 448))
    result = tile_image(image)
    assert result.mode == "grid"
    assert result.grid_candidates == 6
    assert sorted(result.coords) == [(0, 0), (0, 224), (224, 0), (224, 224)]
    assert all(p.shape == (224, 224, 3) for p in result.patches)


def test_partial_edge_tiles_are_dropped() -> None:
    result = tile_image(_image(500, 700, (0, 0, 500, 700)))
    assert result.grid_candidates == 2 * 3


def test_patches_are_capped_and_evenly_spaced() -> None:
    params = TilingParams(max_patches_per_image=4)
    image_with_glass = _image(448, 1792, (0, 0, 448, 1792))  # 2 x 8 = 16 tissue tiles
    image_with_glass[:5, :5] = GLASS  # keep a little glass so Otsu has two levels
    result = tile_image(image_with_glass, params)
    assert len(result.patches) == 4
    lefts = [c for _, c in result.coords]
    assert lefts[0] == 0  # first and last kept tiles span the image
    assert result.coords[-1] == (224, 1568)


def test_image_without_enough_tissue_keeps_its_best_tile() -> None:
    image = _image(448, 448, (0, 0, 60, 60))  # a small speck of tissue
    result = tile_image(image)
    assert result.mode == "grid_fallback"
    assert result.coords == [(0, 0)]


@pytest.mark.parametrize("shape", [(500, 200), (200, 500)])
def test_long_thin_images_fall_back_to_resize(shape: tuple[int, int]) -> None:
    result = tile_image(_image(*shape, (0, 0, *shape)))
    assert result.mode == "resize"
    assert len(result.patches) == 1


def test_threshold_cap_keeps_pale_tissue_on_full_frames() -> None:
    """A frame with no glass: pale (eosin-like) left half, dense (haematoxylin-like) right half.
    Plain Otsu splits the two stains; the cap (default since ADR-0002) counts both as tissue."""
    image = np.zeros((448, 448, 3), dtype=np.uint8)
    image[:, :224] = [225, 185, 205]  # pale pink, saturation ~45
    image[:, 224:] = [120, 60, 150]  # dense purple, saturation ~153
    plain = tile_image(image, TilingParams(max_tissue_threshold=None))
    capped = tile_image(image)
    assert sorted(c for _, c in plain.coords) == [224, 224]  # pale half lost
    assert len(capped.patches) == 4


def test_module_defaults_match_the_protocol() -> None:
    """Inference uses ``TilingParams()``, training uses protocol.yaml; they must agree."""
    from oscc_ml.data.prepare import protocol_tiling

    assert protocol_tiling() == TilingParams()
    assert TilingParams().max_tissue_threshold == 40
    assert protocol_tiling(255).max_tissue_threshold == 255
