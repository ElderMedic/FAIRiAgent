#!/usr/bin/env python3
"""Summarize FAIRiAgent full-pipeline artifacts for manuscript evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ISA_ORDER = ["investigation", "study", "observationunit", "sample", "assay"]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def sheet_rows(sheet: Any) -> list[dict[str, Any]]:
    if isinstance(sheet, dict) and isinstance(sheet.get("rows"), list):
        return sheet["rows"]
    if isinstance(sheet, list):
        return sheet
    return []


def sheet_columns(sheet: Any) -> list[str]:
    if isinstance(sheet, dict) and isinstance(sheet.get("columns"), list):
        return sheet["columns"]
    rows = sheet_rows(sheet)
    if not rows:
        return []
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def non_empty(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def collect_entities(isa_values: dict[str, Any]) -> dict[str, list[str]]:
    identifiers = {
        "observationunit": "observation unit identifier",
        "sample": "sample identifier",
        "assay": "assay identifier",
    }
    entities: dict[str, list[str]] = {}
    for sheet, identifier in identifiers.items():
        values: list[str] = []
        for row in sheet_rows(isa_values.get(sheet)):
            value = row.get(identifier)
            if non_empty(value):
                values.append(str(value))
        entities[sheet] = values
    return entities


def summarize(run_dir: Path) -> dict[str, Any]:
    manifest = read_json(run_dir / "source_workspace" / "source_manifest.json")
    metadata = read_json(run_dir / "metadata.json")
    workflow_report = read_json(run_dir / "workflow_report.json")
    runtime_config = read_json(run_dir / "runtime_config.json")
    isa_values = read_json(run_dir / "isa_values_json.json")

    sources = manifest.get("sources", [])
    source_summary = []
    total_materialized_tables = 0
    total_materialized_table_rows = 0
    for source in sources:
        tables = source.get("tables", []) or []
        total_materialized_tables += len(tables)
        total_materialized_table_rows += sum(int(t.get("rows") or 0) for t in tables)
        source_summary.append(
            {
                "source_id": source.get("source_id"),
                "path": source.get("path"),
                "method": source.get("method"),
                "content_type": source.get("content_type"),
                "source_role": source.get("source_role"),
                "chars": source.get("chars"),
                "tables": tables,
            }
        )

    isa_row_counts = {}
    isa_column_counts = {}
    isa_non_empty_cells = {}
    for sheet in ISA_ORDER:
        rows = sheet_rows(isa_values.get(sheet))
        columns = sheet_columns(isa_values.get(sheet))
        isa_row_counts[sheet] = len(rows)
        isa_column_counts[sheet] = len(columns)
        isa_non_empty_cells[sheet] = sum(
            1 for row in rows for column in columns if non_empty(row.get(column))
        )

    quality = workflow_report.get("quality_metrics", {})
    source_grounding = quality.get("source_grounding", {})
    runtime_info = runtime_config.get("runtime_info", {})
    config = runtime_config.get("config", {})

    return {
        "run_dir": str(run_dir),
        "project_id": runtime_info.get("project_id"),
        "generated_at": metadata.get("generated_at") or workflow_report.get("generated_at"),
        "model": config.get("llm_model"),
        "llm_provider": config.get("llm_provider"),
        "workflow_status": workflow_report.get("workflow_status"),
        "document_source": runtime_info.get("document_path") or metadata.get("document_source"),
        "sources": {
            "count": manifest.get("source_count", len(sources)),
            "items": source_summary,
            "materialized_table_count": total_materialized_tables,
            "materialized_table_rows": total_materialized_table_rows,
        },
        "isa_order": ISA_ORDER,
        "isa_row_counts": isa_row_counts,
        "isa_column_counts": isa_column_counts,
        "isa_non_empty_cells": isa_non_empty_cells,
        "key_entities": collect_entities(isa_values),
        "quality_metrics": {
            "metadata_overall_confidence": quality.get("metadata_overall_confidence")
            or metadata.get("overall_confidence"),
            "needs_review": quality.get("needs_review", metadata.get("needs_review")),
            "total_fields": quality.get("total_fields"),
            "confirmed_fields": quality.get("confirmed_fields"),
            "provisional_fields": quality.get("provisional_fields"),
            "source_grounded_fields": source_grounding.get("source_grounded_fields"),
            "ungrounded_high_confidence_fields": source_grounding.get(
                "ungrounded_high_confidence_fields"
            ),
            "table_backed_fields": source_grounding.get("table_backed_fields"),
        },
        "workflow_execution": workflow_report.get("execution_summary", {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    summary = summarize(args.run_dir.resolve())
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
