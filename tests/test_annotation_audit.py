"""Ground-truth overlap and evidence-policy audit tests."""

import json
from pathlib import Path

import pytest

from evaluation.benchmark.annotation_audit import (
    audit_collections,
    merge_non_overlapping_collections,
)


def _write_collection(path: Path, value: str) -> None:
    path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "shared",
                        "document_path": "shared.md",
                        "metadata": {"domain": "synthetic"},
                        "ground_truth_fields": [{"field_name": value}],
                    }
                ]
            }
        )
    )


def test_annotation_audit_distinguishes_different_overlap_without_requiring_evidence(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    _write_collection(left, "field_a")
    _write_collection(right, "field_b")
    report = audit_collections([left, right])
    overlap = report["pairwise_overlap"][0]
    assert overlap["shared_document_ids"] == ["shared"]
    assert overlap["annotation_different_ids"] == ["shared"]
    assert report["documents"][0]["contains_evidence_annotation"] is False
    assert report["evidence_annotation_required"] is False
    assert report["model_or_api_calls_performed"] is False


def test_merge_requires_explicit_authoritative_source_for_overlap(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    _write_collection(left, "field_a")
    _write_collection(right, "field_b")
    with pytest.raises(ValueError, match="authoritative collection"):
        merge_non_overlapping_collections([left, right], authoritative_overlaps={})

    merged = merge_non_overlapping_collections(
        [left, right],
        authoritative_overlaps={"shared": str(right)},
    )
    assert merged["documents"][0]["ground_truth_fields"][0]["field_name"] == "field_b"
    assert merged["provenance"]["selected_source_by_document"]["shared"] == str(right)
    assert merged["evidence_annotation_required"] is False
    assert merged["model_or_api_calls_performed"] is False


def test_merge_rejects_unknown_authoritative_choice(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    _write_collection(left, "field_a")
    with pytest.raises(ValueError, match="absent from collections"):
        merge_non_overlapping_collections(
            [left],
            authoritative_overlaps={"missing": str(left)},
        )


def test_merge_carries_adjacent_values_path_from_selected_collection(tmp_path: Path) -> None:
    collection = tmp_path / "collection.json"
    _write_collection(collection, "field_a")
    values_dir = tmp_path / "values"
    values_dir.mkdir()
    values = values_dir / "ground_truth_shared_values.json"
    values.write_text(json.dumps({"document_id": "shared"}), encoding="utf-8")
    merged = merge_non_overlapping_collections([collection], authoritative_overlaps={})
    assert merged["documents"][0]["ground_truth_values_path"] == str(values)
