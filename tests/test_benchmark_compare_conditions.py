"""CLI-free tests for paired score-file comparison."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.benchmark.compare_conditions import compare_score_files


def test_compare_score_files_uses_canonical_standard_runs(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    treatment = tmp_path / "treatment.json"
    baseline.write_text(
        json.dumps(
            {
                "standard_runs": [
                    {
                        "instance_id": "doc",
                        "model_id": "model",
                        "repetition": 1,
                        "axes": {"value_accuracy": 0.5},
                    }
                ]
            }
        )
    )
    treatment.write_text(
        json.dumps(
            {
                "standard_runs": [
                    {
                        "instance_id": "doc",
                        "model_id": "model",
                        "repetition": 1,
                        "axes": {"value_accuracy": 0.8},
                    }
                ]
            }
        )
    )
    result = compare_score_files(baseline, treatment, resamples=100)
    assert result["matched_cells"] == 1
    assert result["axes"]["value_accuracy"]["mean"] == pytest.approx(0.3)
