"""Model factory: four architectures, one logit each, SDS names, ViT eager attention."""

from __future__ import annotations

import pytest
import torch

from oscc_ml.config import load_model_config, model_config_names
from oscc_ml.models.factory import (
    ALL_ARCHITECTURES,
    DISPLAY_NAME,
    FAMILY,
    attention_implementation,
    build_model,
    parameter_count,
)

# Approximate sizes with a 1-logit head (published backbones), as a sanity check.
EXPECTED_PARAMS_M = {
    "resnet50": (23.0, 24.0),
    "efficientnet_b0": (3.9, 4.2),
    "densenet121": (6.8, 7.1),
    "vit_b_16": (85.0, 86.5),
}


def test_sds_display_names_and_families() -> None:
    # SDS data dictionary, model_versions.architecture examples
    assert [DISPLAY_NAME[a] for a in ALL_ARCHITECTURES] == [
        "ResNet50",
        "EfficientNet-B0",
        "DenseNet121",
        "ViT-B/16",
    ]
    assert [FAMILY[a] for a in ALL_ARCHITECTURES] == ["CNN", "CNN", "CNN", "ViT"]


def test_every_architecture_has_a_config() -> None:
    assert sorted(load_model_config(n) for n in model_config_names()) == sorted(ALL_ARCHITECTURES)


@pytest.mark.parametrize("architecture", ALL_ARCHITECTURES)
def test_single_logit_output_and_size(architecture: str) -> None:
    torch.manual_seed(0)
    model = build_model(architecture, pretrained=False).eval()
    with torch.no_grad():
        out = model(torch.zeros(2, 3, 224, 224))
    assert out.shape == (2, 1)
    low, high = EXPECTED_PARAMS_M[architecture]
    assert low <= parameter_count(model) / 1e6 <= high


def test_vit_uses_eager_attention() -> None:
    model = build_model("vit_b_16", pretrained=False)
    assert attention_implementation(model) == "eager"
    assert attention_implementation(build_model("resnet50", pretrained=False)) is None


def test_vit_attention_weights_are_available_for_rollout() -> None:
    model = build_model("vit_b_16", pretrained=False).eval()
    with torch.no_grad():
        out = model.vit(pixel_values=torch.zeros(1, 3, 224, 224), output_attentions=True)  # type: ignore[operator]
    assert len(out.attentions) == 12
    assert out.attentions[0].shape == (1, 12, 197, 197)


def test_unknown_architecture_rejected() -> None:
    with pytest.raises(ValueError, match="unknown architecture"):
        build_model("alexnet", pretrained=False)
