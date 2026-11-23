"""``oscc-ml report``: the baseline table and the FYP-I results package, generated only from run
folders (CNN, ViT and tabular runs share one format).

Every number comes from ``run_info.json``, ``metrics.json`` and ``evaluation.json`` written by the
pipeline. Nothing is typed by hand. The report refuses:

* smoke runs and runs on synthetic data,
* runs that deviate from the protocol (``protocol_compliant: false``),
* runs without ``evaluation.json`` (run ``oscc-ml evaluate`` first),
* mixing dataset versions in one table, or image runs with different learning rates or batch
  sizes (tabular runs have neither).

Architectures without a usable run are listed as "not yet run". Besides ``baseline.md`` /
``summary.csv`` / ``summary.json`` the report writes ``MODEL_SELECTION.md`` (SDS rule, paired
comparisons, per-magnification, calibration, errors, stability, cost, "why not" per model),
``cost.md``, ``dataset.md``, ``FYP1_RESULTS_TEMPLATE.md`` and ``figures/`` (ROC, PR, confusion
matrices, training curves, accuracy vs cost). Synthetic test runs are labelled SYNTHETIC everywhere.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oscc_ml.catalog import (
    ALL_ARCHITECTURES,
    DISPLAY_NAME,
    EVALUATION_FILE,
    FAMILY,
    TABULAR_ARCHITECTURES,
    is_synthetic,
)
from oscc_ml.utils.io import iso, read_json, utc_now, write_json

NOT_YET_RUN = "not yet run"
REPORT_ARCHITECTURES = ALL_ARCHITECTURES + TABULAR_ARCHITECTURES
SYNTHETIC_BANNER = "> **SYNTHETIC — not real results.** Built from synthetic test runs."


class ReportRefusedError(RuntimeError):
    """The run folders cannot produce an honest report."""


@dataclass(frozen=True)
class RunRecord:
    path: Path
    info: dict[str, Any]
    metrics: dict[str, Any]
    evaluation: dict[str, Any] | None


def _load(run_dir: Path) -> RunRecord | None:
    try:
        info = read_json(run_dir / "run_info.json")
    except (OSError, ValueError):
        return None
    metrics_path = run_dir / "metrics.json"
    eval_path = run_dir / EVALUATION_FILE
    return RunRecord(
        run_dir,
        info,
        read_json(metrics_path) if metrics_path.is_file() else {},
        read_json(eval_path) if eval_path.is_file() else None,
    )


def collect(
    runs_dir: Path,
    *,
    seed: int = 42,
    allow_synthetic: bool = False,
    allow_noncompliant: bool = False,
) -> tuple[dict[str, RunRecord], list[str]]:
    """Pick the latest completed training run per architecture; return it with notes.

    ``allow_synthetic`` and ``allow_noncompliant`` exist only for the test suite; the CLI never
    sets them.
    """
    notes: list[str] = []
    records = [r for p in sorted(runs_dir.glob("*/run_info.json")) if (r := _load(p.parent))]
    ignored_smoke = [r for r in records if r.info.get("smoke") or r.info.get("purpose") == "smoke"]
    if ignored_smoke:
        notes.append(
            f"ignored {len(ignored_smoke)} smoke run folder(s): smoke runs are never reported"
        )
    candidates = [
        r
        for r in records
        if r.info.get("purpose") == "train"
        and not r.info.get("smoke")
        and r.info.get("status") == "completed"
        and r.info.get("seed") == seed
    ]
    if not candidates:
        if ignored_smoke:
            raise ReportRefusedError(
                "only smoke runs were found; smoke runs are never reported. Train real models first."
            )
        raise ReportRefusedError(f"no completed training runs with seed {seed} in {runs_dir}")

    chosen: dict[str, RunRecord] = {}
    for record in sorted(candidates, key=lambda r: r.path.name):
        arch = str(record.info.get("architecture"))
        if arch in chosen:
            notes.append(f"{chosen[arch].path.name} superseded by the later run {record.path.name}")
        chosen[arch] = record

    problems: list[str] = []
    for arch, record in chosen.items():
        name = record.path.name
        version = str(record.info.get("dataset_version", ""))
        if is_synthetic(version) and not allow_synthetic:
            problems.append(f"{name}: synthetic dataset {version!r} is never reported")
        if not record.info.get("protocol_compliant") and not allow_noncompliant:
            deviations = "; ".join(record.info.get("deviations", [])) or "unknown"
            problems.append(f"{name}: not protocol-compliant ({deviations})")
        if record.evaluation is None:
            problems.append(f"{name}: no {EVALUATION_FILE}; run `oscc-ml evaluate` first")
        del arch
    image_runs = [r for r in chosen.values() if r.info.get("model_type") != "tabular"]
    for field_name, group in (
        ("dataset_version", list(chosen.values())),
        ("lr", image_runs),
        ("batch_size", image_runs),
    ):
        values = {str(r.info.get(field_name)) for r in group}
        if len(values) > 1:
            problems.append(f"runs disagree on {field_name}: {sorted(values)}")
    if problems:
        raise ReportRefusedError("report refused:\n  " + "\n  ".join(problems))
    return chosen, notes


def _ci(entry: dict[str, Any] | None) -> str:
    if not entry or entry.get("estimate") is None:
        return "n/a"
    low, high = entry.get("ci_low"), entry.get("ci_high")
    if low is None or high is None:
        return f"{entry['estimate']:.3f}"
    return f"{entry['estimate']:.3f} [{low:.3f}, {high:.3f}]"


def _num(value: Any, fmt: str) -> str:
    return "n/a" if value is None else format(value, fmt)


def summary_rows(chosen: dict[str, RunRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for arch in REPORT_ARCHITECTURES:
        record = chosen.get(arch)
        if record is None or record.evaluation is None:
            rows.append({"architecture": arch, "model": DISPLAY_NAME[arch], "status": NOT_YET_RUN})
            continue
        ev, m = record.evaluation, record.metrics
        test, cost = ev["test"], ev["cost"]
        gpu = cost.get("latency_gpu") or {}
        rows.append(
            {
                "architecture": arch,
                "model": DISPLAY_NAME[arch],
                "family": FAMILY[arch],
                "status": "completed",
                "synthetic": is_synthetic(str(record.info.get("dataset_version", ""))),
                "run": record.path.name,
                **{
                    f"{metric}_{part}": test[metric][part]
                    for metric in (
                        "auc_roc",
                        "accuracy",
                        "precision",
                        "recall",
                        "specificity",
                        "f1",
                    )
                    for part in ("estimate", "ci_low", "ci_high")
                },
                "threshold": ev["threshold"]["threshold"],
                "parameter_count": cost["parameter_count"],
                "gflops_per_patch": cost["gflops_per_patch"],
                "cpu_latency_mean_ms": cost["latency_cpu"]["mean_ms"],
                "latency_unit": "feature row" if FAMILY[arch] == "Tabular" else "224 px patch",
                "cpu_latency_p95_ms": cost["latency_cpu"]["p95_ms"],
                "gpu_latency_mean_ms": gpu.get("mean_ms"),
                "gpu_latency_p95_ms": gpu.get("p95_ms"),
                "peak_gpu_memory_train_mb": cost.get("peak_gpu_memory_train_mb"),
                "peak_gpu_memory_inference_mb": cost.get("peak_gpu_memory_inference_mb"),
                "training_time_seconds": m.get("training_time_seconds"),
                "mean_epoch_seconds": m.get("mean_epoch_seconds"),
                "best_epoch": m.get("best_epoch"),
                "epochs_run": m.get("epochs_run"),
            }
        )
    return rows


def render_markdown(
    chosen: dict[str, RunRecord], rows: list[dict[str, Any]], notes: list[str]
) -> str:
    image_records = [r for r in chosen.values() if r.info.get("model_type") != "tabular"]
    any_record = image_records[0] if image_records else next(iter(chosen.values()))
    info = any_record.info
    ev = any_record.evaluation or {}
    meta = ev.get("test", {}).get("_meta", {})
    synthetic = any(is_synthetic(str(r.info.get("dataset_version", ""))) for r in chosen.values())
    lr = info.get("lr")
    lines = [
        "# Baseline results (FYP-I, seed 42)",
        "",
        *([SYNTHETIC_BANNER, ""] if synthetic else []),
        f"_Generated by `oscc-ml report` on {iso(utc_now())} from run folders only. "
        "Do not edit by hand; regenerate instead._",
        "",
        f"- Dataset: `{info.get('dataset_version')}`; image models: "
        + (
            f"learning rate {lr:g} ({info.get('lr_source')}); batch size {info.get('batch_size')}; "
            f"protocol `{info.get('protocol_version')}`."
            if image_records and lr is not None
            else "not yet run."
        ),
        "- Tabular models: one feature row per image, grouped-CV tuning on train (ADR-0006).",
        "- Unit: image (image models: mean of patch probabilities). Threshold tau calibrated on "
        "validation "
        f"(target recall {ev.get('threshold', {}).get('target_recall')}); inconclusive margin "
        f"{ev.get('inconclusive_margin')}.",
        f"- 95% CIs: {meta.get('n_resamples')} bootstrap resamples of {meta.get('resampled_unit')} "
        f"({meta.get('n_groups')} groups, {meta.get('n_images')} test images).",
        "",
        "## Test performance",
        "",
        "| Model | Family | AUC-ROC [95% CI] | Accuracy | Precision | Recall | Specificity | F1 | tau |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        if row["status"] == NOT_YET_RUN:
            lines.append(
                f"| {row['model']} | {FAMILY[row['architecture']]} | {NOT_YET_RUN} |  |  |  |  |  |  |"
            )
            continue
        test = chosen[row["architecture"]].evaluation["test"]  # type: ignore[index]
        lines.append(
            f"| {row['model']} | {row['family']} | {_ci(test['auc_roc'])} | {_ci(test['accuracy'])} "
            f"| {_ci(test['precision'])} | {_ci(test['recall'])} | {_ci(test['specificity'])} "
            f"| {_ci(test['f1'])} | {row['threshold']:.3f} |"
        )
    lines += [
        "",
        "## Cost",
        "",
        "| Model | Params (M) | GFLOPs / patch | CPU latency ms (mean / p95) | GPU latency ms "
        "(mean / p95) | Peak GPU MB (train / infer) | Training time | s / epoch | Best / run epochs |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        if row["status"] == NOT_YET_RUN:
            lines.append(f"| {row['model']} | {NOT_YET_RUN} |  |  |  |  |  |  |  |")
            continue
        train_s = row["training_time_seconds"]
        lines.append(
            f"| {row['model']} | {row['parameter_count'] / 1e6:.4f} "
            f"| {_num(row['gflops_per_patch'], '.2f')} "
            f"| {row['cpu_latency_mean_ms']:.1f} / {row['cpu_latency_p95_ms']:.1f} "
            f"| {_num(row['gpu_latency_mean_ms'], '.2f')} / {_num(row['gpu_latency_p95_ms'], '.2f')} "
            f"| {_num(row['peak_gpu_memory_train_mb'], '.0f')} / "
            f"{_num(row['peak_gpu_memory_inference_mb'], '.0f')} "
            f"| {_num(None if train_s is None else train_s / 3600, '.2f')} h "
            f"| {_num(row['mean_epoch_seconds'], '.1f')} "
            f"| {_num(row['best_epoch'], 'd')} / {_num(row['epochs_run'], 'd')} |"
        )
    lines += [
        "",
        "## Provenance",
        "",
        "| Model | Run folder | Git commit | Dirty | GPU | torch |",
        "|---|---|---|---|---|---|",
    ]
    for arch in REPORT_ARCHITECTURES:
        record = chosen.get(arch)
        if record is None:
            continue
        env = (
            read_json(record.path / "environment.json")
            if (record.path / "environment.json").is_file()
            else {}
        )
        gpus = ", ".join(env.get("gpu_names", [])) or "none"
        lines.append(
            f"| {DISPLAY_NAME[arch]} | `{record.path.name}` | `{str(record.info.get('git_commit'))[:12]}` "
            f"| {record.info.get('git_dirty')} | {gpus} | {env.get('torch')} |"
        )
    if notes:
        lines += ["", "## Notes", ""] + [f"- {note}" for note in notes]
    lines += [
        "",
        "Paired comparisons (bootstrap of the AUC difference, McNemar, Holm) and the selection rule "
        "are in `MODEL_SELECTION.md`; the 3-seed analysis is Phase R3 (FYP-II). This table alone "
        "does not show that one model is better.",
        "",
    ]
    return "\n".join(lines)


def build_report(
    runs_dir: Path,
    out_dir: Path,
    *,
    seed: int = 42,
    allow_synthetic: bool = False,
    allow_noncompliant: bool = False,
    dataset_info: Path | None = None,
    n_resamples: int = 2000,
) -> dict[str, Path]:
    chosen, notes = collect(
        runs_dir, seed=seed, allow_synthetic=allow_synthetic, allow_noncompliant=allow_noncompliant
    )
    rows = summary_rows(chosen)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "baseline.md"
    md_path.write_text(render_markdown(chosen, rows, notes), "utf-8")
    columns: list[str] = []
    for row in rows:
        columns += [k for k in row if k not in columns]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    csv_path = out_dir / "summary.csv"
    csv_path.write_text(buffer.getvalue(), "utf-8")
    json_path = out_dir / "summary.json"
    write_json(json_path, {"generated_at": iso(utc_now()), "rows": rows, "notes": notes})
    from oscc_ml.report.package import write_package

    extra = write_package(
        out_dir, chosen, rows, seed=seed, dataset_info=dataset_info, n_resamples=n_resamples
    )
    return {"markdown": md_path, "csv": csv_path, "json": json_path, **extra}
