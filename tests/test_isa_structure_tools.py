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
