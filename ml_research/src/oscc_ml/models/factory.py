"""Model factory: architecture name -> ``nn.Module`` that maps Nx3x224x224 to N x 1 logits.

Architectures (SDS data dictionary ``model_versions.architecture``; plan section 4.1):

    resnet50         ResNet50         torchvision IMAGENET1K_V1
    efficientnet_b0  EfficientNet-B0  torchvision IMAGENET1K_V1
    densenet121      DenseNet121      torchvision IMAGENET1K_V1
    vit_b_16         ViT-B/16         HuggingFace google/vit-base-patch16-224, eager attention

All CNNs use the classic torchvision V1 recipe (confirmed at gate G2). ``pretrained=False``
builds the same architecture with random weights (offline; tests and cost measurement).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import torch
from torch import nn
from torchvision import models

VIT_CHECKPOINT = "google/vit-base-patch16-224"

DISPLAY_NAME = {
    "resnet50": "ResNet50",
    "efficientnet_b0": "EfficientNet-B0",
    "densenet121": "DenseNet121",
    "vit_b_16": "ViT-B/16",
}
FAMILY = {
    "resnet50": "CNN",
    "efficientnet_b0": "CNN",
    "densenet121": "CNN",
    "vit_b_16": "ViT",
}
WEIGHTS_SOURCE = {
    "resnet50": "torchvision ResNet50_Weights.IMAGENET1K_V1",
    "efficientnet_b0": "torchvision EfficientNet_B0_Weights.IMAGENET1K_V1",
    "densenet121": "torchvision DenseNet121_Weights.IMAGENET1K_V1",
    "vit_b_16": f"huggingface {VIT_CHECKPOINT} (ImageNet-21k pretrain, ImageNet-1k fine-tune)",
}

Builder = Callable[[bool], nn.Module]


def _resnet50(pretrained: bool) -> nn.Module:
    weights = models.ResNet50_Weights.IMAGENET1K_V1 if pretrained else None
    model = models.resnet50(weights=weights)  # torchvision is untyped (Any)
    model.fc = nn.Linear(model.fc.in_features, 1)
    return cast("nn.Module", model)


def _efficientnet_b0(pretrained: bool) -> nn.Module:
    weights = models.EfficientNet_B0_Weights.IMAGENET1K_V1 if pretrained else None
    model = models.efficientnet_b0(weights=weights)
    last = model.classifier[-1]
    model.classifier[-1] = nn.Linear(last.in_features, 1)
    return cast("nn.Module", model)


def _densenet121(pretrained: bool) -> nn.Module:
    weights = models.DenseNet121_Weights.IMAGENET1K_V1 if pretrained else None
    model = models.densenet121(weights=weights)
    model.classifier = nn.Linear(model.classifier.in_features, 1)
    return cast("nn.Module", model)


class ViTBinary(nn.Module):
    """HuggingFace ViT-B/16 with a 1-logit head; ``forward`` returns a plain tensor.

    Eager attention keeps attention weights available for attention rollout (Phase R4).
    """

    def __init__(self, pretrained: bool) -> None:
        super().__init__()
        from transformers import ViTConfig, ViTForImageClassification

        if pretrained:
            self.vit = ViTForImageClassification.from_pretrained(
                VIT_CHECKPOINT,
                num_labels=1,
                ignore_mismatched_sizes=True,  # replaces the 1000-class head with 1 logit
                attn_implementation="eager",
            )
        else:
            # ViTConfig defaults are exactly ViT-B/16 at 224 px (12 layers, 768 hidden, 12 heads).
            config = ViTConfig()
            config.num_labels = 1
            config._attn_implementation = "eager"
            self.vit = ViTForImageClassification(config)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return cast("torch.Tensor", self.vit(pixel_values=x).logits)


def _vit_b_16(pretrained: bool) -> nn.Module:
    return ViTBinary(pretrained)


_REGISTRY: dict[str, Builder] = {
    "resnet50": _resnet50,
    "efficientnet_b0": _efficientnet_b0,
    "densenet121": _densenet121,
    "vit_b_16": _vit_b_16,
}

ALL_ARCHITECTURES = ("resnet50", "efficientnet_b0", "densenet121", "vit_b_16")


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


def attention_implementation(model: nn.Module) -> str | None:
    """The attention backend actually in use (``eager`` for ViT), for tests and run records."""
    if isinstance(model, ViTBinary):
        return cast("str", model.vit.config._attn_implementation)
    return None


def parameter_count(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
