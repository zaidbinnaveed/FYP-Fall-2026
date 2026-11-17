"""``oscc-ml uni-run``: the whole university pipeline in one resumable command.

    prepare -> sweep -> train-all -> evaluate -> report -> pack-results

* Every step is skipped when its output is already complete (prepare: same input and settings;
  sweep: chosen_lr.json for this dataset; train-all: completed runs; evaluate: evaluation.json),
  so re-running after a crash, power cut or reboot continues where it stopped.
* Full tracebacks go to ``runs/uni_run.log``; the console shows progress.
* A step that fails stops the steps that depend on it; the summary lists every step as
  done / skipped / failed / not run, with times.
* Only one uni-run can run at a time (OS file lock, released automatically if the process dies).
* On Windows the machine is kept awake while the pipeline runs.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import time
import traceback
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from oscc_ml.paths import EXPORT_DIR_NAME, REPORT_DIR_NAME, RUNS_DIR
from oscc_ml.utils.io import iso, read_json, utc_now

logger = logging.getLogger("oscc_ml")
LOG_NAME = "uni_run.log"
LOCK_NAME = "uni_run.lock"


class AlreadyRunningError(RuntimeError):
    pass


@dataclass
class StepResult:
    name: str
    status: str  # done | skipped | failed | not run
    seconds: float = 0.0
    detail: str = ""


@dataclass
class PipelineOptions:
    raw: Path
    data_root: Path
    runs_dir: Path = RUNS_DIR
    dataset_version: str = "oscc-unified-v1"
    device: str = "auto"
    sweep_epochs: int = 5
    # Test-only overrides (make runs non-reportable; never used at the university).
    epochs: int | None = None
    random_init: bool = False
    bootstrap: int = 2000
    latency_warmup: int = 50
    latency_runs: int = 200
    config_dir: Path | None = None
    prepare_kwargs: dict[str, Any] = field(default_factory=dict)


@contextlib.contextmanager
def single_instance(lock_path: Path) -> Iterator[None]:
    """Exclusive OS lock on ``lock_path`` (msvcrt on Windows, fcntl elsewhere)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle: IO[str] = lock_path.open("a+")
    try:
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise AlreadyRunningError(
                f"another uni-run is already running (lock {lock_path}); wait for it to finish "
                "or stop it before starting a new one"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid {os.getpid()} started {iso(utc_now())}\n")
        handle.flush()
        yield
    finally:
        handle.close()


@contextlib.contextmanager
def keep_awake() -> Iterator[None]:
    """Ask Windows not to sleep while the pipeline runs (no effect elsewhere)."""
    if sys.platform != "win32":
        yield
        return
    import ctypes

    es_continuous, es_system_required = 0x80000000, 0x00000001
    kernel32 = ctypes.windll.kernel32
    kernel32.SetThreadExecutionState(es_continuous | es_system_required)
    try:
        yield
    finally:
        kernel32.SetThreadExecutionState(es_continuous)


def _attach_log(runs_dir: Path) -> logging.Handler:
    handler = logging.FileHandler(runs_dir / LOG_NAME, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    if logger.level == logging.NOTSET or logger.level > logging.INFO:
        logger.setLevel(logging.INFO)
    return handler


def _run_step(results: list[StepResult], name: str, action: Callable[[], tuple[str, str]]) -> bool:
    """Run one step; record done/skipped/failed. Returns True if later steps may continue."""
    logger.info("===== step %s: start =====", name)
    started = time.perf_counter()
    try:
        status, detail = action()
    except KeyboardInterrupt:
        results.append(StepResult(name, "failed", time.perf_counter() - started, "interrupted"))
        raise
    except Exception as exc:
        seconds = time.perf_counter() - started
        logger.error("step %s FAILED: %s\n%s", name, exc, traceback.format_exc())
        first_line = str(exc).splitlines()[0] if str(exc) else ""
        results.append(StepResult(name, "failed", seconds, f"{type(exc).__name__}: {first_line}"))
        return False
    seconds = time.perf_counter() - started
    results.append(StepResult(name, status, seconds, detail))
    logger.info("===== step %s: %s (%.0f s) %s =====", name, status, seconds, detail)
    return True


def run_pipeline(options: PipelineOptions) -> list[StepResult]:
    from oscc_ml.data.prepare import PrepareSettings, prepare
    from oscc_ml.data.processed import read_dataset_info
    from oscc_ml.eval.evaluate import evaluate_all
    from oscc_ml.report import build_report
    from oscc_ml.results import pack_results
    from oscc_ml.train.sweep import chosen_lr_path, run_sweep
    from oscc_ml.train.train_all import train_all

    runs = options.runs_dir
    runs.mkdir(parents=True, exist_ok=True)
    handler = _attach_log(runs)
    results: list[StepResult] = []
    total_start = time.perf_counter()
    try:
        with single_instance(runs / LOCK_NAME), keep_awake():
            logger.info(
                "uni-run started: raw=%s data=%s runs=%s", options.raw, options.data_root, runs
            )
            pretrained = not options.random_init

            def step_prepare() -> tuple[str, str]:
                info_path = options.data_root / "dataset.json"
                before = read_json(info_path).get("created_at") if info_path.is_file() else None
                settings = PrepareSettings(
                    dataset_version=options.dataset_version, **options.prepare_kwargs
                )
                prepare(options.raw, options.data_root, settings)
                info = read_dataset_info(options.data_root)
                counts = ", ".join(f"{s} {c['images']} img" for s, c in info["counts"].items())
                # prepare() leaves an identical dataset untouched, so created_at is unchanged
                return ("skipped" if before == info.get("created_at") else "done", counts)

            def step_sweep() -> tuple[str, str]:
                path = chosen_lr_path(runs)
                version = str(read_dataset_info(options.data_root)["dataset_version"])
                if path.is_file():
                    existing = read_json(path)
                    if (
                        existing.get("dataset_version") == version
                        and existing.get("pretrained") == pretrained
                    ):
                        return "skipped", f"chosen LR {existing['chosen_lr']:g} (already swept)"
                result = run_sweep(
                    options.data_root,
                    runs,
                    epochs=options.sweep_epochs,
                    device=options.device,
                    config_dir=options.config_dir,
                    pretrained=pretrained,
                )
                return "done", f"chosen LR {result['chosen_lr']:g}"

            def step_train() -> tuple[str, str]:
                result = train_all(
                    options.data_root,
                    runs,
                    resume=True,
                    device=options.device,
                    config_dir=options.config_dir,
                    epochs=options.epochs,
                    pretrained=pretrained,
                )
                if result.failed:
                    raise RuntimeError("; ".join(result.failed))
                return "done", f"{len(result.completed)} model(s) trained or already complete"

            def step_evaluate() -> tuple[str, str]:
                done, failed = evaluate_all(
                    runs,
                    n_bootstrap=options.bootstrap,
                    warmup=options.latency_warmup,
                    latency_runs=options.latency_runs,
                    config_dir=options.config_dir,
                )
                if failed:
                    raise RuntimeError("; ".join(failed))
                return "done", f"{len(done)} run(s) evaluated"

            def step_report() -> tuple[str, str]:
                paths = build_report(runs, runs / REPORT_DIR_NAME)
                return "done", str(paths["markdown"])

            def step_pack() -> tuple[str, str]:
                paths = pack_results(runs, runs / EXPORT_DIR_NAME)
                sizes = ", ".join(
                    f"{p.name} {p.stat().st_size / 2**20:.1f} MB" for p in paths.values()
                )
                return "done", sizes

            plan: list[tuple[str, Callable[[], tuple[str, str]], bool]] = [
                ("prepare", step_prepare, True),
                ("sweep", step_sweep, True),
                ("train-all", step_train, False),
                ("evaluate", step_evaluate, False),
                ("report", step_report, False),
                ("pack-results", step_pack, False),
            ]
            blocked = False
            for name, action, required in plan:
                if blocked:
                    results.append(
                        StepResult(name, "not run", 0.0, "an earlier required step failed")
                    )
                    continue
                ok = _run_step(results, name, action)
                if not ok and required:
                    blocked = True
    finally:
        total = time.perf_counter() - total_start
        write_summary(results, total, runs)
        logger.removeHandler(handler)
        handler.close()
    return results


def write_summary(results: list[StepResult], total_seconds: float, runs: Path) -> None:
    lines = ["", "=" * 72, "uni-run summary", "=" * 72]
    for r in results:
        lines.append(f"  {r.name:<13} {r.status.upper():<8} {r.seconds / 60:7.1f} min  {r.detail}")
    hours, rem = divmod(int(total_seconds), 3600)
    lines.append(f"  total time: {hours} h {rem // 60:02d} min")
    failed = [r for r in results if r.status == "failed"]
    if failed:
        lines.append(f"  RESULT: {len(failed)} step(s) FAILED. Full tracebacks: {runs / LOG_NAME}")
        lines.append("  Fix the cause and run uni_run again: completed work is kept and skipped.")
    else:
        lines.append(
            f"  RESULT: all steps completed. Results to take home: {runs / EXPORT_DIR_NAME}"
        )
    lines.append("=" * 72)
    text = "\n".join(lines)
    print(text, flush=True)
    logger.info(text)
