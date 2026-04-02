from __future__ import annotations

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
    assert any("ingestion incomplete" in issue.lower() for issue in gate["issues"])
