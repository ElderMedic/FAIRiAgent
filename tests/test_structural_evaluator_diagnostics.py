"""Tests for Layer 3 structural evaluator diagnostics."""

import json
from pathlib import Path

from evaluation.evaluators.structural_evaluator import StructuralEvaluator


def test_row_alignment_includes_diagnostics_and_fragmentation_hint():
    evaluator = StructuralEvaluator()
    gt_rows = [
        {"sample identifier": "S1", "reaction temperature": "30 °C", "reaction ph": "8"},
        {"sample identifier": "S2", "reaction temperature": "40 °C", "reaction ph": "7"},
    ]
    pred_rows = [
        {"sample identifier": "S1", "reaction temperature": "30 °C", "reaction ph": ""},
        {"sample identifier": "", "reaction temperature": "", "reaction ph": "8"},
        {"sample identifier": "S2", "reaction temperature": "40 °C", "reaction ph": "7"},
        {"sample identifier": "", "reaction temperature": "noise", "reaction ph": ""},
    ]
    result = evaluator.evaluate_row_alignment("sample", gt_rows, pred_rows)
    assert "diagnostics" in result
    assert result["row_count_ratio"] == 2.0
    assert result["diagnostics"]["fragmentation_hint"] == "over_fragmentation"
    assert result["diagnostics"]["avg_fields_per_gt_row"] == 3.0
    assert len(result["diagnostics"]["unmatched_pred_rows"]) >= 1


def test_value_accuracy_splits_missing_and_wrong():
    evaluator = StructuralEvaluator()
    pairs = [
        (
            {"reaction temperature": "30 °C", "reaction ph": "8.0", "enzyme name": "PETase"},
            {"reaction temperature": "99 °C", "reaction ph": "", "enzyme name": "PETase"},
        )
    ]
    detail = evaluator._value_accuracy_within_pairs(pairs)
    assert detail["n_fields"] == 3
    assert detail["missing_field_rate"] > 0
    assert detail["wrong_value_rate"] > 0


def test_petase_run_structural_diagnostics_smoke():
    run_dir = Path(
        "evaluation/runs/shadow_gate_20260703/workflow_phase4_hybrid_on/"
        "deepseek_v4-flash_v1.4.0_fairds8090_localpkg_phase4/"
        "petase_10_1038_s41586-020-2149-4/run_1"
    )
    gt_path = Path(
        "evaluation/datasets/annotated/values/"
        "ground_truth_petase_10_1038_s41586-020-2149-4_values.json"
    )
    if not run_dir.exists() or not gt_path.exists():
        return

    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    gt_doc = json.loads(gt_path.read_text(encoding="utf-8"))
    result = StructuralEvaluator().evaluate(metadata, gt_doc)
    summary = result["summary_metrics"]
    assert "row_count_ratio" in summary
    assert "missing_field_rate_given_correct_structure" in summary
    sample = result["row_alignment_by_sheet"].get("sample", {})
    assert "diagnostics" in sample
    assert sample["diagnostics"]["fragmentation_hint"] == "over_fragmentation"
