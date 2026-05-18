#!/usr/bin/env python3
"""Run legacy paper evaluation method on latest paper_experiments runs.

This script intentionally reuses the legacy scoring logic from
`run_paper_analysis.py` and writes all artifacts into a fresh output folder.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from evaluation.paper_experiments_v1 import run_paper_analysis as legacy


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_DIR = PROJECT_ROOT / "evaluation" / "paper_experiments_v1" / "runs"
DEFAULT_OUTPUT_PARENT = PROJECT_ROOT / "evaluation" / "paper_experiments_v1" / "legacy_eval_outputs"


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown_table(path: Path, title: str, rows: list[dict], fieldnames: list[str]) -> None:
    lines = [f"# {title}", ""]
    if not rows:
        lines.append("_No rows available._")
    else:
        lines.append("| " + " | ".join(fieldnames) + " |")
        lines.append("| " + " | ".join("---" for _ in fieldnames) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(row.get(k, "")) for k in fieldnames) + " |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _aggregate_model_rows(summary_rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in summary_rows:
        grouped[row["model"]].append(row)

    out: list[dict] = []
    for model, rows in sorted(grouped.items()):
        out.append(
            {
                "model": model,
                "n_documents": len(rows),
                "mean_f1_field_id": round(mean(float(r["mean_f1_field_id"]) for r in rows), 4),
                "mean_f1_value": round(mean(float(r["mean_f1_value"]) for r in rows), 4),
                "mean_best_f1_value": round(mean(float(r["best_f1_value"]) for r in rows), 4),
                "mean_confidence": round(
                    mean(float(r["mean_confidence"]) for r in rows if r.get("mean_confidence") not in (None, "")),
                    4,
                )
                if any(r.get("mean_confidence") not in (None, "") for r in rows)
                else "",
                "mean_ungrounded": round(
                    mean(float(r["mean_ungrounded"]) for r in rows if r.get("mean_ungrounded") not in (None, "")),
                    2,
                )
                if any(r.get("mean_ungrounded") not in (None, "") for r in rows)
                else "",
            }
        )
    return out


def _aggregate_sheet_rows(all_results: list[dict]) -> list[dict]:
    sheet_metric_lists: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"f1_field_id": [], "f1_value": [], "precision_id": [], "recall_id": []}
    )
    for entry in all_results:
        per_sheet = entry.get("per_sheet", {})
        for sheet, sm in per_sheet.items():
            sheet_metric_lists[sheet]["f1_field_id"].append(float(sm.get("f1_field_id", 0.0)))
            sheet_metric_lists[sheet]["f1_value"].append(float(sm.get("f1_value", 0.0)))
            sheet_metric_lists[sheet]["precision_id"].append(float(sm.get("precision_id", 0.0)))
            sheet_metric_lists[sheet]["recall_id"].append(float(sm.get("recall_id", 0.0)))

    out = []
    for sheet in ["investigation", "study", "observationunit", "sample", "assay"]:
        metrics = sheet_metric_lists.get(sheet)
        if not metrics or not metrics["f1_value"]:
            continue
        out.append(
            {
                "sheet": sheet,
                "n_cells": len(metrics["f1_value"]),
                "mean_f1_field_id": round(mean(metrics["f1_field_id"]), 4),
                "mean_f1_value": round(mean(metrics["f1_value"]), 4),
                "mean_precision_id": round(mean(metrics["precision_id"]), 4),
                "mean_recall_id": round(mean(metrics["recall_id"]), 4),
            }
        )
    return out


def _plot_model_value_f1(model_rows: list[dict], out_dir: Path) -> None:
    if not model_rows:
        return

    labels = [r["model"] for r in model_rows]
    vals = [float(r["mean_f1_value"]) for r in model_rows]
    order = np.argsort(vals)[::-1]
    labels = [labels[i] for i in order]
    vals = [vals[i] for i in order]

    plt.figure(figsize=(7.2, 4.4))
    bars = plt.bar(range(len(labels)), vals, color="#4c78a8", alpha=0.85)
    plt.xticks(range(len(labels)), labels, rotation=20, ha="right")
    plt.ylabel("Mean value F1 (legacy method)")
    plt.title("Legacy evaluation on latest paper runs: model ranking")
    plt.ylim(0, max(1.0, max(vals) + 0.05))
    for idx, (bar, v) in enumerate(zip(bars, vals)):
        plt.text(idx, v + 0.01, f"{v:.3f}", ha="center", va="bottom", fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "fig_legacy_model_value_f1_bar.png", dpi=300)
    plt.savefig(out_dir / "fig_legacy_model_value_f1_bar.pdf")
    plt.close()


def _plot_sheet_value_f1(sheet_rows: list[dict], out_dir: Path) -> None:
    if not sheet_rows:
        return

    labels = [r["sheet"] for r in sheet_rows]
    vals = [float(r["mean_f1_value"]) for r in sheet_rows]

    plt.figure(figsize=(7.2, 4.4))
    bars = plt.bar(range(len(labels)), vals, color="#59a14f", alpha=0.85)
    plt.xticks(range(len(labels)), labels, rotation=20, ha="right")
    plt.ylabel("Mean value F1 (legacy method)")
    plt.title("Legacy evaluation on latest paper runs: ISA sheet profile")
    plt.ylim(0, max(1.0, max(vals) + 0.05))
    for idx, (bar, v) in enumerate(zip(bars, vals)):
        plt.text(idx, v + 0.01, f"{v:.3f}", ha="center", va="bottom", fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "fig_legacy_sheet_value_f1_bar.png", dpi=300)
    plt.savefig(out_dir / "fig_legacy_sheet_value_f1_bar.pdf")
    plt.close()


def _write_run_metadata(output_dir: Path, runs_dir: Path) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(),
        "method": "legacy_run_paper_analysis",
        "runs_dir": str(runs_dir),
        "notes": [
            "Uses legacy metrics logic from evaluation/paper_experiments_v1/run_paper_analysis.py",
            "For this rerun, batch output collection is disabled to avoid mixing in old output/*eval_batch* artifacts.",
            "Only latest paper_experiments_v1/runs artifacts are included.",
        ],
    }
    (output_dir / "analysis_run_meta.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_legacy_eval(runs_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for sub in ["analysis", "tables", "figures"]:
        (output_dir / sub).mkdir(parents=True, exist_ok=True)

    # Reuse legacy method but pin to latest paper runs and avoid mixed old batch outputs.
    legacy.RUNS_DIR = runs_dir
    legacy.OUTPUT_DIR = output_dir
    legacy.collect_batch_outputs = lambda: []

    export = legacy.main()
    summary_rows = export.get("summary", [])
    all_results = export.get("all_results", [])

    model_rows = _aggregate_model_rows(summary_rows)
    sheet_rows = _aggregate_sheet_rows(all_results)

    # Tables
    if summary_rows:
        fields = list(summary_rows[0].keys())
        _write_csv(output_dir / "tables" / "table_legacy_model_document_metrics.csv", summary_rows, fields)
        _write_markdown_table(
            output_dir / "tables" / "table_legacy_model_document_metrics.md",
            "Legacy Model x Document Metrics",
            summary_rows,
            fields,
        )

    if model_rows:
        fields = list(model_rows[0].keys())
        _write_csv(output_dir / "tables" / "table_legacy_model_aggregate.csv", model_rows, fields)
        _write_markdown_table(
            output_dir / "tables" / "table_legacy_model_aggregate.md",
            "Legacy Model Aggregate Metrics",
            model_rows,
            fields,
        )

    if sheet_rows:
        fields = list(sheet_rows[0].keys())
        _write_csv(output_dir / "tables" / "table_legacy_sheet_aggregate.csv", sheet_rows, fields)
        _write_markdown_table(
            output_dir / "tables" / "table_legacy_sheet_aggregate.md",
            "Legacy Sheet Aggregate Metrics",
            sheet_rows,
            fields,
        )

    # Figures
    _plot_model_value_f1(model_rows, output_dir / "figures")
    _plot_sheet_value_f1(sheet_rows, output_dir / "figures")

    _write_run_metadata(output_dir, runs_dir)
    print(f"\n[OK] Legacy evaluation artifacts written to: {output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run legacy evaluation method on latest paper experiment runs into a new output folder."
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help=f"Runs directory to evaluate (default: {DEFAULT_RUNS_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. If omitted, creates a timestamped folder under legacy_eval_outputs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runs_dir = args.runs_dir.resolve()
    if not runs_dir.exists():
        raise FileNotFoundError(f"Runs directory not found: {runs_dir}")

    output_dir = args.output_dir
    if output_dir is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = DEFAULT_OUTPUT_PARENT / f"legacy_eval_latest_runs_{stamp}"
    output_dir = output_dir.resolve()

    run_legacy_eval(runs_dir=runs_dir, output_dir=output_dir)


if __name__ == "__main__":
    main()

