import asyncio
import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from fairifier.utils.llm_helper import (
    LLMHelper,
    prompt_length_from_serialized_messages,
    serialize_llm_message_content,
    serialize_llm_messages,
)


def test_serialize_llm_messages_preserves_full_prompt():
    prefix = "Extract fields from this document:\n"
    messages = [
        SystemMessage(content="You are a metadata assistant."),
        HumanMessage(content=prefix + ("x" * 5000)),
    ]

    serialized = serialize_llm_messages(messages)

    assert len(serialized) == 2
    assert serialized[0]["role"] == "system"
    assert serialized[0]["content"] == "You are a metadata assistant."
    assert serialized[1]["role"] == "human"
    assert serialized[1]["content"].startswith(prefix)
    assert len(serialized[1]["content"]) == len(prefix) + 5000


def test_serialize_llm_message_content_handles_block_payloads():
    content = [
        {"type": "text", "text": "first block"},
        {"type": "text", "text": "second block"},
    ]

    serialized = serialize_llm_message_content(content)

    assert serialized == content


def test_log_llm_response_stores_full_prompt_and_response_metadata(monkeypatch):
    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "deepseek"
    helper.model = "deepseek-chat"
    helper.llm_responses = []

    messages = [
        SystemMessage(content="system prompt"),
        HumanMessage(content="user prompt with full context"),
    ]
    result = AIMessage(
        content='{"score": 0.9}',
        response_metadata={
            "token_usage": {"input_tokens": 12, "output_tokens": 4},
        },
        usage_metadata={
            "input_tokens": 12,
            "output_tokens": 4,
            "total_tokens": 16,
        },
    )

    helper._log_llm_response(result, messages, "Critic.DocumentParser")

    assert len(helper.llm_responses) == 1
    entry = helper.llm_responses[0]
    assert entry["operation"] == "critic_documentparser"
    assert entry["provider"] == "deepseek"
    assert entry["model"] == "deepseek-chat"
    assert entry["prompt"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "human", "content": "user prompt with full context"},
    ]
    prompt_length = prompt_length_from_serialized_messages(entry["prompt"])
    assert entry["prompt_length"] == prompt_length
    assert entry["response"] == '{"score": 0.9}'
    assert entry["response_length"] == len(entry["response"])
    usage = entry["response_metadata"]["token_usage"]
    assert usage["input_tokens"] == 12
    assert entry["usage_metadata"]["total_tokens"] == 16
    assert entry["latency_seconds"] is None

    json.dumps(helper.llm_responses, ensure_ascii=False)


def test_call_llm_records_end_to_end_latency():
    class FakeLLM:
        async def ainvoke(self, messages, config=None):
            return AIMessage(
                content="ok",
                usage_metadata={
                    "input_tokens": 3,
                    "output_tokens": 1,
                    "total_tokens": 4,
                },
            )

    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "custom"
    helper.model = "fake"
    helper.llm = FakeLLM()
    helper.llm_responses = []
    helper._build_run_config = lambda: None

    asyncio.run(helper._call_llm([HumanMessage(content="hello")], "Timed Call"))

    assert helper.llm_responses[0]["latency_seconds"] is not None
    assert helper.llm_responses[0]["latency_seconds"] >= 0


def test_usage_callback_records_deep_agent_inner_call():
    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "custom"
    helper.model = "fake"
    helper.llm_responses = []
    callback = helper.build_usage_callback("DocumentParser")
    run_id = "deep-agent-call"

    callback.on_chat_model_start(
        {},
        [[HumanMessage(content="inspect the document")]],
        run_id=run_id,
    )
    message = AIMessage(
        content="done",
        usage_metadata={
            "input_tokens": 7,
            "output_tokens": 2,
            "total_tokens": 9,
        },
    )
    callback.on_llm_end(
        SimpleNamespace(
            generations=[[SimpleNamespace(message=message)]],
            llm_output={},
        ),
        run_id=run_id,
    )

    assert len(helper.llm_responses) == 1
    entry = helper.llm_responses[0]
    assert entry["operation"] == "documentparser_inner_loop"
    assert entry["usage_metadata"]["total_tokens"] == 9
    assert entry["latency_seconds"] is not None
