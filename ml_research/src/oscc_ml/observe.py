"""Training observation record (Phase 2A): what happened during every sweep trial, training run and
evaluation, so the choice of model can be defended from the evidence.

Recording never changes training: it only reads values the loop already has (losses, gradients after
``backward``, validation predictions) and writes extra files. ``ENABLED = False`` switches every
hook off; ``tests/test_observe.py`` trains with and without it and checks that checkpoints and
predictions are byte-identical.

Files:
* ``<run>/observations/epochs.jsonl``: one line per epoch;
* ``<run>/observations/training_summary.json``: best epoch, stop epoch and reason, resumes,
  warnings, non-finite batches;
* ``<runs>/decisions.jsonl``: one line per decision (chosen LR and why each other LR was rejected,
  each run's stopping decision, tau per run, paired comparisons);
* ``<runs>/environment.json``: environment snapshot of the machine that ran the pipeline.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from oscc_ml.utils.io import iso, utc_now

ENABLED = True  # tests set this to False to prove that recording changes nothing

OBSERVATIONS_DIR = "observations"
EPOCHS_FILE = "epochs.jsonl"
SUMMARY_FILE = "training_summary.json"
DECISIONS_FILE = "decisions.jsonl"
ENVIRONMENT_FILE = "environment.json"
UNCALIBRATED = 0.5  # per-epoch validation recall/specificity/F1 use 0.5; tau is chosen in evaluate

logger = logging.getLogger("oscc_ml.observe")


def _clean(value: Any) -> Any:
    """JSON-safe: NaN/inf become strings so the files stay valid JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if isinstance(value, np.generic):
        return _clean(value.item())
    return value


@contextlib.contextmanager
def capture_warnings(enabled: bool = True) -> Iterator[list[str]]:
    """Collect the warnings raised inside the block as sorted, de-duplicated ``"Category: text"``.

    Exception-safe: ``warnings.catch_warnings`` restores the global filters and ``showwarning`` on
    any exit, and the list is filled in a ``finally`` so warnings raised before an exception are
    still logged before the exception propagates. With ``enabled=False`` nothing is captured and the
    global warning state is never touched (the list stays empty).
    """
    messages: list[str] = []
    if not enabled:
        yield messages
        return
    failed = True
    with warnings.catch_warnings(record=True) as caught:
        try:
            yield messages
            failed = False
        finally:
            messages[:] = sorted({f"{w.category.__name__}: {w.message}" for w in caught or []})
            if failed:
                for message in messages:
                    logger.warning("warning before the failure: %s", message)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_clean(record), sort_keys=True) + "\n")


def write_json_file(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(record), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record_decision(runs_dir: Path, step: str, decision: str, **details: Any) -> None:
    """Append one decision to ``<runs_dir>/decisions.jsonl``."""
    if not ENABLED:
        return
    append_jsonl(
        runs_dir / DECISIONS_FILE,
        {"time": iso(utc_now()), "step": step, "decision": decision, **details},
    )


def already_recorded(runs_dir: Path, step: str, run: str) -> bool:
    """True if ``decisions.jsonl`` already has an entry for this step and run (resumes)."""
    path = runs_dir / DECISIONS_FILE
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            if entry.get("step") == step and entry.get("run") == run:
                return True
    return False


def record_training_decision(runs_dir: Path, run_dir: Path) -> None:
    """One decision per training run: which checkpoint was kept and why training stopped."""
    summary_path = run_dir / OBSERVATIONS_DIR / SUMMARY_FILE
    if (
        not ENABLED
        or not summary_path.is_file()
        or already_recorded(runs_dir, "train", run_dir.name)
    ):
        return
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    record_decision(
        runs_dir,
        "train",
        f"{summary['architecture']} seed {summary['seed']}: kept epoch {summary['best_epoch']} "
        f"(best validation AUC {summary['best_val_auc']}); stopped at epoch "
        f"{summary['stop_epoch']}",
        run=run_dir.name,
        reason=summary["stop_reason"],
        resumed_at_epochs=summary["resumed_at_epochs"],
        warnings=summary["warnings"],
        non_finite_loss_batches=summary["non_finite_loss_batches"],
        evidence=f"{run_dir.name}/{OBSERVATIONS_DIR}/{EPOCHS_FILE}",
    )


def snapshot_environment(runs_dir: Path, device: torch.device | str = "cpu") -> None:
    """Write ``<runs_dir>/environment.json`` (overwritten on every pipeline step that calls it)."""
    if not ENABLED:
        return
    from oscc_ml.runinfo import environment_info

    if str(device) == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    write_json_file(
        runs_dir / ENVIRONMENT_FILE,
        {"recorded_at": iso(utc_now()), **environment_info(torch.device(device))},
    )


class GradNormTracker:
    """Global L2 norm of the gradients of every batch, read after ``backward`` and before the
    optimizer step. With AMP the gradients are scaled; the norm is divided by the scale, so it is
    the unscaled norm. Nothing is modified. Norms stay on the device and are summarised once per
    epoch."""

    def __init__(self) -> None:
        self._norms: list[torch.Tensor] = []

    def add(self, model: nn.Module, scale: float) -> None:
        if not ENABLED:
            return
        grads = [p.grad.detach() for p in model.parameters() if p.grad is not None]
        if not grads:
            return
        norm = torch.linalg.vector_norm(
            torch.stack([torch.linalg.vector_norm(g.float()) for g in grads])
        )
        self._norms.append(norm / scale)

    def summary(self) -> dict[str, Any]:
        if not self._norms:
            return {"n": 0}
        values = torch.stack(self._norms).cpu().double().numpy()
        finite = values[np.isfinite(values)]
        self._norms = []
        out: dict[str, Any] = {
            "n": int(values.size),
            "n_non_finite": int(values.size - finite.size),
        }
        if finite.size:
            out.update(
                min=float(finite.min()),
                mean=float(finite.mean()),
                median=float(np.median(finite)),
                p95=float(np.percentile(finite, 95)),
                max=float(finite.max()),
            )
        return out


def validation_metrics(labels: list[int], probabilities: list[float]) -> dict[str, Any]:
    """Recall, specificity, precision, F1 and accuracy at the uncalibrated 0.5 (image level)."""
    from oscc_ml.eval.bootstrap import point_metrics

    y = np.asarray(labels, dtype=int)
    p = np.asarray(probabilities, dtype=float)
    metrics = point_metrics(y, p, UNCALIBRATED)
    return {
        f"val_{k}_at_0.5": metrics[k]
        for k in ("recall", "specificity", "precision", "f1", "accuracy")
    }


def peak_gpu_memory_mb(device: torch.device) -> float | None:
    if device.type != "cuda":
        return None
    return float(torch.cuda.max_memory_allocated(device) / 2**20)


def stop_reason(stopped_early: bool, patience: int, epochs_run: int, max_epochs: int) -> str:
    if stopped_early:
        return (
            f"early stopping: validation image-level AUC did not improve for {patience} "
            "consecutive epochs (patience)"
        )
    if epochs_run >= max_epochs:
        return f"reached the maximum number of epochs ({max_epochs})"
    return "interrupted before the end"
