"""Figures for the results package, drawn ONLY from run folders: ROC and PR curves and the confusion
matrix at tau per model (test predictions), and training curves (``train_log.csv``) for the image
models. Matplotlib is optional (``train`` extra): without it the figures are skipped and the report
says so."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve, roc_curve

logger = logging.getLogger("oscc_ml.report")


def _plt() -> Any | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    return plt


def available() -> bool:
    return _plt() is not None


def _test_frame(run_dir: Path) -> pd.DataFrame:
    return pd.read_csv(run_dir / "predictions" / "test_images.csv", dtype={"image_id": str})


def roc_pr(
    runs: dict[str, tuple[str, Path]], out_dir: Path, *, title_suffix: str = ""
) -> list[Path]:
    """One ROC and one PR figure with every model (label -> (display name, run folder))."""
    plt = _plt()
    if plt is None or not runs:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for kind in ("roc", "pr"):
        fig, ax = plt.subplots(figsize=(6, 5), dpi=120)
        for name, run_dir in runs.values():
            frame = _test_frame(run_dir)
            y, p = frame["label"].to_numpy(int), frame["oscc_probability"].to_numpy(float)
            if len(np.unique(y)) < 2:
                continue
            if kind == "roc":
                fpr, tpr, _ = roc_curve(y, p)
                ax.plot(fpr, tpr, label=name)
            else:
                precision, recall, _ = precision_recall_curve(y, p)
                ax.plot(recall, precision, label=name)
        if kind == "roc":
            ax.plot([0, 1], [0, 1], linestyle=":", color="grey", label="chance")
            ax.set_xlabel("False-positive rate (1 - specificity)")
            ax.set_ylabel("True-positive rate (recall)")
            ax.set_title(f"ROC, test images{title_suffix}")
        else:
            ax.set_xlabel("Recall")
            ax.set_ylabel("Precision")
            ax.set_title(f"Precision-recall, test images{title_suffix}")
        ax.legend(fontsize=7, loc="lower right" if kind == "roc" else "lower left")
        ax.grid(alpha=0.3)
        path = out_dir / f"{kind}_test.png"
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        paths.append(path)
    return paths


def confusion(
    name: str, arch: str, evaluation: dict[str, Any], out_dir: Path, suffix: str = ""
) -> Path | None:
    plt = _plt()
    if plt is None:
        return None
    cm = evaluation["test_at_tau"]["confusion_matrix"]
    grid = np.array([[cm["tn"], cm["fp"]], [cm["fn"], cm["tp"]]])
    fig, ax = plt.subplots(figsize=(3.6, 3.2), dpi=120)
    ax.imshow(grid, cmap="Blues")
    for (i, j), value in np.ndenumerate(grid):
        ax.text(
            j,
            i,
            str(value),
            ha="center",
            va="center",
            fontsize=12,
            color="white" if value > grid.max() / 2 else "black",
        )
    ax.set_xticks([0, 1], ["pred non-OSCC", "pred OSCC"], fontsize=8)
    ax.set_yticks([0, 1], ["true non-OSCC", "true OSCC"], fontsize=8)
    ax.set_title(f"{name}{suffix}\nat tau = {evaluation['threshold']['threshold']:.3f}", fontsize=9)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"confusion_{arch}.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def training_curve(
    name: str, arch: str, run_dir: Path, out_dir: Path, suffix: str = ""
) -> Path | None:
    plt = _plt()
    log = run_dir / "train_log.csv"
    if plt is None or not log.is_file():
        return None
    frame = pd.read_csv(log)
    if frame.empty:
        return None
    fig, ax1 = plt.subplots(figsize=(6, 3.6), dpi=120)
    ax1.plot(frame["epoch"], frame["train_loss"], label="train loss")
    ax1.plot(frame["epoch"], frame["val_loss"], label="validation loss")
    ax1.set_xlabel("epoch")
    ax1.set_ylabel("loss")
    ax2 = ax1.twinx()
    ax2.plot(
        frame["epoch"], frame["val_auc"], color="black", linestyle="--", label="validation AUC"
    )
    ax2.set_ylabel("validation AUC")
    handles = ax1.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
    labels = ax1.get_legend_handles_labels()[1] + ax2.get_legend_handles_labels()[1]
    ax1.legend(handles, labels, fontsize=7, loc="center right")
    ax1.set_title(f"{name}: training curve{suffix}", fontsize=9)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"training_{arch}.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def accuracy_vs_cost(points: list[dict[str, Any]], out_dir: Path, suffix: str = "") -> Path | None:
    """Test AUC (with CI bars) against CPU latency per image, log x axis."""
    plt = _plt()
    usable = [p for p in points if p.get("latency_ms") and p.get("auc") is not None]
    if plt is None or not usable:
        return None
    fig, ax = plt.subplots(figsize=(6, 4.2), dpi=120)
    for p in usable:
        low, high = p.get("auc_low"), p.get("auc_high")
        yerr = None if low is None or high is None else [[p["auc"] - low], [high - p["auc"]]]
        ax.errorbar(p["latency_ms"], p["auc"], yerr=yerr, fmt="o", capsize=3)
        ax.annotate(
            p["name"],
            (p["latency_ms"], p["auc"]),
            fontsize=7,
            xytext=(4, 4),
            textcoords="offset points",
        )
    ax.set_xscale("log")
    ax.set_xlabel("CPU latency per image or patch, ms (log scale)")
    ax.set_ylabel("Test AUC-ROC [95% CI]")
    ax.set_title(f"Accuracy vs cost{suffix}", fontsize=9)
    ax.grid(alpha=0.3)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "accuracy_vs_cost.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
