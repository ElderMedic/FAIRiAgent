"""Condition-difference audits for progressive and focused comparisons."""

from __future__ import annotations

from evaluation.benchmark.condition_comparison import (
    audit_focused_ablations,
    audit_progressive_ladder,
    compare_condition_definitions,
)


def _manifest() -> dict:
    # Keep this fixture independent of the optional import above: the smoke
    # manifest is JSON and the test constructs only the condition matrix.
    conditions = [
        {
            "condition_id": "single_pass_structured_extraction",
            "publication_name": "Single-pass structured extraction",
            "component_settings": {
                "document_retrieval": False,
                "standards_context": False,
                "planning_and_specialized_roles": False,
                "critique_and_revision": False,
                "deterministic_correction": False,
            },
        },
        {
            "condition_id": "standards_guided_extraction",
            "publication_name": "Standards-guided extraction",
            "component_settings": {
                "document_retrieval": False,
                "standards_context": True,
                "planning_and_specialized_roles": False,
                "critique_and_revision": False,
                "deterministic_correction": False,
            },
        },
        {
            "condition_id": "retrieval_assisted_extraction",
            "publication_name": "Retrieval-assisted extraction",
            "component_settings": {
                "document_retrieval": True,
                "standards_context": True,
                "planning_and_specialized_roles": False,
                "critique_and_revision": False,
                "deterministic_correction": False,
            },
        },
        {
            "condition_id": "iterative_agentic_extraction",
            "publication_name": "Iterative agentic extraction",
            "component_settings": {
                "document_retrieval": True,
                "standards_context": True,
                "planning_and_specialized_roles": True,
                "critique_and_revision": True,
                "deterministic_correction": False,
            },
        },
        {
            "condition_id": "complete_fairiagent_system",
            "publication_name": "Complete FAIRiAgent system",
            "component_settings": {
                "document_retrieval": True,
                "standards_context": True,
                "planning_and_specialized_roles": True,
                "critique_and_revision": True,
                "deterministic_correction": True,
            },
        },
        {
            "condition_id": "lexical_retrieval_control",
            "publication_name": "Lexical-retrieval control",
            "component_settings": {"retrieval_method": "lexical"},
        },
        {
            "condition_id": "hybrid_retrieval_system",
            "publication_name": "Hybrid-retrieval system",
            "component_settings": {"retrieval_method": "lexical_and_semantic"},
        },
        {
            "condition_id": "hybrid_retrieval_with_deterministic_metadata_correction",
            "publication_name": "Hybrid retrieval with deterministic metadata correction",
            "component_settings": {
                "retrieval_method": "lexical_and_semantic",
                "deterministic_correction": True,
            },
        },
    ]
    return {"conditions": conditions}


def test_progressive_ladder_passes_exact_component_differences() -> None:
    result = audit_progressive_ladder(_manifest())
    assert result["status"] == "passed"
    assert result["model_or_api_calls_performed"] is False


def test_focused_ablations_pass_exact_component_differences() -> None:
    assert audit_focused_ablations(_manifest())["status"] == "passed"


def test_unexpected_component_change_is_rejected() -> None:
    manifest = _manifest()
    manifest["conditions"][1]["component_settings"]["document_retrieval"] = True
    diff = compare_condition_definitions(
        manifest,
        "single_pass_structured_extraction",
        "standards_guided_extraction",
    )
    assert sorted(diff["changed_keys"]) == ["document_retrieval", "standards_context"]
    assert audit_progressive_ladder(manifest)["status"] == "failed"
