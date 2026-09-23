"""Tests for attaching current evaluator output to a persisted run index."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.benchmark.attach_evaluator import attach_evaluator_results
from evaluation.benchmark.scorer import score_run


def test_attach_evaluator_preserves_manifest_identity_and_metrics(tmp_path: Path) -> None:
    source = tmp_path / "document.md"
    source.write_text("A fixture document.")
    ground_truth = tmp_path / "ground_truth.json"
    ground_truth.write_text(
        json.dumps(
            {
                "document_id": "doc",
                "ground_truth_fields": [{"field_name": "investigation title"}],
            }
        )
    )
    manifest = {
        "schema_version": "fairiagent.benchmark_manifest.v2",
        "benchmark_release": "test",
        "instances": [
            {
                "instance_id": "doc",
                "source_path": "document.md",
                "ground_truth_path": "ground_truth.json",
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
                "model_id": "model_alias",
                "provider": "fixture",
                "model_name": "fixture",
                "endpoint_class": "snapshot",
                "configuration_hash": "fixture",
            }
        ],
        "scheduled_runs": [
            {
                "run_id": "doc__single_pass_structured_extraction__model_alias__r01",
                "instance_id": "doc",
                "condition_id": "single_pass_structured_extraction",
                "model_id": "model_alias",
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

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "metadata_json.json").write_text(
        json.dumps(
            {
                "fairifier_version": "test",
                "generated_at": "2026-07-21T00:00:00",
                "document_source": "fixture",
                "isa_structure": {
                    "investigation": {
                        "fields": [
                            {"field_name": "investigation title", "value": "A study"}
                        ]
                    }
                },
                "isa_values": {
                    "investigation": {
                        "columns": ["investigation title"],
                        "rows": [["A study"]],
                    }
                },
            }
        )
    )
    run_id = manifest["scheduled_runs"][0]["run_id"]
    run_index_path = tmp_path / "run_index.json"
    run_index_path.write_text(
        json.dumps(
            {
                "schema_version": "fairiagent.run_index.v2",
                "benchmark_release": "test",
                "results": [
                    {
                        "schema_version": "fairiagent.result_envelope.v2",
                        "run_id": run_id,
                        "instance_id": "doc",
                        "condition_id": "single_pass_structured_extraction",
                        "model_id": "model_alias",
                        "repetition": 1,
                        "status": "success",
                        "artifact": {
                            "exists": True,
                            "parseable": True,
                            "path": str(run_dir / "metadata_json.json"),
                        },
                        "validation": {
                            "fairds_valid": False,
                            "isa_round_trip_valid": False,
                            "critical_errors": 0,
                        },
                        "axes": {
                            "information_coverage": 0.0,
                            "value_accuracy": 0.0,
                            "structural_fidelity": 0.0,
                            "interoperability": 0.0,
                        },
                        "resources": {"latency_seconds": 1.0},
                    }
                ],
                "scheduled_runs": manifest["scheduled_runs"],
                "scheduled_count": 1,
                "observed_count": 1,
                "missing_count": 0,
            }
        )
    )

    attached = attach_evaluator_results(
        manifest_path,
        run_index_path,
        project_root=tmp_path,
    )
    result = attached["results"][0]
    assert result["run_id"] == run_id
    assert result["model_id"] == "model_alias"
    assert result["axes"]["information_coverage"] == 1.0
    assert result["provenance"]["output_validation"]["isa_round_trip_valid"] is True
    assert result["resources"]["latency_seconds"] == 1.0
    assert score_run(result)["success"] is False  # no values-GT: fail closed
