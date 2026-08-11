"""Golden-fixture tests for the benchmark version 2 contract and scorer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.benchmark.contracts import ManifestValidationError, load_manifest
from evaluation.benchmark.scorer import ScoreError, score_batch


FIXTURES = Path(__file__).parents[1] / "evaluation" / "benchmark" / "fixtures"


def _load_results() -> list[dict]:
    return json.loads((FIXTURES / "benchmark_v2_smoke_results.json").read_text())


def test_smoke_manifest_is_reproducible_contract() -> None:
    manifest = load_manifest(FIXTURES / "benchmark_v2_smoke_manifest.json")
    assert manifest["schema_version"] == "fairiagent.benchmark_manifest.v2"
    assert len(manifest["scheduled_runs"]) == 3


def test_scorer_keeps_missing_run_in_denominator() -> None:
    manifest = load_manifest(FIXTURES / "benchmark_v2_smoke_manifest.json")
    score = score_batch(manifest, _load_results())

    assert score["scheduled_count"] == 3
    assert score["observed_count"] == 2
    assert score["missing_count"] == 1
    assert score["standard_success_rate"] == pytest.approx(1 / 3)
    assert score["strict_success_rate"] == pytest.approx(1 / 3)
    assert score["standard_success_rate_ci95"][0] == pytest.approx(0.0615, abs=1e-4)
    assert score["standard_success_rate_ci95"][1] == pytest.approx(0.7923, abs=1e-4)
    assert score["pass_to_the_power_of_k"]["3"]["eligible_groups"] == 1
    assert score["pass_to_the_power_of_k"]["3"]["estimate"] == 0.0
    assert score["pass_to_the_power_of_k"]["3"]["ci95"][0] == 0.0
    assert score["pass_to_the_power_of_k"]["3"]["ci95"][1] == pytest.approx(0.7935, abs=1e-4)

    run_status = {run["run_id"]: run for run in score["standard_runs"]}
    missing = run_status[manifest["scheduled_runs"][2]["run_id"]]
    assert missing["success"] is False
    assert "status:not_observed" in missing["failure_reasons"]


def test_scoped_score_excludes_supplemental_instances_from_headline_denominator() -> None:
    manifest = load_manifest(FIXTURES / "benchmark_v2_smoke_manifest.json")
    manifest["instances"][0]["reporting_role"] = "core"
    supplemental = dict(manifest["instances"][0])
    supplemental["instance_id"] = "supplemental_document"
    supplemental["reporting_role"] = "supplemental"
    manifest["instances"].append(supplemental)
    original_runs = list(manifest["scheduled_runs"])
    supplemental_runs = []
    for run in original_runs:
        copied = dict(run)
        copied["instance_id"] = "supplemental_document"
        copied["run_id"] = copied["run_id"].replace("fixture_document", "supplemental_document")
        supplemental_runs.append(copied)
    manifest["scheduled_runs"] = original_runs + supplemental_runs
    results = _load_results()
    results += [
        {**result, "instance_id": "supplemental_document", "run_id": result["run_id"].replace("fixture_document", "supplemental_document")}
        for result in results
    ]

    score = score_batch(manifest, results, scope="core")

    assert score["scope"] == "core"
    assert score["scheduled_count"] == 3
    assert score["excluded_scheduled_count"] == 3
    assert score["observed_count"] == 2


def test_scoped_score_requires_reporting_roles() -> None:
    manifest = load_manifest(FIXTURES / "benchmark_v2_smoke_manifest.json")
    with pytest.raises(ScoreError, match="requires reporting_role"):
        score_batch(manifest, _load_results(), scope="core")


def test_critical_validation_error_cannot_be_hidden_by_high_quality_axes() -> None:
    manifest = load_manifest(FIXTURES / "benchmark_v2_smoke_manifest.json")
    score = score_batch(manifest, _load_results())
    broken = score["standard_runs"][1]

    assert broken["axes"]["value_accuracy"] == pytest.approx(0.96)
    assert broken["success"] is False
    assert "critical_errors:1" in broken["failure_reasons"]


def test_score_rejects_result_not_scheduled_in_manifest() -> None:
    manifest = load_manifest(FIXTURES / "benchmark_v2_smoke_manifest.json")
    results = _load_results()
    extra = dict(results[0])
    extra["run_id"] = "not_scheduled"

    with pytest.raises(ScoreError, match="absent from manifest"):
        score_batch(manifest, results + [extra])


def test_manifest_rejects_unknown_scheduled_instance(tmp_path: Path) -> None:
    manifest = json.loads((FIXTURES / "benchmark_v2_smoke_manifest.json").read_text())
    manifest["scheduled_runs"][0]["instance_id"] = "unknown"
    path = tmp_path / "invalid_manifest.json"
    path.write_text(json.dumps(manifest))

    with pytest.raises(ManifestValidationError, match="unknown instance_id"):
        load_manifest(path)


def test_manifest_rejects_noncontiguous_repetitions(tmp_path: Path) -> None:
    manifest = json.loads((FIXTURES / "benchmark_v2_smoke_manifest.json").read_text())
    manifest["scheduled_runs"][1]["repetition"] = 4
    path = tmp_path / "invalid_repetitions.json"
    path.write_text(json.dumps(manifest))

    with pytest.raises(ManifestValidationError, match="contiguous"):
        load_manifest(path)


def test_manifest_requires_model_identity_fields(tmp_path: Path) -> None:
    manifest = json.loads((FIXTURES / "benchmark_v2_smoke_manifest.json").read_text())
    manifest["models"][0].pop("provider")
    path = tmp_path / "invalid_model.json"
    path.write_text(json.dumps(manifest))

    with pytest.raises(ManifestValidationError, match=r"models\[0\]\.provider"):
        load_manifest(path)


def test_manifest_rejects_unknown_publication_condition(tmp_path: Path) -> None:
    manifest = json.loads((FIXTURES / "benchmark_v2_smoke_manifest.json").read_text())
    manifest["conditions"][0]["condition_id"] = "historical_short_alias"
    manifest["scheduled_runs"][0]["condition_id"] = "historical_short_alias"
    path = tmp_path / "invalid_condition.json"
    path.write_text(json.dumps(manifest))

    with pytest.raises(ManifestValidationError, match="condition_registry"):
        load_manifest(path)


def test_manifest_rejects_unknown_split_and_endpoint_class(tmp_path: Path) -> None:
    manifest = json.loads((FIXTURES / "benchmark_v2_smoke_manifest.json").read_text())
    manifest["instances"][0]["split"] = "internal_only"
    manifest["models"][0]["endpoint_class"] = "unknown"
    path = tmp_path / "invalid_vocabularies.json"
    path.write_text(json.dumps(manifest))

    with pytest.raises(ManifestValidationError) as exc:
        load_manifest(path)
    assert "supported benchmark split" in str(exc.value)
    assert "endpoint_class is not supported" in str(exc.value)


def test_manifest_rejects_unknown_reporting_role(tmp_path: Path) -> None:
    manifest = json.loads((FIXTURES / "benchmark_v2_smoke_manifest.json").read_text())
    manifest["instances"][0]["reporting_role"] = "headline_only"
    path = tmp_path / "invalid_reporting_role.json"
    path.write_text(json.dumps(manifest))

    with pytest.raises(ManifestValidationError, match="reporting_role"):
        load_manifest(path)
