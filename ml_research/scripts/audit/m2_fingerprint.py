"""Before/after fingerprint for Phase 2A PR (B): moving test prediction into `evaluate` and adding
the training observation record must not change training.

Runs a small deterministic CPU pipeline on synthetic data (sweep -> train-all -> evaluate, random
init, all four architectures) and writes a JSON fingerprint of everything that must stay
byte-identical:
* SHA-256 of every best.pt and of its state_dict tensors;
* the chosen LR and the sweep's validation-AUC table;
* per run: tau (the whole threshold record), validation and test image predictions (SHA-256 of the
  CSV with normalised line endings), test metrics with CIs, per-magnification metrics and the
  outcome counts.
Timing, latency and timestamps are excluded (never reproducible).

Run it once on the old code and once on the new code, then compare the two JSON files:

    python scripts/audit/m2_fingerprint.py --out <folder>/before
    python scripts/audit/m2_fingerprint.py --out <folder>/after
    python scripts/audit/m2_fingerprint.py --compare <before.json> <after.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import torch
import yaml

GRID = [1.0e-4, 1.0e-3]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _csv_sha(path: Path) -> str:
    return _sha(path.read_bytes().replace(b"\r\n", b"\n"))


def _state_sha(path: Path) -> str:
    state = torch.load(path, map_location="cpu", weights_only=True)["state_dict"]
    digest = hashlib.sha256()
    for key in sorted(state):
        digest.update(key.encode())
        digest.update(state[key].detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def build(out: Path) -> Path:
    from oscc_ml.config import DEFAULT_CONFIG_DIR
    from oscc_ml.data.synthetic import write_synthetic_dataset
    from oscc_ml.eval.evaluate import evaluate_all
    from oscc_ml.train.sweep import run_sweep
    from oscc_ml.train.train_all import train_all

    if out.exists():
        shutil.rmtree(out)
    configs = out / "configs"
    configs.mkdir(parents=True)
    for path in DEFAULT_CONFIG_DIR.glob("*.yaml"):
        shutil.copy(path, configs / path.name)
    protocol = yaml.safe_load((configs / "protocol.yaml").read_text("utf-8"))
    protocol["optimizer"]["lr_grid"] = GRID
    protocol["data"]["num_workers"] = 0
    (configs / "protocol.yaml").write_text(yaml.safe_dump(protocol), "utf-8")
    data = write_synthetic_dataset(
        out / "data",
        (8, 8, 8),
        seed=11,
        patches_per_image=(1, 2),
        dataset_version="synthetic-m2",
    )
    runs = out / "runs"
    common: dict[str, Any] = {"device": "cpu", "config_dir": configs, "pretrained": False}
    run_sweep(data, runs, epochs=1, **common)
    result = train_all(data, runs, epochs=2, resume=True, **common)
    if result.failed:
        raise RuntimeError(result.failed)
    _, failed = evaluate_all(
        runs, n_bootstrap=200, warmup=1, latency_runs=2, measure_gpu=False, config_dir=configs
    )
    if failed:
        raise RuntimeError(failed)
    return runs


def fingerprint(runs: Path) -> dict[str, Any]:
    chosen = json.loads((runs / "sweep" / "chosen_lr.json").read_text("utf-8"))
    out: dict[str, Any] = {
        "chosen_lr": chosen["chosen_lr"],
        "val_auc_table": chosen["val_auc_table"],
        "sweep_best_pt": {},
        "runs": {},
    }
    for best in sorted((runs / "sweep").glob("*/checkpoints/best.pt")):
        info = json.loads((best.parents[1] / "run_info.json").read_text("utf-8"))
        key = f"{info['architecture']} lr={info['lr']:g}"
        out["sweep_best_pt"][key] = {"file": _sha(best.read_bytes()), "state": _state_sha(best)}
    for info_path in sorted(runs.glob("*/run_info.json")):
        run = info_path.parent
        info = json.loads(info_path.read_text("utf-8"))
        ev = json.loads((run / "evaluation.json").read_text("utf-8"))
        best = run / "checkpoints" / "best.pt"
        out["runs"][info["architecture"]] = {
            "best_pt_file": _sha(best.read_bytes()),
            "best_pt_state": _state_sha(best),
            "lr": info["lr"],
            "threshold": ev["threshold"],
            "val_images": _csv_sha(run / "predictions" / "val_images.csv"),
            "val_patches": _csv_sha(run / "predictions" / "val_patches.csv"),
            "test_images": _csv_sha(run / "predictions" / "test_images.csv"),
            "test_patches": _csv_sha(run / "predictions" / "test_patches.csv"),
            "test": ev["test"],
            "test_by_magnification": ev["test_by_magnification"],
            "test_outcomes": ev["test_outcomes"],
        }
    return out


def compare(a: Path, b: Path) -> int:
    before = json.loads(a.read_text("utf-8"))
    after = json.loads(b.read_text("utf-8"))
    problems: list[str] = []

    def walk(x: Any, y: Any, where: str) -> None:
        if isinstance(x, dict) and isinstance(y, dict):
            for key in sorted(set(x) | set(y)):
                if key not in x or key not in y:
                    problems.append(f"{where}.{key}: only in {'before' if key in x else 'after'}")
                else:
                    walk(x[key], y[key], f"{where}.{key}")
        elif x != y:
            problems.append(f"{where}: {x!r} != {y!r}")

    walk(before, after, "fingerprint")
    if problems:
        print("DIFFERENT:\n  " + "\n  ".join(problems[:50]))
        return 1
    n = len(before["runs"])
    print(
        f"IDENTICAL: chosen LR, {len(before['sweep_best_pt'])} sweep checkpoints, {n} training "
        "checkpoints (file + tensors), tau, val/test predictions and test metrics"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path)
    p.add_argument("--compare", nargs=2, type=Path)
    p.add_argument("--keep", action="store_true", help="keep the run folders (several GB)")
    args = p.parse_args(argv)
    if args.compare:
        return compare(*args.compare)
    if args.out is None:
        p.error("--out or --compare is required")
    runs = build(args.out)
    result = fingerprint(runs)
    (args.out / "fingerprint.json").write_text(
        json.dumps(result, indent=1, sort_keys=True), "utf-8"
    )
    if not args.keep:  # checkpoints of four models take several GB on a small laptop disk
        for name in ("runs", "data"):
            shutil.rmtree(args.out / name, ignore_errors=True)
    print(f"fingerprint written: {args.out / 'fingerprint.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
