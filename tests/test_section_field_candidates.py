"""Tests for section map-reduce field candidate extraction."""

from __future__ import annotations

from fairifier.agents.json_generator import JSONGeneratorAgent, FieldCandidate
from fairifier.services.evidence_store import evidence_from_section
from fairifier.services.section_field_candidates import extract_field_candidates_from_section


METHODS_TEXT = """## Materials and Methods

RNA extraction: RNeasy kit (Qiagen).
Sequencing method: Illumina NovaSeq 6000.
Sampling site latitude: 53.4 N
Sampling site longitude: 5.8 E
"""


def test_extract_field_candidates_from_label_value_lines():
    section = {
        "section_id": "source_001_section_002",
        "source_id": "source_001",
        "title": "Methods",
        "section_type": "methods",
        "char_start": 120,
        "char_end": 420,
        "text": METHODS_TEXT,
    }
    records = extract_field_candidates_from_section(section)
    fields = {record["field_name"] for record in records}
    assert "sequencing method" in fields
    assert any("NovaSeq" in record["value"] for record in records)


def test_evidence_from_section_prefers_field_candidates_over_outline():
    section = {
        "section_id": "source_001_section_002",
        "source_id": "source_001",
        "title": "Methods",
        "section_type": "methods",
        "char_start": 0,
        "char_end": 200,
        "text": METHODS_TEXT,
    }
    records = evidence_from_section(section)
    assert records
    assert all(record.get("kind") == "field_candidate" for record in records)


def test_json_generator_merges_section_field_candidates():
    agent = JSONGeneratorAgent()
    all_candidates: dict[str, list[FieldCandidate]] = {}
    state = {
        "section_field_candidates": [
            {
                "field_name": "sequencing method",
                "value": "Illumina NovaSeq 6000",
                "source_id": "source_001",
                "source_role": "main_manuscript",
                "relevance_score": 0.9,
                "evidence": "source_001:10-40 [role=main_manuscript] (Methods): NovaSeq",
                "confidence": 0.55,
                "char_start": 10,
                "char_end": 40,
                "retrieval_method": "section_map_reduce",
            }
        ],
        "retrieval_telemetry": {},
    }
    agent._merge_section_field_candidates(state, all_candidates)
    assert "sequencing method" in all_candidates
    assert all_candidates["sequencing method"][0].retrieval_method == "section_map_reduce"
    assert state["retrieval_telemetry"]["section_map_reduce"]["field_candidates_merged"] == 1
