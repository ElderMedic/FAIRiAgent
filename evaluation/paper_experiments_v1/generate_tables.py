#!/usr/bin/env python3
"""Generate manuscript tables from artifact-backed paper experiment outputs."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from statistics import mean
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = PROJECT_ROOT / "evaluation" / "paper_experiments_v1"
TABLE_DIR = BASE_DIR / "tables"
ANALYSIS_DIR = BASE_DIR / "analysis"
RESULTS_DIR = BASE_DIR / "results"
VALUES_DIR = PROJECT_ROOT / "evaluation" / "datasets" / "annotated" / "values"

ISA_ORDER = ["investigation", "study", "observationunit", "sample", "assay"]
SKIP_KEYS = {"_evidence", "_ambiguity", "_ambiguity_rationale", "generated_by", "generated_at"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, title: str, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    lines = [f"# {title}", ""]
    if not rows:
        lines.append("_No rows available._")
    else:
        lines.append("| " + " | ".join(fieldnames) + " |")
        lines.append("| " + " | ".join("---" for _ in fieldnames) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(row.get(field, "")) for field in fieldnames) + " |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def ground_truth_rows() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(VALUES_DIR.glob("ground_truth_*_values.json")):
        data = read_json(path)
        doc_id = data["document_id"]
        sheets = data.get("isa_sheets", {})
        sheet_rows = {}
        total_rows = 0
        total_values = 0
        for sheet in ISA_ORDER:
            expected = sheets.get(sheet, {}).get("expected_rows", [])
            sheet_rows[sheet] = len(expected)
            total_rows += len(expected)
            for row in expected:
                if isinstance(row, dict):
                    total_values += sum(
                        1
                        for key, value in row.items()
                        if key not in SKIP_KEYS and value not in (None, "")
                    )
        rows.append(
            {
                "document": doc_id,
                "gt_rows_total": total_rows,
                "gt_values_total": total_values,
                **{f"{sheet}_rows": sheet_rows[sheet] for sheet in ISA_ORDER},
            }
        )
    return rows


def b1_rows() -> list[dict[str, Any]]:
    data = read_json(RESULTS_DIR / "b1_value_comparison.json")
    rows = []
    for doc_id, result in sorted(data.items()):
        rows.append(
            {
                "document": doc_id,
                "score": result.get("score"),
                "coverage_pct": result.get("coverage"),
                "match": result.get("match"),
                "total": result.get("total"),
            }
        )
    rows.append(
        {
            "document": "mean",
            "score": round(mean(float(row["score"]) for row in rows), 3),
            "coverage_pct": round(mean(float(row["coverage_pct"]) for row in rows), 1),
            "match": "",
            "total": "",
        }
    )
    return rows


def parse_b123_rows() -> list[dict[str, Any]]:
    text = (RESULTS_DIR / "B1_B2_B3_COMPARISON.md").read_text(encoding="utf-8")
    rows = []
    pattern = re.compile(r"^\| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$")
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        document, b1, b2, b3, best = [part.strip() for part in match.groups()]
        if document in {"Document", "----------"}:
            continue
        rows.append({"document": document, "B1": b1, "B2": b2, "B3": b3, "best": best})
    return rows


def full_pipeline_analysis_rows() -> list[dict[str, Any]]:
    rows = []
    with (ANALYSIS_DIR / "per_document_metrics.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["model"] != "qwen3.6-27b":
                continue
            rows.append(
                {
                    "document": row["document"],
                    "field_id_f1": row["mean_f1_field_id"],
                    "value_f1": row["mean_f1_value"],
                    "confidence": row["mean_confidence"],
                    "pred_rows": row["total_rows_pred"],
                    "gt_rows": row["total_rows_gt"],
                    "confirmed": row["confirmed"],
                    "provisional": row["provisional"],
                }
            )
    return rows


def per_sheet_rows() -> list[dict[str, Any]]:
    rows_by_sheet: dict[str, dict[str, list[float]]] = {
        sheet: {"field_id_f1": [], "value_f1": [], "precision": [], "recall": []}
        for sheet in ISA_ORDER
    }
    with (ANALYSIS_DIR / "per_sheet_metrics.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            sheet = row["sheet"]
            rows_by_sheet[sheet]["field_id_f1"].append(float(row["f1_field_id"]))
            rows_by_sheet[sheet]["value_f1"].append(float(row["f1_value"]))
            rows_by_sheet[sheet]["precision"].append(float(row["precision_id"]))
            rows_by_sheet[sheet]["recall"].append(float(row["recall_id"]))
    return [
        {
            "sheet": sheet,
            "field_id_f1_mean": round(mean(values["field_id_f1"]), 3),
            "value_f1_mean": round(mean(values["value_f1"]), 3),
            "precision_mean": round(mean(values["precision"]), 3),
            "recall_mean": round(mean(values["recall"]), 3),
        }
        for sheet, values in rows_by_sheet.items()
    ]


def model_comparison_rows() -> list[dict[str, Any]]:
    text = (RESULTS_DIR / "MODEL_COMPARISON.md").read_text(encoding="utf-8")
    rows = []
    pattern = re.compile(r"^\| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$")
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        metric, qwen, gemma, delta = [part.strip() for part in match.groups()]
        if metric in {"Metric", "--------"}:
            continue
        rows.append({"metric": metric, "qwen3.6_27b": qwen, "gemma4_31b": gemma, "delta": delta})
    return rows


def multifile_reference_rows() -> list[dict[str, Any]]:
    summary = read_json(RESULTS_DIR / "full_pipeline_multifile_reference_20260505.json")
    source_rows = [
        {
            "source_id": item["source_id"],
            "path": item["path"],
            "method": item["method"],
            "role": item["source_role"],
            "tables": "; ".join(f"{t['name']} ({t['rows']})" for t in item.get("tables", [])),
        }
        for item in summary["sources"]["items"]
    ]
    isa_rows = [
        {
            "sheet": sheet,
            "rows": summary["isa_row_counts"][sheet],
            "columns": summary["isa_column_counts"][sheet],
            "non_empty_cells": summary["isa_non_empty_cells"][sheet],
            "key_entities": "; ".join(summary["key_entities"].get(sheet, [])),
        }
        for sheet in ISA_ORDER
    ]
    metric_rows = [
        {"metric": key, "value": value}
        for key, value in summary["quality_metrics"].items()
    ]
    return source_rows, isa_rows, metric_rows


def main() -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)

    table_specs = [
        ("table1_benchmark_composition", "Benchmark Composition", ground_truth_rows()),
        ("table2_b1_scores", "B1 Baseline Scores", b1_rows()),
        ("table3_b1_b2_b3_subset", "B1/B2/B3 Subset Comparison", parse_b123_rows()),
        ("table4_full_pipeline_analysis_diagnostic", "Full Pipeline Diagnostic Analysis", full_pipeline_analysis_rows()),
        ("table5_per_sheet_performance", "Per-Sheet Performance", per_sheet_rows()),
        ("table6_model_comparison", "Local Model Comparison", model_comparison_rows()),
    ]

    for stem, title, rows in table_specs:
        if not rows:
            continue
        fields = list(rows[0].keys())
        write_csv(TABLE_DIR / f"{stem}.csv", rows, fields)
        write_markdown(TABLE_DIR / f"{stem}.md", title, rows, fields)

    source_rows, isa_rows, metric_rows = multifile_reference_rows()
    for stem, title, rows in [
        ("table7_multifile_sources", "Positive Multi-File Reference Sources", source_rows),
        ("table8_multifile_isa_reconstruction", "Positive Multi-File ISA Reconstruction", isa_rows),
        ("table9_multifile_quality_metrics", "Positive Multi-File Quality Metrics", metric_rows),
    ]:
        fields = list(rows[0].keys())
        write_csv(TABLE_DIR / f"{stem}.csv", rows, fields)
        write_markdown(TABLE_DIR / f"{stem}.md", title, rows, fields)

    print(f"Wrote manuscript tables to {TABLE_DIR}")


if __name__ == "__main__":
    main()
