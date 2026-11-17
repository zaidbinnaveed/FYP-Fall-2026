"""``oscc-ml``: one CLI for the laptop, the university GPU machine and Colab/Kaggle.

Pipeline (each step resumable; see docs and scripts/uni_*):
    sweep -> train-all -> evaluate -> report -> pack-results  (import-results at home)
Utilities: train (single model), check (machine readiness), make-synthetic-data, env.
Data preparation (prepare, make-sample) is Phase R1.

Exit codes: 0 success, 1 a step failed, 2 refused or invalid input.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from oscc_ml.config import model_config_names
from oscc_ml.paths import DEFAULT_DATA_ROOT, REPORT_DIR_NAME, RUNS_DIR, configure_caches

configure_caches()
app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
logger = logging.getLogger("oscc_ml")

RunsDir = Annotated[Path, typer.Option(help="Folder holding run folders")]
DataRoot = Annotated[Path, typer.Option(help="Prepared dataset folder (from `oscc-ml prepare`)")]
Device = Annotated[str, typer.Option(help="auto | cpu | cuda")]
ConfigDir = Annotated[
    Path | None,
    typer.Option(help="Folder with protocol.yaml and model configs (default: configs/)"),
]
RandomInit = Annotated[
    bool,
    typer.Option(
        "--random-init", help="Random weights instead of ImageNet (tests only; not reportable)"
    ),
]


def _setup_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def _models(value: str | None) -> tuple[str, ...]:
    from oscc_ml.models.factory import ALL_ARCHITECTURES

    if not value:
        return ALL_ARCHITECTURES
    names = tuple(v.strip() for v in value.split(",") if v.strip())
    unknown = [n for n in names if n not in ALL_ARCHITECTURES]
    if unknown:
        typer.echo(f"error: unknown model(s) {unknown}; choose from {ALL_ARCHITECTURES}", err=True)
        raise typer.Exit(code=2)
    return names


def _fail(message: str, code: int = 2) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code=code)


@app.command("train")
def train_command(
    model: Annotated[str, typer.Option("--model", help="Model config name, e.g. resnet50")],
    smoke: Annotated[
        bool, typer.Option("--smoke", help="CPU pipeline check on 32 synthetic images")
    ] = False,
    seed: Annotated[int | None, typer.Option(help="Override the protocol seed (42)")] = None,
    runs_dir: RunsDir = RUNS_DIR,
    data_root: DataRoot = DEFAULT_DATA_ROOT,
    device: Device = "auto",
    resume: Annotated[
        bool, typer.Option(help="Continue the latest unfinished matching run")
    ] = False,
    lr: Annotated[float | None, typer.Option(help="Manual LR (not reportable)")] = None,
    epochs: Annotated[int | None, typer.Option(help="Override max epochs (not reportable)")] = None,
    batch_size: Annotated[int | None, typer.Option(help="Uniform batch-size reduction")] = None,
    random_init: RandomInit = False,
    config_dir: ConfigDir = None,
) -> None:
    """Train one model under the shared protocol and write a run folder."""
    from oscc_ml.train.runner import DatasetUnavailableError, run_training
    from oscc_ml.utils.io import read_json

    _setup_logging()
    names = model_config_names(config_dir)
    if model not in names:
        raise _fail(f"unknown model {model!r}; configs available: {names}")
    started = time.perf_counter()
    try:
        run_dir = run_training(
            model,
            smoke=smoke,
            runs_dir=runs_dir,
            data_root=None if smoke else data_root,
            seed=seed,
            device=device,
            config_dir=config_dir,
            lr=lr,
            lr_source=None if lr is None else "manual",
            epochs=epochs,
            batch_size=batch_size,
            pretrained=False if random_init else None,
            resume=resume,
        )
    except (DatasetUnavailableError, ValueError) as exc:
        raise _fail(str(exc)) from exc
    elapsed = time.perf_counter() - started
    info = read_json(run_dir / "run_info.json")
    typer.echo(f"run folder: {run_dir}")
    typer.echo(f"wall time: {elapsed:.1f} s")
    if info.get("smoke"):
        typer.echo("smoke run: synthetic data, pipeline check only, not reportable")
    elif not info.get("protocol_compliant"):
        typer.echo("not reportable: " + "; ".join(info.get("deviations", [])))


@app.command("sweep")
def sweep_command(
    data_root: DataRoot = DEFAULT_DATA_ROOT,
    runs_dir: RunsDir = RUNS_DIR,
    epochs: Annotated[int, typer.Option(help="Epochs per short trial")] = 5,
    models: Annotated[
        str | None, typer.Option(help="Comma-separated subset (default: all 4)")
    ] = None,
    seed: Annotated[int | None, typer.Option()] = None,
    device: Device = "auto",
    random_init: RandomInit = False,
    config_dir: ConfigDir = None,
) -> None:
    """Shared LR sweep over protocol.yaml's grid; writes runs/sweep/chosen_lr.json."""
    from oscc_ml.train.sweep import SweepIncompleteError, chosen_lr_path, run_sweep

    _setup_logging()
    try:
        result = run_sweep(
            data_root,
            runs_dir,
            epochs=epochs,
            models=_models(models),
            seed=seed,
            device=device,
            config_dir=config_dir,
            pretrained=not random_init,
        )
    except FileNotFoundError as exc:
        raise _fail(str(exc)) from exc
    except SweepIncompleteError as exc:
        raise _fail(str(exc), code=1) from exc
    typer.echo(f"chosen LR: {result['chosen_lr']:g}  ->  {chosen_lr_path(runs_dir)}")


@app.command("train-all")
def train_all_command(
    data_root: DataRoot = DEFAULT_DATA_ROOT,
    runs_dir: RunsDir = RUNS_DIR,
    resume: Annotated[
        bool, typer.Option(help="Skip completed runs, continue interrupted ones")
    ] = False,
    seeds: Annotated[str, typer.Option(help="Comma-separated seeds (baseline: 42)")] = "42",
    models: Annotated[
        str | None, typer.Option(help="Comma-separated subset (default: all 4)")
    ] = None,
    device: Device = "auto",
    lr: Annotated[
        float | None, typer.Option(help="Manual LR instead of the sweep (not reportable)")
    ] = None,
    epochs: Annotated[int | None, typer.Option(help="Override max epochs (not reportable)")] = None,
    batch_size: Annotated[int | None, typer.Option(help="Uniform batch-size reduction")] = None,
    random_init: RandomInit = False,
    config_dir: ConfigDir = None,
) -> None:
    """Train all four models with the chosen LR (seed 42 by default)."""
    from oscc_ml.train.train_all import NoChosenLearningRateError, train_all

    _setup_logging()
    try:
        seed_values = tuple(int(s) for s in seeds.split(",") if s.strip())
    except ValueError as exc:
        raise _fail(f"--seeds must be integers, got {seeds!r}") from exc
    try:
        result = train_all(
            data_root,
            runs_dir,
            models=_models(models),
            seeds=seed_values,
            resume=resume,
            device=device,
            config_dir=config_dir,
            lr=lr,
            epochs=epochs,
            batch_size=batch_size,
            pretrained=not random_init,
        )
    except (NoChosenLearningRateError, FileNotFoundError) as exc:
        raise _fail(str(exc)) from exc
    for path in result.completed:
        typer.echo(f"completed: {path.name}")
    for failure in result.failed:
        typer.echo(f"FAILED: {failure}", err=True)
    if result.failed:
        raise typer.Exit(code=1)


@app.command("evaluate")
def evaluate_command(
    runs_dir: RunsDir = RUNS_DIR,
    bootstrap: Annotated[int, typer.Option(help="Bootstrap resamples")] = 2000,
    warmup: Annotated[int, typer.Option(help="Latency warm-up runs")] = 50,
    latency_runs: Annotated[int, typer.Option(help="Timed latency runs")] = 200,
    gpu: Annotated[bool, typer.Option(help="Also measure GPU latency if a GPU exists")] = True,
    force: Annotated[bool, typer.Option(help="Re-evaluate runs that already have results")] = False,
    config_dir: ConfigDir = None,
) -> None:
    """Test metrics with grouped bootstrap CIs, tau from validation, params, GFLOPs, latency."""
    from oscc_ml.eval.evaluate import evaluate_all

    _setup_logging()
    done, failed = evaluate_all(
        runs_dir,
        force=force,
        n_bootstrap=bootstrap,
        warmup=warmup,
        latency_runs=latency_runs,
        measure_gpu=gpu,
        config_dir=config_dir,
    )
    typer.echo(f"evaluated: {len(done)} run(s)")
    for failure in failed:
        typer.echo(f"FAILED: {failure}", err=True)
    if failed:
        raise typer.Exit(code=1)
    if not done:
        raise _fail(f"no completed training runs in {runs_dir}")


@app.command("report")
def report_command(
    runs_dir: RunsDir = RUNS_DIR,
    out_dir: Annotated[Path | None, typer.Option(help="Default: runs/report/")] = None,
    copy_to: Annotated[
        Path | None,
        typer.Option(help="Also copy the Markdown table here, e.g. docs/results/baseline_fyp1.md"),
    ] = None,
    seed: Annotated[int, typer.Option()] = 42,
) -> None:
    """Baseline table built only from run folders (smoke and synthetic runs are refused)."""
    from oscc_ml.report import ReportRefusedError, build_report

    try:
        paths = build_report(runs_dir, out_dir or runs_dir / REPORT_DIR_NAME, seed=seed)
    except ReportRefusedError as exc:
        raise _fail(str(exc)) from exc
    if copy_to is not None:
        copy_to.parent.mkdir(parents=True, exist_ok=True)
        copy_to.write_text(paths["markdown"].read_text("utf-8"), "utf-8")
        typer.echo(f"copied: {copy_to}")
    for kind, path in paths.items():
        typer.echo(f"{kind}: {path}")


@app.command("pack-results")
def pack_results_command(
    runs_dir: RunsDir = RUNS_DIR,
    out_dir: Annotated[Path | None, typer.Option(help="Default: runs/export/")] = None,
) -> None:
    """results_small.zip (no checkpoints) and checkpoints.zip, each with a SHA-256 manifest."""
    from oscc_ml.results import pack_results

    try:
        paths = pack_results(runs_dir, out_dir)
    except FileNotFoundError as exc:
        raise _fail(str(exc)) from exc
    for kind, path in paths.items():
        typer.echo(f"{kind}: {path} ({path.stat().st_size / 2**20:.1f} MB)")


@app.command("import-results")
def import_results_command(
    archive: Annotated[Path, typer.Argument(help="results_small.zip or checkpoints.zip")],
    runs_dir: RunsDir = RUNS_DIR,
    overwrite: Annotated[bool, typer.Option(help="Replace files that differ")] = False,
) -> None:
    """Verify and unpack an archive from pack-results into runs/."""
    import zipfile

    from oscc_ml.results import ImportRefusedError, import_results

    if not archive.is_file():
        raise _fail(f"{archive} not found")
    try:
        result = import_results(archive, runs_dir, overwrite=overwrite)
    except (ImportRefusedError, zipfile.BadZipFile) as exc:
        raise _fail(str(exc)) from exc
    typer.echo(f"imported {len(result.written)} file(s), {len(result.unchanged)} already present")


@app.command("check")
def check_command(
    allow_cpu: Annotated[bool, typer.Option(help="Do not fail without a GPU (CI only)")] = False,
    skip_download: Annotated[bool, typer.Option(help="Skip the pretrained-weight check")] = False,
    min_free_gb: Annotated[float, typer.Option(help="Required free disk space")] = 40.0,
    budget_seconds: Annotated[float, typer.Option(help="Time budget of the GPU smoke run")] = 120.0,
    batch_size: Annotated[
        int | None, typer.Option(help="Smoke batch (default: protocol, 32)")
    ] = None,
) -> None:
    """Machine readiness: Python, GPU/VRAM, disk, write access, weights, 2-minute GPU smoke run."""
    from oscc_ml.check import run_checks

    report = run_checks(
        allow_cpu=allow_cpu,
        skip_download=skip_download,
        min_free_gb=min_free_gb,
        budget_seconds=budget_seconds,
        batch_size=batch_size,
    )
    if report.failures:
        raise typer.Exit(code=1)


@app.command("make-synthetic-data")
def make_synthetic_command(
    out: Annotated[Path, typer.Option(help="Output folder")],
    images: Annotated[str, typer.Option(help="Images per split train,val,test")] = "16,8,8",
    patches: Annotated[str, typer.Option(help="Min,max patches per image")] = "1,3",
    seed: Annotated[int, typer.Option()] = 42,
) -> None:
    """Write a synthetic prepared dataset (pipeline tests only; never reportable)."""
    from oscc_ml.data.synthetic import write_synthetic_dataset

    try:
        counts = tuple(int(v) for v in images.split(","))
        low, high = (int(v) for v in patches.split(","))
        if len(counts) != 3:
            raise ValueError
    except ValueError as exc:
        raise _fail("--images needs three integers and --patches two") from exc
    write_synthetic_dataset(
        out,
        (counts[0], counts[1], counts[2]),
        seed,
        patches_per_image=(low, high),
        dataset_version="synthetic-pipeline",
    )
    typer.echo(f"synthetic dataset written to {out}")


@app.command("env")
def env_command() -> None:
    """Print the environment info that every run records."""
    import torch

    from oscc_ml.runinfo import environment_info

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    typer.echo(json.dumps(environment_info(device), indent=2))


if __name__ == "__main__":
    app()
