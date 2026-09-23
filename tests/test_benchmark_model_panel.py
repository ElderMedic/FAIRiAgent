"""Token-free frozen model-panel artifact tests."""

from __future__ import annotations

import pytest

from evaluation.benchmark.model_panel import ModelPanelError, freeze_model_panel


def _inputs() -> tuple[dict, dict, list[dict]]:
    inventory = {
        "candidates": [
            {
                "model_id": "local_model",
                "selection_slot": "local_medium",
                "provider": "ollama",
                "model_name": "fixture:30b",
                "endpoint_class": "local",
                "configuration_hash": "config-sha",
            }
        ]
    }
    plan = {
        "schema_version": "fairiagent.model_preflight_plan.v2",
        "jobs": [{"model_id": "local_model", "instance_id": "doc", "repetition": 1}],
    }
    records = [
        {
            "model_id": "local_model",
            "instance_id": "doc",
            "repetition": 1,
            "status": "passed",
            "standard_success_rate": 0.9,
            "endpoint_health": "passed",
            "context_length": "passed",
            "structured_output": "passed",
            "tool_contract": "passed",
        }
    ]
    return inventory, plan, records


def test_freeze_model_panel_records_evidence_and_local_hardware() -> None:
    inventory, plan, records = _inputs()
    panel = freeze_model_panel(
        inventory,
        plan,
        records,
        freeze_confirmation="researcher-approved:fixture",
        hardware_records={
            "local_model": {
                "serving_version": "ollama-fixture",
                "quantization": "Q4_K_M",
                "hardware_model": "fixture-gpu",
                "memory_gb": 48,
            }
        },
        slots=("local_medium",),
    )
    assert panel["status"] == "frozen"
    assert panel["models"][0]["model_id"] == "local_model"
    assert panel["models"][0]["local_hardware"]["quantization"] == "Q4_K_M"
    assert panel["models"][0]["preflight_status"] == "passed"
    assert panel["models"][0]["preflight_tool_contract"] == "passed"
    assert panel["preflight"]["coverage_validated"] is True
    assert panel["materialized_without_new_model_calls"] is True


def test_freeze_model_panel_requires_local_hardware_and_confirmation() -> None:
    inventory, plan, records = _inputs()
    with pytest.raises(ModelPanelError, match="freeze_confirmation"):
        freeze_model_panel(inventory, plan, records, freeze_confirmation="", slots=("local_medium",))
    with pytest.raises(ModelPanelError, match="local hardware"):
        freeze_model_panel(
            inventory,
            plan,
            records,
            freeze_confirmation="researcher-approved:fixture",
            slots=("local_medium",),
        )


def test_freeze_model_panel_accepts_explicit_models_sharing_a_slot() -> None:
    inventory = {
        "candidates": [
            {
                "model_id": model_id,
                "selection_slot": "local_medium",
                "provider": "ollama",
                "model_name": model_id,
                "endpoint_class": "local",
                "configuration_hash": model_id,
            }
            for model_id in ("qwen", "gemma")
        ]
    }
    plan = {
        "schema_version": "fairiagent.model_preflight_plan.v2",
        "jobs": [
            {"model_id": model_id, "instance_id": "doc", "repetition": 1}
            for model_id in ("qwen", "gemma")
        ],
    }
    records = [
        {
            "model_id": model_id,
            "instance_id": "doc",
            "repetition": 1,
            "status": "passed",
            "standard_success_rate": 0.8,
            "endpoint_health": "passed",
            "context_length": "passed",
            "structured_output": "passed",
            "tool_contract": "passed",
        }
        for model_id in ("qwen", "gemma")
    ]
    panel = freeze_model_panel(
        inventory,
        plan,
        records,
        freeze_confirmation="researcher-approved:explicit-panel",
        required_model_ids=("qwen", "gemma"),
        hardware_records={
            model_id: {
                "serving_version": "ollama-fixture",
                "quantization": "Q4_K_M",
                "hardware_model": "fixture-gpu",
                "memory_gb": 48,
            }
            for model_id in ("qwen", "gemma")
        },
    )
    assert [model["model_id"] for model in panel["models"]] == ["qwen", "gemma"]
    assert panel["selection_rule"] == "explicit_researcher_requested_panel"
