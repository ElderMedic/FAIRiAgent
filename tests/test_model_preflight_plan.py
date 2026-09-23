"""Token-free preflight plan tests."""

import pytest

from evaluation.benchmark.model_preflight import (
    build_preflight_plan,
    select_model_panel,
    validate_preflight_plan_coverage,
    validate_preflight_records,
)


def test_preflight_plan_deduplicates_configuration_aliases() -> None:
    inventory = {
        "candidates": [
            {
                "model_id": "alias_b",
                "canonical_model_identity": "same",
                "selection_slot": "local_medium",
            },
            {
                "model_id": "alias_a",
                "canonical_model_identity": "same",
                "selection_slot": "local_medium",
            },
            {
                "model_id": "other",
                "canonical_model_identity": "other",
                "selection_slot": "hosted_efficient",
            },
        ]
    }
    plan = build_preflight_plan(inventory, ["doc_a"], repetitions=1)
    assert plan["candidate_identity_count"] == 2
    assert plan["estimated_llm_calls"] == 2
    assert plan["token_calls_performed"] is False
    assert plan["model_or_api_calls_performed"] is False
    assert plan["jobs"][0]["model_id"] == "alias_a"


def test_preflight_records_require_interface_evidence_before_freezing() -> None:
    inventory = {
        "candidates": [
            {"model_id": "model_a", "selection_slot": "local_medium"},
        ]
    }
    record = {
        "model_id": "model_a",
        "status": "passed",
        "standard_success_rate": 0.8,
        "endpoint_health": "passed",
        "context_length": "passed",
        "structured_output": "passed",
        "tool_contract": "failed",
    }
    errors = validate_preflight_records(inventory, [record])
    assert errors == ["model_a:tool_contract"]


def test_preflight_records_can_cover_multiple_development_instances() -> None:
    inventory = {
        "candidates": [
            {"model_id": "model_a", "selection_slot": "local_medium"},
        ]
    }
    records = [
        {
            "model_id": "model_a",
            "instance_id": instance_id,
            "repetition": 1,
            "status": "passed",
            "standard_success_rate": rate,
            "estimated_cost_usd": 1.0,
            "endpoint_health": "passed",
            "context_length": "passed",
            "structured_output": "passed",
            "tool_contract": "passed",
        }
        for instance_id, rate in (("doc_a", 0.8), ("doc_b", 0.9))
    ]
    assert validate_preflight_records(inventory, records) == []
    panel = select_model_panel(inventory, records, slots=("local_medium",))
    assert panel["status"] == "ready"
    assert panel["slots"]["local_medium"]["standard_success_rate"] == pytest.approx(0.85)


def test_preflight_plan_coverage_rejects_partial_records() -> None:
    plan = {
        "jobs": [
            {"model_id": "model_a", "instance_id": "doc_a", "repetition": 1},
            {"model_id": "model_a", "instance_id": "doc_b", "repetition": 1},
        ]
    }
    records = [{"model_id": "model_a", "instance_id": "doc_a", "repetition": 1}]
    errors = validate_preflight_plan_coverage(plan, records)
    assert any("missing preflight records" in error for error in errors)


def test_preflight_plan_coverage_keeps_failed_probe_in_denominator() -> None:
    plan = {"jobs": [{"model_id": "model_a", "instance_id": "doc_a", "repetition": 1}]}
    records = [
        {
            "model_id": "model_a",
            "instance_id": "doc_a",
            "repetition": 1,
            "status": "failed",
        }
    ]
    assert validate_preflight_plan_coverage(plan, records) == []


def test_excluded_preflight_records_require_a_reason() -> None:
    inventory = {"candidates": [{"model_id": "model_a", "selection_slot": "local_medium"}]}
    errors = validate_preflight_records(
        inventory,
        [{"model_id": "model_a", "status": "excluded"}],
    )
    assert errors == ["model_a:exclusion_reason_missing"]
