import asyncio
import json

from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
from fairifier.agents.response_models import ISAValueMappingResponse
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


def test_isa_value_mapper_prefers_agentic_structure_result(monkeypatch):
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
