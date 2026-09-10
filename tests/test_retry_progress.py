"""Framework-level tests for deterministic Critic retry progress."""

import pytest

from fairifier.graph.langgraph_app import FAIRifierLangGraphApp
from fairifier.utils.retry_progress import (
    build_retry_contract,
    build_retry_observation,
    classify_retry_progress,
)


def test_same_output_and_same_issue_is_stagnation():
    state = {"document_info": {"title": "same"}}
    first = build_retry_observation(
        "DocumentParser",
        state,
        {"score": 0.50, "issues": ["missing abstract"]},
        [],
    )
    second = build_retry_observation(
        "DocumentParser",
        state,
        {"score": 0.55, "issues": ["missing abstract"]},
        [first],
    )

    assert second["status"] == "stagnant"
    assert second["same_output"] is True
    assert second["feedback_applied"] is False


def test_same_output_cannot_be_improved_by_critic_score_or_rewording():
    first = {
        "output_fingerprint": "same",
        "score": 0.0,
        "issue_signature": ["critic transport failure"],
    }
    current = {
        "output_fingerprint": "same",
        "score": 0.75,
        "issue_signature": ["missing parent link"],
    }

    result = classify_retry_progress([first], current)

    assert result["status"] == "stagnant"
    assert result["feedback_applied"] is False


def test_changed_output_with_higher_score_is_improved():
    first = {
        "output_fingerprint": "a",
        "score": 0.50,
        "issue_signature": ["missing abstract", "missing title"],
    }
    current = {
        "output_fingerprint": "b",
        "score": 0.70,
        "issue_signature": ["missing title"],
    }

    result = classify_retry_progress([first], current)

    assert result["status"] == "improved"
    assert result["feedback_applied"] is True


def test_output_cycle_is_oscillation():
    history = [
        {"output_fingerprint": "a", "score": 0.5, "issue_signature": ["x"]},
        {"output_fingerprint": "b", "score": 0.6, "issue_signature": ["y"]},
    ]
    current = {"output_fingerprint": "a", "score": 0.5, "issue_signature": ["x"]}

    result = classify_retry_progress(history, current)

    assert result["status"] == "oscillating"


def test_retry_contract_is_explicit_and_bounded():
    contract = build_retry_contract(
        {
            "issues": ["irrelevant package selected"],
            "improvement_ops": ["remove irrelevant package"],
        },
        {"status": "stagnant", "output_fingerprint": "abcd"},
    )

    assert contract["must_change"] == ["remove irrelevant package"]
    assert contract["must_not_repeat"] == ["irrelevant package selected"]
    assert contract["verification"]


def _bare_app(max_step_retries=2):
    app = FAIRifierLangGraphApp.__new__(FAIRifierLangGraphApp)
    app.mem0_service = None
    app.global_retry_count = 0
    app.max_step_retries = max_step_retries
    app.max_global_retries = 10
    return app


class _RetryCritic:
    def __init__(self, scores):
        self.scores = iter(scores)
        self.feedback_calls = 0

    async def execute(self, state):
        score = next(self.scores)
        state["execution_history"][-1]["critic_evaluation"] = {
            "decision": "ACCEPT" if score >= 0.7 else "RETRY",
            "score": score,
            "issues": [] if score >= 0.7 else ["missing abstract"],
            "improvement_ops": [] if score >= 0.7 else ["extract the abstract"],
        }
        return state

    async def provide_feedback_to_agent(self, agent_name, evaluation, state):
        self.feedback_calls += 1
        state.setdefault("context", {})["critic_feedback"] = {
            **evaluation,
            "target_agent": agent_name,
        }
        return state


@pytest.mark.anyio
async def test_retry_controller_stops_repeating_model_output(monkeypatch):
    from fairifier.config import config

    monkeypatch.setattr(config, "disable_critic", False)
    app = _bare_app(max_step_retries=3)
    app.critic = _RetryCritic([0.5, 0.55, 0.6])
    calls = 0

    class Agent:
        async def execute(self, state):
            nonlocal calls
            calls += 1
            state["document_info"] = {"title": "unchanged"}
            return state

    result = await app._execute_agent_with_retry(
        {"context": {}, "execution_history": [], "errors": []},
        Agent(),
        "DocumentParser",
        lambda state: bool(state.get("document_info")),
    )

    assert calls == 2
    assert result["retry_termination_reason"] == "stagnation"
    assert result["needs_human_review"] is True
    assert result["retry_trajectory"]["DocumentParser"][-1]["same_output"] is True


@pytest.mark.anyio
async def test_retry_controller_allows_a_real_improvement(monkeypatch):
    from fairifier.config import config

    monkeypatch.setattr(config, "disable_critic", False)
    app = _bare_app(max_step_retries=2)
    app.critic = _RetryCritic([0.5, 0.8])
    calls = 0

    class Agent:
        async def execute(self, state):
            nonlocal calls
            calls += 1
            state["document_info"] = {"title": f"revision-{calls}"}
            return state

    result = await app._execute_agent_with_retry(
        {"context": {}, "execution_history": [], "errors": []},
        Agent(),
        "DocumentParser",
        lambda state: bool(state.get("document_info")),
    )

    assert calls == 2
    assert result["retry_trajectory"]["DocumentParser"][-1]["status"] == "improved"
    assert result["execution_history"][-1]["critic_evaluation"]["decision"] == "ACCEPT"


@pytest.mark.anyio
async def test_per_source_retry_scope_does_not_consume_or_obey_global_budget(monkeypatch):
    from fairifier.config import config

    monkeypatch.setattr(config, "disable_critic", False)
    app = _bare_app(max_step_retries=1)
    app.global_retry_count = app.max_global_retries
    app.critic = _RetryCritic([0.8])
    calls = 0

    class Agent:
        async def execute(self, state):
            nonlocal calls
            calls += 1
            state["document_info"] = {"title": "source-local result"}
            return state

    result = await app._execute_agent_with_retry(
        {"context": {}, "execution_history": [], "errors": []},
        Agent(),
        "DocumentParser",
        lambda state: bool(state.get("document_info")),
        enforce_global_retry_limit=False,
    )

    assert calls == 1
    assert app.global_retry_count == app.max_global_retries
    assert result["document_info"]["title"] == "source-local result"


@pytest.mark.anyio
async def test_retry_controller_restores_best_candidate_after_regression(monkeypatch):
    from fairifier.config import config

    monkeypatch.setattr(config, "disable_critic", False)
    app = _bare_app(max_step_retries=3)
    app.critic = _RetryCritic([0.6, 0.5, 0.4])
    calls = 0

    class Agent:
        async def execute(self, state):
            nonlocal calls
            calls += 1
            state["document_info"] = {"title": f"revision-{calls}"}
            return state

    result = await app._execute_agent_with_retry(
        {"context": {}, "execution_history": [], "errors": []},
        Agent(),
        "DocumentParser",
        lambda state: bool(state.get("document_info")),
    )

    assert calls == 3
    assert result["retry_termination_reason"] == "repeated_regression"
    assert result["retry_restored_best"] is True
    assert result["retry_best_attempt"] == 1
    assert result["document_info"]["title"] == "revision-1"
