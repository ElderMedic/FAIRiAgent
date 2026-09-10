"""Tests for provider-aware structured LLM output helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from fairifier.agents.response_models import EntityPlanScopeAuditResponse
from fairifier.utils.structured_output import (
    StructuredOutputMode,
    append_json_schema_instructions,
    invoke_structured_output,
    pydantic_json_example,
    resolve_structured_output_mode,
    supports_api_json_object,
)


class SampleSchema(BaseModel):
    score: float = Field(description="Score")
    critique: str = ""
    issues: list[str] = Field(default_factory=list)


class AliasSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_name: str = Field(
        validation_alias=AliasChoices("dimension_name", "dimension")
    )


class TestStructuredOutputMode:
    def test_deepseek_uses_json_object(self):
        assert resolve_structured_output_mode("deepseek") == StructuredOutputMode.JSON_OBJECT

    def test_openai_uses_json_schema(self):
        assert resolve_structured_output_mode("openai") == StructuredOutputMode.JSON_SCHEMA

    def test_ollama_uses_prompt_json(self):
        assert resolve_structured_output_mode("ollama") == StructuredOutputMode.PROMPT_JSON

    def test_supports_api_json_object(self):
        assert supports_api_json_object("deepseek") is True
        assert supports_api_json_object("ollama") is False


class TestPromptHelpers:
    def test_append_json_schema_instructions_includes_json_word(self):
        prompt = append_json_schema_instructions("Evaluate output.", SampleSchema)
        assert "json" in prompt.lower()
        assert "score" in prompt

    def test_pydantic_json_example_has_all_fields(self):
        example = pydantic_json_example(SampleSchema)
        assert set(example.keys()) == {"score", "critique", "issues"}


@pytest.mark.asyncio
async def test_invoke_structured_output_deepseek_json_object():
    llm_helper = MagicMock()
    llm_helper.provider = "deepseek"
    llm_helper._call_llm = AsyncMock(
        return_value=MagicMock(
            content='{"score": 0.9, "critique": "good", "issues": [], "suggestions": []}'
        )
    )

    parsed = await invoke_structured_output(
        llm_helper,
        [HumanMessage(content="Evaluate this output.")],
        SampleSchema,
        operation_name="test.critic",
        max_tokens=512,
    )

    llm_helper._call_llm.assert_awaited_once()
    call_kwargs = llm_helper._call_llm.await_args.kwargs
    assert call_kwargs["json_mode"] is True
    assert call_kwargs["max_tokens"] == 512
    assert parsed["score"] == 0.9


@pytest.mark.asyncio
async def test_invoke_structured_output_openai_json_schema():
    llm_helper = MagicMock()
    llm_helper.provider = "openai"
    llm = MagicMock()
    llm.max_tokens = 65536
    llm.model_fields = {"max_tokens": object()}
    copied = MagicMock()
    structured_llm = MagicMock()
    raw = AIMessage(
        content='{"score": 0.8, "critique": "ok", "issues": []}',
        usage_metadata={
            "input_tokens": 11,
            "output_tokens": 5,
            "total_tokens": 16,
            "input_token_details": {"cache_read": 7},
        },
    )
    structured_llm.ainvoke = AsyncMock(
        return_value={
            "raw": raw,
            "parsed": SampleSchema(score=0.8, critique="ok", issues=[]),
            "parsing_error": None,
        }
    )
    copied.with_structured_output.return_value = structured_llm
    llm.model_copy.return_value = copied
    llm_helper.get_llm.return_value = llm

    parsed = await invoke_structured_output(
        llm_helper,
        [HumanMessage(content="Evaluate.")],
        SampleSchema,
        max_tokens=1024,
    )

    llm.model_copy.assert_called_once_with(update={"max_tokens": 1024})
    # Shared instance must not be mutated by Critic's low budget.
    assert llm.max_tokens == 65536
    copied.with_structured_output.assert_called_once_with(
        SampleSchema,
        include_raw=True,
    )
    llm_helper._log_llm_response.assert_called_once_with(
        raw,
        [HumanMessage(content="Evaluate.")],
        "StructuredOutput",
    )
    assert parsed["score"] == 0.8


@pytest.mark.asyncio
async def test_invoke_structured_output_logs_direct_schema_errors_before_fallback():
    llm_helper = MagicMock()
    llm_helper.provider = "openai"
    llm = MagicMock()
    llm.model_fields = {}
    structured_llm = MagicMock()
    failure = RuntimeError("provider rejected schema")
    structured_llm.ainvoke = AsyncMock(side_effect=failure)
    llm.with_structured_output.return_value = structured_llm
    llm.model_copy.return_value = llm
    llm_helper.get_llm.return_value = llm
    llm_helper._call_llm = AsyncMock(
        return_value=MagicMock(
            content='{"score": 0.7, "critique": "fallback", "issues": []}'
        )
    )

    parsed = await invoke_structured_output(
        llm_helper,
        [HumanMessage(content="Evaluate.")],
        SampleSchema,
        operation_name="Critic.DocumentParser",
    )

    llm_helper._log_llm_error.assert_called_once_with(
        [HumanMessage(content="Evaluate.")],
        "Critic.DocumentParser",
        failure,
    )
    assert parsed["score"] == 0.7


@pytest.mark.asyncio
async def test_prompt_json_is_schema_validated_and_aliases_are_canonicalized():
    llm_helper = MagicMock()
    llm_helper.provider = "ollama"
    llm_helper._call_llm = AsyncMock(
        return_value=MagicMock(content='{"dimension": "developmental_stage"}')
    )

    parsed = await invoke_structured_output(
        llm_helper,
        [HumanMessage(content="Audit the dimension.")],
        AliasSchema,
    )

    assert parsed == {"dimension_name": "developmental_stage"}


@pytest.mark.asyncio
async def test_prompt_json_returns_none_when_schema_validation_fails():
    llm_helper = MagicMock()
    llm_helper.provider = "ollama"
    llm_helper._call_llm = AsyncMock(
        return_value=MagicMock(content='{"unexpected": "value"}')
    )

    parsed = await invoke_structured_output(
        llm_helper,
        [HumanMessage(content="Audit the dimension.")],
        AliasSchema,
    )

    assert parsed is None


@pytest.mark.asyncio
async def test_prompt_json_retries_one_transient_transport_failure():
    llm_helper = MagicMock()
    llm_helper.provider = "ollama"
    llm_helper._call_llm = AsyncMock(
        side_effect=[
            RuntimeError("incomplete chunked read"),
            MagicMock(content='{"dimension": "developmental_stage"}'),
        ]
    )

    parsed = await invoke_structured_output(
        llm_helper,
        [HumanMessage(content="Audit the dimension.")],
        AliasSchema,
        operation_name="EntityStructurePlanner.scope_audit",
    )

    assert parsed == {"dimension_name": "developmental_stage"}
    assert llm_helper._call_llm.await_count == 2


@pytest.mark.asyncio
async def test_prompt_json_returns_none_after_transport_retries_exhausted():
    llm_helper = MagicMock()
    llm_helper.provider = "ollama"
    llm_helper._call_llm = AsyncMock(side_effect=RuntimeError("connection reset"))

    parsed = await invoke_structured_output(
        llm_helper,
        [HumanMessage(content="Audit the dimension.")],
        AliasSchema,
        operation_name="EntityStructurePlanner.scope_audit",
    )

    assert parsed is None
    assert llm_helper._call_llm.await_count == 2


@pytest.mark.asyncio
async def test_prompt_json_scope_audit_accepts_common_group_alias():
    llm_helper = MagicMock()
    llm_helper.provider = "ollama"
    llm_helper._call_llm = AsyncMock(
        return_value=MagicMock(
            content="""{
                "missing_conditions": [],
                "mapping_corrections": [],
                "mapping_decisions": [{
                    "group": "group_001",
                    "dimension": "stage",
                    "mappings": []
                }],
                "reuse_validations": [{
                    "group": "group_001",
                    "approved": false,
                    "reason": "No source-grounded reuse"
                }],
                "dimension_scopes": [{
                    "group": "group_001",
                    "dimension": "stage",
                    "applies_to": ["sample", "assay"]
                }]
            }"""
        )
    )

    parsed = await invoke_structured_output(
        llm_helper,
        [HumanMessage(content="Audit the entity plan.")],
        EntityPlanScopeAuditResponse,
    )

    assert parsed["mapping_decisions"][0]["group_id"] == "group_001"
    assert parsed["reuse_validations"][0]["group_id"] == "group_001"
    assert parsed["reuse_validations"][0]["rationale"] == "No source-grounded reuse"
    assert parsed["dimension_scopes"][0]["group_id"] == "group_001"
