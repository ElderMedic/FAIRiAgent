"""Asset checksum and run-index tests."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.benchmark.assets import collect_asset_checksums
from evaluation.benchmark.contracts import load_manifest
from evaluation.benchmark.run_index import create_run_index, merge_run_indices, record_result


FIXTURES = Path(__file__).parents[1] / "evaluation" / "benchmark" / "fixtures"


def test_smoke_assets_are_hashed_before_execution() -> None:
    path = FIXTURES / "benchmark_v2_smoke_manifest.json"
    manifest = load_manifest(path)
    assets = collect_asset_checksums(
        manifest,
        path,
        project_root=Path(__file__).parents[1],
        require_ground_truth=True,
    )
    assert len(assets["fixture_document"]["source"]["sha256"]) == 64
    assert len(assets["fixture_document"]["ground_truth"]["sha256"]) == 64


def test_declared_context_assets_are_hashed(tmp_path: Path) -> None:
    source = tmp_path / "document.md"
    ground_truth = tmp_path / "ground_truth.json"
    standards = tmp_path / "standards.md"
    retrieved = tmp_path / "retrieved.md"
    for path in (source, ground_truth, standards, retrieved):
        path.write_text(path.name, encoding="utf-8")
    manifest = {
        "instances": [
            {
                "instance_id": "doc",
                "source_path": str(source),
                "ground_truth_path": str(ground_truth),
                "standards_context_path": str(standards),
                "retrieved_context_path": str(retrieved),
            }
        ]
    }
    assets = collect_asset_checksums(
        manifest,
        tmp_path / "manifest.json",
        project_root=tmp_path,
        require_ground_truth=True,
    )
    assert assets["doc"]["standards_context"]["sha256"]
    assert assets["doc"]["retrieved_context"]["sha256"]


def test_declared_ground_truth_values_asset_is_hashed(tmp_path: Path) -> None:
    source = tmp_path / "document.md"
    ground_truth = tmp_path / "ground_truth.json"
    values = tmp_path / "values.json"
    for path in (source, ground_truth, values):
        path.write_text(path.name, encoding="utf-8")
    manifest = {
        "instances": [
            {
                "instance_id": "doc",
                "source_path": str(source),
                "ground_truth_path": str(ground_truth),
                "ground_truth_values_path": str(values),
            }
        ]
    }
    assets = collect_asset_checksums(
        manifest,
        tmp_path / "manifest.json",
        project_root=tmp_path,
        require_ground_truth=True,
    )
    assert assets["doc"]["ground_truth_values"]["sha256"]


def test_declared_supplementary_assets_are_hashed(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")
    gold = tmp_path / "gold.json"
    gold.write_text("{}", encoding="utf-8")
    supplementary = tmp_path / "supplement.txt"
    supplementary.write_text("supplement", encoding="utf-8")
    manifest = {
        "instances": [
            {
                "instance_id": "doc",
                "source_path": str(source),
                "ground_truth_path": str(gold),
                "supplementary_paths": [str(supplementary)],
            }
        ]
    }
    assets = collect_asset_checksums(
        manifest,
        tmp_path / "manifest.json",
        project_root=tmp_path,
    )
    assert assets["doc"]["supplementary"][0]["sha256"]


def test_run_index_preserves_scheduled_and_observed_counts() -> None:
    manifest_path = FIXTURES / "benchmark_v2_smoke_manifest.json"
    manifest = load_manifest(manifest_path)
    assets = collect_asset_checksums(
        manifest,
        manifest_path,
        project_root=FIXTURES,
        require_ground_truth=True,
    )
    index = create_run_index(
        manifest,
        manifest_path="manifest.json",
        config_file="model.env",
        asset_checksums=assets,
        scheduled_jobs=manifest["scheduled_runs"],
    )
    result = json.loads((FIXTURES / "benchmark_v2_smoke_results.json").read_text())[0]
    record_result(index, result)
    assert index["scheduled_count"] == 3
    assert index["observed_count"] == 1
    assert index["missing_count"] == 2


def test_run_index_rejects_unscheduled_or_mismatched_results() -> None:
    manifest_path = FIXTURES / "benchmark_v2_smoke_manifest.json"
    manifest = load_manifest(manifest_path)
    assets = collect_asset_checksums(
        manifest,
        manifest_path,
        project_root=FIXTURES,
        require_ground_truth=True,
    )
    index = create_run_index(
        manifest,
        manifest_path="manifest.json",
        config_file="model.env",
        asset_checksums=assets,
        scheduled_jobs=manifest["scheduled_runs"],
    )
    result = json.loads((FIXTURES / "benchmark_v2_smoke_results.json").read_text())[0]
    unscheduled = dict(result)
    unscheduled["run_id"] = "not_scheduled"
    import pytest

    with pytest.raises(ValueError, match="not scheduled"):
        record_result(index, unscheduled)
    mismatched = dict(result)
    mismatched["model_id"] = "other_model"
    with pytest.raises(ValueError, match="does not match schedule"):
        record_result(index, mismatched)


def test_persisted_run_index_rejects_identity_mismatch() -> None:
    from evaluation.benchmark.run_index import validate_run_index

    manifest_path = FIXTURES / "benchmark_v2_smoke_manifest.json"
    manifest = load_manifest(manifest_path)
    assets = collect_asset_checksums(
        manifest,
        manifest_path,
        project_root=FIXTURES,
        require_ground_truth=True,
    )
    index = create_run_index(
        manifest,
        manifest_path="manifest.json",
        config_file="model.env",
        asset_checksums=assets,
        scheduled_jobs=manifest["scheduled_runs"],
    )
    result = json.loads((FIXTURES / "benchmark_v2_smoke_results.json").read_text())[0]
    result["model_id"] = "wrong_model"
    index["results"].append(result)
    index["observed_count"] = 1
    index["missing_count"] = 2
    errors = validate_run_index(index)
    assert any("model_id does not match scheduled run" in error for error in errors)


def test_run_index_requires_source_and_ground_truth_checksums() -> None:
    manifest = load_manifest(FIXTURES / "benchmark_v2_smoke_manifest.json")
    import pytest

    with pytest.raises(ValueError, match="asset_checksums are required"):
        create_run_index(
            manifest,
            manifest_path="manifest.json",
            config_file="model.env",
            asset_checksums={},
            scheduled_jobs=manifest["scheduled_runs"],
        )


def test_run_index_partitions_merge_without_changing_denominator() -> None:
    manifest_path = FIXTURES / "benchmark_v2_smoke_manifest.json"
    manifest = load_manifest(manifest_path)
    assets = collect_asset_checksums(
        manifest,
        manifest_path,
        project_root=FIXTURES,
        require_ground_truth=True,
    )
    partitions = []
    results = json.loads((FIXTURES / "benchmark_v2_smoke_results.json").read_text())
    for position, scheduled in enumerate(manifest["scheduled_runs"]):
        partition = create_run_index(
            manifest,
            manifest_path="manifest.json",
            config_file="model.env",
            asset_checksums=assets,
            scheduled_jobs=[scheduled],
        )
        if position < len(results):
            record_result(partition, results[position])
        partition["partition_path"] = "partition-%d.json" % position
        partitions.append(partition)

    merged = merge_run_indices(partitions)
    assert merged["scheduled_count"] == 3
    assert merged["observed_count"] == 2
    assert merged["missing_count"] == 1
    assert merged["partitioned_from"] == [
        "partition-0.json",
        "partition-1.json",
        "partition-2.json",
    ]


def test_run_index_partition_merge_rejects_overlap() -> None:
    manifest_path = FIXTURES / "benchmark_v2_smoke_manifest.json"
    manifest = load_manifest(manifest_path)
    assets = collect_asset_checksums(
        manifest,
        manifest_path,
        project_root=FIXTURES,
        require_ground_truth=True,
    )
    partition = create_run_index(
        manifest,
        manifest_path="manifest.json",
        config_file="model.env",
        asset_checksums=assets,
        scheduled_jobs=[manifest["scheduled_runs"][0]],
    )
    import pytest

    with pytest.raises(ValueError, match="overlaps partitions"):
        merge_run_indices([partition, partition])
