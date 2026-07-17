import json

from openpyxl import load_workbook

from fairifier.services.fairds_excel_export import try_export_fairds_metadata_excel
from fairifier.services.auto_repair import generate_auto_repair_trace


def test_excel_export_prefers_isa_values_matrix_and_preserves_linkage_columns(tmp_path):
    metadata = {
        "isa_structure": {
            "observationunit": {
                "columns": ["observation unit name"],
                "rows": [{"observation unit name": "collapsed"}],
            }
        }
    }
    isa_values = {
        "observationunit": {
            "columns": [
                "observation unit identifier",
                "observation unit name",
                "study identifier",
            ],
            "rows": [
                {
                    "observation unit identifier": "ZYMO_LOG_mocktest_cwl",
                    "observation unit name": "ZYMO_LOG_mocktest_cwl",
                    "study identifier": "ZYMO_PRJEB29504",
                }
            ],
        }
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (tmp_path / "isa_values_json.json").write_text(json.dumps(isa_values), encoding="utf-8")

    out = try_export_fairds_metadata_excel(tmp_path, fair_ds_api_url="")

    assert out is not None
    wb = load_workbook(out, data_only=True)
    ws = wb["Observationunit"]
    headers = [ws.cell(1, col).value for col in range(1, ws.max_column + 1)]
    assert "observation unit identifier" in headers
    assert "study identifier" in headers
    row = {
        headers[col - 1]: ws.cell(2, col).value
        for col in range(1, ws.max_column + 1)
    }
    assert row["observation unit identifier"] == "ZYMO_LOG_mocktest_cwl"
    assert row["study identifier"] == "ZYMO_PRJEB29504"


def test_excel_export_uses_auto_repaired_isa_values_json(tmp_path):
    metadata = {
        "fairifier_version": "Vtest",
        "generated_at": "2026-07-14T00:00:00",
        "document_source": "test.pdf",
        "isa_structure": {
            "study": {
                "fields": [{"field_name": "study identifier", "value": "study_1"}],
                "columns": ["study identifier"],
                "rows": [{"study identifier": "study_1"}],
            }
        },
        "isa_values": {
            "study": {
                "columns": ["study identifier"],
                "rows": [{"study identifier": "study_1"}],
            }
        },
        "statistics": {
            "total_fields": 1,
            "study_fields": 1,
            "confirmed_fields": 1,
            "provisional_fields": 0,
        },
    }
    state = {
        "retrieved_knowledge": [
            {
                "term": "study title",
                "metadata": {
                    "name": "study title",
                    "requirement": "MANDATORY",
                    "isa_sheet": "study",
                },
            }
        ],
        "metadata_fields": [
            {
                "field_name": "study identifier",
                "value": "study_1",
                "confidence": 0.95,
                "isa_sheet": "study",
                "requirement": "MANDATORY",
            }
        ],
        "retrieval_telemetry": {
            "study title": {
                "lexical_hit_count": 0,
                "semantic_hit_count": 12,
                "prompt_mode": "auto_semantic_fallback",
                "retrieval_mode": "auto",
            }
        },
        "section_field_candidates": [
            {
                "field_name": "study title",
                "field_candidate": "study title",
                "value": "Pea cold stress response",
                "evidence": "source_001:10-40 [role=primary] Study Title: Pea cold stress response",
                "source_id": "source_001",
                "source_role": "primary",
                "char_start": 10,
                "char_end": 40,
                "confidence": 0.82,
                "retrieval_method": "section_map_reduce",
                "provenance": {"agent": "section_map_reduce"},
            }
        ],
        "artifacts": {
            "metadata_json": json.dumps(metadata),
            "isa_values_json": json.dumps(metadata["isa_values"]),
        },
    }

    trace = generate_auto_repair_trace(state)
    assert trace["summary"]["accepted_patch_count"] == 1
    (tmp_path / "metadata.json").write_text(
        state["artifacts"]["metadata_json"],
        encoding="utf-8",
    )
    (tmp_path / "isa_values_json.json").write_text(
        state["artifacts"]["isa_values_json"],
        encoding="utf-8",
    )

    out = try_export_fairds_metadata_excel(tmp_path, fair_ds_api_url="")

    assert out is not None
    wb = load_workbook(out, data_only=True)
    ws = wb["Study"]
    headers = [ws.cell(1, col).value for col in range(1, ws.max_column + 1)]
    assert "study title" in headers
    row = {
        headers[col - 1]: ws.cell(2, col).value
        for col in range(1, ws.max_column + 1)
    }
    assert row["study title"] == "Pea cold stress response"
