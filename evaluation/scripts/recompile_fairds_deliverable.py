#!/usr/bin/env python3
"""Deterministically recompile a completed FAIRiAgent FAIR-DS deliverable.

This utility is intentionally source-agnostic.  It re-applies the persisted
FAIR-DS field contracts and the run's authoritative entity plan, validates the
result, renders a staged workbook, and only then replaces the three deliverable
artifacts.  It is useful when compiler logic is fixed after a costly LLM run:
no extraction or semantic inference is repeated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
from fairifier.graph.excel import try_export_fairds_metadata_excel
from fairifier.utils.entity_plan import (
    enrich_contacts_from_source_text,
    project_matrix_onto_entity_plan,
    validate_entity_matrix_against_plan,
)
from fairifier.utils.fairds_value_contracts import build_contract_index
from fairifier.utils.isa_matrix_projection import apply_matrix_to_metadata
from fairifier.utils.isa_matrix_compiler import compile_isa_matrix


def _load_object(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def recompile_run(run_dir: Path, *, apply: bool = False) -> Dict[str, Any]:
    run_dir = run_dir.resolve()
    deliverables = run_dir / "deliverables"
    reports = run_dir / "reports"
    metadata_path = deliverables / "metadata.json"
    matrix_path = deliverables / "isa_values.json"
    workbook_path = deliverables / "metadata_fairds.xlsx"
    plan_path = reports / "entity_plan.json"
    for required in (metadata_path, matrix_path, plan_path):
        if not required.is_file():
            raise FileNotFoundError(required)

    metadata = _load_object(metadata_path)
    matrix = _load_object(matrix_path)
    plan_document = _load_object(plan_path)
    plan = deepcopy(plan_document.get("plan") or {})
    if not plan:
        raise ValueError(f"No authoritative entity plan in {plan_path}")
    contracts = build_contract_index(metadata.get("_field_definitions") or [])
    if not contracts:
        raise ValueError("No persisted FAIR-DS value contracts are available")

    source_text_path = run_dir / "workspace" / "extracted_document_content.txt"
    if not source_text_path.is_file():
        source_text_path = run_dir / "extracted_document_content.txt"
    if source_text_path.is_file():
        plan["investigation_contacts"] = enrich_contacts_from_source_text(
            plan.get("investigation_contacts") or [],
            source_text_path.read_text(encoding="utf-8", errors="replace"),
        )
        matrix = project_matrix_onto_entity_plan(matrix, plan)

    compiler = ISAValueMapperAgent.__new__(ISAValueMapperAgent)
    matrix, identifier_issues = compiler._canonicalize_structural_identifiers(
        matrix, plan, contracts
    )
    matrix, mapping_issues = compiler._demote_invalid_plan_attribute_mappings(
        matrix, plan, contracts
    )
    matrix, contract_issues = compiler._enforce_fairds_value_contracts(
        matrix, contracts
    )
    compiled = compile_isa_matrix(matrix)
    matrix = compiled["matrix"]
    validation = validate_entity_matrix_against_plan(
        matrix,
        plan,
        expected_authors=(metadata.get("document_info") or {}).get("authors") or [],
    )
    if not validation.get("passed"):
        raise ValueError(
            "Deterministic recompilation failed entity-plan validation: "
            + "; ".join(validation.get("errors") or [])
        )

    updated_metadata = apply_matrix_to_metadata(
        metadata, matrix, matrix_id=compiled["matrix_id"]
    )
    updated_plan_document = {
        **plan_document,
        "plan": plan,
        "validation": validation,
    }
    original_hashes = {
        path.name: _sha256(path)
        for path in (metadata_path, matrix_path, workbook_path)
        if path.is_file()
    }
    issues = identifier_issues + mapping_issues + contract_issues

    with tempfile.TemporaryDirectory(prefix="fairiagent-recompile-") as temp_name:
        staging = Path(temp_name) / "run"
        staged_deliverables = staging / "deliverables"
        _write_json(staged_deliverables / "metadata.json", updated_metadata)
        _write_json(staged_deliverables / "isa_values.json", matrix)
        _write_json(staging / "reports" / "entity_plan.json", updated_plan_document)
        rendered = try_export_fairds_metadata_excel(staging, fair_ds_api_url="")
        if rendered is None or not rendered.is_file():
            raise RuntimeError("Staged FAIR-DS workbook export failed")

        staged_paths = {
            metadata_path: staged_deliverables / "metadata.json",
            matrix_path: staged_deliverables / "isa_values.json",
            workbook_path: rendered,
            plan_path: staging / "reports" / "entity_plan.json",
        }
        staged_hashes = {
            target.name: _sha256(source) for target, source in staged_paths.items()
        }
        if apply:
            for target, source in staged_paths.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary_target = target.with_name(f".{target.name}.recompile.tmp")
                shutil.copy2(source, temporary_target)
                os.replace(temporary_target, target)

    report = {
        "schema_version": "fairiagent.deterministic_recompile.v1",
        "run_dir": str(run_dir),
        "applied": apply,
        "matrix_id": compiled["matrix_id"],
        "row_counts": validation.get("row_counts", {}),
        "entity_plan_validation": validation,
        "compiler_issues": issues,
        "original_sha256": original_hashes,
        "result_sha256": staged_hashes,
    }
    if apply:
        _write_json(reports / "deterministic_recompile.json", report)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Atomically replace the validated JSON and workbook artifacts.",
    )
    args = parser.parse_args(argv)
    report = recompile_run(args.run_dir, apply=args.apply)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
