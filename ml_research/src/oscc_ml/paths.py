"""Default locations. All generated data stays in gitignored folders under ``ml_research/``.

data/raw/        downloaded archives (never modified by the code)
data/sample/     small local sample (make-sample, Phase R1)
data/processed/  prepared datasets (manifest, splits, 224x224 patches)
runs/            run folders, sweep results, reports, exports
.cache/          pretrained weights (torchvision, HuggingFace)
"""

from __future__ import annotations

import os
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ML_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SAMPLE_DIR = DATA_DIR / "sample"
PROCESSED_DIR = DATA_DIR / "processed"
DEFAULT_DATASET_VERSION = "oscc-unified-v1"
DEFAULT_DATA_ROOT = PROCESSED_DIR / DEFAULT_DATASET_VERSION
RUNS_DIR = ML_ROOT / "runs"
SWEEP_DIR_NAME = "sweep"
REPORT_DIR_NAME = "report"
EXPORT_DIR_NAME = "export"
CACHE_DIR = ML_ROOT / ".cache"


def configure_caches() -> None:
    """Keep pretrained-weight caches inside the repo (no admin rights, no profile clutter).

    Respects TORCH_HOME / HF_HOME if the user already set them.
    """
    os.environ.setdefault("TORCH_HOME", str(CACHE_DIR / "torch"))
    os.environ.setdefault("HF_HOME", str(CACHE_DIR / "huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
