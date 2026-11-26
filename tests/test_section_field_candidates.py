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


SI_TABLE = """
Supporting information

ACGTTCGGTGGCATCGCGATGAGTCCGGGTTATACCGCAGATGCTAGCTCTCTGGCATGGCTGGGTCGTCGCCTG

<table><tr><td>Temperature</td><td>Performance criteria</td><td>FAST-PETase</td><td>LCC ICCG</td></tr>
<tr><td>45 °C</td><td>Specific activity (µmol h^-1 mg enzyme^-1)</td><td>245.5 ± 12.5</td><td>55.8 ± 15.3</td></tr>
<tr><td></td><td>Specific activity (µmol h^-1 mg enzyme^-1)</td><td>347.5 ± 46.1</td><td>1350.8 ± 135.8</td></tr>
</table>
"""


def test_html_table_cells_become_field_candidates():
    section = {
        "section_id": "source_002_section_004",
        "source_id": "source_002",
        "title": "Supporting information",
        "section_type": "supplement",
        "char_start": 0,
        "char_end": len(SI_TABLE),
        "text": SI_TABLE,
    }
    records = extract_field_candidates_from_section(section)
    blob = " ".join(f"{record['field_name']} {record['value']} {record['evidence_text']}" for record in records)
    assert "245.5" in blob
    assert "347.5" in blob
    assert "1350.8" in blob


def test_html_table_keeps_later_measurement_rows():
    body = "".join(f"<tr><td>Var{i}</td><td>{i}.63 ± 0.1</td></tr>" for i in range(1, 91))
    section = {
        "section_id": "source_002_section_005",
        "source_id": "source_002",
        "title": "Table S4",
        "section_type": "supplement",
        "char_start": 0,
        "char_end": 10,
        "text": f"<table><tr><td>Enzyme</td><td>Activity</td></tr>{body}</table>",
    }
    records = extract_field_candidates_from_section(section)
    blob = " ".join(record["value"] for record in records)
    assert "90.63" in blob


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
