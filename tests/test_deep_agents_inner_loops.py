"""Behavioral tests for deepagents-backed inner loop integration."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from fairifier.agents.document_parser import DocumentParserAgent
from fairifier.agents.json_generator import JSONGeneratorAgent
from fairifier.agents.knowledge_retriever import KnowledgeRetrieverAgent
from fairifier.agents import knowledge_retriever_llm_methods as kr_llm_methods
from fairifier.agents.response_models import DocumentInfoResponse, KnowledgeResponse
from fairifier.config import config


@dataclass
class StubTool:
    """Simple invoke-compatible tool stub."""

    name: str
    responder: callable

    def invoke(self, payload):
        return self.responder(payload)


@pytest.mark.anyio
async def test_document_parser_uses_deep_response_without_fallback(monkeypatch):
    agent = DocumentParserAgent()

    async def fail_extract(*args, **kwargs):
        raise AssertionError("fallback extractor should not be called")

    async def fake_invoke(*args, **kwargs):
        return DocumentInfoResponse(
            document_type="research_paper",
            title="Earthworm response to nanomaterials",
            authors=["A. Researcher"],
            research_domain="ecotoxicology",
            keywords=["earthworm", "nanotoxicology"],
            methodology="RNA-seq",
            confidence=0.91,
        )

    monkeypatch.setattr(agent.llm_helper, "extract_document_info", fail_extract)
    monkeypatch.setattr(agent, "_build_dp_inner_agent", lambda *args, **kwargs: object())
    monkeypatch.setattr(agent, "_invoke_react_agent", fake_invoke)

    state = {
        "document_path": "examples/inputs/earthworm_4n_paper_bioRxiv.pdf",
        "document_content": "Title: Earthworm response to nanomaterials\nMethods: RNA-seq...",
        "document_conversion": {},
        "context": {},
        "agent_guidance": {},
        "confidence_scores": {},
        "errors": [],
    }

    result = await agent.execute(state)

    assert result["document_info"]["document_type"] == "research_paper"
    assert result["document_info"]["title"] == "Earthworm response to nanomaterials"
    assert result["evidence_packets"]
    assert result["evidence_packets"][0]["field_candidate"]
    assert result["confidence_scores"]["document_parsing"] > 0


@pytest.mark.anyio
async def test_document_parser_falls_back_when_deep_result_is_too_sparse(monkeypatch):
    agent = DocumentParserAgent()

    async def fallback_extract(*args, **kwargs):
        return {
            "document_type": "research_paper",
            "title": "Fallback title",
            "authors": ["Fallback Author"],
            "research_domain": "genomics",
        }

    async def fake_invoke(*args, **kwargs):
        return DocumentInfoResponse(document_type="research_paper", confidence=0.2)

    monkeypatch.setattr(agent.llm_helper, "extract_document_info", fallback_extract)
    monkeypatch.setattr(agent, "_build_dp_inner_agent", lambda *args, **kwargs: object())
    monkeypatch.setattr(agent, "_invoke_react_agent", fake_invoke)

    state = {
        "document_path": "examples/inputs/test_document.txt",
        "document_content": "Short test document",
        "document_conversion": {},
        "context": {},
        "agent_guidance": {},
        "confidence_scores": {},
        "errors": [],
    }

    result = await agent.execute(state)

    assert result["document_info"]["title"] == "Fallback title"
    assert result["document_info"]["research_domain"] == "genomics"
    assert result["evidence_packets"]


@pytest.mark.anyio
async def test_document_parser_skips_deep_react_for_long_raw_qwen(monkeypatch):
    agent = DocumentParserAgent()

    async def fallback_extract(*args, **kwargs):
        return {
            "document_type": "research_paper",
            "title": "Fallback long-doc title",
            "authors": ["Fallback Author"],
            "research_domain": "ecotoxicology",
        }

    monkeypatch.setattr(config, "llm_provider", "qwen")
    monkeypatch.setattr(agent.llm_helper, "extract_document_info", fallback_extract)
    monkeypatch.setattr(
        agent,
        "_build_dp_inner_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("deep ReAct should be skipped")),
    )

    state = {
        "document_path": "examples/inputs/earthworm_4n_paper_bioRxiv.pdf",
        "document_content": "A" * 50000,
        "document_conversion": {},
        "context": {},
        "agent_guidance": {},
        "confidence_scores": {},
        "errors": [],
    }

    result = await agent.execute(state)

    assert result["document_info"]["title"] == "Fallback long-doc title"
    assert result["evidence_packets"]


@pytest.mark.anyio
async def test_knowledge_retriever_uses_deep_selection_and_preserves_state_shape(monkeypatch):
    agent = KnowledgeRetrieverAgent()

    def get_available_packages(_payload):
        return {"success": True, "data": ["default", "miappe"], "error": None}

    def get_package(payload):
        package_name = payload["package_name"]
        if package_name == "default":
            return {
                "success": True,
                "data": {
                    "packageName": "default",
                    "metadata": [
                        {
                            "sheetName": "Investigation",
                            "packageName": "default",
                            "requirement": "MANDATORY",
                            "label": "investigation identifier",
                            "term": {"definition": "Investigation id", "url": "http://example.org/inv"},
                        }
                    ],
                },
                "error": None,
            }
        return {
            "success": True,
            "data": {
                "packageName": "miappe",
                "metadata": [
                    {
                        "sheetName": "Study",
                        "packageName": "miappe",
                        "requirement": "MANDATORY",
                        "label": "study title",
                        "term": {"definition": "Study title", "url": "http://example.org/study-title"},
                    },
                    {
                        "sheetName": "Study",
                        "packageName": "miappe",
                        "requirement": "OPTIONAL",
                        "label": "study description",
                        "term": {"definition": "Study description", "url": "http://example.org/study-description"},
                    },
                ],
            },
            "error": None,
        }

    agent.tools = {
        "get_available_packages": StubTool("get_available_packages", get_available_packages),
        "get_package": StubTool("get_package", get_package),
        "get_terms": StubTool("get_terms", lambda _payload: {"success": True, "data": {}, "error": None}),
        "search_terms_for_fields": StubTool("search_terms_for_fields", lambda _payload: {"success": True, "data": [], "error": None}),
        "search_fields_in_packages": StubTool("search_fields_in_packages", lambda _payload: {"success": True, "data": [], "error": None}),
    }
    agent.fair_ds_client = object()

    async def fake_invoke(*args, **kwargs):
        return KnowledgeResponse(
            selected_packages=["default", "miappe"],
            selected_optional_fields={"Study": ["study description"]},
            terms_to_search=["earthworm"],
            coverage_confidence=0.88,
        )

    async def fail_package_select(*args, **kwargs):
        raise AssertionError("fallback package selector should not be called")

    async def fail_field_select(*args, **kwargs):
        raise AssertionError("fallback field selector should not be called")

    monkeypatch.setattr(agent, "_build_kr_inner_agent", lambda *args, **kwargs: object())
    monkeypatch.setattr(agent, "_invoke_react_agent", fake_invoke)
    monkeypatch.setattr(
        "fairifier.agents.knowledge_retriever_llm_methods.llm_select_relevant_packages",
        fail_package_select,
    )
    monkeypatch.setattr(
        "fairifier.agents.knowledge_retriever_llm_methods.llm_select_fields_from_package",
        fail_field_select,
    )

    state = {
        "document_info": {
            "document_type": "research_paper",
            "research_domain": "ecotoxicology",
            "title": "Earthworm response",
            "keywords": ["earthworm"],
        },
        "context": {},
        "agent_guidance": {},
        "confidence_scores": {},
        "errors": [],
        "evidence_packets": [
            {
                "packet_id": "ep-001",
                "field_candidate": "methodology",
                "value": "RNA-seq",
                "evidence_text": "Methods section mentions RNA-seq on earthworm exposure samples.",
                "section": "Methods",
                "source_type": "mineru_markdown",
                "confidence": 0.9,
                "provenance": {"agent": "DocumentParser"},
            }
        ],
    }

    result = await agent.execute(state)

    assert len(result["retrieved_knowledge"]) == 3
    assert result["api_capabilities"]["available_packages"] == ["default", "miappe"]
    assert any(item["metadata"]["label"] == "study description" for item in result["retrieved_knowledge"])


def test_knowledge_retriever_runtime_cache_persists_across_state_snapshots():
    class CountingClient:
        def __init__(self):
            self.available_calls = 0

        def get_available_packages(self, force_refresh: bool = False):
            self.available_calls += 1
            return ["default", "soil"]

        def get_package(self, package_name: str):
            return {"packageName": package_name, "metadata": []}

        def get_terms(self, force_refresh: bool = False):
            return {}

        def search_terms_for_fields(self, term_label: str, definition: str | None = None):
            return []

        def search_fields_in_packages(self, field_label: str, package_names=None):
            return []

    agent = KnowledgeRetrieverAgent.__new__(KnowledgeRetrieverAgent)
    agent.fair_ds_client = CountingClient()
    agent.tools = {}
    agent._fairds_runtime_cache = {}
    agent._science_runtime_cache = {}

    state_one = {"retrieval_cache": {}}
    state_two = {"retrieval_cache": {}}

    tools_one = agent._build_runtime_tools(state_one)
    tools_two = agent._build_runtime_tools(state_two)
    result_one = tools_one["get_available_packages"].invoke({"force_refresh": False})
    result_two = tools_two["get_available_packages"].invoke({"force_refresh": False})

    assert result_one["success"] is True
    assert result_two["success"] is True
    assert agent.fair_ds_client.available_calls == 1
    assert state_one["retrieval_cache"]["fairds_tools"]
    assert state_two["retrieval_cache"]["fairds_tools"]


def test_knowledge_retriever_candidate_packages_exclude_obvious_domain_mismatch():
    agent = KnowledgeRetrieverAgent.__new__(KnowledgeRetrieverAgent)

    available = [
        "default",
        "soil",
        "sediment",
        "Illumina",
        "Genome",
        "human oral",
        "Plant Sample Checklist",
        "miappe",
        "pig_blood",
    ]
    doc_info = {
        "title": "Gene expression profile dynamics of earthworms exposed to ZnO nanomaterials",
        "research_domain": "Systems Biology, Nanotoxicology, Ecotoxicology",
        "keywords": ["earthworm", "soil", "RNA-seq"],
        "methodology": "RNA-seq transcriptomics",
    }
    evidence_packets = [
        {"value": "earthworm soil exposure RNA-seq"},
    ]

    excluded = agent._infer_excluded_packages(doc_info, None, available, evidence_packets)
    candidates = agent._build_candidate_package_names(
        doc_info,
        None,
        available,
        evidence_packets,
        ["default", "soil", "Illumina"],
        excluded,
    )

    assert "human oral" in excluded
    assert "Plant Sample Checklist" in excluded
    assert "pig_blood" in excluded
    assert "default" in candidates
    assert "soil" in candidates
    assert "Illumina" in candidates
    assert "human oral" not in candidates
    assert "Plant Sample Checklist" not in candidates


@pytest.mark.anyio
async def test_llm_package_selector_does_not_force_priority_hints():
    class StubResponse:
        content = """```json
{
  "selected_packages": ["ENA Micro B3"],
  "reasoning": "Best environmental assay package"
}
```"""

    class StubLLMHelper:
        async def _call_llm(self, messages, operation_name=None):
            return StubResponse()

    selected = await kr_llm_methods.llm_select_relevant_packages(
        StubLLMHelper(),
        doc_info={"title": "Earthworm ZnO RNA-seq"},
        all_packages=[
            {"name": "default", "field_count": 10, "mandatory_count": 8, "optional_count": 2, "sheets": ["Investigation"]},
            {"name": "soil", "field_count": 12, "mandatory_count": 6, "optional_count": 6, "sheets": ["Sample"]},
            {"name": "Illumina", "field_count": 8, "mandatory_count": 6, "optional_count": 2, "sheets": ["Assay"]},
            {"name": "ENA Micro B3", "field_count": 20, "mandatory_count": 10, "optional_count": 10, "sheets": ["Assay", "Sample"]},
        ],
        priority_package_hints=["default", "soil", "Illumina"],
    )

    assert selected == ["ENA Micro B3"]


@pytest.mark.anyio
async def test_llm_field_selector_handles_list_based_content_blocks():
    class StubResponse:
        content = [
            {
                "type": "text",
                "text": """```json
{
  "selected_fields": ["study title", "study description"],
  "terms_to_search": ["phytosanitary regulation"]
}
```""",
            }
        ]

    class StubLLMHelper:
        async def _call_llm(self, messages, operation_name=None):
            return StubResponse()

    result = await kr_llm_methods.llm_select_fields_from_package(
        StubLLMHelper(),
        doc_info={"title": "POMATO proposal"},
        isa_sheet="study",
        package_name="default",
        mandatory_fields=[],
        optional_fields=[
            {"label": "study title"},
            {"label": "study description"},
            {"label": "study design type"},
        ],
    )

    assert [field["label"] for field in result["selected_fields"]] == [
        "study title",
        "study description",
    ]
    assert result["terms_to_search"] == ["phytosanitary regulation"]


def test_knowledge_retriever_extracts_packages_named_in_guidance():
    agent = KnowledgeRetrieverAgent.__new__(KnowledgeRetrieverAgent)

    guided = agent._extract_guided_package_names(
        ["air", "default", "soil", "Illumina", "ENA Micro B3", "ENA parasite sample checklist"],
        critic_feedback={
            "suggestions": [
                "Prioritize 'ENA Micro B3' for environmental microbiome context",
                "Re-query API using 'ENA parasite sample checklist'",
            ]
        },
        planner_instruction="Use soil metadata when possible, not just generic FAIR-DS package names.",
        guidance_history=["default is only for missing investigation fields"],
    )

    assert guided == ["default", "soil", "ENA Micro B3", "ENA parasite sample checklist"]
    assert "air" not in guided


def test_knowledge_retriever_normalizes_selected_packages_and_preserves_gaps():
    agent = KnowledgeRetrieverAgent.__new__(KnowledgeRetrieverAgent)

    selected, gaps = agent._normalize_selected_packages(
        ["default", "transcriptomics", "Illumina", "custom exposomics"],
        ["default", "Illumina", "soil"],
    )

    assert selected == ["default", "Illumina"]
    assert gaps == ["transcriptomics", "custom exposomics"]


def test_knowledge_retriever_builds_metadata_gap_hints_from_unmapped_requests():
    agent = KnowledgeRetrieverAgent.__new__(KnowledgeRetrieverAgent)

    hints = agent._build_metadata_gap_hints(
        doc_info={"title": "Earthworm transcriptomics under ZnO exposure", "methodology": "RNA-seq"},
        evidence_packets=[
            {
                "packet_id": "ep-001",
                "field_candidate": "transcriptomics profile",
                "value": "RNA-seq gene expression measurements",
                "evidence_text": "Methods describe transcriptomics profiling with Illumina sequencing.",
                "confidence": 0.88,
            }
        ],
        final_selected_fields=[{"label": "study title"}],
        planner_instruction="Prioritize transcriptomics metadata even if FAIR-DS lacks a dedicated package.",
        structured_gap_hints=["transcriptomics"],
        all_terms_to_search=["transcriptomics", "exposure duration"],
        term_search_outcomes={
            "transcriptomics": {"terms_found": 0, "fields_found": 0},
            "exposure duration": {"terms_found": 1, "fields_found": 0},
        },
        selected_package_names=["default", "Illumina"],
        available_package_names=["default", "Illumina", "soil"],
    )

    labels = {hint["label"] for hint in hints}

    assert "transcriptomics" in labels
    assert "transcriptomics profile" in labels
    assert "exposure duration" not in labels
    assert all(hint["status"] == "unmapped_to_fairds" for hint in hints)


def test_kr_inner_agent_scopes_field_search_to_candidate_packages(monkeypatch):
    captured_payloads = []
    agent = KnowledgeRetrieverAgent.__new__(KnowledgeRetrieverAgent)
    agent.tools = {
        "get_available_packages": StubTool("get_available_packages", lambda _payload: {"success": True, "data": ["soil"], "error": None}),
        "get_package": StubTool("get_package", lambda payload: {"success": True, "data": {"packageName": payload["package_name"], "metadata": []}, "error": None}),
        "search_terms_for_fields": StubTool("search_terms_for_fields", lambda payload: {"success": True, "data": [], "error": None}),
        "search_fields_in_packages": StubTool(
            "search_fields_in_packages",
            lambda payload: captured_payloads.append(payload) or {"success": True, "data": [], "error": None},
        ),
    }
    agent._get_memory_files = lambda: []
    monkeypatch.setattr("fairifier.agents.knowledge_retriever.create_science_tools", lambda cache_store=None: [])
    monkeypatch.setattr(agent, "_build_react_agent", lambda **kwargs: kwargs["tools"])

    tools = agent._build_kr_inner_agent(default_candidate_packages=["soil", "ENA Micro B3"])
    search_tool = next(tool for tool in tools if tool.name == "search_package_fields")

    search_tool.invoke({"field_label": "RNA-seq", "package_names": ""})

    assert captured_payloads == [
        {"field_label": "RNA-seq", "package_names": "soil,ENA Micro B3"}
    ]


def test_knowledge_retriever_skips_deep_react_for_broad_qwen_candidate_set(monkeypatch):
    agent = KnowledgeRetrieverAgent.__new__(KnowledgeRetrieverAgent)

    monkeypatch.setattr(config, "llm_provider", "qwen")
    assert agent._should_skip_deep_react(["default", "Illumina", "soil", "sediment", "water", "misc", "Genome", "built"]) is True
    assert agent._should_skip_deep_react(["default", "Illumina", "soil"]) is False


def test_json_generator_emits_inferred_extensions_for_metadata_gaps():
    agent = JSONGeneratorAgent()

    extensions = agent._build_inferred_metadata_extensions(
        [
            {
                "label": "transcriptomics",
                "source": "term_search",
                "reason": "No FAIR-DS package directly captures transcriptomics context.",
                "confidence": 0.7,
                "packet_id": "ep-001",
            }
        ],
        {"title": "Earthworm transcriptomics response"},
        [
            {
                "packet_id": "ep-001",
                "field_candidate": "transcriptomics profile",
                "value": "RNA-seq gene expression measurements",
                "evidence_text": "Methods describe transcriptomics profiling with Illumina sequencing.",
                "confidence": 0.88,
            }
        ],
    )

    assert len(extensions) == 1
    assert extensions[0]["field_name"] == "transcriptomics"
    assert extensions[0]["value"] == "RNA-seq gene expression measurements"
    assert extensions[0]["status"] == "provisional_extension"
