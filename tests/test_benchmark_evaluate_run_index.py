"""Tests for the authoritative no-best-run evaluation entry point."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.benchmark.evaluate_run_index import evaluate_run_index


def test_evaluate_run_index_materializes_missing_runs(tmp_path: Path) -> None:
    fixture_root = Path(__file__).parents[1] / "evaluation" / "benchmark" / "fixtures"
    manifest = json.loads((fixture_root / "benchmark_v2_smoke_manifest.json").read_text())
    run_results = json.loads((fixture_root / "benchmark_v2_smoke_results.json").read_text())
    manifest_path = tmp_path / "manifest.json"
    index_path = tmp_path / "run_index.json"
    manifest_path.write_text(json.dumps(manifest))
    index_path.write_text(
        json.dumps(
            {
                "schema_version": "fairiagent.run_index.v2",
                "scheduled_runs": manifest["scheduled_runs"],
                "scheduled_count": 3,
                "observed_count": 2,
                "missing_count": 1,
                "results": run_results,
            }
        )
    )
    score = evaluate_run_index(manifest_path, index_path, project_root=fixture_root)
    assert score["scheduled_count"] == 3
    assert score["missing_count"] == 1
    assert score["evaluated_run_index"]["evaluated_with"] == "evaluation.benchmark.attach_evaluator"


def test_evaluate_run_index_accepts_explicit_core_scope(tmp_path: Path) -> None:
    fixture_root = Path(__file__).parents[1] / "evaluation" / "benchmark" / "fixtures"
    manifest = json.loads((fixture_root / "benchmark_v2_smoke_manifest.json").read_text())
    manifest["instances"][0]["reporting_role"] = "core"
    run_results = json.loads((fixture_root / "benchmark_v2_smoke_results.json").read_text())
    manifest_path = tmp_path / "manifest.json"
    index_path = tmp_path / "run_index.json"
    manifest_path.write_text(json.dumps(manifest))
    index_path.write_text(
        json.dumps(
            {
                "schema_version": "fairiagent.run_index.v2",
                "scheduled_runs": manifest["scheduled_runs"],
                "scheduled_count": 3,
                "observed_count": 2,
                "missing_count": 1,
                "results": run_results,
            }
        )
    )
    score = evaluate_run_index(
        manifest_path,
        index_path,
        project_root=fixture_root,
        scope="core",
    )
    assert score["scope"] == "core"
    assert score["excluded_scheduled_count"] == 0
