"""R0 acceptance: ``oscc-ml train --model resnet50 --smoke`` on CPU, < 5 minutes, full run folder,
and two runs with the same seed give identical results."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from oscc_ml.cli import app
from oscc_ml.train.runner import run_training

pytestmark = pytest.mark.slow

SMOKE_BUDGET_SECONDS = 300
EXPECTED_FILES = [
    "config.resolved.yaml",
    "run_info.json",
    "environment.json",
    "run.log",
    "train_log.csv",
    "checkpoints/best.pt",
    "checkpoints/last.pt",
    "predictions/val_patches.csv",
    "predictions/val_images.csv",
    "metrics.json",
    "observations/epochs.jsonl",
    "observations/training_summary.json",
]
# Training never writes test predictions (audit M2); `oscc-ml evaluate` does.
NEVER_WRITTEN = ["predictions/test_patches.csv", "predictions/test_images.csv"]
TIMING_KEYS = {"training_time_seconds", "mean_epoch_seconds"}


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, float]:
    root = tmp_path_factory.mktemp("runs")
    started = time.perf_counter()
    first = run_training("resnet50", smoke=True, runs_dir=root / "a")
    elapsed = time.perf_counter() - started
    second = run_training("resnet50", smoke=True, runs_dir=root / "b")
    return first, second, elapsed


def test_smoke_run_finishes_within_budget(two_runs: tuple[Path, Path, float]) -> None:
    assert two_runs[2] < SMOKE_BUDGET_SECONDS, f"smoke run took {two_runs[2]:.0f} s"


def test_run_folder_has_every_artifact(two_runs: tuple[Path, Path, float]) -> None:
    run_dir = two_runs[0]
    assert run_dir.name.endswith("_resnet50_42")
    missing = [f for f in EXPECTED_FILES if not (run_dir / f).is_file()]
    assert not missing, f"missing: {missing}"


def test_run_info_records_provenance(two_runs: tuple[Path, Path, float]) -> None:
    info = json.loads((two_runs[0] / "run_info.json").read_text("utf-8"))
    assert info["status"] == "completed"
    assert info["smoke"] is True
    assert info["purpose"] == "smoke"
    assert info["reportable"] is False
    assert info["protocol_compliant"] is False
    assert info["dataset_version"] == "synthetic-smoke"
    assert info["git_commit"]
    assert "git_dirty" in info
    assert info["protocol_version"] == "sds-appendix-a-v1"


def test_environment_records_versions_and_gpu(two_runs: tuple[Path, Path, float]) -> None:
    env = json.loads((two_runs[0] / "environment.json").read_text("utf-8"))
    for key in ("torch", "torchvision", "transformers", "cuda_version", "gpu_names", "python"):
        assert key in env, key
    assert env["device_used"] == "cpu"
    assert isinstance(env["gpu_names"], list)


def test_resolved_config_marks_smoke(two_runs: tuple[Path, Path, float]) -> None:
    cfg = yaml.safe_load((two_runs[0] / "config.resolved.yaml").read_text("utf-8"))
    assert cfg["architecture"] == "resnet50"
    assert cfg["run"]["smoke"] is True
    assert cfg["run"]["pretrained"] is False
    assert cfg["run"]["dataset_version"] == "synthetic-smoke"


def test_metrics_and_predictions_are_consistent(two_runs: tuple[Path, Path, float]) -> None:
    run_dir = two_runs[0]
    metrics = json.loads((run_dir / "metrics.json").read_text("utf-8"))
    with (run_dir / "predictions" / "val_images.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == metrics["val"]["image"]["n"]
    assert "test" not in metrics
    for name in NEVER_WRITTEN:
        assert not (run_dir / name).exists()
    assert all(0.0 <= float(r["oscc_probability"]) <= 1.0 for r in rows)
    assert {"group_id", "magnification"} <= set(rows[0])
    log = (run_dir / "train_log.csv").read_text("utf-8").splitlines()
    assert len(log) == 1 + metrics["epochs_run"]
    assert "epoch_seconds" in log[0]


def _strip_timing(row: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in row.items() if k != "epoch_seconds"}


def test_same_seed_runs_are_identical(two_runs: tuple[Path, Path, float]) -> None:
    a, b, _ = two_runs
    for name in ("val_patches.csv", "val_images.csv"):
        assert (a / "predictions" / name).read_bytes() == (b / "predictions" / name).read_bytes()
    epochs = [
        [
            {k: v for k, v in json.loads(line).items() if k != "epoch_seconds"}
            for line in (d / "observations" / "epochs.jsonl").read_text("utf-8").splitlines()
        ]
        for d in (a, b)
    ]
    assert epochs[0] == epochs[1]
    with (a / "train_log.csv").open() as fa, (b / "train_log.csv").open() as fb:
        assert [_strip_timing(r) for r in csv.DictReader(fa)] == [
            _strip_timing(r) for r in csv.DictReader(fb)
        ]
    ma = json.loads((a / "metrics.json").read_text("utf-8"))
    mb = json.loads((b / "metrics.json").read_text("utf-8"))
    assert {k: v for k, v in ma.items() if k not in TIMING_KEYS} == {
        k: v for k, v in mb.items() if k not in TIMING_KEYS
    }


def test_cli_rejects_training_without_a_prepared_dataset(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "train",
            "--model",
            "resnet50",
            "--runs-dir",
            str(tmp_path),
            "--data-root",
            str(tmp_path / "none"),
        ],
    )
    assert result.exit_code == 2
    assert "oscc-ml prepare" in result.output
    assert not any(tmp_path.iterdir())


def test_cli_rejects_unknown_model() -> None:
    assert CliRunner().invoke(app, ["train", "--model", "vgg16", "--smoke"]).exit_code == 2


def test_cli_rejects_gpu_for_smoke(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "train",
            "--model",
            "resnet50",
            "--smoke",
            "--device",
            "cuda",
            "--runs-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    assert "CPU-only" in result.output
