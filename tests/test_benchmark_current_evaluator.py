"""Single-run bridge tests; no model or external service is used."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.benchmark.current_evaluator import evaluate_current_run
from evaluation.benchmark.scorer import score_run


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
