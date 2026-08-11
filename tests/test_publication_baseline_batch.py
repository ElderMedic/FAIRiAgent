"""Dry-run scheduling tests for publication baseline conditions."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.baselines.run_publication_baselines import main, plan_runs, validate_job


def test_plan_and_validate_single_pass_job_without_model_call(tmp_path: Path) -> None:
    document = tmp_path / "document.md"
    document.write_text("A document with explicit sample information.")
    manifest_path = tmp_path / "manifest.json"
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({"document_id": "doc", "ground_truth_fields": []}))
    manifest = {
        "schema_version": "fairiagent.benchmark_manifest.v2",
        "benchmark_release": "test",
        "instances": [
            {
                "instance_id": "doc",
                "source_path": "document.md",
                "ground_truth_path": "gold.json",
            }
        ],
        "conditions": [
            {
                "condition_id": "single_pass_structured_extraction",
                "publication_name": "Single-pass structured extraction",
                "component_settings": {},
            }
        ],
        "models": [{"model_id": "fixture_model", "provider": "fixture", "model_name": "fixture"}],
        "scheduled_runs": [
            {
                "run_id": "doc__single_pass_structured_extraction__fixture_model__r01",
                "instance_id": "doc",
                "condition_id": "single_pass_structured_extraction",
                "model_id": "fixture_model",
                "repetition": 1,
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest))
    jobs = plan_runs(manifest, manifest_path, output_dir=tmp_path / "runs")

    assert len(jobs) == 1
    plan = validate_job(jobs[0])
    assert plan["estimated_llm_calls"] == 1
    assert plan["document_characters"] > 0
    strict_plan = validate_job(jobs[0], require_ground_truth=True)
    assert strict_plan["ground_truth_sha256"]


def test_plan_preserves_explicit_per_model_configuration(tmp_path: Path) -> None:
    source = tmp_path / "document.md"
    source.write_text("A document with explicit sample information.")
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({"document_id": "doc", "ground_truth_fields": []}))
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "schema_version": "fairiagent.benchmark_manifest.v2",
        "benchmark_release": "test",
        "instances": [{"instance_id": "doc", "source_path": str(source), "ground_truth_path": str(gold)}],
        "conditions": [
            {
                "condition_id": "single_pass_structured_extraction",
                "publication_name": "Single-pass structured extraction",
                "component_settings": {},
            }
        ],
        "models": [
            {"model_id": "model_a", "provider": "fixture", "model_name": "a"},
            {"model_id": "model_b", "provider": "fixture", "model_name": "b"},
        ],
        "scheduled_runs": [
            {
                "run_id": "doc__single_pass_structured_extraction__model_a__r01",
                "instance_id": "doc",
                "condition_id": "single_pass_structured_extraction",
                "model_id": "model_a",
                "repetition": 1,
            },
            {
                "run_id": "doc__single_pass_structured_extraction__model_b__r01",
                "instance_id": "doc",
                "condition_id": "single_pass_structured_extraction",
                "model_id": "model_b",
                "repetition": 1,
            },
        ],
    }
    manifest_path.write_text(json.dumps(manifest))
    config_a = tmp_path / "a.env"
    config_b = tmp_path / "b.env"
    config_a.write_text("LLM_PROVIDER=fixture\nFAIRIFIER_LLM_MODEL=a\n")
    config_b.write_text("LLM_PROVIDER=fixture\nFAIRIFIER_LLM_MODEL=b\n")

    jobs = plan_runs(
        manifest,
        manifest_path,
        output_dir=tmp_path / "runs",
        model_configs={"model_a": config_a, "model_b": config_b},
    )

    assert {job["model_id"]: job["config_file"] for job in jobs} == {
        "model_a": config_a,
        "model_b": config_b,
    }


def test_cli_persists_token_free_dry_run_output(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "document.md"
    source.write_text("A document with explicit sample information.")
    gold = tmp_path / "ground_truth.json"
    gold.write_text(json.dumps({"document_id": "doc", "ground_truth_fields": []}))
    manifest = {
        "schema_version": "fairiagent.benchmark_manifest.v2",
        "benchmark_release": "test",
        "instances": [
            {
                "instance_id": "doc",
                "source_path": str(source),
                "ground_truth_path": str(gold),
                "package_id": "fixture_package",
                "package_version": "1",
                "split": "development",
                "strata": {"domain": "synthetic"},
            }
        ],
        "conditions": [
            {
                "condition_id": "single_pass_structured_extraction",
                "publication_name": "Single-pass structured extraction",
                "component_settings": {},
            }
        ],
        "models": [
            {
                "model_id": "fixture_model",
                "provider": "fixture",
                "model_name": "fixture-model",
                "endpoint_class": "snapshot",
                "configuration_hash": "fixture",
            }
        ],
        "scheduled_runs": [
            {
                "run_id": "doc__single_pass_structured_extraction__fixture_model__r01",
                "instance_id": "doc",
                "condition_id": "single_pass_structured_extraction",
                "model_id": "fixture_model",
                "repetition": 1,
            }
        ],
        "provenance": {
            "repository_commit": "fixture",
            "evaluator_version": "fixture-v2",
            "created_at": "2026-07-21T00:00:00Z",
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    config_path = tmp_path / "model.env"
    config_path.write_text("LLM_PROVIDER=fixture\nFAIRIFIER_LLM_MODEL=fixture\n")
    output_path = tmp_path / "dry_run.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_publication_baselines",
            "--manifest",
            str(manifest_path),
            "--config-file",
            str(config_path),
            "--output-dir",
            str(tmp_path / "runs"),
            "--dry-run",
            "--dry-run-output",
            str(output_path),
        ],
    )
    assert main() == 0
    result = json.loads(output_path.read_text())
    assert result["status"] == "dry_run"
    assert result["model_or_api_calls_performed"] is False
    assert result["run_index"]["estimated_llm_calls"] == 1
    assert len(result["jobs"]) == 1
