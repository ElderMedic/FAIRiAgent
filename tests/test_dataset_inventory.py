"""Dataset inventory tests, including split leakage and evidence policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.benchmark.dataset_inventory import _source_summary, build_inventory, validate_split_leakage


FIXTURES = Path(__file__).parents[1] / "evaluation" / "benchmark" / "fixtures"


def test_inventory_reports_distribution_and_does_not_require_evidence() -> None:
    inventory = build_inventory(
        FIXTURES / "benchmark_v2_smoke_manifest.json",
        project_root=Path(__file__).parents[1],
    )
    assert inventory["instance_count"] == 1
    assert inventory["evidence_annotation_required"] is False
    assert inventory["model_or_api_calls_performed"] is False
    assert inventory["instances"][0]["ground_truth"]["field_count"] == 1
    assert inventory["instances"][0]["distribution"]["supplementary_asset_count"] == "not_declared"


def test_split_leakage_detects_shared_project_group() -> None:
    instances = [
        {"instance_id": "a", "split": "development", "project_id": "P1"},
        {"instance_id": "b", "split": "verified", "project_id": "P1"},
    ]
    errors = validate_split_leakage(instances, {})
    assert any("project_id=P1" in error for error in errors)


def test_inventory_reads_document_fields_from_collection_ground_truth(tmp_path: Path) -> None:
    source = tmp_path / "document.md"
    source.write_text("a source document", encoding="utf-8")
    ground_truth = tmp_path / "collection.json"
    ground_truth.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc",
                        "ground_truth_fields": [
                            {"field_name": "a", "is_required": True},
                            {"field_name": "b", "is_required": False},
                        ],
                    }
                ]
            }
        )
    )
    manifest = json.loads((FIXTURES / "benchmark_v2_smoke_manifest.json").read_text())
    manifest["instances"][0].update(
        {"instance_id": "doc", "source_path": str(source), "ground_truth_path": str(ground_truth)}
    )
    for run in manifest["scheduled_runs"]:
        run["instance_id"] = "doc"
        run["run_id"] = run["run_id"].replace("fixture_document", "doc")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    inventory = build_inventory(manifest_path, project_root=tmp_path)
    detail = inventory["instances"][0]
    assert detail["ground_truth"]["field_count"] == 2
    assert detail["ground_truth"]["required_field_count"] == 1
    assert detail["source"]["characters"] == len("a source document")


def test_inventory_reports_distribution_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("a" * 12_000, encoding="utf-8")
    gold = tmp_path / "gold.json"
    gold.write_text(
        json.dumps(
            {
                "document_id": "doc",
                "ground_truth_fields": [{"field_name": "x", "is_required": True}],
            }
        ),
        encoding="utf-8",
    )
    manifest = json.loads((FIXTURES / "benchmark_v2_smoke_manifest.json").read_text())
    manifest["instances"][0].update(
        {
            "instance_id": "doc",
            "source_path": str(source),
            "ground_truth_path": str(gold),
            "strata": {"domain": "synthetic", "table_density": "high"},
        }
    )
    for run in manifest["scheduled_runs"]:
        run["instance_id"] = "doc"
        run["run_id"] = run["run_id"].replace("fixture_document", "doc")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    inventory = build_inventory(manifest_path, project_root=tmp_path)
    assert inventory["distribution_counts"]["length_bin"]["medium_10k_to_50k_characters"] == 1
    assert inventory["instances"][0]["distribution"]["table_density"] == "high"


def test_pdf_inventory_reports_layout_signals_without_inventing_strata(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    pdf = tmp_path / "paper.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "A short extracted paragraph.")
    document.save(str(pdf))
    document.close()
    summary = _source_summary(pdf)
    signals = summary["layout_signals"]
    assert signals["measurement_status"] == "passed"
    assert signals["text_block_count"] >= 1
    assert signals["pages_with_no_text"] == 0
    assert signals["tables_detected"] == 0
