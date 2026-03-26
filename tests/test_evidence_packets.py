"""Tests for evidence packet generation and rendering."""

from fairifier.services.evidence_packets import build_evidence_context, build_evidence_packets


def test_build_evidence_packets_creates_grounded_packets():
    doc_info = {
        "title": "Earthworm RNA-seq exposure study",
        "research_domain": "ecotoxicology",
        "methodology": "RNA-seq",
        "keywords": ["earthworm", "ZnO"],
    }
    text = """
    # Title
    Earthworm RNA-seq exposure study

    ## Methods
    RNA-seq was used after ZnO exposure in earthworms.
    """

    packets = build_evidence_packets(doc_info, text, source_type="mineru_markdown")

    assert packets
    assert packets[0]["packet_id"].startswith("ep-")
    assert packets[0]["source_type"] == "mineru_markdown"
    assert any(packet["section"] == "Methods" for packet in packets)


def test_build_evidence_context_renders_compact_summary():
    packets = [
        {
            "packet_id": "ep-001",
            "field_candidate": "methodology",
            "value": "RNA-seq",
            "evidence_text": "Methods section mentions RNA-seq.",
            "section": "Methods",
            "source_type": "mineru_markdown",
            "confidence": 0.9,
            "provenance": {"agent": "DocumentParser"},
        }
    ]

    context = build_evidence_context(packets)

    assert "Evidence packets:" in context
    assert "methodology: RNA-seq" in context
