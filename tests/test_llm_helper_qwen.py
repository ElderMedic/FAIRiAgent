"""Tests for provider-specific LLM parameter normalization."""

from types import MethodType, SimpleNamespace

import pytest

from fairifier.utils.llm_helper import (
    LLMHelper,
    QWEN_MAX_TOKENS_LIMIT,
    _normalize_extracted_document_info,
)
from fairifier.config import config


def test_qwen_max_tokens_is_clamped(monkeypatch):
    """DashScope-backed Qwen requests should cap max_tokens to provider limits."""
    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "qwen"

    monkeypatch.setattr(config, "llm_max_tokens", 100000)

    assert helper._resolved_max_tokens() == QWEN_MAX_TOKENS_LIMIT


def test_qwen_max_tokens_preserves_valid_values(monkeypatch):
    """Valid Qwen max_tokens should pass through unchanged."""
    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "qwen"

    monkeypatch.setattr(config, "llm_max_tokens", 4096)

    assert helper._resolved_max_tokens() == 4096


def test_non_qwen_providers_keep_configured_max_tokens(monkeypatch):
    """Other providers should keep the configured value."""
    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "ollama"

    monkeypatch.setattr(config, "llm_max_tokens", 100000)

    assert helper._resolved_max_tokens() == 100000


def test_document_info_normalization_salvages_nested_metadata():
    """Nested adaptive JSON should be normalized back into the compact document_info schema."""
    raw = {
        "document_type": "Research Article",
        "domain": "Environmental Toxicology",
        "bibliographic_metadata": {
            "title": "Gene expression profile dynamics of earthworms exposed to nanomaterials",
            "authors": [
                {"name": "Henk J. van Lingen"},
                {"name": "Changlin Ke"},
            ],
        },
        "experimental_design": {
            "analysis_workflow": "RNA-seq differential expression analysis",
            "variables": ["time point", "treatment"],
        },
        "study_objectives": [
            "Investigate time-dependent gene expression response in earthworms"
        ],
    }

    normalized = _normalize_extracted_document_info(raw)

    assert normalized["title"].startswith("Gene expression profile")
    assert normalized["research_domain"] == "Environmental Toxicology"
    assert normalized["authors"] == ["Henk J. van Lingen", "Changlin Ke"]
    assert normalized["methodology"] == "RNA-seq differential expression analysis"
    assert normalized["variables"] == ["time point", "treatment"]
    assert normalized["key_findings"] == [
        "Investigate time-dependent gene expression response in earthworms"
    ]


@pytest.mark.anyio
async def test_openai_uses_reasoning_effort_not_enable_thinking(monkeypatch):
    """OpenAI reasoning models use reasoning_effort, not DashScope extra_body flags."""

    class DummyLLM:
        def __init__(self):
            self.bind_calls = []
            self.ainvoke_calls = []

        def bind(self, **kwargs):
            self.bind_calls.append(kwargs)
            return self

        async def ainvoke(self, messages, config=None):
            self.ainvoke_calls.append({"messages": messages, "config": config})
            return SimpleNamespace(content="OK")

    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "openai"
    helper.model = "gpt-5.4"
    helper.llm = DummyLLM()
    helper._langfuse_handler = None
    helper._log_llm_response = lambda *args, **kwargs: None

    monkeypatch.setattr(config, "llm_enable_thinking", True)

    result = await helper._call_llm(["hello"], operation_name="test-openai")

    assert result.content == "OK"
    assert helper.llm.bind_calls == [{"reasoning_effort": "medium"}]
    assert len(helper.llm.ainvoke_calls) == 1


@pytest.mark.anyio
async def test_openai_thinking_disabled_no_bind(monkeypatch):
    """When thinking is disabled, OpenAI should not bind any extra parameters."""

    class DummyLLM:
        def __init__(self):
            self.bind_calls = []
            self.ainvoke_calls = []

        def bind(self, **kwargs):
            self.bind_calls.append(kwargs)
            return self

        async def ainvoke(self, messages, config=None):
            self.ainvoke_calls.append({"messages": messages, "config": config})
            return SimpleNamespace(content="OK")

    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "openai"
    helper.model = "gpt-4.1"
    helper.llm = DummyLLM()
    helper._langfuse_handler = None
    helper._log_llm_response = lambda *args, **kwargs: None

    monkeypatch.setattr(config, "llm_enable_thinking", False)

    result = await helper._call_llm(["hello"], operation_name="test-openai")

    assert result.content == "OK"
    assert helper.llm.bind_calls == []
    assert len(helper.llm.ainvoke_calls) == 1


@pytest.mark.anyio
async def test_generate_complete_metadata_splits_large_batches():
    """Large metadata generations should be split into smaller LLM batches."""
    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "anthropic"
    helper.model = "claude-opus-4-6"

    calls = []

    async def fake_batch(
        self,
        document_info,
        selected_fields,
        document_text,
        critic_feedback=None,
        planner_instruction=None,
        prior_memory_context=None,
        batch_label=None,
    ):
        calls.append([field["name"] for field in selected_fields])
        return [
            {
                "field_name": field["name"],
                "value": "value",
                "evidence": f"batch {batch_label}",
                "confidence": 0.9,
            }
            for field in selected_fields
        ]

    helper._generate_complete_metadata_batch = MethodType(fake_batch, helper)
    helper._metadata_generation_batch_size = MethodType(lambda self: 10, helper)

    selected_fields = [
        {"name": f"field_{idx}", "description": "desc", "required": False, "isa_sheet": "sample"}
        for idx in range(25)
    ]

    result = await helper.generate_complete_metadata(
        document_info={"title": "doc"},
        selected_fields=selected_fields,
        document_text="text",
    )

    assert len(calls) == 3
    assert [len(batch) for batch in calls] == [10, 10, 5]
    assert len(result) == 25
    assert result[0]["field_name"] == "field_0"
    assert result[-1]["field_name"] == "field_24"


@pytest.mark.anyio
async def test_generate_complete_metadata_recursively_splits_failed_batch():
    """Failed large batches should recursively split until they succeed."""
    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "anthropic"
    helper.model = "claude-opus-4-6"

    call_sizes = []

    async def flaky_batch(
        self,
        document_info,
        selected_fields,
        document_text,
        critic_feedback=None,
        planner_instruction=None,
        prior_memory_context=None,
        batch_label=None,
    ):
        call_sizes.append(len(selected_fields))
        if len(selected_fields) > 2:
            raise ValueError("empty response")
        return [
            {
                "field_name": field["name"],
                "value": "ok",
                "evidence": "split batch",
                "confidence": 0.8,
            }
            for field in selected_fields
        ]

    helper._generate_complete_metadata_batch = MethodType(flaky_batch, helper)
    helper._metadata_generation_batch_size = MethodType(lambda self: 6, helper)

    selected_fields = [
        {"name": f"field_{idx}", "description": "desc", "required": False, "isa_sheet": "sample"}
        for idx in range(6)
    ]

    result = await helper.generate_complete_metadata(
        document_info={"title": "doc"},
        selected_fields=selected_fields,
        document_text="text",
    )

    assert call_sizes[0] == 6
    assert any(size == 3 for size in call_sizes)
    assert len(result) == 6
    assert [item["field_name"] for item in result] == [f"field_{idx}" for idx in range(6)]
