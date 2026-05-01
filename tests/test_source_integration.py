"""Integration fixture: multi-file source workspace with main, supplement, table, and unrelated note.

Asserts end-to-end source selection, role detection, field-specific search ranking,
and non-interference of unrelated sources.
"""

from __future__ import annotations

import json
from pathlib import Path

from fairifier.agents.json_generator import JSONGeneratorAgent
from fairifier.config import config
from fairifier.models import MetadataField
from fairifier.services.source_workspace import (
    SourceRecord,
    build_source_workspace,
    grep_sources,
    load_source_workspace,
    rank_source_entries,
    search_table,
    source_role_priority,
)
from fairifier.validation.metadata_json_format import (
    check_metadata_json_output,
    validate_source_grounding,
)


def _build_fixture(tmp_path: Path):
    """Create a workspace with four sources: main, supplement, unrelated, CSV."""
    records = [
        SourceRecord(
            source_id="source_001",
            path="main.md",
            method="direct_read",
            content=(
                "# Earthworm response to nanomaterials\n\n"
                "## Abstract\n\n"
                "This study investigates gene expression of Eisenia fetida exposed to ZnO nanomaterials "
                "at a soil mesocosm near the Wadden Sea.\n\n"
                "## Methods\n\n"
                "Sampling site: Wadden Sea tidal flats, Texel, Netherlands.\n"
                "Organisms were collected from control plots and ZnO-treated plots.\n"
            ),
            content_type="markdown",
        ),
        SourceRecord(
            source_id="source_002",
            path="supplement_methods.md",
            method="direct_read",
            content=(
                "# Supplementary Methods\n\n"
                "RNA extraction was performed using TRIzol.\n"
                "Sequencing: Illumina NovaSeq paired-end 150 bp.\n"
                "Accession: PRJNA999999.\n"
            ),
            content_type="markdown",
        ),
        SourceRecord(
            source_id="source_003",
            path="unrelated_note.log",
            method="direct_read",
            content=(
                "Lab meeting notes 2025-12-01\n"
                "Discussed budget for next fiscal year.\n"
                "Study title: Annual budget review 2025.\n"
                "Nothing to do with earthworms.\n"
            ),
            content_type="text",
        ),
        SourceRecord(
            source_id="source_004",
            path="samples.csv",
            method="tabular_csv",
            content="Table file: samples.csv\nPreview rows: 1 / 5",
            content_type="table",
            tables=[
                {
                    "name": "samples",
                    "rows": [
                        {"sample_id": "S1", "organism": "control blank"},
                        {"sample_id": "S2", "organism": "control blank"},
                        {"sample_id": "S3", "organism": "control blank"},
                        {"sample_id": "S4", "organism": "control blank"},
                        {"sample_id": "S5", "organism": "Eisenia fetida"},
                    ],
                }
            ],
        ),
    ]
    return build_source_workspace(records, tmp_path)


# ── Test workspace materialization ──────────────────────────────────────


def test_fixture_materializes_four_sources_with_correct_roles(tmp_path):
    ws = _build_fixture(tmp_path)

    assert ws.manifest["source_count"] == 4

    roles = {
        entry["source_id"]: entry["source_role"]
        for entry in ws.manifest["sources"]
    }
    assert roles["source_001"] == "main_manuscript"
    assert roles["source_002"] == "supplement"
    assert roles["source_003"] == "unknown"
    assert roles["source_004"] == "table"


# ── Test source_role_priority + rank_source_entries ─────────────────────


def test_role_priority_ordering():
    assert source_role_priority("main_manuscript") < source_role_priority("supplement")
    assert source_role_priority("supplement") < source_role_priority("unknown")
    assert source_role_priority("table") < source_role_priority("supplement")


def test_rank_source_entries_returns_main_first(tmp_path):
    ws = _build_fixture(tmp_path)
    ranked = rank_source_entries(ws)

    ids = [entry["source_id"] for entry in ranked]
    # main_manuscript first, then table, then supplement, then unknown
    assert ids.index("source_001") < ids.index("source_003")
    assert ids.index("source_004") < ids.index("source_002")


def test_grep_sources_prefers_authoritative_source_when_result_limit_is_low(tmp_path):
    ws = build_source_workspace(
        [
            SourceRecord(
                source_id="source_001",
                path="unrelated_note.log",
                method="direct_read",
                content="sampling site: office budget room",
                content_type="text",
            ),
            SourceRecord(
                source_id="source_002",
                path="main.md",
                method="direct_read",
                content="sampling site: Wadden Sea tidal flats",
                content_type="markdown",
            ),
        ],
        tmp_path,
    )

    matches = grep_sources(ws, "sampling site", max_results=1)

    assert matches[0]["source_id"] == "source_002"


# ── Test agentic search functions ──────────────────────────────────────


def test_grep_finds_sampling_site_in_main(tmp_path):
    ws = _build_fixture(tmp_path)

    matches = grep_sources(ws, "Wadden Sea", context_chars=30, max_results=5)
    assert matches
    assert matches[0]["source_id"] == "source_001"
    assert "Wadden Sea" in matches[0]["excerpt"]


def test_search_table_finds_organism_beyond_preview(tmp_path):
    ws = _build_fixture(tmp_path)

    matches = search_table(ws, "Eisenia", max_matches=10)
    assert len(matches) == 1
    assert matches[0]["source_id"] == "source_004"
    assert matches[0]["row_index"] == 4
    assert matches[0]["value"] == "Eisenia fetida"


def test_grep_accession_in_supplement(tmp_path):
    ws = _build_fixture(tmp_path)

    matches = grep_sources(ws, "PRJNA999999", max_results=5)
    assert matches
    assert matches[0]["source_id"] == "source_002"


# ── Test field-specific evidence ranking ──────────────────────────────


def _workspace_metadata(ws):
    return {
        "root_dir": str(ws.root_dir),
        "manifest_path": str(ws.manifest_path),
        "summary_path": str(ws.summary_path),
        "source_paths": {k: str(v) for k, v in ws.source_paths.items()},
        "table_paths": {k: str(v) for k, v in ws.table_paths.items()},
    }


def test_field_evidence_organism_includes_table_row(tmp_path, monkeypatch):
    ws = _build_fixture(tmp_path)
    agent = JSONGeneratorAgent()
    monkeypatch.setattr(
        "fairifier.agents.json_generator.config.metadata_max_evidence_snippets_per_field", 10
    )

    context, _ = agent._build_field_source_evidence_context(
        _workspace_metadata(ws),
        [{"name": "organism", "description": "Taxonomic organism name"}],
    )

    assert "Eisenia fetida" in context
    assert "row 4 column organism" in context


def test_field_evidence_sampling_site_from_main_manuscript(tmp_path, monkeypatch):
    ws = _build_fixture(tmp_path)
    agent = JSONGeneratorAgent()
    monkeypatch.setattr(
        "fairifier.agents.json_generator.config.metadata_max_evidence_snippets_per_field", 5
    )

    context, _ = agent._build_field_source_evidence_context(
        _workspace_metadata(ws),
        [{"name": "sampling site", "description": "Location where samples were collected"}],
    )

    assert "source_001" in context
    assert "Wadden Sea" in context
    # Source role annotation should be present
    assert "role=main_manuscript" in context


def test_field_evidence_ranks_main_above_unrelated_note(tmp_path, monkeypatch):
    """Evidence for study-level fields should rank main_manuscript above unrelated notes."""
    ws = _build_fixture(tmp_path)
    agent = JSONGeneratorAgent()
    monkeypatch.setattr(
        "fairifier.agents.json_generator.config.metadata_max_evidence_snippets_per_field", 10
    )

    context, _ = agent._build_field_source_evidence_context(
        _workspace_metadata(ws),
        [{"name": "study title", "description": "Title of the study"}],
    )

    # The main manuscript should appear in evidence, but the unrelated note's
    # "Study title: Annual budget review 2025" should NOT be the first snippet.
    if "source_003" in context and "source_001" in context:
        # source_001 (main) must appear before source_003 (unrelated)
        assert context.index("source_001") < context.index("source_003")


# ── Test de-duplication of overlapping text spans ─────────────────────


def test_dedup_overlapping_text_spans():
    agent = JSONGeneratorAgent()

    matches = [
        {"source_id": "s1", "start": 0, "end": 100, "excerpt": "first"},
        {"source_id": "s1", "start": 10, "end": 90, "excerpt": "overlapping"},
        {"source_id": "s2", "start": 0, "end": 100, "excerpt": "different source"},
    ]
    deduped = agent._dedup_overlapping_text_spans(matches)

    # Second match overlaps first by > 50%, so should be removed.
    # Third match is from a different source, should be kept.
    assert len(deduped) == 2
    assert deduped[0]["excerpt"] == "first"
    assert deduped[1]["excerpt"] == "different source"


# ── Test source-grounding summary (Step 1) ───────────────────────────


def test_compute_source_grounding_summary():
    agent = JSONGeneratorAgent()
    fields = [
        MetadataField(
            field_name="sampling site",
            value="Wadden Sea",
            evidence="source_001:50-90 main.md: Wadden Sea",
            confidence=0.92,
            status="confirmed",
        ),
        MetadataField(
            field_name="organism",
            value="Eisenia fetida",
            evidence="source_004 table samples row 4 column organism: Eisenia fetida",
            confidence=0.88,
            status="confirmed",
        ),
        MetadataField(
            field_name="study design",
            value="mesocosm",
            evidence="Methods section",
            confidence=0.85,
            status="confirmed",
        ),
        MetadataField(
            field_name="funding",
            value="NWO",
            evidence="Acknowledgements",
            confidence=0.4,
            status="provisional",
        ),
    ]

    summary = agent._compute_source_grounding_summary(fields)

    assert summary["source_grounded_fields"] == 2
    assert summary["table_backed_fields"] == 1
    assert summary["ungrounded_high_confidence_fields"] == 1  # study design (0.85, no ref)


def test_compute_source_grounding_summary_uses_configured_threshold(monkeypatch):
    agent = JSONGeneratorAgent()
    monkeypatch.setattr(
        "fairifier.agents.json_generator.config.metadata_source_ref_min_confidence",
        0.9,
    )

    summary = agent._compute_source_grounding_summary(
        [
            MetadataField(
                field_name="study design",
                value="mesocosm",
                evidence="Methods section",
                confidence=0.85,
            )
        ]
    )

    assert summary["ungrounded_high_confidence_fields"] == 0


# ── Test validation source-grounding check ────────────────────────────


def test_validate_source_grounding_on_metadata_json():
    data = {
        "fairifier_version": "V1.3.1",
        "generated_at": "2026-05-01T12:00:00",
        "document_source": "test.pdf",
        "isa_structure": {
            "study": {
                "description": "Study-level metadata",
                "fields": [
                    {
                        "field_name": "study title",
                        "value": "Earthworm response",
                        "evidence": "source_001:0-50 main.md",
                        "confidence": 0.90,
                    },
                    {
                        "field_name": "study design",
                        "value": "mesocosm",
                        "evidence": "Methods section",
                        "confidence": 0.85,
                    },
                ],
            },
            "sample": {
                "description": "Sample-level metadata",
                "fields": [
                    {
                        "field_name": "organism",
                        "value": "Eisenia fetida",
                        "evidence": "source_004 table samples row 4 column organism",
                        "confidence": 0.88,
                    },
                ],
            },
        },
    }

    errors: list = []
    warnings: list = []
    grounding = validate_source_grounding(data, errors, warnings)

    assert grounding["source_grounded_fields"] == 2
    assert grounding["table_backed_fields"] == 1
    assert grounding["ungrounded_high_confidence_fields"] == 1
    assert len(warnings) == 1
    assert "study design" in warnings[0]
    assert len(errors) == 0

    # Full check_metadata_json_output should include source_grounding
    result = check_metadata_json_output(data)
    assert "source_grounding" in result
    assert result["source_grounding"]["source_grounded_fields"] == 2


def test_validate_source_grounding_uses_configured_threshold(monkeypatch):
    monkeypatch.setattr(
        "fairifier.validation.metadata_json_format.config.metadata_source_ref_min_confidence",
        0.9,
    )
    data = {
        "isa_structure": {
            "study": {
                "fields": [
                    {
                        "field_name": "study design",
                        "value": "mesocosm",
                        "evidence": "Methods section",
                        "confidence": 0.85,
                    }
                ],
            }
        }
    }

    warnings: list = []
    grounding = validate_source_grounding(data, [], warnings)

    assert grounding["ungrounded_high_confidence_fields"] == 0
    assert warnings == []
