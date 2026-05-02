"""Tests for field-level candidate merging and provenance."""

from __future__ import annotations

import pytest

from fairifier.agents.json_generator import JSONGeneratorAgent, FieldCandidate
from fairifier.models import MetadataField


def test_field_candidate_sorting():
    # Sort key order: source role priority (asc), relevance (desc), confidence (desc)
    c_main = FieldCandidate(
        field_name="organism",
        value="value",
        source_id="s1",
        source_role="main_manuscript",
        relevance_score=0.9,
        evidence="s1:100",
        confidence=0.8,
    )
    c_supp = FieldCandidate(
        field_name="organism",
        value="value",
        source_id="s2",
        source_role="supplement",
        relevance_score=0.95,  # Higher relevance but worse role
        evidence="s2:100",
        confidence=0.8,
    )
    c_main_better = FieldCandidate(
        field_name="organism",
        value="value",
        source_id="s1",
        source_role="main_manuscript",
        relevance_score=0.95, # Better relevance than c_main
        evidence="s1:200",
        confidence=0.8,
    )
    
    candidates = [c_supp, c_main, c_main_better]
    sorted_candidates = sorted(candidates, key=lambda x: x.sort_key)
    
    # main_manuscript with highest relevance first
    assert sorted_candidates[0] == c_main_better
    assert sorted_candidates[1] == c_main
    assert sorted_candidates[2] == c_supp


def test_collect_field_candidates():
    agent = JSONGeneratorAgent()
    
    text_matches = [
        {
            "source_id": "s1",
            "start": 10,
            "end": 20,
            "excerpt": "Eisenia fetida",
            "source_path": "paper.md"
        }
    ]
    table_matches = [
        {
            "source_id": "s2",
            "table": "Table 1",
            "row_index": 0,
            "column": "Species",
            "row": {"Species": "Eisenia fetida"}
        }
    ]
    source_meta = {
        "s1": {"source_role": "main_manuscript", "relevance_score": 0.8},
        "s2": {"source_role": "supplement", "relevance_score": 0.7},
    }
    
    candidates = agent._collect_field_candidates("organism", text_matches, table_matches, source_meta)
    
    assert len(candidates) == 2
    
    # Text candidate
    assert candidates[0].field_name == "organism"
    assert candidates[0].source_role == "main_manuscript"
    assert "Eisenia fetida" in candidates[0].evidence
    
    # Table candidate
    assert candidates[1].source_role == "supplement"
    assert "Table 1" in candidates[1].evidence


def test_reconcile_candidates():
    agent = JSONGeneratorAgent()
    
    candidates = [
        FieldCandidate("org", "v1", "s1", "main", 0.9, "ev1"),
        FieldCandidate("org", "v2", "s2", "supp", 0.8, "ev2"),
        FieldCandidate("org", "v3", "s3", "supp", 0.7, "ev3"),
    ]
    
    primary, secondary = agent._reconcile_candidates(candidates)
    
    assert primary == candidates[0]
    assert len(secondary) == 2
    assert secondary[0] == candidates[1]
    assert secondary[1] == candidates[2]


def test_postcheck_enriches_evidence_with_primary_candidate():
    agent = JSONGeneratorAgent()
    
    fields = [
        MetadataField(
            field_name="organism",
            value="Eisenia fetida",
            evidence="extracted from text", # No source_ref pattern
            confidence=0.9,
            status="confirmed",
            metadata={}
        )
    ]
    
    # Strong candidate exists
    field_candidates = {
        "organism": [
            FieldCandidate(
                field_name="organism",
                value="Eisenia fetida",
                source_id="s1",
                source_role="main_manuscript",
                relevance_score=0.9,
                evidence="source_001:10-20 [role=main_manuscript] (paper.md): Eisenia fetida"
            ),
            FieldCandidate(
                field_name="organism",
                value="Eisenia fetida",
                source_id="s2",
                source_role="supplement",
                relevance_score=0.8,
                evidence="source_002 table 1 row 0 column org [role=supplement]: {'org': 'Eisenia'}"
            )
        ]
    }
    
    result, downgrades = agent._postcheck_source_grounding(fields, {"some": "workspace"}, field_candidates)
    assert downgrades == 0
    
    # Because of candidate reconciliation, evidence is enriched and confidence is kept high!
    assert result[0].confidence == 0.9
    assert result[0].status == "confirmed"
    assert "source_001:10-20" in result[0].evidence
    assert result[0].metadata["primary_provenance"] == field_candidates["organism"][0].evidence
    assert len(result[0].metadata["secondary_provenance"]) == 1
    assert result[0].metadata["secondary_provenance"][0] == field_candidates["organism"][1].evidence


def test_postcheck_downgrades_when_no_candidates():
    agent = JSONGeneratorAgent()
    
    fields = [
        MetadataField(
            field_name="missing_field",
            value="something",
            evidence="hallucinated",
            confidence=0.9,
            status="confirmed"
        )
    ]
    
    result, downgrades = agent._postcheck_source_grounding(fields, {"some": "workspace"}, {})
    assert downgrades == 1
    
    # Downgraded because no source ref and no candidates
    from fairifier.config import config
    assert result[0].confidence == float(config.metadata_source_ref_downgrade_confidence)
    assert result[0].status == "provisional"
    assert "missing source reference" in result[0].evidence
