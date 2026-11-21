"""`oscc-ml uni-run`: the whole pipeline, its resume behaviour, logging and single-instance lock."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from oscc_ml.config import DEFAULT_CONFIG_DIR
from oscc_ml.data.processed import read_dataset_info
from oscc_ml.data.testzip import make_test_zip
from oscc_ml.pipeline import (
    LOCK_NAME,
    LOG_NAME,
    AlreadyRunningError,
    PipelineOptions,
    run_pipeline,
    single_instance,
)

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> PipelineOptions:
    root = tmp_path_factory.mktemp("uni")
    configs = root / "configs"
    configs.mkdir()
    for path in DEFAULT_CONFIG_DIR.glob("*.yaml"):
        shutil.copy(path, configs / path.name)
    protocol = yaml.safe_load((configs / "protocol.yaml").read_text("utf-8"))
    protocol["optimizer"]["lr_grid"] = [1.0e-4, 1.0e-3]
    protocol["data"]["num_workers"] = 0
    (configs / "protocol.yaml").write_text(yaml.safe_dump(protocol), "utf-8")
    raw = make_test_zip(
        root / "raw.zip",
        originals_per_class=24,
        augmented_per_original=1,
        size=(300, 260),
        label_conflicts=2,  # ADR-0003: the run must exclude them, not abort
    )
    return PipelineOptions(
        raw=raw,
        data_root=root / "processed" / "synthetic-uni",
        runs_dir=root / "runs",
        dataset_version="synthetic-uni",
        device="cpu",
        sweep_epochs=1,
        epochs=1,
        random_init=True,
        bootstrap=50,
        latency_warmup=1,
        latency_runs=2,
        config_dir=configs,
    )


@pytest.fixture(scope="module")
def first_run(setup: PipelineOptions) -> dict[str, str]:
    return {r.name: r.status for r in run_pipeline(setup)}


def test_all_steps_run_and_the_report_refuses_synthetic_data(
    first_run: dict[str, str], setup: PipelineOptions
) -> None:
    assert first_run == {
        "prepare": "done",
        "sweep": "done",
        "train-all": "done",
        "evaluate": "done",
        "report": "failed",  # synthetic + random init: refused, as it must be
        "pack-results": "done",
    }
    log = (setup.runs_dir / LOG_NAME).read_text("utf-8")
    assert "Traceback" in log  # the refusal is logged with its full traceback
    assert "synthetic" in log
    assert "uni-run summary" in log
    assert (setup.runs_dir / "export" / "results_small.zip").is_file()


def test_label_conflicts_are_excluded_by_the_uni_run(
    first_run: dict[str, str], setup: PipelineOptions
) -> None:
    assert first_run["prepare"] == "done"
    info = read_dataset_info(setup.data_root)
    assert info["n_label_conflict_clusters"] == {"byte_identical": 1, "near_duplicate": 1}
    assert info["n_label_conflict_images_excluded"] == 4
    assert "carry both labels" in (setup.runs_dir / LOG_NAME).read_text("utf-8")


def test_rerun_skips_completed_work(first_run: dict[str, str], setup: PipelineOptions) -> None:
    before = sorted(p.name for p in setup.runs_dir.glob("*/run_info.json"))
    second = {r.name: r.status for r in run_pipeline(setup)}
    assert second["prepare"] == "skipped"
    assert second["sweep"] == "skipped"
    assert second["train-all"] == "done"  # every model reported "already completed"
    assert sorted(p.name for p in setup.runs_dir.glob("*/run_info.json")) == before


def test_failed_prepare_stops_dependent_steps(tmp_path: Path, setup: PipelineOptions) -> None:
    options = PipelineOptions(
        raw=tmp_path / "missing.zip", data_root=tmp_path / "p", runs_dir=tmp_path / "runs"
    )
    results = {r.name: r.status for r in run_pipeline(options)}
    assert results["prepare"] == "failed"
    assert results["sweep"] == "not run"
    assert results["pack-results"] == "not run"


def test_only_one_uni_run_at_a_time(tmp_path: Path) -> None:
    lock = tmp_path / LOCK_NAME
    with single_instance(lock), pytest.raises(AlreadyRunningError), single_instance(lock):
        pass
    with single_instance(lock):  # released after the first holder exits
        pass
