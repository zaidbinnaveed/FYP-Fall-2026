"""``oscc-ml`` command line. The same commands run on a laptop, the lab GPU and Colab/Kaggle.

R0 commands: ``train`` (``--smoke`` only until the Phase R1 dataset exists) and ``env``.
``data``, ``eval``, ``report`` and ``export`` arrive in Phases R1-R5.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated

import typer

from oscc_ml.config import DEFAULT_RUNS_DIR, model_config_names

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)


@app.command("train")
def train_command(
    model: Annotated[str, typer.Option("--model", help="Model config name, e.g. resnet50")],
    smoke: Annotated[
        bool, typer.Option("--smoke", help="CPU pipeline check on 32 synthetic images")
    ] = False,
    seed: Annotated[int | None, typer.Option(help="Override the protocol seed (42)")] = None,
    runs_dir: Annotated[Path, typer.Option(help="Where run folders are written")] = (
        DEFAULT_RUNS_DIR
    ),
    device: Annotated[str, typer.Option(help="auto | cpu | cuda")] = "auto",
    config_dir: Annotated[
        Path | None, typer.Option(help="Directory with protocol.yaml and model configs")
    ] = None,
) -> None:
    """Train one model under the shared protocol and write a run folder."""
    from oscc_ml.train.runner import DatasetUnavailableError, run_training

    names = model_config_names(config_dir)
    if model not in names:
        typer.echo(f"unknown model {model!r}; configs available: {names}", err=True)
        raise typer.Exit(code=2)
    started = time.perf_counter()
    try:
        run_dir = run_training(
            model, smoke=smoke, seed=seed, runs_dir=runs_dir, device=device, config_dir=config_dir
        )
    except (DatasetUnavailableError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    elapsed = time.perf_counter() - started
    metrics = json.loads((run_dir / "metrics.json").read_text("utf-8"))
    typer.echo(f"run folder: {run_dir}")
    typer.echo(f"wall time: {elapsed:.1f} s")
    if metrics["smoke"]:
        typer.echo("smoke run: synthetic data, pipeline check only, not reportable")


@app.command("env")
def env_command() -> None:
    """Print the environment info that every run records."""
    import torch

    from oscc_ml.runinfo import environment_info

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    typer.echo(json.dumps(environment_info(device), indent=2))


if __name__ == "__main__":
    app()
