"""Token-free model candidate inventory tests."""

from __future__ import annotations

from pathlib import Path

from evaluation.benchmark.model_preflight import (
    inventory_model_configs,
    read_safe_env,
    restrict_model_inventory,
    select_model_panel,
)


def test_safe_env_reader_excludes_secrets(tmp_path: Path) -> None:
    env = tmp_path / "model.env"
    env.write_text(
        "LLM_PROVIDER=ollama\nFAIRIFIER_LLM_MODEL=qwen3:30b\n"
        "LLM_REPEAT_PENALTY=1.0\nLLM_PRESENCE_PENALTY=1.5\n"
        "OPENAI_API_KEY=secret\n"
    )
    values = read_safe_env(env)
    assert values["LLM_PROVIDER"] == "ollama"
    assert values["LLM_REPEAT_PENALTY"] == "1.0"
    assert values["LLM_PRESENCE_PENALTY"] == "1.5"
    assert "OPENAI_API_KEY" not in values


def test_model_inventory_does_not_perform_endpoint_or_token_calls(tmp_path: Path) -> None:
    (tmp_path / "ollama_qwen.env").write_text(
        "LLM_PROVIDER=ollama\nFAIRIFIER_LLM_MODEL=qwen3:30b\n"
    )
    (tmp_path / "openai_fast.env").write_text(
        "LLM_PROVIDER=openai\nFAIRIFIER_LLM_MODEL=gpt-mini\n"
    )
    inventory = inventory_model_configs(tmp_path)
    assert inventory["candidate_count"] == 2
    assert inventory["endpoint_checks_performed"] is False
    assert inventory["token_calls_performed"] is False
    assert inventory["unique_model_identity_count"] == 2
    assert all(candidate["canonical_model_identity"] for candidate in inventory["candidates"])
    assert all(candidate["configuration_hash"] for candidate in inventory["candidates"])
    slots = {candidate["selection_slot"] for candidate in inventory["candidates"]}
    assert "local_medium" in slots
    assert "hosted_efficient" in slots


def test_repeat_penalty_is_part_of_model_identity(tmp_path: Path) -> None:
    (tmp_path / "a.env").write_text(
        "LLM_PROVIDER=ollama\nFAIRIFIER_LLM_MODEL=qwen3:27b\n"
        "LLM_REPEAT_PENALTY=1.0\nLLM_PRESENCE_PENALTY=1.5\n"
    )
    (tmp_path / "b.env").write_text(
        "LLM_PROVIDER=ollama\nFAIRIFIER_LLM_MODEL=qwen3:27b\n"
        "LLM_REPEAT_PENALTY=1.1\nLLM_PRESENCE_PENALTY=1.5\n"
    )
    inventory = inventory_model_configs(tmp_path)
    assert inventory["unique_model_identity_count"] == 2
    values = {candidate["model_id"]: candidate["repeat_penalty"] for candidate in inventory["candidates"]}
    assert values == {"a": "1.0", "b": "1.1"}


def test_panel_selection_is_not_ready_without_passed_preflight() -> None:
    inventory = {
        "candidates": [
            {"model_id": "local_a", "selection_slot": "local_medium"},
        ]
    }
    panel = select_model_panel(inventory)
    assert panel["status"] == "not_ready"
    assert panel["slots"]["local_medium"]["selected_model_id"] is None


def test_panel_selection_applies_cost_tolerance_after_preflight() -> None:
    inventory = {
        "candidates": [
            {"model_id": "local_a", "selection_slot": "local_medium"},
            {"model_id": "local_b", "selection_slot": "local_medium"},
        ]
    }
    panel = select_model_panel(
        inventory,
        [
            {"model_id": "local_a", "status": "passed", "standard_success_rate": 0.90, "estimated_cost_usd": 2.0},
            {"model_id": "local_b", "status": "passed", "standard_success_rate": 0.86, "estimated_cost_usd": 1.0},
        ],
    )
    assert panel["slots"]["local_medium"]["selected_model_id"] == "local_b"


def test_panel_can_explicitly_exclude_a_slot_with_reasons() -> None:
    inventory = {
        "candidates": [
            {"model_id": "local_a", "selection_slot": "local_medium"},
            {"model_id": "local_b", "selection_slot": "local_medium"},
        ]
    }
    records = [
        {
            "model_id": model_id,
            "status": "excluded",
            "exclusion_reason": "endpoint unavailable",
        }
        for model_id in ("local_a", "local_b")
    ]
    panel = select_model_panel(inventory, records, slots=("local_medium",))
    assert panel["status"] == "ready"
    assert panel["slots"]["local_medium"]["status"] == "excluded"
    assert panel["slots"]["local_medium"]["selected_model_id"] is None


def test_explicit_panel_keeps_multiple_models_from_one_slot() -> None:
    inventory = {
        "candidates": [
            {"model_id": "qwen", "selection_slot": "local_medium"},
            {"model_id": "gemma", "selection_slot": "local_medium"},
        ]
    }
    records = [
        {
            "model_id": model_id,
            "status": "passed",
            "standard_success_rate": 0.8,
            "endpoint_health": "passed",
            "context_length": "passed",
            "structured_output": "passed",
            "tool_contract": "passed",
        }
        for model_id in ("qwen", "gemma")
    ]
    panel = select_model_panel(inventory, records, required_model_ids=("qwen", "gemma"))
    assert panel["status"] == "ready"
    assert panel["selected_model_ids"] == ["qwen", "gemma"]


def test_restrict_inventory_requires_all_requested_models(tmp_path: Path) -> None:
    (tmp_path / "a.env").write_text("LLM_PROVIDER=ollama\nFAIRIFIER_LLM_MODEL=a:1b\n")
    (tmp_path / "b.env").write_text("LLM_PROVIDER=ollama\nFAIRIFIER_LLM_MODEL=b:1b\n")
    inventory = inventory_model_configs(tmp_path)
    selected = restrict_model_inventory(inventory, ("b",))
    assert selected["candidate_count"] == 1
    assert selected["candidates"][0]["model_id"] == "b"
