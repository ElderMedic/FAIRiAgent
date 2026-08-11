"""Integration test for scoring a persisted v2 run index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.benchmark.score_run_index import score_run_index


FIXTURES = Path(__file__).parents[1] / "evaluation" / "benchmark" / "fixtures"


def test_persisted_run_index_is_scored_with_all_scheduled_runs(tmp_path: Path) -> None:
    manifest_path = FIXTURES / "benchmark_v2_smoke_manifest.json"
    results = json.loads((FIXTURES / "benchmark_v2_smoke_results.json").read_text())
    run_index_path = tmp_path / "run_index.json"
    run_index_path.write_text(
        json.dumps(
            {
                "schema_version": "fairiagent.run_index.v2",
                "scheduled_runs": json.loads(manifest_path.read_text())["scheduled_runs"],
                "scheduled_count": 3,
                "observed_count": 2,
                "missing_count": 1,
                "results": results,
            }
        )
    )

    score = score_run_index(manifest_path, run_index_path)
    assert score["scheduled_count"] == 3
    assert score["standard_success_rate"] == pytest.approx(1 / 3)
    assert score["run_index_missing_count"] == 1
