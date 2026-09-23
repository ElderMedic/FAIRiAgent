import inspect
import io
import json

import pytest
from openpyxl import Workbook, load_workbook

from fairifier.graph.excel import (
    _fill_missing_data_rows,
    _index_fairds_terms,
    _load_local_term_catalog,
    _lookup_term_record,
    _merge_term_catalogs,
    _slim_isa_for_api,
)
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
    ws = _sheet(wb, "observationunit")
    headers = [ws.cell(1, col).value for col in range(1, ws.max_column + 1)]
    assert "observation unit identifier" in headers
    assert "study identifier" in headers
    row = {
        headers[col - 1]: ws.cell(2, col).value
        for col in range(1, ws.max_column + 1)
    }
    assert row["observation unit identifier"] == "ZYMO_LOG_mocktest_cwl"
    assert row["study identifier"] == "ZYMO_PRJEB29504"


def test_api_template_columns_are_replaced_by_authoritative_matrix_columns():
    wb = Workbook()
    ws = wb.active
    ws.title = "investigation - default"
    ws.append(["investigation identifier", "investigation title", "role"])
    ws.append(["placeholder", "placeholder", "contact"])
    buf = io.BytesIO()
    wb.save(buf)

    matrix = {
        "investigation": {
            "columns": ["investigation identifier", "investigation title"],
            "rows": [
                {
                    "investigation identifier": "investigation_001",
                    "investigation title": "A source-grounded title",
                }
            ],
        }
    }
    rewritten = _fill_missing_data_rows(buf.getvalue(), matrix)
    out = load_workbook(io.BytesIO(rewritten), data_only=True)
    result = out["investigation - default"]

    assert [cell.value for cell in result[1]] == [
        "investigation identifier",
        "investigation title",
    ]
    assert [cell.value for cell in result[2]] == [
        "investigation_001",
        "A source-grounded title",
    ]


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
    ws = _sheet(wb, "study")
    headers = [ws.cell(1, col).value for col in range(1, ws.max_column + 1)]
    normalized = [
        str(header).split("  (")[0].strip() if header is not None else ""
        for header in headers
    ]
    assert "study title" in normalized
    row = {
        normalized[col - 1]: ws.cell(2, col).value
        for col in range(1, ws.max_column + 1)
        if normalized[col - 1]
    }
    assert row["study title"] == "Pea cold stress response"


def _help_rows(workbook):
    ws = workbook["Help"]
    return [
        [ws.cell(row, col).value for col in range(1, (ws.max_column or 1) + 1)]
        for row in range(1, (ws.max_row or 1) + 1)
    ]


def test_excel_help_sheet_lists_fairds_style_terms_when_sidecar_has_no_fields(tmp_path):
    """Help must list used metadata types even when isa_values is columns×rows only.

    FAIR-DS Help is built from ``isa_structure`` fields (name, definition,
    requirement, package, example). Preferring the compiled sidecar for data
    rows must not drop those field definitions from Help.
    """
    metadata = {
        "packages_used": ["default", "petase_enzyme_engineering"],
        "isa_structure": {
            "investigation": {
                "description": "Investigation-level metadata",
                "fields": [
                    {
                        "field_name": "investigation title",
                        "value": "PETase directed evolution",
                        "requirement": "MANDATORY",
                        "package_source": "default",
                        "definition": "Title describing the investigation",
                        "example": "Synergies between biological processes",
                    }
                ],
            },
            "sample": {
                "description": "Sample-level metadata",
                "fields": [
                    {
                        "field_name": "sample name",
                        "value": "IsPETase WT",
                        "requirement": "OPTIONAL",
                        "package_source": "petase_enzyme_engineering",
                        "definition": "Human-readable sample name",
                        "example": "IsPETase WT",
                    }
                ],
            },
        },
    }
    isa_values = {
        "investigation": {
            "columns": ["investigation title", "investigation identifier"],
            "rows": [
                {
                    "investigation title": "PETase directed evolution",
                    "investigation identifier": "anie_202218390",
                }
            ],
        },
        "sample": {
            "columns": ["sample name"],
            "rows": [{"sample name": "IsPETase WT"}],
        },
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (tmp_path / "isa_values_json.json").write_text(json.dumps(isa_values), encoding="utf-8")

    out = try_export_fairds_metadata_excel(tmp_path, fair_ds_api_url="")

    assert out is not None
    wb = load_workbook(out, data_only=True)
    assert "Help" in wb.sheetnames
    rows = _help_rows(wb)
    assert any(
        row and row[0] == "Below are the metadata terms that are used in the investigation sheet"
        for row in rows
    )
    assert any(
        row and row[0] == "Below are the metadata terms that are used in the sample sheet"
        for row in rows
    )

    title_row = next(
        row for row in rows if row and row[0] == "investigation title"
    )
    assert title_row[1] == "Title describing the investigation"
    assert str(title_row[2]).upper() == "MANDATORY"
    assert title_row[3] == "default"
    assert title_row[4] == "Synergies between biological processes"

    sample_row = next(row for row in rows if row and row[0] == "sample name")
    assert sample_row[1] == "Human-readable sample name"
    assert str(sample_row[2]).upper() == "OPTIONAL"
    assert sample_row[3] == "petase_enzyme_engineering"

    linkage_row = next(
        row for row in rows if row and row[0] == "investigation identifier"
    )
    assert linkage_row[0] == "investigation identifier"


def test_excel_help_sheet_fills_definition_from_explicit_local_package(
    tmp_path, monkeypatch
):
    """Help definitions should come from the local package catalog when fields omit them."""
    from pathlib import Path
    from fairifier.graph import excel as excel_module

    package_path = (
        Path(__file__).resolve().parents[1]
        / "evaluation/config/packages/petase_enzyme_engineering_package.json"
    )
    monkeypatch.setattr(
        "fairifier.config.config.local_package_paths",
        (str(package_path),),
        raising=False,
    )
    excel_module._LOCAL_TERM_CATALOG = None
    metadata = {
        "packages_used": ["petase_enzyme_engineering"],
        "isa_structure": {
            "observationunit": {
                "fields": [
                    {
                        "field_name": "observation unit type",
                        "value": "enzyme_substrate_pair",
                        "requirement": "MANDATORY",
                        "package_source": "petase_enzyme_engineering",
                    }
                ],
            }
        },
    }
    isa_values = {
        "observationunit": {
            "columns": ["observation unit type"],
            "rows": [{"observation unit type": "enzyme_substrate_pair"}],
        }
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (tmp_path / "isa_values_json.json").write_text(json.dumps(isa_values), encoding="utf-8")

    out = try_export_fairds_metadata_excel(tmp_path, fair_ds_api_url="")

    assert out is not None
    rows = _help_rows(load_workbook(out, data_only=True))
    type_row = next(row for row in rows if row and row[0] == "observation unit type")
    assert "PETase experimental subject" in str(type_row[1] or "")
    assert str(type_row[2]).upper() == "MANDATORY"
    assert type_row[3] == "petase_enzyme_engineering"
    assert type_row[4] == "enzyme_substrate_pair"
    excel_module._LOCAL_TERM_CATALOG = None


def test_unconfigured_evaluation_packages_do_not_leak_into_help(monkeypatch):
    from fairifier.graph import excel as excel_module

    monkeypatch.setattr(
        "fairifier.config.config.local_package_paths", (), raising=False
    )
    excel_module._LOCAL_TERM_CATALOG = None

    catalog = _load_local_term_catalog(force_refresh=True)

    assert _lookup_term_record(
        catalog,
        name="observation unit type",
        package="petase_enzyme_engineering",
    ) == {}
    excel_module._LOCAL_TERM_CATALOG = None


def test_fairds_api_term_metadata_overrides_local_catalog():
    local = _index_fairds_terms(
        {
            "sample identifier": {
                "label": "sample identifier",
                "definition": "stale local definition",
                "packageName": "default",
            }
        }
    )
    api = _index_fairds_terms(
        {
            "sample identifier": {
                "label": "sample identifier",
                "definition": "Identifier corresponding to the sample obtained",
                "requirement": "MANDATORY",
                "packageName": "default",
            }
        }
    )

    merged = _merge_term_catalogs(local, api)
    record = _lookup_term_record(
        merged, name="sample identifier", package="default"
    )

    assert record["definition"] == "Identifier corresponding to the sample obtained"
    assert record["requirement"] == "MANDATORY"


def _sheet(workbook, name):
    for title in workbook.sheetnames:
        normalized = title.lower()
        requested = name.lower()
        if normalized == requested or normalized.startswith(f"{requested} - "):
            return workbook[title]
    raise AssertionError(f"missing sheet {name!r} in {workbook.sheetnames}")


def _write_evaluation_run_artifacts(run_dir, metadata, isa_values):
    """Match v2 harness layout: ``<run_01>/deliverables/{metadata,isa_values}.json``."""
    deliverables = run_dir / "deliverables"
    deliverables.mkdir(parents=True)
    (deliverables / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (deliverables / "isa_values.json").write_text(json.dumps(isa_values), encoding="utf-8")
    return deliverables


def _run_like_metadata_and_values():
    metadata = {
        "packages_used": ["default", "petase_enzyme_engineering"],
        "isa_structure": {
            "investigation": {
                "description": "Investigation-level metadata",
                "fields": [
                    {
                        "field_name": "investigation title",
                        "value": "PETase directed evolution",
                        "evidence": "long evidence that must not be posted to /api/isa",
                        "requirement": "MANDATORY",
                        "package_source": "default",
                        "definition": "Title describing the investigation",
                        "example": "Synergies between biological processes",
                    }
                ],
            },
            "sample": {
                "description": "Sample-level metadata",
                "fields": [
                    {
                        "field_name": "sample name",
                        "value": "IsPETase WT",
                        "requirement": "OPTIONAL",
                        "package_source": "petase_enzyme_engineering",
                        "definition": "Human-readable sample name",
                        "example": "IsPETase WT",
                    }
                ],
            },
        },
    }
    isa_values = {
        "investigation": {
            "columns": ["investigation title"],
            "rows": [{"investigation title": "PETase directed evolution"}],
        },
        "sample": {
            "columns": ["sample name", "study identifier"],
            "rows": [
                {
                    "sample name": "IsPETase WT",
                    "study identifier": "anie_202218390",
                }
            ],
        },
    }
    return metadata, isa_values


def _header_only_help_xlsx():
    """Reproduce FAIR-DS Help when ``POST /api/isa`` received columns×rows only."""
    wb = Workbook()
    ws = wb.active
    ws.title = "investigation"
    ws.cell(1, 1, value="investigation title")
    ws.cell(2, 1, value="placeholder")
    help_ws = wb.create_sheet("Help")
    help_ws.cell(
        1, 1,
        value="Below are the metadata terms that are used in the investigation sheet",
    )
    help_ws.cell(
        4, 1,
        value="Below are the metadata terms that are used in the study sheet",
    )
    wb.create_sheet("Person")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_slim_isa_for_api_posts_fields_not_the_value_matrix():
    payload = _slim_isa_for_api(
        {
            "investigation": {
                "description": "Investigation-level metadata",
                "fields": [
                    {
                        "field_name": "investigation title",
                        "value": "PETase directed evolution",
                        "evidence": "must be stripped",
                        "requirement": "MANDATORY",
                        "package_source": "default",
                    }
                ],
                "columns": ["investigation title"],
                "rows": [{"investigation title": "PETase directed evolution"}],
            }
        }
    )
    block = payload["investigation"]
    assert "fields" in block
    assert block["fields"][0]["field_name"] == "investigation title"
    assert "evidence" not in block["fields"][0]
    assert "columns" not in block
    assert "rows" not in block


def test_evaluation_run_layout_with_fairds_stub_help_lists_metadata_types(
    tmp_path, monkeypatch
):
    """v2 run dirs + live FAIR-DS URL must still emit a FAIR-DS Help catalog.

    Evaluation jobs call ``fairifier.cli process --output-dir <run_01>`` which
    exports with ``config.fair_ds_api_url``. Historically FAIR-DS returned a
    header-only Help sheet because the sidecar matrix had no ``fields``.
    """
    metadata, isa_values = _run_like_metadata_and_values()
    run_dir = (
        tmp_path
        / "complete_fairiagent_system"
        / "ollama_qwen3.8-27b"
        / "petase_doc"
        / "run_01"
    )
    deliverables = _write_evaluation_run_artifacts(run_dir, metadata, isa_values)
    captured = {}

    class _StubFairDSClient:
        def __init__(self, base_url, timeout=15):
            self.base_url = base_url

        def is_available(self):
            return True

        def get_terms(self, force_refresh=False):
            return {
                "investigation title": {
                    "label": "investigation title",
                    "definition": "Title describing the investigation",
                    "example": "Synergies between biological processes",
                    "packageName": "default",
                }
            }

        def generate_excel_from_isa_structure(self, isa_structure):
            captured["payload"] = isa_structure
            return _header_only_help_xlsx()

    monkeypatch.setattr(
        "fairifier.services.fair_data_station.FAIRDataStationClient",
        _StubFairDSClient,
    )
    monkeypatch.setattr(
        "fairifier.config.config.fair_ds_api_url",
        "http://fairds.test",
        raising=False,
    )

    # Same call signature as CLI / evaluation harness (no URL override).
    out = try_export_fairds_metadata_excel(run_dir)

    assert out == deliverables / "metadata_fairds.xlsx"
    assert out.is_file()
    payload = captured["payload"]
    assert payload["investigation"]["fields"][0]["field_name"] == "investigation title"
    assert "columns" not in payload["investigation"]
    assert "rows" not in payload["investigation"]
    assert payload["sample"]["fields"][0]["field_name"] == "sample name"

    wb = load_workbook(out, data_only=True)
    assert all(not name.lower().startswith("person") for name in wb.sheetnames)
    rows = _help_rows(wb)
    title_row = next(row for row in rows if row and row[0] == "investigation title")
    assert title_row[1] == "Title describing the investigation"
    assert str(title_row[2]).upper() == "MANDATORY"
    assert title_row[3] == "default"
    sample_row = next(row for row in rows if row and row[0] == "sample name")
    assert sample_row[1] == "Human-readable sample name"
    assert sample_row[3] == "petase_enzyme_engineering"
    assert any(
        row and row[0] == "Below are the metadata terms that are used in the sample sheet"
        for row in rows
    )

    sample_ws = _sheet(wb, "sample")
    headers = [sample_ws.cell(1, col).value for col in range(1, sample_ws.max_column + 1)]
    assert "sample name" in headers
    assert "study identifier" in headers
    name_col = headers.index("sample name") + 1
    assert sample_ws.cell(2, name_col).value == "IsPETase WT"


def test_cli_and_web_persist_paths_still_export_fairds_excel():
    from fairifier.cli import _run_workflow
    from fairifier.apps.api.services import runner

    assert "try_export_fairds_metadata_excel" in inspect.getsource(_run_workflow)
    assert "try_export_fairds_metadata_excel" in inspect.getsource(
        runner._persist_run_outputs
    )


@pytest.mark.integration
def test_live_fairds_evaluation_run_help_sheet(tmp_path):
    """End-to-end: evaluation layout against a reachable FAIR-DS ``POST /api/isa``."""
    from fairifier.config import config
    from fairifier.services.fair_data_station import FAIRDataStationClient

    url = (config.fair_ds_api_url or "http://localhost:8083").strip()
    client = FAIRDataStationClient(url)
    if not client.is_available():
        pytest.skip(f"FAIR-DS API not available at {url}")

    metadata, isa_values = _run_like_metadata_and_values()
    run_dir = tmp_path / "run_01"
    _write_evaluation_run_artifacts(run_dir, metadata, isa_values)

    out = try_export_fairds_metadata_excel(run_dir, fair_ds_api_url=url)

    assert out is not None
    wb = load_workbook(out, data_only=True)
    rows = _help_rows(wb)
    title_row = next(row for row in rows if row and row[0] == "investigation title")
    assert title_row[1]
    assert str(title_row[2]).upper() in {"MANDATORY", "RECOMMENDED", "OPTIONAL"}
    sample_row = next(row for row in rows if row and row[0] == "sample name")
    assert "sample" in str(sample_row[1] or "").lower() or sample_row[1]
    assert any(
        row and "sample sheet" in str(row[0] or "")
        for row in rows
    )
