"""Install oscc-ml with the exact versions from uv.lock, choosing how torch is provided.

Standard library only, so it runs on Windows and Linux before anything is installed.

Every package except the torch family (torch, torchvision, triton, nvidia-*) is installed at its
locked version. The torch family:

  --torch cpu        locked torch/torchvision versions, CPU wheels (CI, laptops)
  --torch cuda       locked versions, CUDA wheels from download.pytorch.org/whl/<--cuda-tag>
                     (university GPU machine; scripts/uni_setup picks the tag from nvidia-smi)
  --torch platform   keep the torch already installed (Colab/Kaggle CUDA builds)
  --torch locked     locked versions from PyPI (Linux: CUDA build)

--torch-version/--torchvision-version override the locked versions; use them only when the GPU
driver is too old for the locked build. Every run records the versions actually used.

Examples:
  python scripts/install_pinned.py --torch cpu --extra train --dev
  python scripts/install_pinned.py --torch cuda --extra train --python .venv/bin/python
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TORCH_FAMILY = re.compile(r"^(torch|torchvision|triton|pytorch-triton|nvidia-[a-z0-9-]+)==", re.I)
INDEX = "https://download.pytorch.org/whl/{tag}"
# CUDA builds published on download.pytorch.org for each locked torch version (checked when the
# lock was updated; update this table together with uv.lock).
CUDA_TAGS = {"2.15.0": ["cu132", "cu134"]}


def driver_cuda_version() -> tuple[int, int] | None:
    """Highest CUDA version the installed NVIDIA driver supports, from nvidia-smi."""
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return None
    try:
        out = subprocess.run([exe], capture_output=True, text=True, check=True, timeout=60).stdout  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
    return (int(match.group(1)), int(match.group(2))) if match else None


def pick_cuda_tag(torch_version: str, driver: tuple[int, int]) -> str | None:
    """Newest published CUDA build of ``torch_version`` that the driver can run."""
    usable = []
    for tag in CUDA_TAGS.get(torch_version.split("+")[0], []):
        digits = tag[2:]
        version = (int(digits[:-1]), int(digits[-1]))
        if version <= driver:
            usable.append((version, tag))
    return max(usable)[1] if usable else None


def run(cmd: list[str], **kwargs: object) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kwargs)  # type: ignore[call-overload]  # noqa: S603


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--torch", choices=["cpu", "cuda", "platform", "locked"], default="cpu")
    parser.add_argument("--cuda-tag", default="auto", help="e.g. cu134, or auto (from nvidia-smi)")
    parser.add_argument("--torch-version")
    parser.add_argument("--torchvision-version")
    parser.add_argument("--extra", action="append", default=[])
    parser.add_argument("--dev", action="store_true", help="include the dev dependency group")
    parser.add_argument("--python", default=sys.executable, help="interpreter to install into")
    args = parser.parse_args()

    uv = os.environ.get("UV") or shutil.which("uv")
    if uv is None:
        print(
            "ERROR: uv not found on PATH; run scripts/uni_setup or install uv first",
            file=sys.stderr,
        )
        return 1

    export = [
        uv,
        "export",
        "--frozen",
        "--no-hashes",
        "--no-annotate",
        "--no-header",
        "--no-emit-project",
        "--format",
        "requirements.txt",
    ]
    for extra in args.extra:
        export += ["--extra", extra]
    export += ["--group", "dev"] if args.dev else ["--no-dev"]
    requirements = subprocess.run(  # noqa: S603
        export, cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()

    def locked(name: str) -> str | None:
        for line in requirements:
            match = re.match(rf"^{name}==([^ ;]+)", line)
            if match:
                return match.group(1)
        return None

    rest = [line for line in requirements if line.strip() and not TORCH_FAMILY.match(line)]
    torch_version = args.torch_version or locked("torch")
    vision_version = args.torchvision_version or locked("torchvision")
    if args.torch_version or args.torchvision_version:
        print(
            f"WARNING: overriding locked torch versions -> torch {torch_version}, "
            f"torchvision {vision_version}",
            flush=True,
        )
    pip = [uv, "pip", "install", "--python", args.python]

    if args.torch == "cuda" and args.cuda_tag == "auto":
        driver = driver_cuda_version()
        if driver is None:
            print(
                "SETUP FAILED: nvidia-smi not found or not working, so no NVIDIA driver is usable. "
                "FIX: install/update the NVIDIA driver (ask IT), or run with --cpu to test only.",
                file=sys.stderr,
            )
            return 1
        tag = pick_cuda_tag(str(torch_version), driver)
        if tag is None:
            available = ", ".join(CUDA_TAGS.get(str(torch_version), [])) or "none listed"
            print(
                f"SETUP FAILED: the NVIDIA driver supports CUDA {driver[0]}.{driver[1]}, but torch "
                f"{torch_version} is only built for {available}. FIX: ask IT to update the NVIDIA "
                "driver; or pass --torch-version/--torchvision-version/--cuda-tag for an older "
                "build (see docs/UNI_RUNBOOK.md).",
                file=sys.stderr,
            )
            return 1
        print(f"driver supports CUDA {driver[0]}.{driver[1]} -> using {tag} wheels", flush=True)
        args.cuda_tag = tag

    if torch_version:
        if args.torch == "cpu":
            run(
                [
                    *pip,
                    "--no-deps",
                    "--index-url",
                    INDEX.format(tag="cpu"),
                    f"torch=={torch_version}",
                    f"torchvision=={vision_version}",
                ]
            )
        elif args.torch == "cuda":
            # Without --no-deps: CUDA wheels from this index need their CUDA runtime packages.
            run(
                [
                    *pip,
                    "--index-url",
                    INDEX.format(tag=args.cuda_tag),
                    "--extra-index-url",
                    "https://pypi.org/simple",
                    "--index-strategy",
                    "unsafe-best-match",
                    f"torch=={torch_version}",
                    f"torchvision=={vision_version}",
                ]
            )
        elif args.torch == "platform":
            run(
                [
                    args.python,
                    "-c",
                    "import torch, torchvision; "
                    "print('using platform torch', torch.__version__, 'CUDA', torch.version.cuda)",
                ]
            )
        else:
            family = [line for line in requirements if TORCH_FAMILY.match(line)]
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
                handle.write("\n".join(family) + "\n")
            run([*pip, "-r", handle.name])
            os.unlink(handle.name)

    # The exported set is complete and pinned, so dependency resolution is unnecessary.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
        handle.write("\n".join(rest) + "\n")
    try:
        run([*pip, "--no-deps", "-r", handle.name])
    finally:
        os.unlink(handle.name)
    run([*pip, "--no-deps", "-e", str(ROOT)])
    run(
        [
            args.python,
            "-c",
            "import oscc_ml, torch; print('oscc_ml', oscc_ml.__version__, "
            "'| torch', torch.__version__, '| CUDA available:', torch.cuda.is_available())",
        ]
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
