"""Tests for local FAIR-DS/ISA output validation."""

from __future__ import annotations

from evaluation.benchmark.output_validation import (
    validate_isa_projection_round_trip,
    validate_output_payload,
)


def _matrix_payload() -> dict:
    return {
        "fairifier_version": "test",
        "generated_at": "2026-07-21T00:00:00",
        "document_source": "fixture",
        "isa_values": {
            "investigation": {
                "columns": ["investigation title"],
                "rows": [["A study"]],
            }
        },
    }


def test_isa_projection_round_trip_is_deterministic() -> None:
    result = validate_isa_projection_round_trip(_matrix_payload())
    assert result["valid"] is True
    assert result["recovered_matrix_id"] == result["recovered_again_matrix_id"]


def test_missing_matrix_fails_round_trip_without_external_service() -> None:
    result = validate_isa_projection_round_trip({"isa_structure": {}})
    assert result["valid"] is False
    assert result["reason"] == "no_isa_matrix_projection"


def test_output_validation_reports_round_trip_as_explicit_gate() -> None:
    result = validate_output_payload(_matrix_payload())
    assert result["isa_round_trip_valid"] is True
    assert "schema" in result
    assert result["critical_errors"] == len(result["schema"].get("errors") or [])
