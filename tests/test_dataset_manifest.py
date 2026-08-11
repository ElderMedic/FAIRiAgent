"""Explicit split/model decision tests for release manifest materialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.benchmark.dataset_manifest import DatasetManifestError, materialize_manifest
from evaluation.benchmark.contracts import validate_manifest


CONDITION = {
    "condition_id": "single_pass_structured_extraction",
    "publication_name": "Single-pass structured extraction",
    "component_settings": {},
}
MODEL = {
    "model_id": "fixture_model",
    "provider": "fixture",
    "model_name": "fixture-model",
    "endpoint_class": "snapshot",
    "configuration_hash": "fixture",
}


def _inputs(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    source_dir = tmp_path / "paper_a"
    source_dir.mkdir()
    (source_dir / "paper.pdf").write_bytes(b"fixture pdf bytes")
    gt_path = tmp_path / "ground_truth.json"
    gt_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_a",
                        "document_path": str(source_dir),
                        "metadata": {"domain": "synthetic"},
                        "ground_truth_fields": [],
                    }
                ]
            }
        )
    )
    return gt_path, source_dir, {"doc_a": "development"}


def test_materializer_requires_explicit_freeze_confirmation(tmp_path: Path) -> None:
    gt_path, _, split_map = _inputs(tmp_path)
    with pytest.raises(DatasetManifestError, match="freeze_confirmation"):
        materialize_manifest(
            [gt_path],
            project_root=tmp_path,
            split_map=split_map,
            model_panel=[MODEL],
            package_id="fairds",
            package_version="local",
            conditions=[CONDITION],
            benchmark_release="test.v2",
            evaluator_version="test",
        )


def test_materializer_expands_paths_and_complete_matrix(tmp_path: Path) -> None:
    gt_path, source_dir, split_map = _inputs(tmp_path)
    package = tmp_path / "package.json"
    package.write_text("{\"package\": \"fixture\"}", encoding="utf-8")
    manifest = materialize_manifest(
        [gt_path],
        project_root=tmp_path,
        split_map=split_map,
        model_panel=[MODEL],
        package_id="fairds",
        package_version="local",
        package_path=str(package),
        conditions=[CONDITION],
        benchmark_release="test.v2",
        evaluator_version="test",
        repetitions=3,
        repository_commit="fixture",
        created_at="2026-07-21T00:00:00Z",
        freeze_confirmation="researcher-approved:test-split",
    )
    assert not validate_manifest(manifest)
    assert manifest["instances"][0]["source_path"] == str(source_dir / "paper.pdf")
    assert manifest["instances"][0]["package_path"] == str(package)
    assert manifest["instances"][0]["split"] == "development"
    assert len(manifest["scheduled_runs"]) == 3
    assert manifest["provenance"]["evidence_annotation_required"] is False
    assert manifest["provenance"]["model_panel_sha256"]
    assert manifest["provenance"]["model_or_api_calls_performed"] is False


def test_materializer_records_explicit_reporting_role(tmp_path: Path) -> None:
    gt_path, _, split_map = _inputs(tmp_path)
    manifest = materialize_manifest(
        [gt_path],
        project_root=tmp_path,
        split_map=split_map,
        reporting_roles={"doc_a": "supplemental"},
        model_panel=[MODEL],
        package_id="fairds",
        package_version="local",
        conditions=[CONDITION],
        benchmark_release="test.v2",
        evaluator_version="test",
        freeze_confirmation="researcher-approved:test-split",
    )
    assert manifest["instances"][0]["reporting_role"] == "supplemental"
    assert "reporting_role_map_sha256" in manifest["provenance"]


def test_materializer_requires_complete_reporting_role_map(tmp_path: Path) -> None:
    gt_path, _, split_map = _inputs(tmp_path)
    with pytest.raises(DatasetManifestError, match="missing reporting roles"):
        materialize_manifest(
            [gt_path],
            project_root=tmp_path,
            split_map=split_map,
            reporting_roles={},
            model_panel=[MODEL],
            package_id="fairds",
            package_version="local",
            conditions=[CONDITION],
            benchmark_release="test.v2",
            evaluator_version="test",
            freeze_confirmation="researcher-approved:test-split",
        )


def test_materializer_uses_declared_schema_extension_as_domain_fallback(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("fixture", encoding="utf-8")
    gt_path = tmp_path / "ground_truth.json"
    gt_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_a",
                        "document_path": str(source),
                        "metadata": {"schema_extensions": ["petase_enzyme_engineering"]},
                    }
                ]
            }
        )
    )
    manifest = materialize_manifest(
        [gt_path],
        project_root=tmp_path,
        split_map={"doc_a": "development"},
        model_panel=[MODEL],
        package_id="fairds",
        package_version="local",
        conditions=[CONDITION],
        benchmark_release="test.v2",
        evaluator_version="test",
        freeze_confirmation="researcher-approved:test-split",
    )
    assert manifest["instances"][0]["strata"]["domain"] == "schema_extension:petase_enzyme_engineering"
    assert manifest["instances"][0]["provenance"]["domain_source"] == "metadata.schema_extensions"


def test_materializer_rejects_incomplete_split_map(tmp_path: Path) -> None:
    gt_path, _, _ = _inputs(tmp_path)
    with pytest.raises(DatasetManifestError, match="missing split assignments"):
        materialize_manifest(
            [gt_path],
            project_root=tmp_path,
            split_map={},
            model_panel=[MODEL],
            package_id="fairds",
            package_version="local",
            conditions=[CONDITION],
            benchmark_release="test.v2",
            evaluator_version="test",
            freeze_confirmation="researcher-approved:test-split",
        )


def test_materializer_supports_declared_repetition_schedule_by_split(tmp_path: Path) -> None:
    gt_path, _, split_map = _inputs(tmp_path)
    manifest = materialize_manifest(
        [gt_path],
        project_root=tmp_path,
        split_map=split_map,
        model_panel=[MODEL],
        package_id="fairds",
        package_version="local",
        conditions=[CONDITION],
        benchmark_release="test.v2",
        evaluator_version="test",
        repetitions=1,
        repetitions_by_split={"development": 3},
        freeze_confirmation="researcher-approved:test-split",
    )
    assert len(manifest["scheduled_runs"]) == 3
    assert manifest["provenance"]["repetitions_by_split"] == {"development": 3}


def test_materializer_preserves_declared_values_ground_truth_path(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("fixture", encoding="utf-8")
    values = tmp_path / "values.json"
    values.write_text(json.dumps({"document_id": "doc_a"}), encoding="utf-8")
    gt_path = tmp_path / "ground_truth.json"
    gt_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_a",
                        "document_path": str(source),
                        "ground_truth_values_path": str(values),
                        "metadata": {"domain": "synthetic"},
                    }
                ]
            }
        )
    )
    manifest = materialize_manifest(
        [gt_path],
        project_root=tmp_path,
        split_map={"doc_a": "development"},
        model_panel=[MODEL],
        package_id="fairds",
        package_version="local",
        conditions=[CONDITION],
        benchmark_release="test.v2",
        evaluator_version="test",
        freeze_confirmation="researcher-approved:test-split",
    )
    assert manifest["instances"][0]["ground_truth_values_path"] == str(values)


def test_materializer_infers_adjacent_values_ground_truth_path(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("fixture", encoding="utf-8")
    values_dir = tmp_path / "values"
    values_dir.mkdir()
    values = values_dir / "ground_truth_doc_a_values.json"
    values.write_text(json.dumps({"document_id": "doc_a"}), encoding="utf-8")
    gt_path = tmp_path / "ground_truth.json"
    gt_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_a",
                        "document_path": str(source),
                        "metadata": {"domain": "synthetic"},
                    }
                ]
            }
        )
    )
    manifest = materialize_manifest(
        [gt_path],
        project_root=tmp_path,
        split_map={"doc_a": "development"},
        model_panel=[MODEL],
        package_id="fairds",
        package_version="local",
        conditions=[CONDITION],
        benchmark_release="test.v2",
        evaluator_version="test",
        freeze_confirmation="researcher-approved:test-split",
    )
    assert manifest["instances"][0]["ground_truth_values_path"] == str(values)


def test_materializer_preserves_context_and_supplementary_assets(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("fixture", encoding="utf-8")
    standards = tmp_path / "standards.md"
    standards.write_text("standards", encoding="utf-8")
    retrieved = tmp_path / "retrieved.md"
    retrieved.write_text("retrieved", encoding="utf-8")
    supplement = tmp_path / "supplement.md"
    supplement.write_text("supplement", encoding="utf-8")
    gt_path = tmp_path / "ground_truth.json"
    gt_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_a",
                        "document_path": str(source),
                        "standards_context_path": str(standards),
                        "retrieved_context_path": str(retrieved),
                        "supplementary_paths": [str(supplement)],
                        "metadata": {"domain": "synthetic", "table_density": "high"},
                    }
                ]
            }
        )
    )
    manifest = materialize_manifest(
        [gt_path],
        project_root=tmp_path,
        split_map={"doc_a": "development"},
        model_panel=[MODEL],
        package_id="fairds",
        package_version="local",
        conditions=[CONDITION],
        benchmark_release="test.v2",
        evaluator_version="test",
        freeze_confirmation="researcher-approved:test-split",
    )
    instance = manifest["instances"][0]
    assert instance["standards_context_path"] == str(standards)
    assert instance["retrieved_context_path"] == str(retrieved)
    assert instance["supplementary_paths"] == [str(supplement)]
    assert instance["strata"]["table_density"] == "high"
