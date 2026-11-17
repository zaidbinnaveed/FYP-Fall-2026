"""Model factory: architecture name -> ``nn.Module`` with a single-logit head.

R0 registers ResNet50. EfficientNet-B0, DenseNet121 and ViT-B/16 (HuggingFace
``google/vit-base-patch16-224``, ``attn_implementation="eager"``) are added in Phase R2.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from torch import nn
from torchvision import models

Builder = Callable[[bool], nn.Module]


def _resnet50(pretrained: bool) -> nn.Module:
    # torchvision ImageNet-1k weights (CLAUDE.md section 4). V1 is the original torchvision
    # recipe; confirm the variant at gate G2 together with the other R2 settings.
    weights = models.ResNet50_Weights.IMAGENET1K_V1 if pretrained else None
    model = models.resnet50(weights=weights)  # torchvision is untyped (Any)
    model.fc = nn.Linear(model.fc.in_features, 1)
    return cast("nn.Module", model)


_REGISTRY: dict[str, Builder] = {"resnet50": _resnet50}

FAMILY = {"resnet50": "CNN"}


def available_architectures() -> list[str]:
    return sorted(_REGISTRY)


def build_model(architecture: str, pretrained: bool) -> nn.Module:
    try:
        builder = _REGISTRY[architecture]
    except KeyError:
        raise ValueError(
            f"unknown architecture {architecture!r}; available: {available_architectures()}"
        ) from None
    return builder(pretrained)


def parameter_count(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
