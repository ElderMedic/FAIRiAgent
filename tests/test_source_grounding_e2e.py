"""End-to-end source grounding validation test.

Tests the full pipeline from workspace → field evidence → statistics → validation
without any LLM dependency. Exercises:
  - _compute_source_grounding_summary on realistic MetadataField lists
  - statistics.source_grounding_summary in _generate_json_output output
  - check_metadata_json_output parsing the emitted JSON
  - warning emission for ungrounded high-confidence fields
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fairifier.agents.json_generator import JSONGeneratorAgent
from fairifier.models import MetadataField
from fairifier.services.source_workspace import (
    SourceRecord,
    build_source_workspace,
)
from fairifier.validation.metadata_json_format import (
    check_metadata_json_output,
    validate_source_grounding,
)


# ── Fixtures ────────────────────────────────────────────────────────────


def _make_realistic_fields() -> list[MetadataField]:
    """Create a representative field set mirroring a real multi-source run."""
    return [
        # Grounded: text reference from main manuscript
        MetadataField(
            field_name="sampling site",
            value="Wadden Sea tidal flats, Texel, Netherlands",
            evidence="source_001:250-310 main.md: Sampling site: Wadden Sea tidal flats",
            confidence=0.92,
            status="confirmed",
        ),
        # Grounded: text reference from supplement
        MetadataField(
            field_name="sequencing platform",
            value="Illumina NovaSeq",
            evidence="source_002:55-90 supplement_methods.md: Sequencing: Illumina NovaSeq",
            confidence=0.89,
            status="confirmed",
        ),
        # Grounded: table row reference
        MetadataField(
            field_name="organism",
            value="Eisenia fetida",
            evidence="source_004 table samples row 4 column organism: Eisenia fetida",
            confidence=0.88,
            status="confirmed",
        ),
        # Ungrounded, HIGH confidence (above 0.75 threshold) → should be flagged
        MetadataField(
            field_name="study design",
            value="mesocosm experiment",
            evidence="Methods section describes soil mesocosm setup",
            confidence=0.85,
            status="confirmed",
        ),
        # Ungrounded, LOW confidence → should NOT be flagged (below threshold)
        MetadataField(
            field_name="funding agency",
            value="NWO",
            evidence="Acknowledgements section",
            confidence=0.40,
            status="provisional",
        ),
        # Downgraded by postcheck → status=provisional, already low confidence
        MetadataField(
            field_name="contact email",
            value="author@example.com",
            evidence="missing source reference (auto-downgraded)",
            confidence=0.60,
            status="provisional",
        ),
    ]


# ── Phase A.1: _compute_source_grounding_summary ─────────────────────


def test_e2e_grounding_summary_counts():
    agent = JSONGeneratorAgent()
    fields = _make_realistic_fields()

    summary = agent._compute_source_grounding_summary(fields)

    assert summary["source_grounded_fields"] == 3   # sampling site, sequencing, organism
    assert summary["table_backed_fields"] == 1       # organism only
    assert summary["ungrounded_high_confidence_fields"] == 1  # study design (conf=0.85)


def test_e2e_grounding_summary_no_fields():
    agent = JSONGeneratorAgent()
    summary = agent._compute_source_grounding_summary([])

    assert summary == {
        "source_grounded_fields": 0,
        "table_backed_fields": 0,
        "ungrounded_high_confidence_fields": 0,
    }


def test_e2e_grounding_summary_all_grounded():
    agent = JSONGeneratorAgent()
    fields = [
        MetadataField(
            field_name=f"field_{i}",
            value="value",
            evidence=f"source_001:{i*10}-{i*10+5} main.md: excerpt",
            confidence=0.9,
            status="confirmed",
        )
        for i in range(5)
    ]
    summary = agent._compute_source_grounding_summary(fields)

    assert summary["source_grounded_fields"] == 5
    assert summary["ungrounded_high_confidence_fields"] == 0


# ── Phase A.2: validate_source_grounding on realistic JSON ───────────


def _make_metadata_json(fields: list[MetadataField]) -> dict:
    """Build a minimal metadata.json-shaped dict from MetadataField list."""
    isa_fields = [
        {
            "field_name": f.field_name,
            "value": f.value,
            "evidence": f.evidence,
            "confidence": f.confidence,
            "status": f.status,
        }
        for f in fields
    ]
    return {
        "fairifier_version": "V1.5.0",
        "generated_at": "2026-05-01T12:00:00",
        "document_source": "test_e2e.pdf",
        "isa_structure": {
            "study": {
                "description": "Study-level metadata",
                "fields": isa_fields[:3],
            },
            "sample": {
                "description": "Sample-level metadata",
                "fields": isa_fields[3:],
            },
        },
    }


def test_e2e_validate_source_grounding_counters():
    fields = _make_realistic_fields()
    data = _make_metadata_json(fields)

    errors: list = []
    warnings: list = []
    grounding = validate_source_grounding(data, errors, warnings)

    assert grounding["source_grounded_fields"] == 3
    assert grounding["table_backed_fields"] == 1
    assert grounding["ungrounded_high_confidence_fields"] == 1
    assert len(errors) == 0


def test_e2e_validate_source_grounding_warning_message():
    fields = _make_realistic_fields()
    data = _make_metadata_json(fields)

    errors: list = []
    warnings: list = []
    validate_source_grounding(data, errors, warnings)

    # Only the high-confidence ungrounded field should produce a warning
    assert len(warnings) == 1
    assert "study design" in warnings[0]
    assert "0.85" in warnings[0]


def test_e2e_check_metadata_json_output_contains_source_grounding():
    fields = _make_realistic_fields()
    data = _make_metadata_json(fields)

    result = check_metadata_json_output(data)

    assert "source_grounding" in result
    sg = result["source_grounding"]
    assert sg["source_grounded_fields"] == 3
    assert sg["table_backed_fields"] == 1
    assert sg["ungrounded_high_confidence_fields"] == 1


def test_e2e_source_grounding_validation_flag():
    """source_grounding validation flag is False when any ungrounded high-conf fields exist."""
    fields = _make_realistic_fields()
    data = _make_metadata_json(fields)

    result = check_metadata_json_output(data)

    # 1 ungrounded high-confidence field → flag should be False
    assert result["validations"]["source_grounding"] is False


def test_e2e_source_grounding_validation_flag_true_when_all_grounded():
    """source_grounding validation flag is True when no ungrounded high-conf fields."""
    fields = [
        MetadataField(
            field_name="sampling site",
            value="Wadden Sea",
            evidence="source_001:10-50 main.md: Wadden Sea",
            confidence=0.92,
            status="confirmed",
        ),
    ]
    data = _make_metadata_json(fields)

    result = check_metadata_json_output(data)

    assert result["validations"]["source_grounding"] is True
    assert result["source_grounding"]["ungrounded_high_confidence_fields"] == 0


# ── Phase A.3: Round-trip through JSON serialisation ─────────────────


def test_e2e_source_grounding_survives_json_roundtrip():
    """JSON serialisation + parse keeps source grounding counts stable."""
    fields = _make_realistic_fields()
    data = _make_metadata_json(fields)

    serialized = json.dumps(data, ensure_ascii=False)
    parsed = json.loads(serialized)

    result = check_metadata_json_output(parsed)

    assert result["source_grounding"]["source_grounded_fields"] == 3
    assert result["source_grounding"]["ungrounded_high_confidence_fields"] == 1


# ── Phase A.4: Multi-source workspace + field evidence context ────────


def test_e2e_field_evidence_context_with_multi_source_workspace(tmp_path, monkeypatch):
    """Full pipeline: workspace → field evidence context → grounding summary."""
    records = [
        SourceRecord(
            source_id="source_001",
            path="paper.md",
            method="direct_read",
            content=(
                "# Earthworm study\n\n"
                "Sampling site: Wadden Sea tidal flats, Texel, Netherlands.\n"
                "Species: Eisenia fetida collected from control and treated mesocosms.\n"
            ),
            content_type="markdown",
        ),
        SourceRecord(
            source_id="source_002",
            path="supplement.md",
            method="direct_read",
            content=(
                "# Supplementary Methods\n\n"
                "RNA was extracted using TRIzol (Thermo Fisher).\n"
                "Accession: PRJNA123456.\n"
            ),
            content_type="markdown",
        ),
        SourceRecord(
            source_id="source_003",
            path="data.csv",
            method="tabular_csv",
            content="Table file: data.csv\nPreview rows: 1 / 3",
            content_type="table",
            tables=[
                {
                    "name": "measurements",
                    "rows": [
                        {"sample_id": "S1", "organism": "Lumbricus terrestris"},
                        {"sample_id": "S2", "organism": "Eisenia fetida"},
                        {"sample_id": "S3", "organism": "Eisenia fetida"},
                    ],
                }
            ],
        ),
    ]
    workspace = build_source_workspace(records, tmp_path)
    workspace_meta = {
        "root_dir": str(workspace.root_dir),
        "manifest_path": str(workspace.manifest_path),
        "summary_path": str(workspace.summary_path),
        "source_paths": {k: str(v) for k, v in workspace.source_paths.items()},
        "table_paths": {k: str(v) for k, v in workspace.table_paths.items()},
    }

    monkeypatch.setattr(
        "fairifier.agents.json_generator.config.metadata_max_evidence_snippets_per_field", 5
    )

    agent = JSONGeneratorAgent()

    context, candidates = agent._build_field_source_evidence_context(
        workspace_meta,
        [
            {"name": "sampling site", "description": "Geographic sampling location"},
            {"name": "organism", "description": "Species name"},
            {"name": "accession", "description": "Sequence database accession"},
        ],
    )

    # Check that evidence is grounded in specific sources
    assert "source_001" in context      # main manuscript for sampling site
    assert "Wadden Sea" in context
    assert "Eisenia fetida" in context   # appears in both text + table
    assert "PRJNA123456" in context      # supplement accession
    assert "role=main_manuscript" in context
    assert "role=supplement" in context
    assert "role=table" in context
    
    # Check candidates
    assert "sampling site" in candidates
    assert len(candidates["sampling site"]) > 0
