"""TRAINING_JOURNAL.md (Phase 2A): written only from saved files, says "not yet run" when a file
is missing and never invents a number."""

from __future__ import annotations

import json
import re
from pathlib import Path

from oscc_ml import journal


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_empty_folders_say_not_yet_run(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    text = journal.write_run_journal(run).read_text("utf-8")
    assert "Not yet run" in text
    assert "No epoch was logged" in text
    sweep = journal.write_sweep_journal(tmp_path).read_text("utf-8")
    assert "Not yet run" in sweep
    top = journal.write_pipeline_journal(tmp_path).read_text("utf-8")
    assert "Sweep: not yet run" in top
    assert "Training: not yet run" in top
    assert "Evaluation: not yet run" in top
    assert "No decision recorded yet" in top
    for body in (text, sweep, top):
        # no number appears without a file behind it
        assert not re.search(r"\d\.\d", body), body


def test_run_journal_copies_the_logged_values(tmp_path: Path) -> None:
    run = tmp_path / "resnet50_42"
    _write(
        run / "run_info.json",
        {
            "architecture": "resnet50",
            "display_name": "ResNet50",
            "seed": 42,
            "status": "completed",
            "lr": 3e-4,
            "purpose": "train",
            "protocol_compliant": True,
            "reportable": True,
        },
    )
    (run / "train_log.csv").write_text(
        "epoch,lr,train_loss,val_loss,val_auc,epoch_seconds\n"
        "1,0.0003,0.61,0.55,0.8123,12.5\n2,0.0003,0.42,0.50,0.8456,12.0\n",
        encoding="utf-8",
    )
    obs = run / "observations"
    obs.mkdir()
    (obs / "epochs.jsonl").write_text(
        json.dumps({"epoch": 1, "improved": True, "warnings": []})
        + "\n"
        + json.dumps({"epoch": 2, "improved": True, "warnings": ["UserWarning: x"]})
        + "\n",
        encoding="utf-8",
    )
    _write(
        obs / "training_summary.json",
        {
            "best_epoch": 2,
            "best_val_auc": 0.8456,
            "stop_reason": "reached the maximum number of epochs (2)",
            "stop_epoch": 2,
            "max_epochs": 2,
            "patience": 7,
            "resumed_at_epochs": [],
            "warnings": 1,
            "non_finite_loss_batches": 0,
            "checkpoint_rule": "best.pt = epoch with the highest validation image-level AUC",
        },
    )
    text = journal.write_run_journal(run).read_text("utf-8")
    assert "Learning rate 0.0003" in text
    assert "| 2 | 0.0003 | 0.4200 | 0.5000 | 0.8456 | yes | 12.0 |" in text
    assert "epoch 2, validation AUC 0.8456" in text
    assert "reached the maximum number of epochs (2)" in text
    assert "warning seen: UserWarning: x" in text
    assert "Not yet run (`oscc-ml evaluate`" in text

    _write(
        run / "evaluation.json",
        {
            "threshold": {"threshold": 0.4321, "rule": "max F1", "target_recall": 0.95},
            "test": {"auc_roc": {"estimate": 0.9, "ci_low": 0.8, "ci_high": 0.95}},
            "test_at_tau": {"confusion_matrix": {"tp": 5, "fp": 1, "fn": 2, "tn": 3}},
            "test_by_magnification": {"100x": {"n_images": 4, "auc_roc": 0.75}},
        },
    )
    text = journal.write_run_journal(run).read_text("utf-8")
    assert "tau = 0.432100" in text
    assert "auc_roc: 0.9000 (95% CI 0.8000-0.9500)" in text
    assert "TP 5, FP 1, FN 2, TN 3" in text
    assert "Magnification 100x: 4 test images, AUC 0.7500" in text


def test_sweep_and_pipeline_journals(tmp_path: Path) -> None:
    _write(
        tmp_path / "sweep" / "chosen_lr.json",
        {
            "chosen_lr": 1e-4,
            "selection_rule": "highest mean validation AUC",
            "lr_grid": [1e-4, 1e-3],
            "models": ["a", "b"],
            "val_auc_table": {"0.0001": {"a": 0.9, "b": 0.8}, "0.001": {"a": 0.7, "b": 0.6}},
            "lr_decisions": [
                {"rank": 1, "lr": 1e-4, "mean_val_auc": 0.85, "decision": "chosen", "reason": "r1"},
                {
                    "rank": 2,
                    "lr": 1e-3,
                    "mean_val_auc": 0.65,
                    "decision": "rejected",
                    "reason": "r2",
                },
            ],
        },
    )
    (tmp_path / "decisions.jsonl").write_text(
        json.dumps({"step": "sweep", "decision": "LR 0.0001 chosen", "reason": "r1"}) + "\n",
        encoding="utf-8",
    )
    sweep = journal.write_sweep_journal(tmp_path).read_text("utf-8")
    assert "Chosen learning rate: 0.0001" in sweep
    assert "| 2 | 0.001 | 0.6500 | rejected | r2 |" in sweep
    assert "| 0.0001 | 0.9000 | 0.8000 |" in sweep
    top = journal.write_pipeline_journal(tmp_path).read_text("utf-8")
    assert "Sweep: chosen LR 0.0001" in top
    assert "[sweep] LR 0.0001 chosen. Why: r1" in top


def test_a_broken_journal_never_fails_the_caller(tmp_path: Path) -> None:
    def boom(_: Path) -> Path:
        raise RuntimeError("bad")

    journal.safely(boom, tmp_path)  # logged, not raised
