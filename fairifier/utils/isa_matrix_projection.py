"""Project one compiled ISA matrix onto metadata + sidecar artifacts.

Keeps a single ``matrix_id`` across ``metadata.json.isa_values`` and
``isa_values_json.json`` so Excel/eval do not diverge.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, Optional

from fairifier.utils.isa_matrix_compiler import compile_isa_matrix, matrix_id_for
from fairifier.utils.isa_order import ISA_LEVEL_ORDER


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def extract_matrix_from_metadata(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Prefer top-level isa_values matrix; fall back to isa_structure columns/rows."""
    isa_values = payload.get("isa_values")
    if isinstance(isa_values, dict) and isa_values:
        return {
            sheet: {
                "columns": list((block or {}).get("columns") or []),
                "rows": list((block or {}).get("rows") or []),
            }
            for sheet, block in isa_values.items()
            if isinstance(block, dict) and ("columns" in block or "rows" in block)
        }
    isa_structure = payload.get("isa_structure") or {}
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(isa_structure, dict):
        for sheet, block in isa_structure.items():
            if isinstance(block, dict) and ("columns" in block or "rows" in block):
                out[sheet] = {
                    "columns": list(block.get("columns") or []),
                    "rows": list(block.get("rows") or []),
                }
    return out


def apply_matrix_to_metadata(
    payload: Dict[str, Any],
    matrix: Dict[str, Dict[str, Any]],
    *,
    matrix_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the same compiled matrix into isa_values and isa_structure projections."""
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    mid = matrix_id or matrix_id_for(matrix)
    isa_values: Dict[str, Any] = {}
    isa_structure = updated.get("isa_structure")
    if not isinstance(isa_structure, dict):
        isa_structure = {}

    for sheet in ISA_LEVEL_ORDER:
        block = matrix.get(sheet) or {"columns": [], "rows": []}
        columns = list(block.get("columns") or [])
        rows = list(block.get("rows") or [])
        isa_values[sheet] = {"columns": columns, "rows": rows}
        sheet_payload = isa_structure.get(sheet)
        if not isinstance(sheet_payload, dict):
            sheet_payload = {"description": "", "fields": []}
        sheet_payload["columns"] = columns
        sheet_payload["rows"] = rows
        isa_structure[sheet] = sheet_payload

    for sheet, block in matrix.items():
        if sheet in isa_values or not isinstance(block, dict):
            continue
        isa_values[sheet] = {
            "columns": list(block.get("columns") or []),
            "rows": list(block.get("rows") or []),
        }

    updated["isa_values"] = isa_values
    updated["isa_structure"] = isa_structure
    updated["isa_matrix_id"] = mid
    return updated


def sync_compiled_matrix_to_state(
    state: Dict[str, Any],
    matrix: Dict[str, Dict[str, Any]],
    *,
    recompile: bool = True,
    compiler_tag: str = "projection",
) -> Dict[str, Any]:
    """Compile (optional) and project one matrix into metadata + sidecar artifacts."""
    if recompile:
        compiled = compile_isa_matrix(matrix)
        matrix = compiled["matrix"]
        matrix_id = compiled["matrix_id"]
    else:
        matrix_id = matrix_id_for(matrix)

    artifacts = state.setdefault("artifacts", {})
    matrix_str = json.dumps(matrix, indent=2, ensure_ascii=False)
    artifacts["isa_values"] = matrix_str
    artifacts["isa_values_json"] = matrix_str
    artifacts["isa_matrix_id"] = matrix_id


    metadata_json = artifacts.get("metadata_json")
    if metadata_json:
        try:
            payload = _parse_jsonish(metadata_json)
            if isinstance(payload, dict):
                updated = apply_matrix_to_metadata(payload, matrix, matrix_id=matrix_id)
                artifacts["metadata_json"] = json.dumps(updated, indent=2, ensure_ascii=False)
        except (TypeError, json.JSONDecodeError, ValueError):
            pass

    context = state.setdefault("context", {})
    context["isa_matrix_id"] = matrix_id
    context["isa_matrix_compiler"] = compiler_tag
    return {"matrix": matrix, "matrix_id": matrix_id}
