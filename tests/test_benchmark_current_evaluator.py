"""Single-run bridge tests; no model or external service is used."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.benchmark.current_evaluator import evaluate_current_run
from evaluation.benchmark.scorer import score_run
from evaluation.evaluators import _value_matching as value_matching
from evaluation.evaluators.correctness_evaluator import CorrectnessEvaluator


RUN_SPEC = {
    "run_id": "doc__condition__model__r01",
    "instance_id": "doc",
    "condition_id": "condition",
    "model_id": "model",
    "repetition": 1,
}
VALIDATION = {
    "fairds_valid": True,
    "isa_round_trip_valid": True,
    "critical_errors": 0,
}


def test_current_evaluator_preserves_single_run_identity(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_1"
    run_dir.mkdir()
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "isa_structure": {
                    "investigation": {
                        "fields": [
                            {
                                "field_name": "investigation title",
                                "value": "A study",
                                "evidence": "",
                            }
                        ]
                    }
                }
            }
        )
    )
    result = evaluate_current_run(
        RUN_SPEC,
        run_dir,
        {
            "document_id": "doc",
            "ground_truth_fields": [{"field_name": "investigation title"}],
        },
        validation=VALIDATION,
    )

    assert result["run_id"] == RUN_SPEC["run_id"]
    assert result["artifact"]["parseable"] is True
    assert result["axes"]["information_coverage"] == 1.0
    assert result["provenance"]["evaluator_adapter"] == "layer1_4_to_result_envelope_v2"
    # Layer 2/3 values-GT was intentionally absent, so the hard-gated score
    # must not silently drop those dimensions.
    assert score_run(result)["success"] is False


def test_missing_artifact_is_recorded_as_failed_run(tmp_path: Path) -> None:
    result = evaluate_current_run(
        RUN_SPEC,
        tmp_path / "missing",
        {"document_id": "doc", "ground_truth_fields": []},
        validation={
            "fairds_valid": False,
            "isa_round_trip_valid": False,
            "critical_errors": 0,
        },
    )
    assert result["artifact"]["exists"] is False
    assert result["artifact"]["parseable"] is False
    assert result["status"] == "failed"
    assert score_run(result)["success"] is False


def _values_first_reference() -> dict:
    return {
        "isa_sheets": {
            "sample": {
                "expected_rows": [{"sample name": "alpha"}, {"sample name": "beta"}]
            },
            "assay": {
                "expected_rows": [
                    {"reaction temperature": "30", "measurement value": "1"},
                    {"reaction temperature": "40", "measurement value": "2"},
                ]
            },
        }
    }


def _partially_populated_matrix() -> dict:
    return {
        "isa_values": {
            "sample": {"columns": ["sample name"], "rows": [["alpha"]]},
            "assay": {
                "columns": ["reaction temperature", "measurement value"],
                "rows": [["30", ""]],
            },
        }
    }


def test_values_first_gt_keeps_field_recall_separate_from_cell_coverage(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(value_matching, "_ST_DISABLED", True)
    (tmp_path / "metadata.json").write_text(json.dumps(_partially_populated_matrix()))

    result = evaluate_current_run(
        RUN_SPEC,
        tmp_path,
        {"document_id": "doc", "ground_truth_fields": []},
        ground_truth_values_doc=_values_first_reference(),
        validation=VALIDATION,
    )

    # Every expected field exists as a column, but four of six GT cells are
    # missing after row alignment. Those are separate completeness questions.
    assert result["axes"]["information_coverage"] == 1.0
    coverage = result["provenance"]["coverage_diagnostics"]
    assert coverage["reference_source"] == "isa_sheets.expected_rows"
    assert coverage["total_ground_truth_fields"] == 3
    assert coverage["present_fields"] == 3
    assert coverage["field_level_recall"] == 1.0
    assert coverage["populated_field_level_recall"] == pytest.approx(2 / 3)
    assert coverage["total_ground_truth_field_level_pairs"] == 3
    assert coverage["n_gt_populated_cells"] == 6
    assert coverage["nonmissing_gt_cells"] == 2
    assert coverage["aligned_cell_coverage"] == pytest.approx(1 / 3)


def test_field_recall_does_not_hide_wrong_isosa_placement() -> None:
    output = _partially_populated_matrix()
    output["isa_values"]["sample"]["columns"].append("reaction temperature")
    output["isa_values"]["sample"]["rows"][0].append("30")
    output["isa_values"]["assay"] = {
        "columns": ["measurement value"],
        "rows": [[""]],
    }
    metrics = CorrectnessEvaluator().evaluate(
        output,
        {"ground_truth_fields": []},
        ground_truth_values_doc=_values_first_reference(),
    )["summary_metrics"]

    assert metrics["field_coverage_recall"] == 1.0
    assert metrics["field_level_recall"] == pytest.approx(2 / 3)
    assert metrics["populated_field_level_recall"] == pytest.approx(1 / 3)
    assert metrics["present_field_level_pairs"] == 2
    assert metrics["populated_field_level_pairs"] == 1


def test_repeated_rows_do_not_change_field_or_placement_denominators() -> None:
    reference = _values_first_reference()
    reference["isa_sheets"]["assay"]["expected_rows"] *= 8
    output = _partially_populated_matrix()
    output["isa_values"]["sample"]["rows"] *= 10
    metrics = CorrectnessEvaluator().evaluate(
        output, {"ground_truth_fields": []}, ground_truth_values_doc=reference
    )["summary_metrics"]

    assert metrics["total_ground_truth_fields"] == 3
    assert metrics["total_ground_truth_field_level_pairs"] == 3
    assert metrics["field_coverage_recall"] == 1.0
    assert metrics["gt_field_populated_rate"] == pytest.approx(2 / 3)


def test_explicit_field_reference_keeps_its_scope_with_values_gt() -> None:
    metrics = CorrectnessEvaluator().evaluate(
        _partially_populated_matrix(),
        {"ground_truth_fields": [{"field_name": "sample name"}]},
        ground_truth_values_doc=_values_first_reference(),
    )["summary_metrics"]

    assert metrics["reference_source"] == "ground_truth_fields"
    assert metrics["total_ground_truth_fields"] == 1
    assert metrics["field_coverage_recall"] == 1.0
    assert metrics["total_ground_truth_field_level_pairs"] == 1


def test_final_matrix_values_override_stale_field_examples_and_preserve_zero() -> None:
    output = {
        "isa_structure": {
            "assay": {
                "fields": [
                    {"field_name": "measurement value", "value": "stale example"},
                    {"field_name": "reaction temperature", "value": ""},
                ]
            }
        },
        "isa_values": {
            "assay": {
                "columns": ["measurement value", "reaction temperature"],
                "rows": [["", 0]],
            }
        },
    }
    reference = {
        "isa_sheets": {
            "assay": {
                "expected_rows": [
                    {"measurement value": "1", "reaction temperature": 0}
                ]
            }
        }
    }
    result = CorrectnessEvaluator().evaluate(
        output, {"ground_truth_fields": []}, ground_truth_values_doc=reference
    )

    assert result["summary_metrics"]["field_coverage_recall"] == 1.0
    assert result["summary_metrics"]["gt_field_populated_rate"] == 0.5
    assert result["summary_metrics"]["populated_field_level_pairs"] == 1
    assert result["field_level_results"]["measurement value"]["has_value"] is False
    assert result["field_level_results"]["reaction temperature"]["has_value"] is True


def test_field_only_reference_does_not_claim_unmeasured_isosa_recall() -> None:
    metrics = CorrectnessEvaluator().evaluate(
        {"isa_structure": {"sample": {"fields": [{"field_name": "sample name"}]}}},
        {"ground_truth_fields": [{"field_name": "sample name"}]},
    )["summary_metrics"]

    assert metrics["field_coverage_recall"] == 1.0
    assert metrics["total_ground_truth_field_level_pairs"] == 0
    assert metrics["field_level_recall"] is None
    assert metrics["populated_field_level_recall"] is None
