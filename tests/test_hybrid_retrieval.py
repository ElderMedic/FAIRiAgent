"""Tests for hybrid retrieval chunking and RRF fusion."""

from __future__ import annotations

import json
from pathlib import Path

from fairifier.services.chunking import chunk_source_text, infer_section_type
from fairifier.services.semantic_index import reciprocal_rank_fusion
from fairifier.services.source_workspace import (
    SourceRecord,
    build_source_workspace,
    hybrid_search_sources,
)


def test_infer_section_type_recognizes_methods():
    assert infer_section_type("Materials and Methods") == "methods"
    assert infer_section_type("Results and Discussion") in {"results", "discussion"}


def test_chunk_source_text_splits_headings_and_paragraphs():
    text = (
        "# Introduction\n\n"
        "We studied earthworm transcriptomics in contaminated soil.\n\n"
        "## Methods\n\n"
        "RNA was extracted using a standard kit and sequenced on Illumina.\n\n"
        "## Results\n\n"
        "Differential expression revealed stress response genes."
    )
    result = chunk_source_text("source_001", text)
    assert result.sections
    assert result.chunks
    assert any(section.section_type == "introduction" for section in result.sections)
    assert any(section.section_type == "methods" for section in result.sections)


def test_reciprocal_rank_fusion_prefers_items_in_both_lists():
    lexical = [
        {"source_id": "s1", "start": 10, "end": 20, "excerpt": "alpha"},
        {"source_id": "s1", "start": 100, "end": 120, "excerpt": "beta"},
    ]
    semantic = [
        {"source_id": "s1", "start": 10, "end": 20, "excerpt": "alpha"},
        {"source_id": "s2", "start": 0, "end": 8, "excerpt": "gamma"},
    ]
    fused = reciprocal_rank_fusion([lexical, semantic], k=60)
    assert fused
    assert fused[0]["source_id"] == "s1"
    assert fused[0]["start"] == 10


def test_hybrid_search_sources_lexical_fallback_without_semantic_index(tmp_path: Path):
    workspace = build_source_workspace(
        [
            SourceRecord(
                source_id="source_001",
                path="paper.md",
                method="direct_read",
                content="The sampling site was Wadden Sea with elevation 2 m.",
                content_type="markdown",
            )
        ],
        tmp_path,
    )
    telemetry = {}
    hits = hybrid_search_sources(
        workspace,
        ["Wadden Sea", "elevation"],
        semantic_index=None,
        telemetry=telemetry,
    )
    assert hits
    assert any("Wadden Sea" in (hit.get("excerpt") or "") for hit in hits)
    assert telemetry.get("lexical_hit_count", 0) >= 1
