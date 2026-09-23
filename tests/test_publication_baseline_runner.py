"""No-token tests for the unified publication baseline conditions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.baselines.publication_runner import (
    BaselineConfigurationError,
    _result_envelope,
    build_publication_prompt,
    canonicalize_publication_output,
    load_document_bundle,
    parse_json_response,
)


DOCUMENT = "The study examined three samples collected in 2024."
STANDARDS = "The FAIR-DS package declares sample_name and collection_date."
RETRIEVED = "Table 1 lists samples S1, S2, and S3."


def test_single_pass_uses_complete_document_without_truncation() -> None:
    long_document = "A" * 40000
    prompt = build_publication_prompt("single_pass_structured_extraction", long_document)
    assert long_document in prompt
    assert len(prompt) > 40000
    assert "# Declared standards" not in prompt


def test_document_bundle_includes_declared_supplementary_assets(tmp_path: Path) -> None:
    primary = tmp_path / "paper.md"
    supplementary = tmp_path / "supplement.md"
    primary.write_text("primary content", encoding="utf-8")
    supplementary.write_text("supplementary table content", encoding="utf-8")
    bundle = load_document_bundle(primary, [supplementary])
    assert "primary content" in bundle
    assert "supplementary table content" in bundle
    assert "Supplementary document 1" in bundle


def test_standards_and_retrieval_context_are_explicit_condition_inputs() -> None:
    standards_prompt = build_publication_prompt(
        "standards_guided_extraction", DOCUMENT, standards_context=STANDARDS
    )
    retrieval_prompt = build_publication_prompt(
        "retrieval_assisted_extraction",
        DOCUMENT,
        standards_context=STANDARDS,
        retrieved_context=RETRIEVED,
    )
    assert STANDARDS in standards_prompt
    assert RETRIEVED in retrieval_prompt


def test_context_required_conditions_fail_before_any_model_call() -> None:
    with pytest.raises(BaselineConfigurationError, match="requires standards_context"):
        build_publication_prompt("standards_guided_extraction", DOCUMENT)
    with pytest.raises(BaselineConfigurationError, match="requires retrieved_context"):
        build_publication_prompt(
            "retrieval_assisted_extraction", DOCUMENT, standards_context=STANDARDS
        )


def test_parser_requires_canonical_isa_structure_and_does_not_repair_facts() -> None:
    value = {"isa_structure": {"sample": {"fields": [{"field_name": "sample_name", "value": "S1"}]}}}
    assert parse_json_response(json.dumps(value)) == value
    with pytest.raises(ValueError, match="isa_structure"):
        parse_json_response(json.dumps({"samples": [{"sample_name": "S1"}]}))


def test_result_identity_keeps_manifest_model_alias() -> None:
    result = _result_envelope(
        run_spec={
            "run_id": "doc__condition__alias__r01",
            "instance_id": "doc",
            "condition_id": "single_pass_structured_extraction",
            "model_id": "alias",
            "repetition": 1,
        },
        status="success",
        artifact_path=Path("metadata.json"),
        parseable=True,
        runtime_seconds=1.0,
        error=None,
        model_id="alias",
        provider="local",
        resolved_model_id="qwen3:30b",
    )
    assert result["model_id"] == "alias"
    assert result["provenance"]["resolved_model_id"] == "qwen3:30b"


def test_canonical_serializer_only_projects_fields_to_rows() -> None:
    output = canonicalize_publication_output(
        {
            "isa_structure": {
                "sample": {
                    "fields": [
                        {"field_name": "sample name", "value": "S1", "entity_id": "s1"},
                        {"field_name": "sample name", "value": "S2", "entity_id": "s2"},
                    ]
                }
            }
        }
    )
    assert output["isa_values"]["sample"]["columns"] == ["entity_id", "sample name"]
    assert output["isa_values"]["sample"]["rows"] == [
        {"entity_id": "s1", "sample name": "S1"},
        {"entity_id": "s2", "sample name": "S2"},
    ]
    assert output["isa_matrix_id"]
    assert output["benchmark_provenance"]["factual_correction"] is False
