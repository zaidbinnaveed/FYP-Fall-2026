"""End-to-end pipeline on synthetic data (CPU, random init, short runs):

sweep -> train-all -> evaluate -> report -> pack-results -> import-results -> report again,
plus resume after an interruption and the refusals that keep reports honest.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from oscc_ml.cli import app
from oscc_ml.config import DEFAULT_CONFIG_DIR
from oscc_ml.data.synthetic import write_synthetic_dataset
from oscc_ml.eval.evaluate import evaluate_all
from oscc_ml.models.factory import ALL_ARCHITECTURES
from oscc_ml.report import ReportRefusedError, build_report
from oscc_ml.results import (
    CHECKPOINTS_ZIP,
    MANIFEST,
    SMALL_ZIP,
    ImportRefusedError,
    import_results,
    pack_results,
)
from oscc_ml.train import trainer
from oscc_ml.train.runner import run_training
from oscc_ml.train.sweep import chosen_lr_path, run_sweep
from oscc_ml.train.train_all import NoChosenLearningRateError, train_all

pytestmark = pytest.mark.slow
TEST_GRID = [1.0e-4, 1.0e-3]


@pytest.fixture(scope="module")
def config_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Protocol copy with a 2-value LR grid and no DataLoader workers (CI speed only)."""
    folder = tmp_path_factory.mktemp("configs")
    for path in DEFAULT_CONFIG_DIR.glob("*.yaml"):
        shutil.copy(path, folder / path.name)
    protocol = yaml.safe_load((folder / "protocol.yaml").read_text("utf-8"))
    protocol["optimizer"]["lr_grid"] = TEST_GRID
    protocol["data"]["num_workers"] = 0
    (folder / "protocol.yaml").write_text(yaml.safe_dump(protocol), "utf-8")
    return folder


@pytest.fixture(scope="module")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_synthetic_dataset(
        tmp_path_factory.mktemp("data"),
        (8, 8, 8),
        seed=11,
        patches_per_image=(1, 2),
        dataset_version="synthetic-pipeline",
    )


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory: pytest.TempPathFactory, config_dir: Path, data_root: Path) -> Path:
    runs = tmp_path_factory.mktemp("runs")
    common = {"device": "cpu", "config_dir": config_dir, "pretrained": False}
    with pytest.raises(NoChosenLearningRateError, match="sweep"):
        train_all(data_root, runs, epochs=1, **common)  # type: ignore[arg-type]
    run_sweep(data_root, runs, epochs=1, **common)  # type: ignore[arg-type]
    result = train_all(data_root, runs, epochs=2, resume=True, **common)  # type: ignore[arg-type]
    assert not result.failed, result.failed
    done, failed = evaluate_all(
        runs, n_bootstrap=100, warmup=1, latency_runs=2, measure_gpu=False, config_dir=config_dir
    )
    assert not failed, failed
    assert len(done) == len(ALL_ARCHITECTURES)
    return runs


def test_sweep_writes_the_choice_and_never_reads_test(pipeline: Path) -> None:
    chosen = json.loads(chosen_lr_path(pipeline).read_text("utf-8"))
    assert chosen["chosen_lr"] in TEST_GRID
    assert set(chosen["val_auc_table"]) == {f"{lr:g}" for lr in TEST_GRID}
    assert set(chosen["best_lr_per_model"]) == set(ALL_ARCHITECTURES)
    assert chosen["protocol_sweep"] is False  # random init + synthetic data
    trials = list((pipeline / "sweep").glob("*/run_info.json"))
    assert len(trials) == len(TEST_GRID) * len(ALL_ARCHITECTURES)
    for info_path in trials:
        assert not (info_path.parent / "predictions" / "test_images.csv").exists()


def test_train_all_uses_the_chosen_lr_and_records_it(pipeline: Path) -> None:
    chosen = json.loads(chosen_lr_path(pipeline).read_text("utf-8"))["chosen_lr"]
    infos = [json.loads(p.read_text("utf-8")) for p in pipeline.glob("*/run_info.json")]
    assert sorted(i["architecture"] for i in infos) == sorted(ALL_ARCHITECTURES)
    for info in infos:
        assert info["lr"] == chosen
        assert info["lr_source"] == "sweep (non-protocol)"
        assert info["status"] == "completed"
        assert info["reportable"] is False
        assert info["batch_size"] == 32  # protocol value, unchanged


def test_train_all_resume_skips_completed_runs(
    pipeline: Path, config_dir: Path, data_root: Path
) -> None:
    before = sorted(p.name for p in pipeline.glob("*/run_info.json"))
    result = train_all(
        data_root,
        pipeline,
        epochs=2,
        resume=True,
        device="cpu",
        config_dir=config_dir,
        pretrained=False,
    )
    assert not result.failed
    assert sorted(p.name for p in pipeline.glob("*/run_info.json")) == before


def test_evaluation_has_ci_threshold_and_cost(pipeline: Path) -> None:
    for path in pipeline.glob("*/evaluation.json"):
        ev = json.loads(path.read_text("utf-8"))
        auc = ev["test"]["auc_roc"]
        assert auc["ci_low"] <= auc["estimate"] <= auc["ci_high"]
        assert ev["test"]["_meta"]["resampled_unit"] == "group_id"
        assert 0.0 <= ev["threshold"]["threshold"] <= 1.0
        assert ev["threshold"]["validation_recall"] >= 0.95
        assert ev["cost"]["parameter_count"] > 1_000_000
        assert ev["cost"]["gflops_per_patch"] > 0.1
        assert ev["cost"]["latency_cpu"]["mean_ms"] > 0
        assert set(ev["test_by_magnification"]) == {"100x", "400x"}
        assert ev["test_predictions"]["source"] == "checkpoints/best.pt"
        assert (path.parent / ev["validation_threshold_curve"]).is_file()
        assert "ece" in ev["calibration"]["test"]


def test_observation_record_and_decisions(pipeline: Path) -> None:
    """Phase 2A: per-epoch records, the sweep's LR reasons, one decision per run, tau per run and
    the paired comparisons, plus the environment snapshot."""
    chosen = json.loads(chosen_lr_path(pipeline).read_text("utf-8"))
    assert [d["decision"] for d in chosen["lr_decisions"]].count("chosen") == 1
    assert all(d["reason"] for d in chosen["lr_decisions"])
    assert {t["per_epoch_record"].split("/")[0] for t in chosen["trials"]} == {
        p.parent.name for p in (pipeline / "sweep").glob("*/run_info.json")
    }
    decisions = [
        json.loads(x) for x in (pipeline / "decisions.jsonl").read_text("utf-8").splitlines()
    ]
    steps = [d["step"] for d in decisions]
    assert steps.count("sweep") == len(TEST_GRID)
    assert steps.count("train") == len(ALL_ARCHITECTURES)
    assert steps.count("evaluate") == len(ALL_ARCHITECTURES)
    assert steps.count("compare") == 6  # 4 models -> 6 pairs
    comparisons = json.loads((pipeline / "comparisons.json").read_text("utf-8"))
    pairs = comparisons["seeds"]["42"]
    assert len(pairs) == 6
    assert all(0.0 <= p["delta_auc"]["p_holm"] <= 1.0 for p in pairs)
    assert (pipeline / "environment.json").is_file()
    for run in pipeline.glob("*/run_info.json"):
        summary = json.loads((run.parent / "observations/training_summary.json").read_text())
        assert summary["epochs_run"] >= 1


def test_cli_report_refuses_synthetic_and_noncompliant_runs(pipeline: Path) -> None:
    result = CliRunner().invoke(app, ["report", "--runs-dir", str(pipeline)])
    assert result.exit_code == 2
    assert "synthetic" in result.output
    assert "not protocol-compliant" in result.output


def test_report_from_run_folders(pipeline: Path, tmp_path: Path) -> None:
    paths = build_report(pipeline, tmp_path, allow_synthetic=True, allow_noncompliant=True)
    text = paths["markdown"].read_text("utf-8")
    for name in ("ResNet50", "EfficientNet-B0", "DenseNet121", "ViT-B/16"):
        assert name in text
    assert "not yet run" not in text
    rows = pd.read_csv(paths["csv"])
    assert len(rows) == 4
    assert rows["auc_roc_estimate"].between(0, 1).all()


def test_report_lists_missing_models_as_not_yet_run(pipeline: Path, tmp_path: Path) -> None:
    partial = tmp_path / "runs"
    partial.mkdir()
    for info in pipeline.glob("*/run_info.json"):
        if json.loads(info.read_text("utf-8"))["architecture"] == "resnet50":
            shutil.copytree(info.parent, partial / info.parent.name)
    paths = build_report(partial, tmp_path / "out", allow_synthetic=True, allow_noncompliant=True)
    assert paths["markdown"].read_text("utf-8").count("not yet run") >= 3


def test_report_refuses_smoke_only(tmp_path: Path) -> None:
    run_training("resnet50", smoke=True, runs_dir=tmp_path)
    with pytest.raises(ReportRefusedError, match="smoke"):
        build_report(tmp_path, tmp_path / "report")


def test_pack_and_import_roundtrip(pipeline: Path, tmp_path: Path) -> None:
    build_report(pipeline, pipeline / "report", allow_synthetic=True, allow_noncompliant=True)
    zips = pack_results(pipeline, tmp_path / "export")
    small, ckpt = zips["results_small"], zips["checkpoints"]
    assert small.name == SMALL_ZIP
    assert ckpt.name == CHECKPOINTS_ZIP
    with zipfile.ZipFile(small) as archive:
        names = archive.namelist()
    assert MANIFEST in names
    assert not any("checkpoints/" in n for n in names)
    assert any(n.endswith("evaluation.json") for n in names)
    assert any(n.endswith("predictions/test_images.csv") for n in names)
    assert "sweep/chosen_lr.json" in names
    for extra in ("decisions.jsonl", "environment.json", "comparisons.json"):
        assert extra in names
    assert any(n.endswith("observations/epochs.jsonl") for n in names)
    assert any(n.endswith("val_threshold_curve.csv") for n in names)
    for journal_name in ("TRAINING_JOURNAL.md", "sweep/TRAINING_JOURNAL.md"):
        assert journal_name in names
    run_journals = [n for n in names if n.endswith("/TRAINING_JOURNAL.md") and n.count("/") == 1]
    assert len(run_journals) >= len(ALL_ARCHITECTURES)
    with zipfile.ZipFile(ckpt) as archive:
        ck_names = [n for n in archive.namelist() if n != MANIFEST]
    assert len(ck_names) == 4
    assert all(n.endswith("checkpoints/best.pt") for n in ck_names)

    home = tmp_path / "home_runs"
    imported = import_results(small, home)
    assert imported.written
    again = import_results(small, home)
    assert not again.written  # idempotent
    original = build_report(
        pipeline, tmp_path / "r1", allow_synthetic=True, allow_noncompliant=True
    )
    rebuilt = build_report(home, tmp_path / "r2", allow_synthetic=True, allow_noncompliant=True)
    assert pd.read_csv(original["csv"]).equals(pd.read_csv(rebuilt["csv"]))


def _zip_with(path: Path, files: dict[str, bytes], manifest: dict[str, object]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr(MANIFEST, json.dumps(manifest))
    return path


def test_import_refuses_path_traversal(tmp_path: Path) -> None:
    evil = _zip_with(
        tmp_path / "evil.zip",
        {"../outside.txt": b"x"},
        {"files": [{"path": "../outside.txt", "size": 1, "sha256": "0"}]},
    )
    with pytest.raises(ImportRefusedError, match="unsafe"):
        import_results(evil, tmp_path / "runs")
    assert not (tmp_path / "outside.txt").exists()


def test_import_refuses_corrupt_and_conflicting_files(tmp_path: Path) -> None:
    bad = _zip_with(
        tmp_path / "bad.zip",
        {"run/a.txt": b"hello"},
        {"files": [{"path": "run/a.txt", "size": 5, "sha256": "0" * 64}]},
    )
    with pytest.raises(ImportRefusedError, match="checksum"):
        import_results(bad, tmp_path / "runs")
    assert not (tmp_path / "runs" / "run" / "a.txt").exists()

    import hashlib

    digest = hashlib.sha256(b"hello").hexdigest()
    good = _zip_with(
        tmp_path / "good.zip",
        {"run/a.txt": b"hello"},
        {"files": [{"path": "run/a.txt", "size": 5, "sha256": digest}]},
    )
    target = tmp_path / "runs" / "run" / "a.txt"
    target.parent.mkdir(parents=True, exist_ok=True)  # the refused import may leave the folder
    target.write_bytes(b"different")
    with pytest.raises(ImportRefusedError, match="overwrite"):
        import_results(good, tmp_path / "runs")
    import_results(good, tmp_path / "runs", overwrite=True)
    assert target.read_bytes() == b"hello"


def test_resume_after_interruption_matches_an_uninterrupted_run(
    tmp_path: Path, config_dir: Path, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = {
        "smoke": False,
        "data_root": data_root,
        "device": "cpu",
        "config_dir": config_dir,
        "lr": 1e-4,
        "epochs": 3,
        "pretrained": False,
    }
    reference = run_training("resnet50", runs_dir=tmp_path / "ref", **kwargs)  # type: ignore[arg-type]

    calls = {"n": 0}
    original = trainer._fmt

    def interrupt_after_first_epoch(seconds: float) -> str:
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        return original(seconds)

    monkeypatch.setattr(trainer, "_fmt", interrupt_after_first_epoch)
    with pytest.raises(KeyboardInterrupt):
        run_training("resnet50", runs_dir=tmp_path / "res", **kwargs)  # type: ignore[arg-type]
    monkeypatch.setattr(trainer, "_fmt", original)
    (interrupted,) = list((tmp_path / "res").iterdir())
    assert json.loads((interrupted / "run_info.json").read_text("utf-8"))["status"] == "interrupted"

    resumed = run_training("resnet50", runs_dir=tmp_path / "res", resume=True, **kwargs)  # type: ignore[arg-type]
    assert resumed == interrupted
    info = json.loads((resumed / "run_info.json").read_text("utf-8"))
    assert info["status"] == "completed"
    assert len(info["resumed_at"]) == 1
    log = pd.read_csv(resumed / "train_log.csv")
    assert list(log["epoch"]) == [1, 2, 3]
    ref_log = pd.read_csv(reference / "train_log.csv")
    pd.testing.assert_frame_equal(
        log.drop(columns="epoch_seconds"), ref_log.drop(columns="epoch_seconds")
    )
    for name in ("val_patches.csv", "val_images.csv"):
        assert (resumed / "predictions" / name).read_bytes() == (
            reference / "predictions" / name
        ).read_bytes()
    # training never writes test predictions (audit M2)
    assert not (resumed / "predictions" / "test_images.csv").exists()
    # the observation record survives the interruption: 3 epochs, the resume at epoch 3
    epochs = [
        json.loads(x)
        for x in (resumed / "observations" / "epochs.jsonl").read_text("utf-8").splitlines()
    ]
    assert [e["epoch"] for e in epochs] == [1, 2, 3]
    summary = json.loads((resumed / "observations" / "training_summary.json").read_text("utf-8"))
    assert summary["resumed_at_epochs"] == [3]
    assert summary["epochs_run"] == 3


def test_training_journals_come_only_from_the_logs(pipeline: Path, tmp_path: Path) -> None:
    """Every sweep trial, training run and the pipeline get a TRAINING_JOURNAL.md whose numbers
    match the saved files, and regenerating it from copies of those files alone gives the same
    bytes (no hidden state)."""
    from oscc_ml import journal

    chosen = json.loads(chosen_lr_path(pipeline).read_text("utf-8"))
    sweep_text = (pipeline / "sweep" / "TRAINING_JOURNAL.md").read_text("utf-8")
    assert f"Chosen learning rate: {chosen['chosen_lr']:g}" in sweep_text
    for trial in (pipeline / "sweep").glob("*/run_info.json"):
        assert (trial.parent / "TRAINING_JOURNAL.md").is_file()
    top = (pipeline / "TRAINING_JOURNAL.md").read_text("utf-8")
    assert "not yet run" not in top.lower()
    for info_path in pipeline.glob("*/run_info.json"):
        run = info_path.parent
        text = (run / "TRAINING_JOURNAL.md").read_text("utf-8")
        evaluation = json.loads((run / "evaluation.json").read_text("utf-8"))
        summary = json.loads((run / "observations/training_summary.json").read_text("utf-8"))
        tau = f"{evaluation['threshold']['threshold']:.6f}"
        assert f"tau = {tau}" in text
        assert tau in top
        assert f"epoch {summary['best_epoch']}" in text
        assert summary["stop_reason"] in text
        assert f"{len(pd.read_csv(run / 'train_log.csv'))} epoch(s) are logged" in text
        copy = tmp_path / run.name
        shutil.copytree(run, copy, ignore=shutil.ignore_patterns("checkpoints"))
        (copy / "TRAINING_JOURNAL.md").unlink()
        rebuilt = journal.write_run_journal(copy).read_bytes()
        assert rebuilt == (run / "TRAINING_JOURNAL.md").read_bytes()
