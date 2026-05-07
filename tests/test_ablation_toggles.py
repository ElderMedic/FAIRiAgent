from types import SimpleNamespace

import pytest

from fairifier.agents.critic import CriticAgent
from fairifier.graph.langgraph_app import FAIRifierLangGraphApp


def _bare_app():
    app = FAIRifierLangGraphApp.__new__(FAIRifierLangGraphApp)
    app.mem0_service = None
    app.global_retry_count = 0
    app.max_step_retries = 0
    app.max_global_retries = 1
    return app


@pytest.mark.anyio
async def test_execute_agent_with_retry_skips_critic_when_disabled_async(monkeypatch):
    from fairifier.config import config

    monkeypatch.setattr(config, "disable_critic", True)

    class Agent:
        async def execute(self, state):
            state["document_info"] = {"title": "ok"}
            return state

    class CriticSpy:
        def __init__(self):
            self.called = False

        async def execute(self, state):
            self.called = True
            return state

        async def provide_feedback_to_agent(self, agent_name, critic_eval, state):
            self.called = True
            return state

    app = _bare_app()
    app.critic = CriticSpy()
    state = {"context": {}, "execution_history": [], "errors": []}

    result = await app._execute_agent_with_retry(
        state,
        Agent(),
        "DocumentParser",
        lambda s: bool(s.get("document_info")),
    )

    assert result["execution_history"][-1]["critic_evaluation"]["decision"] == "ACCEPT"
    assert app.critic.called is False


@pytest.mark.anyio
async def test_json_hard_gate_disable_skips_cross_layer_retry(monkeypatch):
    from fairifier.config import config

    monkeypatch.setattr(config, "disable_critic", False)
    monkeypatch.setattr(config, "disable_hard_gate", True)

    class Agent:
        async def execute(self, state):
            state["metadata_fields"] = [{"field_name": "study title", "isa_sheet": "study"}]
            state["api_capabilities"] = {
                "required_metadata_terms": ["alpha diversity"],
                "uncovered_required_metadata_terms": ["alpha diversity"],
            }
            return state

    class CriticStub:
        def __init__(self):
            self.feedback_targets = []

        async def execute(self, state):
            state["execution_history"][-1]["critic_evaluation"] = {"decision": "ACCEPT", "score": 0.9}
            return state

        async def provide_feedback_to_agent(self, agent_name, critic_eval, state):
            self.feedback_targets.append(agent_name)
            return state

    app = _bare_app()
    app.critic = CriticStub()
    state = {"context": {}, "execution_history": [], "errors": [], "retrieved_knowledge": []}

    result = await app._execute_agent_with_retry(
        state,
        Agent(),
        "JSONGenerator",
        lambda s: bool(s.get("metadata_fields")),
    )

    assert result["context"].get("force_retry_from") is None
    assert "hard_gate" not in result["execution_history"][-1]["critic_evaluation"]


@pytest.mark.anyio
async def test_cross_layer_rollback_disable_keeps_retry_at_json_generator(monkeypatch):
    from fairifier.config import config

    monkeypatch.setattr(config, "disable_critic", False)
    monkeypatch.setattr(config, "disable_hard_gate", False)
    monkeypatch.setattr(config, "disable_cross_layer_rollback", True)

    class Agent:
        async def execute(self, state):
            state["metadata_fields"] = [{"field_name": "study title", "isa_sheet": "study"}]
            state["api_capabilities"] = {
                "required_metadata_terms": ["alpha diversity"],
                "uncovered_required_metadata_terms": ["alpha diversity"],
            }
            return state

    class CriticStub:
        def __init__(self):
            self.feedback_targets = []

        async def execute(self, state):
            state["execution_history"][-1]["critic_evaluation"] = {"decision": "ACCEPT", "score": 0.9}
            return state

        async def provide_feedback_to_agent(self, agent_name, critic_eval, state):
            self.feedback_targets.append(agent_name)
            return state

    app = _bare_app()
    app.critic = CriticStub()
    state = {"context": {}, "execution_history": [], "errors": [], "retrieved_knowledge": []}

    result = await app._execute_agent_with_retry(
        state,
        Agent(),
        "JSONGenerator",
        lambda s: bool(s.get("metadata_fields")),
    )

    assert result["context"].get("force_retry_from") is None
    assert app.critic.feedback_targets[-1] == "JSONGenerator"


@pytest.mark.anyio
async def test_critic_skips_api_grounding_when_disabled(monkeypatch):
    from fairifier.config import config

    monkeypatch.setattr(config, "disable_api_grounding", True)

    agent = CriticAgent.__new__(CriticAgent)
    agent.node_key_map = {"KnowledgeRetriever": "knowledge_retriever"}
    agent.max_retries_per_step = 1

    async def fake_judge(node_key, context):
        return {"decision": "ACCEPT", "score": 0.8}

    def fail_postprocess(node_key, evaluation, state):
        raise AssertionError("API grounding postprocess should be skipped")

    monkeypatch.setattr(agent, "_build_retrieval_context", lambda state: "ctx")
    monkeypatch.setattr(agent, "_judge_with_rubric", fake_judge)
    monkeypatch.setattr(agent, "_postprocess_api_constrained_evaluation", fail_postprocess)
    monkeypatch.setattr(agent, "_stabilize_invalid_critic_output", lambda node_key, evaluation, state: evaluation)

    result = await agent._evaluate_agent_output("KnowledgeRetriever", {})

    assert result["decision"] == "ACCEPT"
