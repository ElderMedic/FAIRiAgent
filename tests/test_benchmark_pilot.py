"""Token-free pilot manifest tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.benchmark.contracts import load_manifest, validate_manifest
from evaluation.benchmark.pilot import PilotManifestError, build_pilot_manifest


FIXTURES = Path(__file__).parents[1] / "evaluation" / "benchmark" / "fixtures"


def test_pilot_expands_only_development_instances_and_preserves_matrix_contract() -> None:
    manifest = load_manifest(FIXTURES / "benchmark_v2_smoke_manifest.json")
    pilot = build_pilot_manifest(manifest, repetitions=3)
    assert len(pilot["instances"]) == 1
    assert all(instance["split"] == "development" for instance in pilot["instances"])
    assert len(pilot["scheduled_runs"]) == 3
    assert {run["repetition"] for run in pilot["scheduled_runs"]} == {1, 2, 3}
    assert pilot["provenance"]["held_out_excluded"] is True
    assert pilot["provenance"]["model_or_api_calls_performed"] is False
    assert pilot["provenance"]["repetitions_by_split"] == {"development": 3}
    assert validate_manifest(pilot) == []


def test_pilot_rejects_held_out_split_and_unknown_selection() -> None:
    manifest = load_manifest(FIXTURES / "benchmark_v2_smoke_manifest.json")
    with pytest.raises(PilotManifestError, match="held-out"):
        build_pilot_manifest(manifest, pilot_split="held_out")
    with pytest.raises(PilotManifestError, match="unknown pilot conditions"):
        build_pilot_manifest(manifest, condition_ids=["missing_condition"])


def test_pilot_records_explicit_model_subset_as_distinct_release() -> None:
    manifest = load_manifest(FIXTURES / "benchmark_v2_smoke_manifest.json")
    pilot = build_pilot_manifest(manifest, repetitions=2, model_ids=["fixture_model"])
    assert ".models_fixture_model" in pilot["benchmark_release"]
    assert pilot["provenance"]["pilot_model_ids"] == ["fixture_model"]
    assert pilot["provenance"]["pilot_model_selection_explicit"] is True
