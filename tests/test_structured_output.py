"""Tests for provider-aware structured LLM output helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

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
    structured_llm = MagicMock()
    structured_llm.ainvoke = AsyncMock(
        return_value=SampleSchema(score=0.8, critique="ok", issues=[])
    )
    llm.with_structured_output.return_value = structured_llm
    llm_helper.get_llm.return_value = llm

    parsed = await invoke_structured_output(
        llm_helper,
        [HumanMessage(content="Evaluate.")],
        SampleSchema,
    )

    llm.with_structured_output.assert_called_once_with(SampleSchema)
    assert parsed["score"] == 0.8
