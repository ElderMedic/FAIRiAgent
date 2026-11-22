"""Tests for provider-aware structured LLM output helpers."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from fairifier.agents.response_models import EntityPlanScopeAuditResponse
from fairifier.utils.json_parse import parse_llm_json
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


class CountedFactorSchema(BaseModel):
    level_count: int | None = Field(default=None, ge=1)


class CountedDesignSchema(BaseModel):
    dimensions: list[CountedFactorSchema]
    design_summary: list[str] = Field(default_factory=list)


@pytest.mark.parametrize("wrapper", ["{}", "```json\n{}\n```", "Answer:\n{}\nDone."])
def test_source_math_backslashes_are_preserved_when_json_escaping_is_missing(wrapper):
    raw = r'{"quote":"at 60^{\circ} C with 1 \mu mol","value":-2.5,"known":false}'
    parsed = parse_llm_json(wrapper.format(raw))
    assert parsed == {"quote": r"at 60^{\circ} C with 1 \mu mol", "value": -2.5, "known": False}


def test_literal_escape_recovery_preserves_valid_json_escapes():
    raw = r'{"quote":"\mu then \\mu","newline":"a\nb","unicode":"\u03bc","path":"a\\b","quoted":"a\"b"}'
    parsed = parse_llm_json(raw)
    assert parsed == {"quote": r"\mu then \mu", "newline": "a\nb",
                      "unicode": "μ", "path": r"a\b", "quoted": 'a"b'}


@pytest.mark.parametrize("raw", [
    r'{"quote":"\mu","value":}',
    r'{"quote":"\mu",',
    r'{"quote":"\mu", "unicode":"\uZZZZ"}',
    r'{"quote":"\mu" "value":1}',
])
def test_literal_escape_recovery_does_not_complete_or_invent_json(raw):
    assert parse_llm_json(raw) is None


class TestStructuredOutputMode:
    def test_deepseek_uses_json_object(self):
        assert resolve_structured_output_mode("deepseek") == StructuredOutputMode.JSON_OBJECT

    def test_openai_uses_json_schema(self):
        assert resolve_structured_output_mode("openai") == StructuredOutputMode.JSON_SCHEMA

    def test_ollama_uses_constrained_json_unless_disabled(self, monkeypatch):
        from fairifier.config import config

        assert resolve_structured_output_mode("ollama") == StructuredOutputMode.JSON_OBJECT
        monkeypatch.setattr(config, "ollama_constrained_json", False)
        assert resolve_structured_output_mode("ollama") == StructuredOutputMode.PROMPT_JSON

    def test_supports_api_json_object(self):
        assert supports_api_json_object("deepseek") is True
        assert supports_api_json_object("ollama") is False


class TestPromptHelpers:
    def test_nested_record_contract_reaches_prompt_json_provider(self):
        prompt = append_json_schema_instructions("Plan source records.", CountedDesignSchema)
        assert '"$defs"' in prompt
        assert '"level_count"' in prompt
        assert '"minimum": 1' in prompt
        assert '"type": "null"' in prompt

    def test_append_json_schema_instructions_includes_json_word(self):
        prompt = append_json_schema_instructions("Evaluate output.", SampleSchema)
        assert "json" in prompt.lower()
        assert "score" in prompt

    def test_pydantic_json_example_has_all_fields(self):
        example = pydantic_json_example(SampleSchema)
        assert set(example.keys()) == {"score", "critique", "issues"}


@pytest.mark.asyncio
@pytest.mark.parametrize("thinking", [True, False])
@pytest.mark.parametrize("format_failure", [True, False])
async def test_deepseek_json_request_preserves_thinking_and_output_budget(
    monkeypatch, thinking, format_failure
):
    from fairifier.config import config
    from fairifier.utils.llm_helper import LLMHelper

    monkeypatch.setattr(config, "llm_enable_thinking", thinking)
    monkeypatch.setattr(config, "llm_reasoning_effort", "high")
    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "deepseek"
    helper.llm = MagicMock()
    helper._log_llm_response = MagicMock()
    reply = AIMessage(content='{"score": 0.9}')
    bound = helper.llm.bind.return_value
    bound.ainvoke = AsyncMock(
        side_effect=[RuntimeError("format rejected"), reply] if format_failure else [reply]
    )
    result = await helper._call_llm_json_object(
        [HumanMessage(content="Return JSON.")], "contract_test", 2048, None
    )
    assert result is reply
    assert len(helper.llm.bind.call_args_list) == (2 if format_failure else 1)
    for call in helper.llm.bind.call_args_list:
        assert call.kwargs["extra_body"]["thinking"]["type"] == (
            "enabled" if thinking else "disabled"
        )
        assert call.kwargs["max_tokens"] == 2048
        if thinking:
            assert call.kwargs["reasoning_effort"] == "high"
    assert helper.llm.bind.call_args_list[0].kwargs["response_format"] == {"type": "json_object"}
    if format_failure:
        assert "response_format" not in helper.llm.bind.call_args_list[-1].kwargs


@pytest.mark.parametrize("call_limit", [None, 8192])
def test_deepseek_wire_payload_uses_supported_token_limit(monkeypatch, call_limit):
    from fairifier.config import config
    from fairifier.utils.llm_helper import LLMHelper

    monkeypatch.setattr(config, "llm_api_key", "test-placeholder-no-network")
    monkeypatch.setattr(config, "llm_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(config, "llm_max_tokens", 32768)
    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "deepseek"
    helper.model = "deepseek-flash"
    adapter = helper._initialize_llm()
    kwargs = {"max_tokens": call_limit} if call_limit is not None else {}
    payload = adapter._get_request_payload(
        [HumanMessage(content="Return JSON.")],
        extra_body={"thinking": {"type": "enabled"}},
        response_format={"type": "json_object"},
        **kwargs,
    )
    assert payload["max_tokens"] == (call_limit or 32768)
    assert "max_completion_tokens" not in payload
    assert payload["extra_body"]["thinking"]["type"] == "enabled"


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
async def test_prompt_json_retries_one_transient_transport_failure(monkeypatch):
    from fairifier.config import config

    monkeypatch.setattr(config, "ollama_constrained_json", False)  # exercise prompt JSON
    sleep = AsyncMock()
    monkeypatch.setattr("fairifier.utils.structured_output.asyncio.sleep", sleep)
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
    sleep.assert_awaited_once_with(5.0)


@pytest.mark.asyncio
async def test_prompt_json_returns_none_after_transport_retries_exhausted(monkeypatch):
    from fairifier.config import config

    monkeypatch.setattr(config, "ollama_constrained_json", False)  # exercise prompt JSON
    sleep = AsyncMock()
    monkeypatch.setattr("fairifier.utils.structured_output.asyncio.sleep", sleep)
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
    assert llm_helper._call_llm.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [5.0, 15.0]


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


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["deepseek", "ollama"])
async def test_schema_error_sink_reports_nested_constraint_without_retry(provider):
    helper = MagicMock()
    helper.provider = provider
    helper._call_llm = AsyncMock(return_value=AIMessage(
        content='{"dimensions": [{"level_count": 0}], "design_summary": []}'
    ))
    errors = []

    parsed = await invoke_structured_output(
        helper, [HumanMessage(content="Extract the reported design.")],
        CountedDesignSchema, validation_errors=errors,
    )

    assert parsed is None
    assert any("dimensions.0.level_count" in error for error in errors)
    assert any("greater_than_equal" in error and "1" in error for error in errors)
    helper._call_llm.assert_awaited_once()


@pytest.mark.asyncio
async def test_schema_error_sink_reports_string_list_item_path_without_input_payload():
    helper = MagicMock()
    helper.provider = "deepseek"
    helper._call_llm = AsyncMock(return_value=AIMessage(content=json.dumps({
        "dimensions": [{"level_count": 2}],
        "design_summary": [{"internal": "DO_NOT_COPY_INVALID_INPUT"}],
    })))
    errors = []

    parsed = await invoke_structured_output(
        helper, [HumanMessage(content="Extract the reported design.")],
        CountedDesignSchema, validation_errors=errors,
    )

    assert parsed is None
    assert any("design_summary.0" in error and "string_type" in error for error in errors)
    assert "DO_NOT_COPY_INVALID_INPUT" not in "\n".join(errors)


@pytest.mark.asyncio
async def test_schema_error_sink_accepts_unknown_null_without_inventing_count():
    helper = MagicMock()
    helper.provider = "ollama"
    helper._call_llm = AsyncMock(return_value=AIMessage(
        content='{"dimensions": [{"level_count": null}], "design_summary": []}'
    ))
    errors = []

    parsed = await invoke_structured_output(
        helper, [HumanMessage(content="Extract the reported design.")],
        CountedDesignSchema, validation_errors=errors,
    )

    assert parsed["dimensions"][0]["level_count"] is None
    assert errors == []
    helper._call_llm.assert_awaited_once()


@pytest.mark.asyncio
async def test_schema_error_sink_bounds_many_errors_without_copying_inputs():
    helper = MagicMock()
    helper.provider = "deepseek"
    helper._call_llm = AsyncMock(return_value=AIMessage(content=json.dumps({
        "dimensions": [],
        "design_summary": [{"raw": "PRIVATE_RAW_INPUT" * 100} for _ in range(100)],
    })))
    errors = []

    parsed = await invoke_structured_output(
        helper, [HumanMessage(content="Extract the reported design.")],
        CountedDesignSchema, validation_errors=errors,
    )

    assert parsed is None
    assert 1 <= len(errors) <= 21
    assert len("\n".join(errors)) <= 5000
    assert "PRIVATE_RAW_INPUT" not in "\n".join(errors)
    assert any("omitted" in error.lower() for error in errors)


@pytest.mark.asyncio
async def test_native_schema_parsing_error_reaches_optional_error_sink():
    helper = MagicMock()
    helper.provider = "openai"
    llm = MagicMock()
    structured = MagicMock()
    with pytest.raises(ValueError) as failure:
        CountedDesignSchema.model_validate({"dimensions": [{"level_count": 0}]})
    structured.ainvoke = AsyncMock(return_value={
        "raw": AIMessage(content='{"dimensions": [{"level_count": 0}]}'),
        "parsed": None,
        "parsing_error": failure.value,
    })
    llm.with_structured_output.return_value = structured
    helper.get_llm.return_value = llm
    errors = []

    parsed = await invoke_structured_output(
        helper, [HumanMessage(content="Extract the reported design.")],
        CountedDesignSchema, validation_errors=errors,
    )

    assert parsed is None
    assert any("dimensions.0.level_count" in error for error in errors)
    assert any("greater_than_equal" in error for error in errors)
    structured.ainvoke.assert_awaited_once()
    helper._call_llm.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_kind", ["value_error", "assertion_error"])
async def test_schema_error_sink_omits_rejected_value_from_custom_validator_messages(
    error_kind, caplog,
):
    class ValidatedTokenSchema(BaseModel):
        token: str

        @field_validator("token")
        @classmethod
        def reject_token(cls, value):
            message = f"Rejected token contains {value}"
            if error_kind == "value_error":
                raise ValueError(message)
            raise AssertionError(message)

    sentinel = "PRIVATE_VALIDATOR_INPUT"
    helper = MagicMock()
    helper.provider = "deepseek"
    helper._call_llm = AsyncMock(return_value=AIMessage(
        content=json.dumps({"token": sentinel})
    ))
    errors = []

    parsed = await invoke_structured_output(
        helper, [HumanMessage(content="Read the token.")],
        ValidatedTokenSchema, validation_errors=errors,
    )

    assert parsed is None
    assert any("token" in error and error_kind in error for error in errors)
    assert sentinel not in "\n".join(errors)
    assert sentinel not in caplog.text


@pytest.mark.asyncio
async def test_schema_error_sink_masks_dynamic_dictionary_keys(caplog):
    class ReadingMapSchema(BaseModel):
        readings: dict[str, int]

    sentinel = "PRIVATE_DICTIONARY_KEY"
    helper = MagicMock()
    helper.provider = "ollama"
    helper._call_llm = AsyncMock(return_value=AIMessage(
        content=json.dumps({"readings": {sentinel: "not an integer"}})
    ))
    errors = []

    parsed = await invoke_structured_output(
        helper, [HumanMessage(content="Read the measurements.")],
        ReadingMapSchema, validation_errors=errors,
    )

    assert parsed is None
    assert any("readings.<key>" in error and "int_parsing" in error for error in errors)
    assert sentinel not in "\n".join(errors)
    assert sentinel not in caplog.text


def test_ollama_transport_blip_is_retried_but_model_errors_are_not(monkeypatch):
    import asyncio
    from fairifier.utils import llm_helper

    monkeypatch.setattr(llm_helper, "_TRANSPORT_RETRY_DELAYS_SECONDS", (0.0, 0.0))

    class Flaky:
        def __init__(self, errors):
            self.errors = list(errors)
            self.calls = 0

        async def ainvoke(self, messages, config=None):
            self.calls += 1
            if self.errors:
                raise self.errors.pop(0)
            return "ok"

    blip = Flaky([RuntimeError("peer closed connection without sending complete message body")])
    assert asyncio.run(llm_helper._ainvoke_with_transport_retry(blip, [], None, "op")) == "ok"
    assert blip.calls == 2

    bad = Flaky([ValueError("invalid JSON from model")])
    try:
        asyncio.run(llm_helper._ainvoke_with_transport_retry(bad, [], None, "op"))
    except ValueError:
        pass
    else:
        raise AssertionError("model errors must not be retried")
    assert bad.calls == 1


def test_ollama_call_honours_per_call_output_budget(monkeypatch):
    import asyncio
    from fairifier.utils import llm_helper as module

    bound = []

    class Stub:
        def bind(self, **kwargs):
            bound.append(kwargs)
            return self

        async def ainvoke(self, messages, config=None):
            return type("R", (), {"content": "{}", "response_metadata": {}})()

    helper = object.__new__(module.LLMHelper)
    helper.provider, helper.model, helper.llm = "ollama", "qwen3.8:27b", Stub()
    helper.llm_responses, helper._langfuse_handler = [], None
    monkeypatch.setattr(module.config, "llm_presence_penalty", None)
    monkeypatch.setattr(module.config, "llm_max_tokens", 32768)
    asyncio.run(helper._call_llm_impl([], "plan", max_tokens=65536))
    options = [b["options"] for b in bound if "options" in b]
    assert options and options[-1]["num_predict"] == 65536


def test_ollama_empty_thinking_answer_is_retried_without_thinking(monkeypatch):
    import asyncio
    from fairifier.utils import llm_helper as module

    calls = []

    class Stub:
        def __init__(self, think=True):
            self.think = think

        def bind(self, **kwargs):
            return Stub(kwargs.get("think", self.think))

        async def ainvoke(self, messages, config=None):
            calls.append(self.think)
            content = "" if self.think else '{"ok": true}'
            return type("R", (), {"content": content, "response_metadata": {}})()

    helper = object.__new__(module.LLMHelper)
    helper.provider, helper.model, helper.llm = "ollama", "qwen3.8:27b", Stub()
    helper.llm_responses, helper._langfuse_handler = [], None
    monkeypatch.setattr(module.config, "llm_presence_penalty", None)
    monkeypatch.setattr(module.config, "llm_enable_thinking", True)
    result = asyncio.run(helper._call_llm_impl([], "plan"))
    assert calls == [True, False]
    assert result.content == '{"ok": true}'


def test_truncated_json_keeps_the_complete_prefix_only():
    from fairifier.utils.json_parse import salvage_truncated_json

    cut = '{"groups": [{"id": "g1", "rows": [1, 2]}, {"id": "g2", "rows": [3'
    assert salvage_truncated_json(cut) == {"groups": [{"id": "g1", "rows": [1, 2]}]}
    assert salvage_truncated_json('{"a": "unterminated') is None
    assert salvage_truncated_json('{"a": 1}') == {"a": 1}


def test_ollama_json_mode_requests_grammar_constrained_output(monkeypatch):
    import asyncio
    from fairifier.utils import llm_helper as module

    bound = []

    class Stub:
        def bind(self, **kwargs):
            bound.append(kwargs)
            return self

        async def ainvoke(self, messages, config=None):
            return type("R", (), {"content": "{}", "response_metadata": {}})()

    helper = object.__new__(module.LLMHelper)
    helper.provider, helper.model, helper.llm = "ollama", "qwen3.8:27b", Stub()
    helper.llm_responses, helper._langfuse_handler = [], None
    monkeypatch.setattr(module.config, "llm_presence_penalty", None)
    asyncio.run(helper._call_llm_impl([], "plan", json_mode=True))
    assert {"format": "json"} in bound


def test_zero_max_tokens_means_no_client_output_cap(monkeypatch):
    import asyncio
    from fairifier.utils import llm_helper as module

    bound = []

    class Stub:
        def bind(self, **kwargs):
            bound.append(kwargs)
            return self

        async def ainvoke(self, messages, config=None):
            return type("R", (), {"content": "{}", "response_metadata": {}})()

    helper = object.__new__(module.LLMHelper)
    helper.provider, helper.model, helper.llm = "ollama", "qwen3.8:27b", Stub()
    helper.llm_responses, helper._langfuse_handler = [], None
    monkeypatch.setattr(module.config, "llm_presence_penalty", 0.0)
    monkeypatch.setattr(module.config, "llm_max_tokens", 0)
    asyncio.run(helper._call_llm_impl([], "critic", max_tokens=1024))
    options = [b["options"] for b in bound if "options" in b]
    assert options and options[-1]["num_predict"] == -1  # per-call 1024 cap ignored
