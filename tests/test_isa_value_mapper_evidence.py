"""Tests for ISAValueMapper EvidenceStore integration (Plan §4.1)."""

from __future__ import annotations

import json
from pathlib import Path


def _make_evidence_store(tmp_path: Path, records: list) -> dict:
    jsonl_path = tmp_path / "source_workspace" / "evidence_store.jsonl"
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return {"jsonl_path": str(jsonl_path), "record_count": len(records)}


def test_build_evidence_store_summary_loads_and_groups_by_field(tmp_path):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    records = [
        {"field_name": "organism", "value": "Lumbricus terrestris", "confidence": 0.9,
         "retrieval_method": "section_map_reduce", "source_id": "source_001", "section": "Methods"},
        {"field_name": "organism", "value": "Earthworm", "confidence": 0.5,
         "retrieval_method": "section_map_reduce", "source_id": "source_001", "section": "Abstract"},
        {"field_name": "sample type", "value": "RNA", "confidence": 0.85,
         "retrieval_method": "section_map_reduce", "source_id": "source_001", "section": "Methods"},
    ]
    meta = _make_evidence_store(tmp_path, records)
    summary = ISAValueMapperAgent._build_evidence_store_summary(meta)

    assert summary is not None
    assert summary["field_count"] == 2
    assert summary["fields"]["organism"][0]["value"] == "Lumbricus terrestris"
    assert "sample type" in summary["fields"]


def test_build_evidence_store_summary_caps_per_field(tmp_path):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    records = [
        {"field_name": "ph", "value": str(i), "confidence": float(i) / 10,
         "retrieval_method": "section_map_reduce", "source_id": "s1", "section": ""}
        for i in range(10)
    ]
    meta = _make_evidence_store(tmp_path, records)
    summary = ISAValueMapperAgent._build_evidence_store_summary(meta, max_candidates_per_field=3)

    assert summary is not None
    assert len(summary["fields"]["ph"]) == 3
    assert float(summary["fields"]["ph"][0]["confidence"]) >= float(summary["fields"]["ph"][1]["confidence"])


def test_build_evidence_store_summary_returns_none_when_missing():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    assert ISAValueMapperAgent._build_evidence_store_summary({}) is None
    assert ISAValueMapperAgent._build_evidence_store_summary({"jsonl_path": "/nonexistent/path.jsonl"}) is None


def test_build_evidence_store_summary_skips_empty_values(tmp_path):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    records = [
        {"field_name": "organism", "value": "", "confidence": 0.9,
         "retrieval_method": "grep", "source_id": "s1", "section": ""},
        {"field_name": "organism", "value": "Lumbricus", "confidence": 0.7,
         "retrieval_method": "grep", "source_id": "s1", "section": ""},
    ]
    meta = _make_evidence_store(tmp_path, records)
    summary = ISAValueMapperAgent._build_evidence_store_summary(meta)

    assert summary is not None
    assert len(summary["fields"]["organism"]) == 1
    assert summary["fields"]["organism"][0]["value"] == "Lumbricus"


def test_build_matrix_heuristic_backfills_empty_cells_from_evidence():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    evidence_summary = {
        "fields": {
            "organism": [{"value": "Lumbricus terrestris", "confidence": 0.9,
                          "retrieval_method": "section_map_reduce", "source_id": "s1", "section": ""}],
            "collection site": [{"value": "Wageningen", "confidence": 0.8,
                                 "retrieval_method": "section_map_reduce", "source_id": "s1", "section": ""}],
        },
        "field_count": 2,
    }
    fields_by_level = {
        "investigation": [], "study": [], "observationunit": [],
        "sample": [
            {"field_name": "organism", "value": "", "isa_sheet": "sample", "entity_id": "sample_1"},
            {"field_name": "collection site", "value": "", "isa_sheet": "sample", "entity_id": "sample_1"},
            {"field_name": "sample name", "value": "S1", "isa_sheet": "sample", "entity_id": "sample_1"},
        ],
        "assay": [],
    }
    agent = ISAValueMapperAgent.__new__(ISAValueMapperAgent)
    matrix = agent._build_matrix_heuristic(fields_by_level, evidence_summary)

    row = matrix["sample"]["rows"][0]
    assert row.get("organism") == "Lumbricus terrestris"
    assert row.get("collection site") == "Wageningen"
    assert row.get("sample name") == "S1"


def test_build_matrix_heuristic_does_not_overwrite_existing_values():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    evidence_summary = {
        "fields": {
            "organism": [{"value": "Wrong value", "confidence": 0.95,
                          "retrieval_method": "section_map_reduce", "source_id": "s1", "section": ""}],
        },
        "field_count": 1,
    }
    fields_by_level = {
        "investigation": [], "study": [], "observationunit": [],
        "sample": [
            {"field_name": "organism", "value": "Correct value", "isa_sheet": "sample", "entity_id": "s1"},
        ],
        "assay": [],
    }
    agent = ISAValueMapperAgent.__new__(ISAValueMapperAgent)
    matrix = agent._build_matrix_heuristic(fields_by_level, evidence_summary)

    assert matrix["sample"]["rows"][0]["organism"] == "Correct value"
