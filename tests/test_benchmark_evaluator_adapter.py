"""Tests for mapping existing Layer 1--4 records to benchmark v2."""

from __future__ import annotations

import pytest

from evaluation.benchmark.evaluator_adapter import (
    EvaluatorAdapterError,
    adapt_evaluator_batch_record,
    adapt_evaluator_record,
)
from evaluation.benchmark.scorer import score_run


RUN_SPEC = {
    "run_id": "doc__condition__model__r01",
    "instance_id": "doc",
    "condition_id": "condition",
    "model_id": "model",
    "repetition": 1,
}

CHECKS = {
    "exists": True,
    "parseable": True,
}
VALIDATION = {
    "fairds_valid": True,
    "isa_round_trip_valid": True,
    "critical_errors": 0,
}


def _record() -> dict:
    return {
        "correctness": {"summary_metrics": {"field_coverage_recall": 0.91}},
        "value_accuracy": {"summary_metrics": {"value_partial_credit_score": 0.88}},
        "structural": {
            "summary_metrics": {
                "sheet_placement_accuracy": 0.90,
                "row_alignment_f1": 0.80,
            }
        },
        "schema_validation": {"schema_compliance_rate": 1.0},
    }


def test_adapts_all_axes_and_passes_standard_gate() -> None:
    result = adapt_evaluator_record(
        RUN_SPEC,
        _record(),
        artifact=CHECKS,
        validation=VALIDATION,
    )

    assert result["axes"] == {
        "information_coverage": pytest.approx(0.91),
        "value_accuracy": pytest.approx(0.88),
        "structural_fidelity": pytest.approx(0.85),
        "interoperability": pytest.approx(1.0),
    }
    assert score_run(result)["success"] is True


def test_missing_value_and_structure_metrics_fail_closed() -> None:
    result = adapt_evaluator_record(
        RUN_SPEC,
        {"correctness": {"summary_metrics": {"field_coverage_recall": 0.95}}},
        artifact=CHECKS,
        validation=VALIDATION,
    )

    assert result["axes"]["value_accuracy"] == 0.0
    assert result["failure"]["missing_metrics"] == [
        "value_accuracy",
        "structural_fidelity",
        "interoperability",
    ]
    assert score_run(result)["success"] is False


def test_batch_record_requires_per_document_evidence() -> None:
    batch = {"correctness": {"aggregated": {"mean_field_coverage_recall": 0.99}}}
    with pytest.raises(EvaluatorAdapterError, match="No per-document"):
        adapt_evaluator_batch_record(
            RUN_SPEC,
            batch,
            "doc",
            artifact=CHECKS,
            validation=VALIDATION,
        )


def test_batch_record_extracts_only_requested_document() -> None:
    batch = {
        name: {"per_document": {"doc": section, "other": {}}}
        for name, section in _record().items()
    }
    result = adapt_evaluator_batch_record(
        RUN_SPEC,
        batch,
        "doc",
        artifact=CHECKS,
        validation=VALIDATION,
    )
    assert result["instance_id"] == "doc"
    assert result["axes"]["value_accuracy"] == pytest.approx(0.88)


def test_aggregate_document_record_is_rejected() -> None:
    with pytest.raises(EvaluatorAdapterError, match="document-level"):
        adapt_evaluator_record(
            RUN_SPEC,
            {"per_document": {}},
            artifact=CHECKS,
            validation=VALIDATION,
        )


def test_cell_coverage_never_substitutes_for_missing_field_recall() -> None:
    record = _record()
    record["correctness"]["summary_metrics"] = {
        "field_coverage_recall": 0.0,
        "total_ground_truth_fields": 0,
    }
    record["value_accuracy"]["summary_metrics"].update(
        {"n_gt_populated_fields": 10, "missing_count": 1}
    )

    result = adapt_evaluator_record(
        RUN_SPEC, record, artifact=CHECKS, validation=VALIDATION
    )

    assert result["axes"]["information_coverage"] == 0.0
    assert "information_coverage" in result["failure"]["missing_metrics"]
    coverage = result["provenance"]["coverage_diagnostics"]
    assert coverage["aligned_cell_coverage"] == pytest.approx(0.9)
    assert coverage["n_gt_populated_cells"] == 10
    assert coverage["nonmissing_gt_cells"] == 9
    assert score_run(result)["success"] is False


def test_field_recall_remains_independent_of_cell_repetition_and_missingness() -> None:
    record = _record()
    record["correctness"]["summary_metrics"].update(
        {"total_ground_truth_fields": 100, "present_fields": 91}
    )
    record["value_accuracy"]["summary_metrics"].update(
        {"n_gt_populated_fields": 1000, "missing_count": 999}
    )

    result = adapt_evaluator_record(
        RUN_SPEC, record, artifact=CHECKS, validation=VALIDATION
    )

    assert result["axes"]["information_coverage"] == pytest.approx(0.91)
    coverage = result["provenance"]["coverage_diagnostics"]
    assert coverage["field_coverage_recall"] == pytest.approx(0.91)
    assert coverage["total_ground_truth_fields"] == 100
    assert coverage["aligned_cell_coverage"] == pytest.approx(0.001)
