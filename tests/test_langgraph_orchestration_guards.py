from __future__ import annotations

import json

import pytest

from fairifier.graph.langgraph_app import FAIRifierLangGraphApp


def _make_app_without_init() -> FAIRifierLangGraphApp:
    app = object.__new__(FAIRifierLangGraphApp)
    app.global_retry_count = 0
    app.max_global_retries = 5
    return app


def test_json_hard_gate_flags_incomplete_bundle_ingestion():
    app = _make_app_without_init()
    state = {
        "metadata_fields": [{"field_name": "study title", "value": "Example"}],
        "retrieved_knowledge": [],
        "api_capabilities": {},
        "context": {"bundle_ingestion_incomplete": True},
    }

    gate = app._evaluate_json_hard_gate(state)

    assert gate["passed"] is False
    assert gate["anchor_agent"] == "DocumentParser"
    assert any(
        "ingestion incomplete" in issue.lower() for issue in gate["issues"]
    )


@pytest.mark.anyio
async def test_finalize_node_handles_a2a_log_path_without_unboundlocal(
    tmp_path,
):
    """Finalize should not crash when writing A2A messages."""
    app = _make_app_without_init()

    state = {
        "execution_history": [
            {
                "agent_name": "DocumentParser",
                "attempt": 1,
                "success": True,
                "critic_evaluation": {"score": 0.95},
            }
        ],
        "retry_trajectory": {},
        "confidence_scores": {"document_parsing": 0.6},
        "needs_human_review": False,
        "retrieved_knowledge": [],
        "artifacts": {"metadata_json": json.dumps({"isa_sheets": {}})},
        "metadata_fields": [{"field_name": "study title", "value": "Example"}],
        "output_dir": str(tmp_path),
        "agent_messages": [
            {
                "created_at": "2026-06-18T01:00:00",
                "from_agent": "DocumentParser",
                "to_agent": "KnowledgeRetriever",
                "message_type": "evidence_bundle",
                "id": "msg-1",
                "priority": 1,
                "acked_by": ["KnowledgeRetriever"],
                "payload": {"evidence_count": 2},
            }
        ],
    }

    finalized = await app._finalize_node(state)

    assert finalized["status"] == "completed"
    assert (tmp_path / "processing_log.jsonl").exists()
