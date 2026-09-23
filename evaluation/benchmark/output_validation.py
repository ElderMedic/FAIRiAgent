"""Deterministic output validation used before benchmark scoring.

The FAIR-DS service is not contacted here.  The local package and ISA matrix
compiler are the declared FAIR-DS-compatible implementation for this release;
the round-trip check verifies that a matrix survives the same canonical
projection used by metadata, sidecar, and Excel producers.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from fairifier.utils.isa_matrix_compiler import compile_isa_matrix, matrix_id_for
from fairifier.utils.isa_matrix_projection import (
    apply_matrix_to_metadata,
    extract_matrix_from_metadata,
)
from fairifier.validation.metadata_json_format import check_metadata_json_output


def validate_isa_projection_round_trip(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Check deterministic ISA matrix -> projection -> matrix preservation."""

    matrix = extract_matrix_from_metadata(dict(payload))
    if not matrix:
        return {
            "valid": False,
            "reason": "no_isa_matrix_projection",
            "matrix_id": None,
        }
    try:
        compiled = compile_isa_matrix(matrix)
        projected = apply_matrix_to_metadata(
            {}, compiled["matrix"], matrix_id=compiled["matrix_id"]
        )
        recovered = extract_matrix_from_metadata(projected)
        # ``apply_matrix_to_metadata`` materializes empty ISA levels as well;
        # compare every input level explicitly, then check that the expanded
        # projection is stable when projected a second time.
        source_preserved = all(
            recovered.get(sheet, {"columns": [], "rows": []}) == block
            for sheet, block in compiled["matrix"].items()
        )
        second_projection = apply_matrix_to_metadata(
            {}, recovered, matrix_id=matrix_id_for(recovered)
        )
        recovered_again = extract_matrix_from_metadata(second_projection)
        recovered_id = matrix_id_for(recovered)
        recovered_again_id = matrix_id_for(recovered_again)
    except (TypeError, ValueError, KeyError) as exc:
        return {"valid": False, "reason": "round_trip_error:%s" % exc, "matrix_id": None}
    valid = source_preserved and recovered_id == recovered_again_id
    return {
        "valid": valid,
        "reason": None if valid else ("matrix_id_changed" if source_preserved else "matrix_content_changed"),
        "matrix_id": compiled["matrix_id"],
        "recovered_matrix_id": recovered_id,
        "recovered_again_matrix_id": recovered_again_id,
    }


def validate_output_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Return explicit FAIR-DS and ISA validation outcomes for one payload."""

    data = dict(payload)
    try:
        schema = check_metadata_json_output(data)
    except (AttributeError, TypeError, ValueError) as exc:
        schema = {
            "is_valid": False,
            "schema_compliance_rate": 0.0,
            "errors": ["schema_validation_error:%s" % exc],
            "warnings": [],
        }
    round_trip = validate_isa_projection_round_trip(data)
    errors = list(schema.get("errors") or [])
    if not round_trip["valid"]:
        errors.append("ISA projection round trip failed: %s" % round_trip["reason"])
    return {
        "fairds_valid": bool(schema.get("is_valid")),
        "isa_round_trip_valid": bool(round_trip["valid"]),
        "critical_errors": len(errors),
        "warnings": len(schema.get("warnings") or []),
        "schema": schema,
        "isa_round_trip": round_trip,
    }
