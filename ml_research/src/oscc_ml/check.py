"""``oscc-ml check``: is this machine ready for the full pipeline? (scripts/uni_check.*)

Checks, in order: Python version, GPU and VRAM, free disk, write access, pretrained weight
downloads, then a short GPU smoke run of all four architectures (AMP, batch 32, a few optimizer
steps each, about two minutes in total). Every independent check runs; each failure prints one
line ``CHECK FAILED: <what> -- FIX: <how>``. Exit code 0 only if everything passed.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import torch
from torch import nn

from oscc_ml.config import load_protocol
from oscc_ml.data.synthetic import synthetic_patch
from oscc_ml.models.factory import ALL_ARCHITECTURES, DISPLAY_NAME, build_model
from oscc_ml.paths import CACHE_DIR, DATA_DIR, ML_ROOT, RUNS_DIR
from oscc_ml.preprocess import normalize

MIN_VRAM_GB = 12.0  # ViT-B/16, batch 32, AMP fits comfortably; 24 GB recommended
RECOMMENDED_VRAM_GB = 24.0
SUPPORTED_PYTHON = ((3, 11), (3, 13))


@dataclass
class CheckReport:
    passed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def ok(self, message: str) -> None:
        self.passed.append(message)
        print(f"[ OK ] {message}", flush=True)

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        print(f"[WARN] {message}", flush=True)

    def fail(self, what: str, fix: str) -> None:
        line = f"CHECK FAILED: {what} -- FIX: {fix}"
        self.failures.append(line)
        print(line, flush=True)


def check_python(report: CheckReport) -> None:
    version = sys.version_info[:2]
    low, high = SUPPORTED_PYTHON
    if low <= version <= high:
        report.ok(f"Python {sys.version.split()[0]}")
    else:
        report.fail(
            f"Python {sys.version.split()[0]} is not supported (need 3.11 to 3.13)",
            "re-run scripts/uni_setup, which installs Python 3.11 with uv (no admin rights needed)",
        )


def check_gpu(report: CheckReport, allow_cpu: bool) -> torch.device | None:
    if not torch.cuda.is_available():
        if allow_cpu:
            report.warn(f"no CUDA GPU visible (torch {torch.__version__}); CPU mode allowed")
            return torch.device("cpu")
        cuda_build = torch.version.cuda
        fix = (
            "this torch build has no CUDA support; re-run scripts/uni_setup so it installs the "
            "CUDA build that matches nvidia-smi"
            if cuda_build is None
            else f"torch was built for CUDA {cuda_build}; run nvidia-smi: if it fails, install or "
            "update the NVIDIA driver (needs a driver supporting this CUDA version), then re-run"
        )
        report.fail(f"PyTorch cannot see a CUDA GPU (torch {torch.__version__})", fix)
        return None
    props = torch.cuda.get_device_properties(0)
    vram_gb = props.total_memory / 2**30
    if vram_gb < MIN_VRAM_GB:
        report.fail(
            f"GPU {props.name} has {vram_gb:.1f} GB VRAM, below the {MIN_VRAM_GB:.0f} GB minimum",
            "use a GPU with at least 16 GB (24 GB recommended); batch size 32 is fixed by the "
            "protocol",
        )
        return None
    report.ok(f"GPU {props.name}, {vram_gb:.1f} GB VRAM, CUDA {torch.version.cuda}")
    if vram_gb < RECOMMENDED_VRAM_GB:
        report.warn(f"{vram_gb:.1f} GB VRAM is below the recommended {RECOMMENDED_VRAM_GB:.0f} GB")
    return torch.device("cuda")


def check_disk(report: CheckReport, min_free_gb: float) -> None:
    free_gb = shutil.disk_usage(ML_ROOT).free / 2**30
    if free_gb >= min_free_gb:
        report.ok(f"{free_gb:.0f} GB free on the drive holding {ML_ROOT}")
    else:
        report.fail(
            f"only {free_gb:.1f} GB free on the drive holding {ML_ROOT} "
            f"(need {min_free_gb:.0f} GB for the dataset, patches and checkpoints)",
            "free space on that drive, or clone the repository onto a larger drive",
        )


def check_write_access(report: CheckReport) -> None:
    for folder in (DATA_DIR, RUNS_DIR, CACHE_DIR):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=folder, prefix=".write-test-", delete=True) as f:
                f.write(b"ok")
        except OSError as exc:
            report.fail(
                f"cannot write to {folder} ({exc.__class__.__name__}: {exc})",
                "clone the repository into a folder you own (e.g. your Documents or home folder)",
            )
            return
    report.ok(f"write access to {DATA_DIR.name}/, {RUNS_DIR.name}/ and {CACHE_DIR.name}/")


def check_downloads(report: CheckReport) -> bool:
    all_ok = True
    for arch in ALL_ARCHITECTURES:
        try:
            build_model(arch, pretrained=True)
        except Exception as exc:
            all_ok = False
            report.fail(
                f"cannot download/load pretrained weights for {DISPLAY_NAME[arch]} "
                f"({exc.__class__.__name__}: {str(exc).splitlines()[0][:160]})",
                "connect to the internet (download.pytorch.org and huggingface.co must be "
                "reachable; set HTTPS_PROXY if the university uses a proxy), or copy "
                f"{CACHE_DIR} from a machine that has them",
            )
    if all_ok:
        report.ok(f"pretrained weights for all four models are in {CACHE_DIR}")
    return all_ok


def _batch(batch_size: int, device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
    rng = np.random.default_rng(0)
    labels = [i % 2 for i in range(batch_size)]
    pixels = np.stack([synthetic_patch(rng, label, 224) for label in labels])
    x = torch.from_numpy(pixels).permute(0, 3, 1, 2).float().div_(255.0)
    return normalize(x).to(device), torch.tensor(labels, dtype=torch.float32, device=device)


def gpu_smoke(
    report: CheckReport,
    device: torch.device,
    pretrained: bool,
    budget_seconds: float,
    batch_size: int,
    build: Callable[[str, bool], nn.Module] = build_model,
) -> None:
    x, y = _batch(batch_size, device)
    use_amp = device.type == "cuda"
    per_model = budget_seconds / len(ALL_ARCHITECTURES)
    total_start = time.perf_counter()
    for arch in ALL_ARCHITECTURES:
        name = DISPLAY_NAME[arch]
        try:
            if device.type == "cuda":
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats(device)
            model = build(arch, pretrained).to(device).train()
            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=0.05)
            scaler = torch.amp.GradScaler(device.type, enabled=use_amp)
            loss_fn = nn.BCEWithLogitsLoss()
            start, steps, loss_value = time.perf_counter(), 0, float("nan")
            while steps < 2 or (time.perf_counter() - start < per_model and steps < 50):
                optimizer.zero_grad(set_to_none=True)
                with torch.autocast(device_type=device.type, enabled=use_amp):
                    logits = model(x).squeeze(1)
                loss = loss_fn(logits.float(), y)
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
                loss_value = float(loss.detach())
                steps += 1
            if not np.isfinite(loss_value):
                report.fail(
                    f"{name} produced a non-finite loss on the GPU smoke run",
                    "send runs/uni_check.log to the team; this points to a driver/CUDA problem",
                )
                continue
            elapsed = time.perf_counter() - start
            peak = (
                f", peak {torch.cuda.max_memory_allocated(device) / 2**30:.1f} GB"
                if device.type == "cuda"
                else ""
            )
            report.ok(
                f"{name}: {steps} training steps at batch {batch_size} in {elapsed:.1f} s "
                f"({steps * batch_size / elapsed:.0f} img/s){peak}"
            )
            del model, optimizer
        except torch.cuda.OutOfMemoryError:
            report.fail(
                f"{name} ran out of GPU memory at batch {batch_size}",
                "close other programs using the GPU (check nvidia-smi) and run uni_check again",
            )
        except Exception as exc:
            report.fail(
                f"{name} failed on the smoke run ({exc.__class__.__name__}: "
                f"{str(exc).splitlines()[0][:160] if str(exc) else ''})",
                "send runs/uni_check.log to the team",
            )
            traceback.print_exc()
    report.ok(f"smoke run finished in {time.perf_counter() - total_start:.0f} s")


def run_checks(
    *,
    allow_cpu: bool = False,
    skip_download: bool = False,
    min_free_gb: float = 40.0,
    budget_seconds: float = 120.0,
    batch_size: int | None = None,
) -> CheckReport:
    report = CheckReport()
    check_python(report)
    device = check_gpu(report, allow_cpu)
    check_disk(report, min_free_gb)
    check_write_access(report)
    downloaded = False if skip_download else check_downloads(report)
    if skip_download:
        report.warn("pretrained weight download skipped (--skip-download)")
    if device is not None:
        size = batch_size or load_protocol().training.batch_size
        gpu_smoke(report, device, downloaded, budget_seconds, size)
    else:
        report.warn("GPU smoke run skipped because no usable GPU was found")
    print("", flush=True)
    if report.failures:
        print(
            f"{len(report.failures)} CHECK(S) FAILED. Fix the lines starting with "
            "'CHECK FAILED' and run uni_check again.",
            flush=True,
        )
    else:
        print("ALL CHECKS PASSED: this machine is ready for scripts/uni_run.", flush=True)
    return report
