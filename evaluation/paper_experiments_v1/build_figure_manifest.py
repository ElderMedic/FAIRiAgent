#!/usr/bin/env python3
"""Build a validated manuscript figure manifest from current paper run artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from evaluation.paper_experiments_v1.figure_manifest_lib import (
    ANALYSIS_DIR,
    CONDITION_DISPLAY,
    MAIN_BENCHMARK_DOCS,
    RUNS_DIR,
    VALUES_DIR,
    detect_source_kind,
    include_main_text_cell,
    normalize_model_name,
)
from evaluation.scripts import compare_values_against_gt as compare_mod


# Make scoring deterministic and lightweight for figure generation.
compare_mod._ST_AVAILABLE = False
compare_mod._ST_DISABLED = True


@dataclass
class CellRecord:
    condition: str
    document: str
    model_key: str
    config_name: str
    run_dir: str
    metadata_path: str | None
    eval_result_path: str | None
    has_metadata: bool
    has_eval_result: bool
    success: bool | None
    source_kind: str
    included_main_text: bool
    exclusion_reason: str | None
    metric_row_mean_score: float | None
    metric_field_coverage: float | None
    metric_match_rate: float | None


def gt_path_for_doc(document: str) -> Path:
    return VALUES_DIR / f"ground_truth_{document}_values.json"


def compute_run_metrics(document: str, run_dir: Path) -> tuple[float, float, float, list[dict]]:
    """Compute row-aligned token-based sheet metrics for one run dir."""
    gt_sheets = compare_mod.load_gt_sheets(gt_path_for_doc(document))
    pred_sheets = compare_mod.load_run_sheets(run_dir)

    per_sheet_rows: list[dict] = []
    weighted_score = 0.0
    weighted_coverage = 0.0
    total_fields = 0
    total_match = 0

    for sheet_name, gt_rows in gt_sheets.items():
        pred_rows = pred_sheets.get(sheet_name, [])
        result = compare_mod.evaluate_sheet(sheet_name, gt_rows, pred_rows)
        fields = result["total_fields"]
        total_fields += fields
        weighted_score += result["mean_score"] * fields
        weighted_coverage += result["field_coverage"] * fields
        total_match += result["match_count"]
        per_sheet_rows.append(
            {
                "document": document,
                "sheet": sheet_name,
                "metric_row_mean_score": result["mean_score"],
                "metric_field_coverage": result["field_coverage"],
                "gt_rows": result["gt_rows"],
                "pred_rows": result["pred_rows"],
                "total_fields": fields,
                "match_count": result["match_count"],
                "partial_count": result["partial_count"],
                "miss_count": result["miss_count"],
            }
        )

    if total_fields == 0:
        return 0.0, 0.0, 0.0, per_sheet_rows

    return (
        round(weighted_score / total_fields, 4),
        round(weighted_coverage / total_fields, 4),
        round(total_match / total_fields, 4),
        per_sheet_rows,
    )


def build_manifest() -> dict:
    cells: list[dict] = []
    per_sheet_rows: list[dict] = []
    for eval_result_path in sorted(RUNS_DIR.glob("*/*/*/run_*/eval_result.json")):
        run_dir = eval_result_path.parent
        parts = run_dir.relative_to(RUNS_DIR).parts
        if len(parts) < 4:
            continue

        condition, config_name, document, _run_name = parts[:4]
        if condition not in CONDITION_DISPLAY or document not in MAIN_BENCHMARK_DOCS:
            continue

        metadata_path = run_dir / "metadata.json"
        has_metadata = metadata_path.exists()
        has_eval_result = True
        success = None
        try:
            success = json.loads(eval_result_path.read_text(encoding="utf-8")).get("success")
        except json.JSONDecodeError:
            success = None

        model_key = normalize_model_name(config_name)
        source_kind = detect_source_kind(condition, document)
        base = {
            "condition": condition,
            "document": document,
            "model_key": model_key,
            "config_name": config_name,
            "run_dir": str(run_dir),
            "metadata_path": str(metadata_path) if has_metadata else None,
            "eval_result_path": str(eval_result_path),
            "has_metadata": has_metadata,
            "has_eval_result": has_eval_result,
            "success": success,
            "source_kind": source_kind,
        }
        included_main_text = include_main_text_cell(base)

        exclusion_reason = None
        if not included_main_text:
            if source_kind != "phase0_run":
                exclusion_reason = source_kind
            elif not has_metadata:
                exclusion_reason = "missing_metadata"
            elif success is not True:
                exclusion_reason = "run_not_successful"
            else:
                exclusion_reason = "excluded_by_scope_rules"

        metric_row_mean_score = None
        metric_field_coverage = None
        metric_match_rate = None
        if has_metadata:
            metric_row_mean_score, metric_field_coverage, metric_match_rate, sheet_metrics = compute_run_metrics(
                document, run_dir
            )
            for row in sheet_metrics:
                row["condition"] = condition
                row["model_key"] = model_key
                row["config_name"] = config_name
                row["included_main_text"] = included_main_text
                per_sheet_rows.append(row)

        cells.append(
            asdict(
                CellRecord(
                    **base,
                    included_main_text=included_main_text,
                    exclusion_reason=exclusion_reason,
                    metric_row_mean_score=metric_row_mean_score,
                    metric_field_coverage=metric_field_coverage,
                    metric_match_rate=metric_match_rate,
                )
            )
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_scope": sorted(MAIN_BENCHMARK_DOCS),
        "conditions": [CONDITION_DISPLAY[c] for c in CONDITION_DISPLAY],
        "selection_rule": "Scans actual eval_result.json artifacts under runs/ and includes only successful main-benchmark runs with metadata for manuscript main-text quantitative figures.",
        "metric_definition": {
            "metric_row_mean_score": "Weighted mean row-aligned token score from compare_values_against_gt.py with semantic similarity disabled.",
            "metric_field_coverage": "Weighted fraction of GT fields whose field names are present after row alignment.",
            "metric_match_rate": "Exact match-count divided by total GT fields after row alignment.",
        },
        "cells": cells,
        "per_sheet_rows": per_sheet_rows,
    }


def main() -> None:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    out_path = ANALYSIS_DIR / "figure_manifest_phase0.json"
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[OK] wrote {out_path}")
    print(f"[OK] cells={len(manifest['cells'])} per_sheet_rows={len(manifest['per_sheet_rows'])}")


if __name__ == "__main__":
    main()
