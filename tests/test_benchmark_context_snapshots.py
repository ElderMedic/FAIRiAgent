"""Token-free context snapshot materialization tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.benchmark.context_snapshots import (
    ContextSnapshotError,
    manifest_with_context_paths,
    materialize_context_snapshots,
)


def _manifest(tmp_path: Path) -> tuple[dict, Path, Path]:
    source = tmp_path / "paper.md"
    source.write_text(
        "Methods\n\nSamples were collected from three sites. The study identifier was S-01.",
        encoding="utf-8",
    )
    package = tmp_path / "package.json"
    package.write_text(
        json.dumps(
            {
                "packageName": "fixture",
                "itemCount": 2,
                "metadata": [
                    {
                        "label": "study identifier",
                        "sheetName": "Study",
                        "term": {"label": "study identifier", "definition": "Identifier of the study."},
                    },
                    {
                        "label": "sample collection site",
                        "sheetName": "Sample",
                        "term": {"label": "sample collection site", "definition": "Site where samples were collected."},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "schema_version": "fairiagent.benchmark_manifest.v2",
        "benchmark_release": "fixture",
        "instances": [
            {
                "instance_id": "doc",
                "source_path": str(source),
                "ground_truth_path": str(tmp_path / "ground_truth.json"),
                "package_path": str(package),
                "package_id": "fixture",
                "package_version": "1",
                "split": "development",
                "strata": {"domain": "fixture"},
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
                "model_id": "fixture",
                "provider": "fixture",
                "model_name": "fixture",
                "endpoint_class": "snapshot",
                "configuration_hash": "fixture",
            }
        ],
        "scheduled_runs": [
            {
                "run_id": "doc__single_pass_structured_extraction__fixture__r01",
                "instance_id": "doc",
                "condition_id": "single_pass_structured_extraction",
                "model_id": "fixture",
                "repetition": 1,
            }
        ],
        "provenance": {
            "repository_commit": "fixture",
            "evaluator_version": "fixture",
            "created_at": "fixture",
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "ground_truth.json").write_text("{}", encoding="utf-8")
    return manifest, manifest_path, package


def test_materialize_context_snapshots_is_deterministic_and_excludes_ground_truth(tmp_path: Path) -> None:
    manifest, manifest_path, _ = _manifest(tmp_path)
    first = materialize_context_snapshots(
        manifest,
        manifest_path,
        project_root=tmp_path,
        output_dir=tmp_path / "contexts_a",
    )
    second = materialize_context_snapshots(
        manifest,
        manifest_path,
        project_root=tmp_path,
        output_dir=tmp_path / "contexts_b",
    )

    assert first["model_or_api_calls_performed"] is False
    assert first["token_calls_performed"] is False
    assert first["retrieval_method"] == "lexical"
    first_record = first["instances"][0]
    second_record = second["instances"][0]
    assert first_record["standards_context"]["sha256"] == second_record["standards_context"]["sha256"]
    assert first_record["retrieved_context"]["sha256"] == second_record["retrieved_context"]["sha256"]

    standards = Path(first["instance_context_paths"]["doc"]["standards_context_path"]).read_text()
    retrieved = Path(first["instance_context_paths"]["doc"]["retrieved_context_path"]).read_text()
    assert "study identifier" in standards
    assert "Samples were collected" in retrieved
    assert "ground_truth" not in retrieved
    patched = manifest_with_context_paths(manifest, first)
    assert "standards_context_path" not in manifest["instances"][0]
    assert patched["instances"][0]["standards_context_path"].endswith("standards_context.json")
    assert patched["provenance"]["context_snapshot_retrieval_method"] == "lexical"


def test_semantic_context_requires_an_explicit_non_token_free_campaign(tmp_path: Path) -> None:
    manifest, manifest_path, _ = _manifest(tmp_path)
    with pytest.raises(ContextSnapshotError, match="only retrieval_method=lexical"):
        materialize_context_snapshots(
            manifest,
            manifest_path,
            project_root=tmp_path,
            output_dir=tmp_path / "contexts",
            retrieval_method="hybrid",
        )
