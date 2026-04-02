from types import SimpleNamespace

import pytest

from fairifier.graph.langgraph_app import FAIRifierLangGraphApp
from fairifier.models import ProcessingStatus
from fairifier.utils.run_control import (
    reset_run_stop_requested,
    set_run_stop_requested,
)


@pytest.mark.anyio
async def test_execute_agent_with_retry_stops_before_critic_when_requested():
    run_id = "proj-stop-test"

    class StopAfterAgent:
        async def execute(self, state):
            set_run_stop_requested(True, run_id=run_id)
            state["document_info"] = {
                "title": "test document"
            }
            return state

    class CriticSpy:
        def __init__(self):
            self.called = False

        async def execute(self, state):
            self.called = True
            return state

        async def provide_feedback_to_agent(
            self, agent_name, critic_eval, state
        ):
            self.called = True
            return state

    app = FAIRifierLangGraphApp.__new__(
        FAIRifierLangGraphApp
    )
    app.mem0_service = None
    app.critic = CriticSpy()
    app.global_retry_count = 0
    app.max_step_retries = 1
    app.max_global_retries = 2

    state = {
        "session_id": run_id,
        "context": {},
        "execution_history": [],
        "errors": [],
    }

    try:
        result = await app._execute_agent_with_retry(
            state,
            StopAfterAgent(),
            "DocumentParser",
            lambda s: bool(s.get("document_info")),
        )

        assert (
            result["status"]
            == ProcessingStatus.INTERRUPTED.value
        )
        assert "Run stopped by user" in result["errors"]
        assert app.critic.called is False
    finally:
        reset_run_stop_requested(run_id)


def test_json_hard_gate_detects_missing_required_terms_and_routes_to_retrieval():
    app = FAIRifierLangGraphApp.__new__(FAIRifierLangGraphApp)

    state = {
        "metadata_fields": [
            {"field_name": "study title", "isa_sheet": "study"},
            {"field_name": "study description", "isa_sheet": "study"},
        ],
        "retrieved_knowledge": [
            {
                "term": "data usage license",
                "metadata": {"required": True, "isa_sheet": "investigation"},
            }
        ],
        "api_capabilities": {
            "required_metadata_terms": ["alpha diversity", "data usage license"],
            "uncovered_required_metadata_terms": ["alpha diversity"],
        },
    }

    gate = app._evaluate_json_hard_gate(state)

    assert gate["passed"] is False
    assert gate["anchor_agent"] == "KnowledgeRetriever"
    assert any("alpha diversity" in issue for issue in gate["issues"])
