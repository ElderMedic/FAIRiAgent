import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
from fairifier.agents.response_models import ISAValueMappingResponse
from fairifier.config import config
from fairifier.tools.isa_structure_tools import create_isa_structure_tools


MINERU_TEXT = """
Table 2. Mock microbial communities (meta) data used for benchmarking.
Bioproject
Description
PRJEB29504
ZYMO (Even Distribution): Mock microbial community standard, ultra-deep, Even: eight bacterial species and two yeast species; long-read nanopore & short-read Illumina available.
PRJEB29504
ZYMO (Log Distribution): Mock microbial community standard, ultra-deep, log distribution based on genomic DNA. Long read nanopore & short read Illumina available.
PRJNA496047
BMOCK12: Mock microbial community for the benchmarking purposes. 12 isolate genomes from Actinobacteria, Proteobacteria and Bacteroidetes phyla; long read nanopore & short read Illumina.

RDF Snippet
<http://fairbydesign.nl/ontology/inv_fdp/stu_ZYMO_PRJEB29504obs_ZYMO_EVEN_mocktest_cwl/sam_Zymo-LOG_community_ONT/asy_ONT_LOG_ERR3152366>
a jerm:Assay ;
fair:platform "OXFORD_NANOPORE" ;
schema:dataset <file://ftp.sra.ebi.ac.uk/vol1/fastq/ERR315/006/ERR3152366/ERR3152366.fastq.gz> ;
schema:identifier "ONT_LOG_ERR3152366" .
"""


def _tool_by_name(tools, name):
    for tool in tools:
        if tool.name == name:
            return tool
    raise AssertionError(f"missing tool {name}")


def test_isa_structure_tools_expose_generic_workspace_search(tmp_path):
    source = tmp_path / "source_001.md"
    source.write_text(MINERU_TEXT, encoding="utf-8")
    workspace = {
        "root_dir": str(tmp_path),
        "source_paths": {"source_001": str(source)},
    }

    tools = create_isa_structure_tools(workspace)
    names = {tool.name for tool in tools}
    assert names == {
        "list_workspace_sources",
        "grep_source_workspace",
        "read_source_excerpt",
        "search_workspace_tables",
        "run_source_shell_command",
    }

    listed = _tool_by_name(tools, "list_workspace_sources").invoke({})
    assert listed["success"] is True
    assert listed["data"]["sources"][0]["source_id"] == "source_001"

    grep_result = _tool_by_name(tools, "grep_source_workspace").invoke(
        {"query": "PRJEB29504"}
    )
    assert grep_result["success"] is True
    assert grep_result["data"]["matches"]

    read_result = _tool_by_name(tools, "read_source_excerpt").invoke(
        {"source_id": "source_001", "start": 0, "max_chars": 120}
    )
    assert read_result["success"] is True
    assert "Mock microbial communities" in read_result["data"]["text"]

    shell_result = _tool_by_name(tools, "run_source_shell_command").invoke(
        {"command": "rg -n \"ERR3152366|PRJEB29504\""}
    )
    assert shell_result["success"] is True
    assert "ERR3152366" in shell_result["data"]["stdout"]


@pytest.mark.parametrize("manifest_location", ["disk", "state"])
def test_source_shell_cannot_read_excluded_raw_chart_artifacts(
    tmp_path, monkeypatch, manifest_location,
):
    source = tmp_path / "source_001.md"
    source.write_text("The experiment ended at 48 h.", encoding="utf-8")
    raw_path = tmp_path / "raw_mineru.md"
    raw_path.write_text("Derived chart: 51 h, signal 999.25.", encoding="utf-8")
    entry = {
        "source_id": "source_001", "path": "paper.pdf",
        "source_evidence": {
            "raw_markdown_path": str(raw_path),
            "derived_regions": [{"kind": "chart_reconstruction", "status": "unverified"}],
        },
    }
    workspace = {
        "root_dir": str(tmp_path),
        "source_paths": {"source_001": str(source)},
    }
    manifest = {"sources": [entry]}
    if manifest_location == "disk":
        manifest_path = tmp_path / "source_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        workspace["manifest_path"] = str(manifest_path)
    else:
        workspace["manifest"] = manifest
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="999.25", stderr="")

    monkeypatch.setattr("fairifier.tools.isa_structure_tools.subprocess.run", fake_run)
    tools = create_isa_structure_tools(workspace)
    result = _tool_by_name(tools, "run_source_shell_command").invoke({
        "command": f"cat {raw_path}",
    })

    assert calls == []
    assert result["success"] is False and result["data"] is None
    for tool_name in (
        "grep_source_workspace", "read_source_excerpt", "search_workspace_tables",
    ):
        assert tool_name in result["error"]
    assert _tool_by_name(tools, "read_source_excerpt").invoke({
        "source_id": "source_001",
    })["data"]["text"] == "The experiment ended at 48 h."
    assert raw_path.read_text(encoding="utf-8") == "Derived chart: 51 h, signal 999.25."


def _publication_table_workspace(tmp_path, *, long_notes=False):
    source = tmp_path / "source_001.md"
    source.write_text("Publication table source.", encoding="utf-8")
    table_path = tmp_path / "rates.jsonl"
    rows = [
        {"Specimen": "A1", "Rate | Initial": "0"},
        {"Specimen": "A2", "Rate | Initial": "−0.025"},
    ]
    table_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "source_manifest.json"
    table = {
        "name": "table_001", "path": table_path.name, "rows": 2,
        "columns": ["Specimen", "Rate | Initial"],
        "captions": ["Table 1. Initial rates at 30 °C."],
        "footnotes": ["Rates are in µmol cm−2 h−1; values are means."],
        "header_status": "resolved", "row_indices": [2, 3],
        "provenance": {
            "artifact_path": "/source/paper_content_list.json",
            "page_idx": 2, "bbox": [10, 20, 300, 180], "json_pointer": "/2/1",
        },
        "raw_html": "DO_NOT_COPY_RAW_TABLE " * 1000,
        "cells": [{"text": "DO_NOT_COPY_GRID_CELL"}] * 1000,
        "grid_origins": [[[0, 0]]] * 1000,
    }
    if long_notes:
        table["captions"] = ["Long caption " * 3000]
        table["footnotes"] = ["Long scientific footnote " * 3000]
    manifest_path.write_text(json.dumps({"sources": [{
        "source_id": "source_001", "path": "paper.pdf",
        "source_role": "main_manuscript", "tables": [table],
    }]}, ensure_ascii=False), encoding="utf-8")
    return {
        "root_dir": str(tmp_path), "manifest_path": str(manifest_path),
        "source_paths": {"source_001": str(source)},
        "table_paths": {"source_001:table_001": str(table_path)},
    }


def test_table_search_tool_preserves_scientific_context_without_full_grid(tmp_path):
    workspace = _publication_table_workspace(tmp_path)
    tool = _tool_by_name(create_isa_structure_tools(workspace), "search_workspace_tables")

    result = tool.invoke({"query": "A", "max_matches": 2})

    matches = result["data"]["matches"]
    assert len(matches) == 2
    assert [match["row"]["Rate | Initial"] for match in matches] == ["0", "−0.025"]
    assert [match["source_row_index"] for match in matches] == [2, 3]
    for match in matches:
        context = match["table_context"]
        assert context["captions"] == ["Table 1. Initial rates at 30 °C."]
        assert context["footnotes"] == ["Rates are in µmol cm−2 h−1; values are means."]
        assert context["columns"] == ["Specimen", "Rate | Initial"]
        assert context["provenance"]["page_idx"] == 2
        assert context["provenance"]["json_pointer"] == "/2/1"
        assert not {"raw_html", "cells", "grid_origins"}.intersection(context)
    rendered = json.dumps(result, ensure_ascii=False)
    assert "DO_NOT_COPY_RAW_TABLE" not in rendered
    assert "DO_NOT_COPY_GRID_CELL" not in rendered
    assert len(rendered) <= 5000


def test_table_search_tool_bounds_context_with_complete_source_reference(tmp_path):
    workspace = _publication_table_workspace(tmp_path, long_notes=True)
    tool = _tool_by_name(create_isa_structure_tools(workspace), "search_workspace_tables")

    result = tool.invoke({"query": "A1", "max_matches": 1})

    match = result["data"]["matches"][0]
    context = match["table_context"]
    assert context["manifest_path"] == workspace["manifest_path"]
    assert context["truncated"] is True
    assert len(json.dumps(result, ensure_ascii=False)) <= 2600
    assert match["row"] == {"Specimen": "A1", "Rate | Initial": "0"}


def test_table_search_tool_retains_unresolved_leading_rows(tmp_path):
    workspace = _publication_table_workspace(tmp_path)
    manifest_path = Path(workspace["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    table = manifest["sources"][0]["tables"][0]
    table.update({
        "header_status": "unresolved",
        "leading_rows": [
            {"source_row_index": 0, "cells": ["Specimen", "Rate (µmol cm−2 h−1)"]},
            {"source_row_index": 1, "cells": ["", "0 h / 24 h"]},
        ],
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    tool = _tool_by_name(create_isa_structure_tools(workspace), "search_workspace_tables")

    result = tool.invoke({"query": "A1", "max_matches": 1})

    context = result["data"]["matches"][0]["table_context"]
    assert context["header_status"] == "unresolved"
    assert context["leading_rows"] == table["leading_rows"]
    assert "raw_html" not in context and "grid_origins" not in context


def test_isa_value_mapper_prefers_agentic_structure_result(monkeypatch):
    monkeypatch.setattr(config, "enable_deep_agents", True)
    agent = ISAValueMapperAgent()

    async def fail_llm_matrix(**_kwargs):
        raise AssertionError("fallback matrix builder should not run")

    async def fake_invoke(*args, **kwargs):
        state = kwargs["state"]
        state["react_scratchpad"] = {
            "ISAValueMapper": {
                "iterations": 3,
                "tools_called": [
                    "list_workspace_sources",
                    "grep_source_workspace",
                    "run_source_shell_command",
                ],
                "budget": {"max_iterations": 6, "max_tool_calls": 18},
            }
        }
        return ISAValueMappingResponse(
            study={
                "columns": ["study identifier", "study title"],
                "rows": [
                    {
                        "study identifier": "ZYMO_PRJEB29504",
                        "study title": "UNmOCK_ZYMO",
                    },
                    {
                        "study identifier": "BMOCK12_PRJNA496047",
                        "study title": "UNmOCK_BMOCK12",
                    },
                ],
            },
            observationunit={
                "columns": [
                    "observation unit identifier",
                    "observation unit name",
                    "study identifier",
                ],
                "rows": [
                    {
                        "observation unit identifier": "ZYMO_EVEN",
                        "observation unit name": "ZYMO even",
                        "study identifier": "ZYMO_PRJEB29504",
                    },
                    {
                        "observation unit identifier": "ZYMO_LOG",
                        "observation unit name": "ZYMO log",
                        "study identifier": "ZYMO_PRJEB29504",
                    },
                ],
            },
            assay={
                "columns": ["assay identifier", "file", "platform", "sample identifier"],
                "rows": [
                    {
                        "assay identifier": "ONT_LOG_ERR3152366",
                        "file": "ftp.sra.ebi.ac.uk/vol1/fastq/ERR315/006/ERR3152366/ERR3152366.fastq.gz",
                        "platform": "OXFORD_NANOPORE",
                        "sample identifier": "",
                    }
                ],
            },
            evidence_summary=[
                "Recovered study and observation-unit rows from table evidence.",
                "Recovered assay row from RDF snippet via shell-assisted search.",
            ],
            quality_issues=["All assay rows are missing their parent linkage field."],
            mapping_confidence=0.82,
        )

    monkeypatch.setattr(agent, "_build_ivm_inner_agent", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(agent, "_invoke_react_agent", fake_invoke)
    monkeypatch.setattr(agent, "_build_matrix_with_llm", fail_llm_matrix)
    state = {
        "metadata_fields": [
            {
                "field_name": "study title",
                "value": "placeholder",
                "isa_sheet": "study",
                "confidence": 0.9,
                "status": "confirmed",
            }
        ],
        "retrieved_knowledge": [],
        "source_workspace": {},
        "artifacts": {},
        "confidence_scores": {},
        "context": {},
        "agent_guidance": {},
        "errors": [],
    }

    result = asyncio.run(agent.execute(state))
    matrix = json.loads(result["artifacts"]["isa_values_json"])
    assert len(matrix["study"]["rows"]) == 2
    assert len(matrix["observationunit"]["rows"]) == 2
    assert matrix["assay"]["rows"][0]["assay identifier"] == "ONT_LOG_ERR3152366"
    assert "run_source_shell_command" in result["react_scratchpad"]["ISAValueMapper"]["tools_called"]
    assert "All assay rows are missing their parent linkage field." in result["isa_value_quality"]["issues"]


def test_isa_value_mapper_falls_back_when_agentic_result_is_empty(monkeypatch):
    monkeypatch.setattr(config, "enable_deep_agents", True)
    agent = ISAValueMapperAgent()

    async def fake_invoke(*args, **kwargs):
        state = kwargs["state"]
        state["react_scratchpad"] = {
            "ISAValueMapper": {
                "iterations": 2,
                "tools_called": ["list_workspace_sources"],
                "budget": {"max_iterations": 6, "max_tool_calls": 18},
            }
        }
        return ISAValueMappingResponse()

    async def fail_llm_matrix(**_kwargs):
        raise AssertionError("empty agentic matrix should use deterministic fallback")

    monkeypatch.setattr(agent, "_build_ivm_inner_agent", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(agent, "_invoke_react_agent", fake_invoke)
    monkeypatch.setattr(agent, "_build_matrix_with_llm", fail_llm_matrix)
    state = {
        "metadata_fields": [
            {
                "field_name": "observation unit identifier",
                "value": "ZYMO_EVEN",
                "isa_sheet": "observationunit",
                "entity_id": "obs_zymo_even",
            },
            {
                "field_name": "observation unit identifier",
                "value": "ZYMO_LOG",
                "isa_sheet": "observationunit",
                "entity_id": "obs_zymo_log",
            },
            {
                "field_name": "sample identifier",
                "value": "ZYMO_EVEN",
                "isa_sheet": "sample",
                "entity_id": "sample_zymo_even",
            },
            {
                "field_name": "sample identifier",
                "value": "ZYMO_LOG",
                "isa_sheet": "sample",
                "entity_id": "sample_zymo_log",
            },
        ],
        "retrieved_knowledge": [],
        "source_workspace": {},
        "artifacts": {},
        "confidence_scores": {},
        "context": {},
        "agent_guidance": {},
        "errors": [],
    }

    result = asyncio.run(agent.execute(state))

    matrix = json.loads(result["artifacts"]["isa_values_json"])
    assert [row["observation unit identifier"] for row in matrix["observationunit"]["rows"]] == [
        "ZYMO_EVEN",
        "ZYMO_LOG",
    ]
    assert [row["sample identifier"] for row in matrix["sample"]["rows"]] == [
        "ZYMO_EVEN",
        "ZYMO_LOG",
    ]


def test_isa_value_mapper_fills_missing_core_study_identifier(monkeypatch):
    monkeypatch.setattr(config, "enable_deep_agents", False)
    agent = ISAValueMapperAgent()

    async def fake_llm_matrix(**_kwargs):
        return {
            "investigation": {
                "columns": ["investigation title"],
                "rows": [{"investigation title": "PETase enzyme engineering"}],
            },
            "study": {
                "columns": ["study title"],
                "rows": [{"study title": "PETase activity screen"}],
            },
            "observationunit": {
                "columns": ["observation unit identifier", "observation unit name"],
                "rows": [
                    {
                        "observation unit identifier": "WT_PETase",
                        "observation unit name": "Wild-type PETase",
                    }
                ],
            },
            "sample": {"columns": [], "rows": []},
            "assay": {"columns": [], "rows": []},
        }

    monkeypatch.setattr(agent, "_build_matrix_with_llm", fake_llm_matrix)
    state = {
        "metadata_fields": [
            {
                "field_name": "study title",
                "value": "PETase activity screen",
                "isa_sheet": "study",
                "confidence": 0.9,
            }
        ],
        "retrieved_knowledge": [],
        "source_workspace": {},
        "document_info": {"doi": "10.1002/anie.202218390"},
        "artifacts": {},
        "confidence_scores": {},
        "context": {},
        "agent_guidance": {},
        "errors": [],
    }

    result = asyncio.run(agent.execute(state))

    matrix = json.loads(result["artifacts"]["isa_values_json"])
    assert matrix["study"]["rows"][0]["study identifier"] == "STUDY_10_1002_anie_202218390"
    assert matrix["study"]["rows"][0]["investigation identifier"] == "INV_10_1002_anie_202218390"
    assert matrix["observationunit"]["rows"][0]["study identifier"] == "STUDY_10_1002_anie_202218390"


def test_isa_value_mapper_normalizes_existing_doi_identifiers(monkeypatch):
    monkeypatch.setattr(config, "enable_deep_agents", False)
    agent = ISAValueMapperAgent()

    async def fake_llm_matrix(**_kwargs):
        return {
            "investigation": {
                "columns": ["investigation identifier", "investigation title"],
                "rows": [{
                    "investigation identifier": "10.1038/s41586-020-2149-4",
                    "investigation title": "PET bottle depolymerase",
                }],
            },
            "study": {
                "columns": ["study identifier", "investigation identifier", "study title"],
                "rows": [{
                    "study identifier": "10.1038/s41586-020-2149-4",
                    "investigation identifier": "10.1038/s41586-020-2149-4",
                    "study title": "Nature 2020 PETase",
                }],
            },
            "observationunit": {
                "columns": ["observation unit identifier", "study identifier"],
                "rows": [{
                    "observation unit identifier": "OU_1",
                    "study identifier": "10.1038/s41586-020-2149-4",
                }],
            },
            "sample": {"columns": [], "rows": []},
            "assay": {"columns": [], "rows": []},
        }

    monkeypatch.setattr(agent, "_build_matrix_with_llm", fake_llm_matrix)
    state = {
        "metadata_fields": [
            {"field_name": "study title", "value": "Nature 2020 PETase", "isa_sheet": "study"}
        ],
        "retrieved_knowledge": [],
        "source_workspace": {},
        "document_info": {"doi": "10.1038/s41586-020-2149-4"},
        "artifacts": {},
        "confidence_scores": {},
        "context": {},
        "agent_guidance": {},
        "errors": [],
    }

    result = asyncio.run(agent.execute(state))

    matrix = json.loads(result["artifacts"]["isa_values_json"])
    assert matrix["investigation"]["rows"][0]["investigation identifier"] == "10_1038_s41586_020_2149_4"
    assert matrix["study"]["rows"][0]["study identifier"] == "10_1038_s41586_020_2149_4"
    assert matrix["study"]["rows"][0]["investigation identifier"] == "10_1038_s41586_020_2149_4"
    assert matrix["observationunit"]["rows"][0]["study identifier"] == "10_1038_s41586_020_2149_4"


def test_isa_value_mapper_seeds_rows_from_source_workspace_sheet_headers(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "enable_deep_agents", True)
    agent = ISAValueMapperAgent()

    source = tmp_path / "source_001.md"
    source.write_text(
        "[Sheet: ZYMO_EVEN]\nrows...\n[Sheet: ZYMO_LOG]\nrows...\n[Sheet: BMOCK12]\nrows...\n",
        encoding="utf-8",
    )

    async def fake_invoke(*args, **kwargs):
        return ISAValueMappingResponse()

    async def fail_llm_matrix(**_kwargs):
        raise AssertionError("empty agentic matrix should use deterministic fallback")

    monkeypatch.setattr(agent, "_build_ivm_inner_agent", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(agent, "_invoke_react_agent", fake_invoke)
    monkeypatch.setattr(agent, "_build_matrix_with_llm", fail_llm_matrix)
    state = {
        "metadata_fields": [
            {
                "field_name": "study identifier",
                "value": "study_mock_metagenomics",
                "isa_sheet": "study",
                "entity_id": "study_001",
            }
        ],
        "retrieved_knowledge": [],
        "source_workspace": {"source_paths": {"source_001": str(source)}},
        "artifacts": {},
        "confidence_scores": {},
        "context": {},
        "agent_guidance": {},
        "errors": [],
    }

    result = asyncio.run(agent.execute(state))

    matrix = json.loads(result["artifacts"]["isa_values_json"])
    assert [row["observation unit identifier"] for row in matrix["observationunit"]["rows"]] == [
        "ZYMO_EVEN",
        "ZYMO_LOG",
        "BMOCK12",
    ]
    assert [row["sample identifier"] for row in matrix["sample"]["rows"]] == [
        "ZYMO_EVEN",
        "ZYMO_LOG",
        "BMOCK12",
    ]
    assert [row["assay identifier"] for row in matrix["assay"]["rows"]] == [
        "ZYMO_EVEN",
        "ZYMO_LOG",
        "BMOCK12",
    ]


def test_isa_value_mapper_merges_identifierless_rows_into_seeded_entities(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "enable_deep_agents", True)
    agent = ISAValueMapperAgent()

    source = tmp_path / "source_001.md"
    source.write_text("[Sheet: ZYMO_EVEN]\nrows...\n[Sheet: ZYMO_LOG]\nrows...\n", encoding="utf-8")

    async def fake_invoke(*args, **kwargs):
        return ISAValueMappingResponse()

    async def fail_llm_matrix(**_kwargs):
        raise AssertionError("empty agentic matrix should use deterministic fallback")

    monkeypatch.setattr(agent, "_build_ivm_inner_agent", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(agent, "_invoke_react_agent", fake_invoke)
    monkeypatch.setattr(agent, "_build_matrix_with_llm", fail_llm_matrix)
    state = {
        "metadata_fields": [
            {
                "field_name": "study identifier",
                "value": "study_mock_metagenomics",
                "isa_sheet": "study",
                "entity_id": "study_001",
            },
            {
                "field_name": "sample identifier",
                "value": "ZYMO_EVEN",
                "isa_sheet": "sample",
                "entity_id": "sample_zymo_even",
            },
            {
                "field_name": "assembly software",
                "value": "Flye; Medaka",
                "isa_sheet": "sample",
                "entity_id": "exp1_assembly",
            },
        ],
        "retrieved_knowledge": [],
        "source_workspace": {"source_paths": {"source_001": str(source)}},
        "artifacts": {},
        "confidence_scores": {},
        "context": {},
        "agent_guidance": {},
        "errors": [],
    }

    result = asyncio.run(agent.execute(state))

    matrix = json.loads(result["artifacts"]["isa_values_json"])
    sample_rows = matrix["sample"]["rows"]
    assert [row["sample identifier"] for row in sample_rows] == ["ZYMO_EVEN", "ZYMO_LOG"]
    assert all(row["assembly software"] == "Flye; Medaka" for row in sample_rows)


def test_isa_value_mapper_collapses_single_row_levels_and_unlinked_assays(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "enable_deep_agents", True)
    agent = ISAValueMapperAgent()

    source = tmp_path / "source_001.md"
    source.write_text("[Sheet: ZYMO_EVEN]\nrows...\n[Sheet: ZYMO_LOG]\nrows...\n", encoding="utf-8")

    async def fake_invoke(*args, **kwargs):
        return ISAValueMappingResponse()

    async def fail_llm_matrix(**_kwargs):
        raise AssertionError("empty agentic matrix should use deterministic fallback")

    monkeypatch.setattr(agent, "_build_ivm_inner_agent", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(agent, "_invoke_react_agent", fake_invoke)
    monkeypatch.setattr(agent, "_build_matrix_with_llm", fail_llm_matrix)
    state = {
        "metadata_fields": [
            {
                "field_name": "investigation title",
                "value": "FAIR workflow",
                "isa_sheet": "investigation",
                "entity_id": "inv_001",
            },
            {
                "field_name": "associated publication",
                "value": "10.5281/zenodo.17990145",
                "isa_sheet": "investigation",
                "entity_id": "investigation_main",
            },
            {
                "field_name": "assay identifier",
                "value": "ERR3152366",
                "isa_sheet": "assay",
                "entity_id": "assay_ERR3152366",
            },
        ],
        "retrieved_knowledge": [],
        "source_workspace": {"source_paths": {"source_001": str(source)}},
        "artifacts": {},
        "confidence_scores": {},
        "context": {},
        "agent_guidance": {},
        "errors": [],
    }

    result = asyncio.run(agent.execute(state))

    matrix = json.loads(result["artifacts"]["isa_values_json"])
    assert len(matrix["investigation"]["rows"]) == 1
    assert matrix["investigation"]["rows"][0]["associated publication"] == "10.5281/zenodo.17990145"
    assert [row["assay identifier"] for row in matrix["assay"]["rows"]] == ["ZYMO_EVEN", "ZYMO_LOG"]
