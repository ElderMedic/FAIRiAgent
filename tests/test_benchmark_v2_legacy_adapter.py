"""Tests for conservative migration of historical per-run records."""

from __future__ import annotations

from evaluation.benchmark.legacy_adapter import adapt_legacy_run
from evaluation.benchmark.scorer import score_run


RUN_SPEC = {
    "run_id": "doc__condition__model__r01",
    "instance_id": "doc",
    "condition_id": "condition",
    "model_id": "model",
    "repetition": 1,
}


def test_legacy_success_without_validation_does_not_pass_v2_gate() -> None:
    result = adapt_legacy_run(
        {"success": True, "n_fields_extracted": 100, "runtime_seconds": 10.0},
        RUN_SPEC,
        layer_metrics={
            "field_coverage_recall": 0.95,
            "value_partial_credit_score": 0.95,
            "sheet_placement_accuracy": 0.95,
            "row_alignment_f1": 0.95,
            "schema_compliance": 1.0,
        },
    )

    scored = score_run(result)
    assert scored["success"] is False
    assert "artifact_missing" in scored["failure_reasons"]
    assert "fairds_validation_failed" in scored["failure_reasons"]


def test_legacy_result_can_pass_after_explicit_checks_are_supplied() -> None:
    result = adapt_legacy_run(
        {"success": True, "runtime_seconds": 10.0},
        RUN_SPEC,
        layer_metrics={
            "field_coverage_recall": 0.95,
            "value_partial_credit_score": 0.95,
            "sheet_placement_accuracy": 0.95,
            "row_alignment_f1": 0.95,
            "schema_compliance": 1.0,
        },
        artifact={"exists": True, "parseable": True},
        validation={
            "fairds_valid": True,
            "isa_round_trip_valid": True,
            "critical_errors": 0,
        },
    )

    assert score_run(result)["success"] is True
