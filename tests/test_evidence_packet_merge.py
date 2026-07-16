"""Evidence packet merge: DocumentParser must not erase SectionMapReduce packets."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from fairifier.agents.document_parser import DocumentParserAgent
from fairifier.services.evidence_packets import merge_evidence_packets


def test_merge_evidence_packets_preserves_prior_and_appends_new():
    existing = [
        {
            "packet_id": "smr-001",
            "field_candidate": "sample temperature",
            "value": "4 °C",
            "evidence_text": "Samples stored at 4 °C",
            "section": "Methods",
            "source_type": "section_map_reduce",
            "confidence": 0.8,
            "provenance": {"agent": "SectionMapReduce", "strategy": "section_coverage"},
            "produced_by": "section_map_reduce",
        }
    ]
    new = [
        {
            "packet_id": "ep-001",
            "field_candidate": "title",
            "value": "Cold stress study",
            "evidence_text": "Cold stress study",
            "section": "Title",
            "source_type": "mineru_markdown",
            "confidence": 0.9,
            "provenance": {
                "agent": "DocumentParser",
                "strategy": "document_parser_structured_extraction",
            },
        }
    ]

    merged = merge_evidence_packets(existing, new)

    assert len(merged) == 2
    assert merged[0]["field_candidate"] == "sample temperature"
    assert merged[1]["field_candidate"] == "title"


def test_merge_evidence_packets_deduplicates_identical_payloads():
    packet = {
        "packet_id": "smr-001",
        "field_candidate": "organism",
        "value": "Pisum sativum",
        "evidence_text": "Pisum sativum cold response",
        "section": "Abstract",
        "source_type": "section_map_reduce",
        "confidence": 0.7,
        "provenance": {"agent": "SectionMapReduce"},
        "produced_by": "section_map_reduce",
        "source_id": "source_001",
        "char_start": 10,
        "char_end": 40,
    }
    merged = merge_evidence_packets([packet], [{**packet, "packet_id": "ep-999"}])
    assert len(merged) == 1
    assert merged[0]["packet_id"] == "smr-001"


def test_document_parser_preserves_section_map_reduce_evidence_packets(monkeypatch):
    """Regression for §12.1: DocumentParser must merge, not replace, prior packets."""
    from fairifier.config import config

    agent = DocumentParserAgent()

    prior = [
        {
            "packet_id": "smr-001",
            "field_candidate": "sample temperature",
            "value": "4 °C",
            "evidence_text": "Samples stored at 4 °C",
            "section": "Methods",
            "source_type": "section_map_reduce",
            "confidence": 0.8,
            "provenance": {"agent": "SectionMapReduce", "strategy": "section_coverage"},
            "produced_by": "section_map_reduce",
        }
    ]

    async def fake_llm(*_args, **_kwargs) -> Dict[str, Any]:
        return {
            "title": "Cold stress study",
            "abstract": "A pea cold stress experiment.",
            "authors": ["A. Author"],
            "keywords": ["pea", "cold"],
            "research_domain": "plant biology",
        }

    monkeypatch.setattr(config, "enable_deep_agents", False)
    monkeypatch.setattr(agent.llm_helper, "extract_document_info", fake_llm)

    state = {
        "document_path": "paper.md",
        "document_content": "# Cold stress study\n\nA pea cold stress experiment.\n",
        "document_text_path": None,
        "document_conversion": {"method": "direct_read"},
        "evidence_packets": prior,
        "confidence_scores": {},
        "context": {},
        "errors": [],
    }

    result = asyncio.run(agent.execute(state))
    packets = result.get("evidence_packets") or []

    assert any(
        p.get("produced_by") == "section_map_reduce"
        or (p.get("provenance") or {}).get("agent") == "SectionMapReduce"
        for p in packets
    ), "SectionMapReduce evidence was overwritten by DocumentParser"
    assert any(p.get("field_candidate") == "title" for p in packets)
    assert any(p.get("field_candidate") == "sample temperature" for p in packets)
    assert result["context"].get("last_parser_evidence_packets")
    assert all(
        (p.get("provenance") or {}).get("agent") == "DocumentParser"
        for p in result["context"]["last_parser_evidence_packets"]
    )
