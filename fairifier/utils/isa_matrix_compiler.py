"""Single ISA matrix compiler projection (§12.1).

Producers (JSONGenerator, ISAValueMapper, AutoRepair) must route entity-matrix
post-processing through ``compile_isa_matrix`` so metadata JSON, ISA sidecar,
Excel, and evaluation share one deterministic ``matrix_id``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from fairifier.utils.entity_merge import postprocess_entity_matrix


def _canonical_matrix_payload(matrix: Dict[str, Dict[str, Any]]) -> Any:
    """Deterministic JSON-ready structure for digesting a compiled matrix."""
    sheets = sorted(matrix.keys())
    payload: Dict[str, Any] = {}
    for sheet in sheets:
        sheet_data = matrix.get(sheet) or {}
        columns = list(sheet_data.get("columns") or [])
        rows_in = list(sheet_data.get("rows") or [])
        ordered_rows = []
        for row in rows_in:
            if not isinstance(row, dict):
                continue
            # Preserve column order first, then any residual keys sorted.
            ordered: Dict[str, Any] = {}
            for col in columns:
                ordered[col] = row.get(col, "")
            for key in sorted(k for k in row.keys() if k not in ordered):
                ordered[key] = row.get(key, "")
            ordered_rows.append(ordered)
        payload[sheet] = {"columns": columns, "rows": ordered_rows}
    return payload


def matrix_id_for(matrix: Dict[str, Dict[str, Any]]) -> str:
    """SHA-256 over deterministic JSON of the compiled matrix."""
    payload = _canonical_matrix_payload(matrix)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compile_isa_matrix(
    matrix: Dict[str, Dict[str, Any]],
    *,
    min_merge_score: float = 0.35,
    sparse_field_threshold: int = 3,
) -> Dict[str, Any]:
    """Compile an ISA entity matrix and return ``{matrix, matrix_id}``.

    Currently applies the shared entity post-process (exact-identifier collapse).
    Sparse identifier-less merges are intentionally disabled in entity_merge
    per §12.1 identity rules.
    """
    compiled = postprocess_entity_matrix(
        matrix,
        min_merge_score=min_merge_score,
        sparse_field_threshold=sparse_field_threshold,
    )
    return {
        "matrix": compiled,
        "matrix_id": matrix_id_for(compiled),
    }
