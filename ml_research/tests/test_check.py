"""`oscc-ml check` and the installer's CUDA selection: clear one-line failures with fixes."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
import torch

from oscc_ml import check
from oscc_ml.check import CheckReport, run_checks

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
FAIL_LINE = re.compile(r"^CHECK FAILED: .+ -- FIX: .+$")


def _installer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("install_pinned", SCRIPTS / "install_pinned.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.slow
def test_cpu_check_passes_in_ci(capsys: pytest.CaptureFixture[str]) -> None:
    report = run_checks(
        allow_cpu=True, skip_download=True, min_free_gb=0.01, budget_seconds=1, batch_size=2
    )
    out = capsys.readouterr().out
    assert not report.failures, report.failures
    assert "ALL CHECKS PASSED" in out
    for name in ("ResNet50", "EfficientNet-B0", "DenseNet121", "ViT-B/16"):
        assert name in out


def test_missing_gpu_fails_with_a_fix(capsys: pytest.CaptureFixture[str]) -> None:
    if torch.cuda.is_available():
        pytest.skip("machine has a GPU")
    report = CheckReport()
    assert check.check_gpu(report, allow_cpu=False) is None
    (line,) = report.failures
    assert FAIL_LINE.match(line)
    assert "CHECK FAILED" in capsys.readouterr().out


def test_low_disk_fails_with_a_fix() -> None:
    report = CheckReport()
    check.check_disk(report, min_free_gb=10**9)
    (line,) = report.failures
    assert FAIL_LINE.match(line)
    assert "free" in line


def test_download_failure_is_one_clear_line(monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(architecture: str, pretrained: bool) -> torch.nn.Module:
        raise ConnectionError("Temporary failure in name resolution\nlong traceback text")

    monkeypatch.setattr(check, "build_model", offline)
    report = CheckReport()
    assert check.check_downloads(report) is False
    assert len(report.failures) == 4
    assert all(FAIL_LINE.match(line) for line in report.failures)
    assert all("\n" not in line for line in report.failures)
    assert "HTTPS_PROXY" in report.failures[0]


def test_unsupported_python_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "SUPPORTED_PYTHON", ((3, 0), (3, 1)))
    report = CheckReport()
    check.check_python(report)
    assert FAIL_LINE.match(report.failures[0])


@pytest.mark.parametrize(
    ("driver", "expected"),
    [
        ((13, 4), "cu134"),
        ((13, 3), "cu132"),
        ((13, 2), "cu132"),
        ((14, 0), "cu134"),
        ((12, 8), None),
    ],
)
def test_cuda_tag_matches_the_driver(driver: tuple[int, int], expected: str | None) -> None:
    assert _installer().pick_cuda_tag("2.15.0", driver) == expected


def test_cuda_table_covers_the_locked_torch() -> None:
    lock = (Path(__file__).resolve().parents[1] / "uv.lock").read_text("utf-8")
    match = re.search(r'name = "torch"\nversion = "([^"]+)"', lock)
    assert match is not None
    assert match.group(1) in _installer().CUDA_TAGS, "update CUDA_TAGS when torch is upgraded"
