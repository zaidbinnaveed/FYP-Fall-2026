"""Names and constants that must stay importable without PyTorch.

``report`` and ``import-results`` use only these, so rebuilding the report at home needs a light
install (core dependencies, no ``train`` extra and no torch).
"""

from __future__ import annotations

ALL_ARCHITECTURES = ("resnet50", "efficientnet_b0", "densenet121", "vit_b_16")
# Classical classifiers on the tabular dataset (Phase T, proposed FR-7.11). Not image models:
# `train-all`, `sweep` and `evaluate` never touch them; `oscc-ml tabular-train` makes their runs.
TABULAR_ARCHITECTURES = ("tab_logreg", "tab_random_forest", "tab_gradient_boosting")

# SDS data dictionary, model_versions.architecture
DISPLAY_NAME = {
    "resnet50": "ResNet50",
    "efficientnet_b0": "EfficientNet-B0",
    "densenet121": "DenseNet121",
    "vit_b_16": "ViT-B/16",
    "tab_logreg": "Logistic regression (tabular)",
    "tab_random_forest": "Random forest (tabular)",
    "tab_gradient_boosting": "Gradient boosting (tabular)",
}
FAMILY = {
    "resnet50": "CNN",
    "efficientnet_b0": "CNN",
    "densenet121": "CNN",
    "vit_b_16": "ViT",
    "tab_logreg": "Tabular",
    "tab_random_forest": "Tabular",
    "tab_gradient_boosting": "Tabular",
}

EVALUATION_FILE = "evaluation.json"
SYNTHETIC_PREFIX = "synthetic"


def is_synthetic(dataset_version: str) -> bool:
    return dataset_version.startswith(SYNTHETIC_PREFIX)
