"""The FYP-I results package (Phase 2B), written next to ``baseline.md`` by ``oscc-ml report``:

* ``MODEL_SELECTION.md`` (``report.selection``);
* ``comparisons.json``: paired comparisons of the reported runs (recomputed here, so tabular and
  image runs evaluated at different times are compared on the same test images);
* ``cost.md``: cost table; ``dataset.md``: dataset table;
* ``figures/``: ROC, PR, confusion matrices, training curves, accuracy vs cost;
* ``FYP1_RESULTS_TEMPLATE.md``: the results chapter skeleton, filled ONLY from the above.

Every number is read from run folders, ``dataset.json`` / ``extraction.json`` or the files written
here. Anything missing reads "not yet run".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from oscc_ml.catalog import DISPLAY_NAME, FAMILY, is_synthetic
from oscc_ml.eval.compare import compare_frames
from oscc_ml.report import figures, selection
from oscc_ml.utils.io import iso, read_json, utc_now, write_json

NOT_YET_RUN = "not yet run"
SYNTHETIC_BANNER = "> **SYNTHETIC — not real results.** Built from synthetic test runs."


def _ci(entry: dict[str, Any] | None) -> str:
    if not entry or entry.get("estimate") is None:
        return "n/a"
    low, high = entry.get("ci_low"), entry.get("ci_high")
    if low is None or high is None:
        return f"{entry['estimate']:.3f}"
    return f"{entry['estimate']:.3f} [{low:.3f}, {high:.3f}]"


def _f(value: Any, fmt: str = ".3f") -> str:
    return "n/a" if value is None else format(value, fmt)


def comparisons(
    records: dict[str, tuple[Path, dict[str, Any], dict[str, Any]]],
    *,
    seed: int,
    n_resamples: int,
) -> dict[str, Any] | None:
    if len(records) < 2:
        return None
    frames, taus = {}, {}
    for arch, (run_dir, _, ev) in records.items():
        frames[arch] = pd.read_csv(
            run_dir / "predictions" / "test_images.csv", dtype={"image_id": str, "group_id": str}
        )
        taus[arch] = float(ev["threshold"]["threshold"])
    return {
        "created_at": iso(utc_now()),
        "seeds": {str(seed): compare_frames(frames, taus, n_resamples=n_resamples, seed=seed)},
    }


def dataset_lines(dataset_info: Path | None) -> list[str]:
    lines = ["# Dataset", ""]
    if dataset_info is None or not dataset_info.is_file():
        return [*lines, "Dataset metadata not found (not yet run).", ""]
    info = read_json(dataset_info)
    counts = info.get("counts") or {}
    lines += [
        f"_Source: `{dataset_info.name}` "
        f"(dataset `{info.get('dataset_version', 'see manifest')}`)._",
        "",
        "| Split | Images | non-OSCC | OSCC | Patches |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for split in ("train", "val", "test"):
        c = counts.get(split) or {}
        by_class = c.get("by_class") or {}
        lines.append(
            f"| {split} | {c.get('images', 'n/a')} | "
            f"{c.get('non_oscc', by_class.get('non_oscc', 'n/a'))} | "
            f"{c.get('oscc', by_class.get('oscc', 'n/a'))} | {c.get('patches', 'n/a')} |"
        )
    lines.append("")
    return lines


def cost_lines(rows: list[dict[str, Any]], synthetic: bool) -> list[str]:
    lines = ["# Cost", "", *([SYNTHETIC_BANNER, ""] if synthetic else [])]
    lines += [
        "| Model | Family | Learnt parameters | GFLOPs / patch | CPU latency ms (unit) | "
        "Training time (s) |",
        "| --- | --- | ---: | ---: | --- | ---: |",
    ]
    for row in rows:
        if row["status"] != "completed":
            lines.append(
                f"| {row['model']} | {FAMILY[row['architecture']]} | {NOT_YET_RUN} | | | |"
            )
            continue
        lines.append(
            f"| {row['model']} | {row['family']} | {row['parameter_count']} | "
            f"{_f(row['gflops_per_patch'], '.2f')} | {_f(row['cpu_latency_mean_ms'], '.2f')} "
            f"({row.get('latency_unit', 'patch')}) | {_f(row['training_time_seconds'], '.1f')} |"
        )
    lines += [
        "",
        "Tabular parameters = coefficients (logistic regression) or tree nodes "
        "(forests, boosting); "
        "image models = network weights. GFLOPs do not apply to the tabular models.",
        "",
    ]
    return lines


def template_lines(
    rows: list[dict[str, Any]],
    selection_text: str,
    dataset_text: list[str],
    figure_files: list[str],
    synthetic: bool,
) -> list[str]:
    """FYP1_RESULTS_TEMPLATE.md: the results chapter, every value from the package."""
    done = [r for r in rows if r["status"] == "completed"]
    lines = [
        "# FYP-I results (generated)",
        "",
        *([SYNTHETIC_BANNER, ""] if synthetic else []),
        "_Filled ONLY by `oscc-ml report`; never edit the numbers by hand. Rows without a run read "
        f'"{NOT_YET_RUN}"._',
        "",
        "## 1. Dataset",
        "",
        *dataset_text[2:],
        "## 2. Baseline performance (test, image level; 95% grouped-bootstrap CIs)",
        "",
        "| Model | Family | Accuracy | Precision | Recall | F1 | AUC-ROC |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        if row["status"] != "completed":
            lines.append(
                f"| {row['model']} | {FAMILY[row['architecture']]} | {NOT_YET_RUN} | | | | |"
            )
            continue

        def ci(metric: str, r: dict[str, Any] = row) -> str:
            return _ci(
                {
                    "estimate": r[f"{metric}_estimate"],
                    "ci_low": r[f"{metric}_ci_low"],
                    "ci_high": r[f"{metric}_ci_high"],
                }
            )

        lines.append(
            f"| {row['model']} | {row['family']} | {ci('accuracy')} | {ci('precision')} | "
            f"{ci('recall')} | {ci('f1')} | {ci('auc_roc')} |"
        )
    lines += ["", "## 3. Cost", "", "See `cost.md` (same folder).", "", "## 4. Figures", ""]
    lines += [f"- `figures/{name}`" for name in figure_files] or ["- not generated (no matplotlib)"]
    lines += [
        "",
        "## 5. Model selection",
        "",
        "See `MODEL_SELECTION.md`. Summary line:",
        "",
        next(
            (x for x in selection_text.splitlines() if "Selected under the rule" in x), NOT_YET_RUN
        ),
        "",
        "## 6. Status",
        "",
        f"- Models with results: {len(done)} of {len(rows)}"
        + (
            "; not yet run: " + ", ".join(r["model"] for r in rows if r["status"] != "completed")
            if len(done) < len(rows)
            else ""
        )
        + ".",
        "- One seed (42) in FYP-I; FYP-II repeats with seeds 42, 43, 44.",
        "",
    ]
    return lines


def write_package(
    out_dir: Path,
    chosen: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    seed: int,
    dataset_info: Path | None,
    n_resamples: int = 2000,
) -> dict[str, Path]:
    records = {
        arch: (rec.path, rec.info, rec.evaluation)
        for arch, rec in chosen.items()
        if rec.evaluation is not None
    }
    synthetic = any(is_synthetic(str(i.get("dataset_version", ""))) for _, i, _ in records.values())
    missing = [r["architecture"] for r in rows if r["status"] != "completed"]
    out: dict[str, Path] = {}

    comp = comparisons(records, seed=seed, n_resamples=n_resamples)
    if comp is not None:
        write_json(out_dir / "comparisons.json", comp)
        out["comparisons"] = out_dir / "comparisons.json"

    sel_text = selection.render(records, comp, seed=seed, synthetic=synthetic, missing=missing)
    (out_dir / "MODEL_SELECTION.md").write_text(sel_text, encoding="utf-8")
    out["model_selection"] = out_dir / "MODEL_SELECTION.md"

    (out_dir / "cost.md").write_text("\n".join(cost_lines(rows, synthetic)), encoding="utf-8")
    out["cost"] = out_dir / "cost.md"
    ds = dataset_lines(dataset_info)
    (out_dir / "dataset.md").write_text("\n".join(ds), encoding="utf-8")
    out["dataset"] = out_dir / "dataset.md"

    fig_dir = out_dir / "figures"
    suffix = " (SYNTHETIC)" if synthetic else ""
    made: list[Path] = []
    named = {a: (DISPLAY_NAME.get(a, a), r[0]) for a, r in records.items()}
    made += figures.roc_pr(named, fig_dir, title_suffix=suffix)
    points = []
    for arch, (run_dir, _, ev) in records.items():
        name = DISPLAY_NAME.get(arch, arch)
        for path in (
            figures.confusion(name, arch, ev, fig_dir, suffix),
            figures.training_curve(name, arch, run_dir, fig_dir, suffix),
        ):
            if path is not None:
                made.append(path)
        auc = ev["test"]["auc_roc"]
        points.append(
            {
                "name": name,
                "auc": auc["estimate"],
                "auc_low": auc.get("ci_low"),
                "auc_high": auc.get("ci_high"),
                "latency_ms": (ev["cost"].get("latency_cpu") or {}).get("mean_ms"),
            }
        )
    cost_fig = figures.accuracy_vs_cost(points, fig_dir, suffix)
    if cost_fig is not None:
        made.append(cost_fig)
    out["figures"] = fig_dir

    template = template_lines(rows, sel_text, ds, sorted(p.name for p in made), synthetic)
    (out_dir / "FYP1_RESULTS_TEMPLATE.md").write_text("\n".join(template), encoding="utf-8")
    out["results_template"] = out_dir / "FYP1_RESULTS_TEMPLATE.md"
    (out_dir / "package.json").write_text(
        json.dumps(
            {
                "synthetic": synthetic,
                "models": sorted(records),
                "not_yet_run": missing,
                "figures": sorted(p.name for p in made),
                "dataset_info": str(dataset_info) if dataset_info else None,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out
