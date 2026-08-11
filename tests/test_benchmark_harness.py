"""Tests for token-free v2 harness dry-run validation."""

from pathlib import Path

from evaluation.harness.runner import summarize_benchmark_manifest
from evaluation.benchmark.contracts import load_manifest


FIXTURES = Path(__file__).parents[1] / "evaluation" / "benchmark" / "fixtures"


def test_harness_dry_run_reports_asset_checksums_without_calls() -> None:
    manifest_path = FIXTURES / "benchmark_v2_smoke_manifest.json"
    manifest = load_manifest(manifest_path)
    summary = summarize_benchmark_manifest(
        manifest,
        manifest_path=manifest_path,
        project_root=FIXTURES,
    )
    assert summary["asset_count"] >= 2
    assert len(summary["asset_checksums"]["fixture_document"]["source"]["sha256"]) == 64
    assert summary["split_leakage_errors"] == []
    assert summary["model_or_api_calls_performed"] is False
