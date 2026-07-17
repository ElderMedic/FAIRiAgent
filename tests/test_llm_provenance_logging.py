import json

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

    json.dumps(helper.llm_responses, ensure_ascii=False)
