"""Tests for hybrid retrieval chunking and RRF fusion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

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


def test_json_generator_persists_retrieval_telemetry_on_state(tmp_path: Path):
    """LangGraph requires top-level reassignment; nested dict mutation is not enough."""
    from fairifier.agents.json_generator import JSONGeneratorAgent

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
    workspace_meta = {
        "root_dir": str(workspace.root_dir),
        "manifest_path": str(workspace.manifest_path),
        "summary_path": str(workspace.summary_path),
        "source_paths": {sid: str(path) for sid, path in workspace.source_paths.items()},
        "table_paths": {},
    }
    state = {
        "session_id": "test_telemetry",
        "semantic_index": {"available": False, "status": "unavailable"},
        "retrieval_telemetry": {},
    }
    agent = JSONGeneratorAgent()
    knowledge_items = [{"field_name": "elevation", "name": "elevation", "description": "site elevation"}]
    agent._build_field_source_evidence_context(workspace_meta, knowledge_items, state=state)
    assert state["retrieval_telemetry"]
    assert "elevation" in state["retrieval_telemetry"]
    assert state["retrieval_telemetry"]["elevation"].get("lexical_hit_count", 0) >= 0


def test_field_source_evidence_context_reads_knowledge_retriever_item_shape(tmp_path: Path):
    """`state["retrieved_knowledge"]` items use `term`/`definition`/`metadata`
    keys (see KnowledgeRetrieverAgent.execute), not `name`/`field_name`/
    `description`. The field-evidence search must resolve field identity from
    the real shape, or every item is silently skipped and
    `retrieval_telemetry` stays empty even though hybrid search succeeds."""
    from fairifier.agents.json_generator import JSONGeneratorAgent

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
    workspace_meta = {
        "root_dir": str(workspace.root_dir),
        "manifest_path": str(workspace.manifest_path),
        "summary_path": str(workspace.summary_path),
        "source_paths": {sid: str(path) for sid, path in workspace.source_paths.items()},
        "table_paths": {},
    }
    state = {
        "session_id": "test_telemetry_real_shape",
        "semantic_index": {"available": False, "status": "unavailable"},
        "retrieval_telemetry": {},
    }
    agent = JSONGeneratorAgent()
    knowledge_items = [
        {
            "term": "elevation",
            "definition": "Elevation of the sampling site above sea level",
            "source": "FAIR-DS-API",
            "ontology_uri": None,
            "confidence": 0.95,
            "metadata": {"name": "elevation", "definition": "site elevation"},
        }
    ]
    context, _ = agent._build_field_source_evidence_context(
        workspace_meta, knowledge_items, state=state
    )
    assert state["retrieval_telemetry"], (
        "retrieval_telemetry stayed empty — field name/description was not "
        "resolved from the KnowledgeRetriever item shape"
    )
    assert "elevation" in state["retrieval_telemetry"]
    assert "Wadden Sea" in context or "elevation" in context.lower()


def test_field_evidence_telemetry_not_truncated_by_prompt_budget(tmp_path: Path):
    """Prompt char budget must not stop hybrid telemetry for later fields."""
    from fairifier.agents.json_generator import JSONGeneratorAgent
    from fairifier import config as cfg

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
    workspace_meta = {
        "root_dir": str(workspace.root_dir),
        "manifest_path": str(workspace.manifest_path),
        "summary_path": str(workspace.summary_path),
        "source_paths": {sid: str(path) for sid, path in workspace.source_paths.items()},
        "table_paths": {},
    }
    state = {
        "session_id": "test_telemetry_budget",
        "semantic_index": {"available": False, "status": "unavailable"},
        "retrieval_telemetry": {},
    }
    agent = JSONGeneratorAgent()
    knowledge_items = [
        {
            "term": f"field_{i}",
            "definition": f"description for field {i}",
            "metadata": {"name": f"field_{i}"},
        }
        for i in range(5)
    ]
    old_budget = cfg.config.metadata_max_context_chars_per_field
    try:
        cfg.config.metadata_max_context_chars_per_field = 50
        agent._build_field_source_evidence_context(
            workspace_meta, knowledge_items, state=state
        )
        assert len(state["retrieval_telemetry"]) == len(knowledge_items)
    finally:
        cfg.config.metadata_max_context_chars_per_field = old_budget


def test_format_section_outline_markdown_includes_section_metadata():
    from fairifier.agents.document_parser import DocumentParserAgent

    sections = [
        {
            "section_id": "source_001_section_001",
            "title": "Introduction",
            "section_type": "introduction",
            "source_id": "source_001",
            "char_start": 0,
            "char_end": 1200,
        },
        {
            "section_id": "source_001_section_002",
            "title": "Methods",
            "section_type": "methods",
            "source_id": "source_001",
            "char_start": 1200,
            "char_end": 4500,
        },
    ]
    outline = DocumentParserAgent._format_section_outline_markdown(sections)
    assert "Introduction" in outline
    assert "methods" in outline
    assert "Total sections: 2" in outline
    assert "source_001" in outline


def test_hybrid_search_returns_lexical_when_adaptive_and_lexical_hits(tmp_path: Path):
    from fairifier import config as cfg

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
    old_shadow = cfg.config.retrieval_shadow_mode
    old_adaptive = cfg.config.retrieval_prompt_adaptive_lexical
    try:
        cfg.config.retrieval_shadow_mode = False
        cfg.config.retrieval_prompt_adaptive_lexical = True
        telemetry: Dict[str, Any] = {}
        hits = hybrid_search_sources(
            workspace, ["Wadden Sea"], semantic_index=None, telemetry=telemetry
        )
        assert hits
        assert telemetry.get("prompt_mode") == "lexical_preferred"
    finally:
        cfg.config.retrieval_shadow_mode = old_shadow
        cfg.config.retrieval_prompt_adaptive_lexical = old_adaptive


def test_hybrid_search_returns_hybrid_output_when_shadow_mode_disabled(tmp_path: Path):
    from fairifier import config as cfg

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
    old_shadow = cfg.config.retrieval_shadow_mode
    try:
        cfg.config.retrieval_shadow_mode = False
        hits = hybrid_search_sources(workspace, ["Wadden Sea"], semantic_index=None)
        assert hits
    finally:
        cfg.config.retrieval_shadow_mode = old_shadow


def test_blend_lexical_first_prefers_lexical_backed_spans():
    from fairifier.services.source_workspace import _blend_lexical_first_hybrid_output

    lexical = [
        {"source_id": "s1", "start": 10, "end": 20, "excerpt": "alpha"},
        {"source_id": "s1", "start": 100, "end": 120, "excerpt": "beta"},
    ]
    hybrid = [
        {"source_id": "s2", "start": 0, "end": 8, "excerpt": "semantic-only"},
        {"source_id": "s1", "start": 10, "end": 20, "excerpt": "alpha"},
    ]
    blended = _blend_lexical_first_hybrid_output(hybrid, lexical, final_limit=2)
    assert len(blended) == 2
    assert blended[0]["source_id"] == "s1"
    assert blended[0]["start"] == 10
    assert blended[1]["source_id"] == "s2"
