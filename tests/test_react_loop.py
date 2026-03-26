"""Tests for deepagents integration helpers."""

from unittest.mock import Mock

from fairifier.config import config
from fairifier.agents.base import BaseAgent
from fairifier.agents.react_loop import ReactLoopMixin


class DummyReactAgent(ReactLoopMixin, BaseAgent):
    """Minimal concrete agent for testing mixin helpers."""

    async def execute(self, state):
        return state


def test_compose_task_message_includes_planner_critic_and_memory():
    agent = DummyReactAgent("Dummy")
    state = {
        "context": {
            "critic_feedback": {
                "critique": "missing identifiers",
                "issues": ["project id absent"],
                "suggestions": ["extract identifiers explicitly"],
                "history": [],
            },
            "retrieved_memories": [{"memory": "proposal documents usually include grant ids"}],
            "critic_guidance_history": {"Dummy": ["previous retry asked for provenance"]},
        },
        "agent_guidance": {"Dummy": "prioritize identifiers"},
        "evidence_packets": [
            {
                "field_candidate": "methodology",
                "value": "RNA-seq",
                "evidence_text": "Methods section",
                "section": "Methods",
            }
        ],
    }

    message = agent._compose_task_message(state, "Base task")

    assert "Base task" in message
    assert "prioritize identifiers" in message
    assert "missing identifiers" in message
    assert "extract identifiers explicitly" in message
    assert "grant ids" in message
    assert "previous retry asked for provenance" in message
    assert "Evidence packets:" in message
    assert "max_iterations" in message


def test_record_react_result_updates_state_scratchpad():
    agent = DummyReactAgent("Dummy")
    state = {}

    agent._record_react_result(
        state,
        "Dummy",
        {
            "iterations": 3,
            "tool_calls": [{"name": "search_ontology_term"}, {"tool": "resolve_doi_metadata"}],
        },
    )

    assert state["react_scratchpad"]["Dummy"]["iterations"] == 3
    assert state["react_scratchpad"]["Dummy"]["tools_called"] == [
        "search_ontology_term",
        "resolve_doi_metadata",
    ]
    assert state["react_scratchpad"]["Dummy"]["budget"]["max_iterations"] > 0


def test_get_context_feedback_prefers_agent_scoped_critic_feedback():
    agent = DummyReactAgent("Dummy")
    state = {
        "context": {
            "critic_feedback": {
                "target_agent": "KnowledgeRetriever",
                "critique": "feedback for another agent",
            },
            "critic_feedback_by_agent": {
                "Dummy": {
                    "target_agent": "Dummy",
                    "critique": "dummy-specific feedback",
                    "issues": ["missing identifier"],
                    "suggestions": ["extract identifier"],
                }
            },
        },
        "agent_guidance": {},
    }

    feedback = agent.get_context_feedback(state)

    assert feedback["critic_feedback"]["critique"] == "dummy-specific feedback"
    assert feedback["critic_feedback"]["target_agent"] == "Dummy"


def test_get_react_model_wraps_qwen_with_thinking_disabled(monkeypatch):
    agent = DummyReactAgent("Dummy")
    agent.llm_helper = Mock(llm="base-llm")

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(config, "llm_provider", "qwen")
    monkeypatch.setattr(config, "llm_model", "qwen-flash")
    monkeypatch.setattr(config, "llm_api_key", "test-key")
    monkeypatch.setattr(
        config,
        "llm_base_url",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setattr(config, "llm_temperature", 0.2)
    monkeypatch.setattr(config, "llm_max_tokens", 100000)

    model = agent._get_react_model()

    assert isinstance(model, FakeChatOpenAI)
    assert captured["model"] == "qwen-flash"
    assert captured["extra_body"] == {"enable_thinking": False}
    assert captured["max_tokens"] == 65536


def test_get_react_model_keeps_existing_non_qwen_model(monkeypatch):
    agent = DummyReactAgent("Dummy")
    agent.llm_helper = Mock(llm="base-llm")

    monkeypatch.setattr(config, "llm_provider", "ollama")

    assert agent._get_react_model() == "base-llm"
