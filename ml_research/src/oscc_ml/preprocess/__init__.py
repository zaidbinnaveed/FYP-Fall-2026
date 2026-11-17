"""THE single preprocessing module, shared by training and the inference service.

R0 provides conversion and ImageNet normalization. Phase R1 adds tiling (O5), the tissue filter,
optional stain normalization and the H&E colour-profile check. Any change here must bump
``PREPROCESS_VERSION``; the parity test (Phase D2) keeps training and inference identical.
"""

from __future__ import annotations

import numpy as np
import torch
from numpy.typing import NDArray

PREPROCESS_VERSION = "pp-0.1.0"

IMAGENET_MEAN: tuple[float, float, float] = (0.485, 0.456, 0.406)
IMAGENET_STD: tuple[float, float, float] = (0.229, 0.224, 0.225)


def to_float_tensor(image: NDArray[np.uint8]) -> torch.Tensor:
    """HxWx3 uint8 RGB -> 3xHxW float32 in [0, 1]."""
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"expected HxWx3 uint8 RGB, got {image.dtype} {image.shape}")
    return torch.from_numpy(np.ascontiguousarray(image)).permute(2, 0, 1).float().div_(255.0)


def normalize(
    tensor: torch.Tensor,
    mean: tuple[float, float, float] = IMAGENET_MEAN,
    std: tuple[float, float, float] = IMAGENET_STD,
) -> torch.Tensor:
    """Channel-wise ``(x - mean) / std`` on a 3xHxW or Nx3xHxW float tensor."""
    shape = (3, 1, 1) if tensor.ndim == 3 else (1, 3, 1, 1)
    m = torch.tensor(mean, dtype=tensor.dtype).view(shape)
    s = torch.tensor(std, dtype=tensor.dtype).view(shape)
    return (tensor - m) / s
