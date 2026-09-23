"""Kimi K3 OpenAI-compatibility adapter tests."""

from langchain_core.messages import AIMessage, HumanMessage

import fairifier.utils.llm_helper as llm_module
from fairifier.config import config
from fairifier.utils.llm_helper import KimiK3ChatOpenAI


def test_k3_response_preserves_reasoning_content_for_follow_up_turns():
    model = KimiK3ChatOpenAI(
        model="kimi-k3",
        api_key="test-key",
        base_url="https://api.moonshot.ai/v1",
    )

    result = model._create_chat_result(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": "kimi-k3",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "final answer",
                        "reasoning_content": "private preserved thought",
                    },
                }
            ],
        }
    )

    message = result.generations[0].message
    assert message.content == "final answer"
    assert message.additional_kwargs["reasoning_content"] == "private preserved thought"


def test_k3_request_replays_reasoning_content_on_assistant_message():
    model = KimiK3ChatOpenAI(
        model="kimi-k3",
        api_key="test-key",
        base_url="https://api.moonshot.ai/v1",
    )
    messages = [
        HumanMessage(content="Use the tool."),
        AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "private preserved thought"},
            tool_calls=[
                {
                    "name": "lookup",
                    "args": {"term": "K3"},
                    "id": "call-1",
                    "type": "tool_call",
                }
            ],
        ),
    ]

    payload = model._get_request_payload(messages)
    assistant = payload["messages"][1]
    assert assistant["reasoning_content"] == "private preserved thought"
    assert assistant["tool_calls"][0]["id"] == "call-1"


def test_k3_initialization_omits_fixed_sampling_and_limits_sdk_retries(monkeypatch):
    captured = {}

    class DummyChat:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_module, "KimiK3ChatOpenAI", DummyChat)
    monkeypatch.setattr(config, "llm_api_key", "test-key")
    monkeypatch.setattr(config, "llm_base_url", "https://api.moonshot.ai/v1")
    monkeypatch.setattr(config, "llm_max_tokens", 131072)
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "900")

    helper = llm_module.LLMHelper.__new__(llm_module.LLMHelper)
    helper.provider = "openai"
    helper.model = "kimi-k3"
    helper.llm = helper._initialize_llm()

    assert "temperature" not in captured
    assert "top_p" not in captured
    assert captured["max_tokens"] == 131072
    assert captured["max_retries"] == 1
