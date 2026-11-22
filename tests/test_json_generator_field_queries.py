from __future__ import annotations

from fairifier.agents.json_generator import JSONGeneratorAgent


def _make_json_generator_without_init() -> JSONGeneratorAgent:
    return object.__new__(JSONGeneratorAgent)


def test_field_search_queries_adds_petase_aliases():
    agent = _make_json_generator_without_init()

    queries = agent._field_search_queries(
        "reaction temperature",
        "Assay condition for enzymatic PET depolymerization.",
    )

    lowered = {q.lower() for q in queries}
    assert "reaction temperature" in lowered
    assert "assay temperature" in lowered
    assert "incubation temperature" in lowered


def _publication_table_match():
    return {
        "source_id": "source_001",
        "table": "table_001",
        "row_index": 0,
        "source_row_index": 2,
        "column": "Rate | Initial",
        "row": {"Specimen": "A1", "Rate | Initial": "0"},
        "table_context": {
            "captions": ["Table 1. Initial rates at 30 °C."],
            "footnotes": ["Rates are in µmol cm−2 h−1; values are means."],
            "columns": ["Specimen", "Rate | Initial"],
            "header_status": "resolved",
            "provenance": {
                "artifact_path": "/source/paper_content_list.json",
                "page_idx": 2,
                "json_pointer": "/2/1",
            },
            "manifest_path": "/workspace/source_manifest.json",
            "raw_html": "DO_NOT_COPY_RAW_TABLE " * 1000,
            "cells": [{"text": "DO_NOT_COPY_GRID_CELL"}] * 1000,
            "grid_origins": [[[0, 0]]] * 1000,
        },
    }


def test_table_evidence_snippets_include_scientific_context_and_location():
    agent = _make_json_generator_without_init()
    snippets = agent._rank_field_snippets(
        "rate", [], [_publication_table_match()],
        {"source_001": {"source_role": "main_manuscript"}},
    )

    assert len(snippets) == 1
    snippet = snippets[0]
    assert "Initial rates at 30 °C" in snippet
    assert "Rates are in µmol cm−2 h−1" in snippet
    assert "Rate | Initial" in snippet and "A1" in snippet
    assert "paper_content_list.json" in snippet and "/2/1" in snippet
    assert "page_idx" in snippet
    assert "DO_NOT_COPY_RAW_TABLE" not in snippet
    assert "DO_NOT_COPY_GRID_CELL" not in snippet
    assert len(snippet) <= 2200


def test_table_evidence_snippets_bound_context_and_link_complete_evidence():
    agent = _make_json_generator_without_init()
    match = _publication_table_match()
    match["table_context"]["captions"] = ["Long caption " * 3000]
    match["table_context"]["footnotes"] = ["Long scientific footnote " * 3000]
    snippets = agent._rank_field_snippets("rate", [], [match], {})

    assert len(snippets[0]) <= 2200
    assert '"truncated":true' in snippets[0].replace(" ", "").lower()
    assert "/workspace/source_manifest.json" in snippets[0]
    assert "A1" in snippets[0] and "Rate | Initial" in snippets[0]


def test_table_evidence_snippets_retain_unresolved_leading_rows():
    agent = _make_json_generator_without_init()
    match = _publication_table_match()
    match["column"] = "column_2"
    match["row"] = {"column_1": "A1", "column_2": "0"}
    match["table_context"].update({
        "header_status": "unresolved",
        "columns": ["column_1", "column_2"],
        "leading_rows": [
            {"source_row_index": 0, "cells": ["Specimen", "Rate (µmol cm−2 h−1)"]},
            {"source_row_index": 1, "cells": ["", "0 h / 24 h"]},
        ],
    })

    snippets = agent._rank_field_snippets("rate", [], [match], {})

    assert "unresolved" in snippets[0]
    assert "leading_rows" in snippets[0]
    assert "0 h / 24 h" in snippets[0]
    assert "Rate (µmol cm−2 h−1)" in snippets[0]
    assert len(snippets[0]) <= 2200


def test_field_evidence_index_keeps_late_fields_after_shared_budget_is_exhausted(monkeypatch):
    from types import SimpleNamespace
    from fairifier.agents import json_generator as module

    agent = _make_json_generator_without_init()
    workspace = SimpleNamespace(manifest={"sources": [{"source_id": "source_001"}]})
    monkeypatch.setattr(module, "load_source_workspace", lambda metadata: workspace)
    monkeypatch.setattr(module.config, "metadata_field_search_enabled", True)
    monkeypatch.setattr(module.config, "hybrid_retrieval_enabled", False)
    monkeypatch.setattr(module.config, "table_full_scan_enabled", False)
    monkeypatch.setattr(module.config, "metadata_max_context_chars_per_field", 300)
    monkeypatch.setattr(agent, "_field_search_queries", lambda name, description: [name])
    monkeypatch.setattr(module, "grep_sources", lambda workspace, query, **kwargs: [{
        "source_id": "source_001", "source_path": "/source/article.md", "start": 0,
        "end": 2000, "excerpt": query + (" large" * 200 if query == "early field" else " late source fact"),
    }])
    monkeypatch.setattr(agent, "_collect_field_candidates", lambda *args: [])
    monkeypatch.setattr(agent, "_merge_section_field_candidates", lambda *args: None)
    state = {"session_id": "offline-test"}
    summary, _ = agent._build_field_source_evidence_context(
        {"manifest_path": "/source/source_manifest.json"},
        [{"term": "early field"}, {"term": "late field"}], state=state,
    )

    index = state["_field_evidence_by_name"]
    assert "source_001" in index["early field"][0]
    assert "late source fact" in index["late field"][0]
    assert "truncated" in summary.lower()


def test_generator_forwards_field_evidence_index_without_turning_it_into_values(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    agent = _make_json_generator_without_init()
    captured = {}

    async def generate(*args, **kwargs):
        captured.update(kwargs)
        return []

    agent.llm_helper = SimpleNamespace(generate_complete_metadata=generate)
    agent.logger = SimpleNamespace(info=lambda *args: None)
    monkeypatch.setattr(agent, "_postcheck_source_grounding", lambda fields, *args: (fields, 0))
    evidence = {"rate": ["- source_001:1-30 specimen B7 rate 0 mmol/L/h"]}
    fields, _ = asyncio.run(agent._generate_with_llm(
        {}, [{"term": "rate", "metadata": {"isa_sheet": "assay"}}],
        "Shared context", field_evidence_by_name=evidence,
    ))

    assert captured["field_evidence_by_name"] == evidence
    assert fields == []


def test_generator_passes_authoritative_plan_separately_from_clipped_document_context(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    agent = _make_json_generator_without_init()
    captured = {}

    async def generate(*args, **kwargs):
        captured["document_context"] = args[2]
        captured.update(kwargs)
        return []

    agent.llm_helper = SimpleNamespace(generate_complete_metadata=generate)
    agent.logger = SimpleNamespace(info=lambda *args: None)
    monkeypatch.setattr(agent, "_postcheck_source_grounding", lambda fields, *args: (fields, 0))
    plan = {"levels": [{"level": "assay", "entities": [{
        "row_id": "ASS_LATE", "parent_row_id": "SAM_LATE", "attributes": [],
    }]}]}
    asyncio.run(agent._generate_with_llm(
        {}, [{"term": "rate", "metadata": {"isa_sheet": "assay"}}],
        "Bounded source context", entity_plan=plan,
    ))

    assert captured["entity_plan"] == plan
    assert captured["document_context"] == "Bounded source context"
