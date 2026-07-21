import json

import pytest


def _state_for_auto_repair():
    metadata_payload = {
        "fairifier_version": "Vtest",
        "generated_at": "2026-07-14T00:00:00",
        "document_source": "test.pdf",
        "isa_structure": {
            "study": {
                "fields": [{"field_name": "study identifier", "value": "study_1"}],
                "columns": ["study identifier"],
                "rows": [{"study identifier": "study_1"}],
            }
        },
        "isa_values": {
            "study": {
                "columns": ["study identifier"],
                "rows": [{"study identifier": "study_1"}],
            }
        },
        "statistics": {
            "total_fields": 1,
            "study_fields": 1,
            "confirmed_fields": 1,
            "provisional_fields": 0,
        },
    }
    return {
        "retrieved_knowledge": [
            {
                "term": "study title",
                "metadata": {
                    "name": "study title",
                    "requirement": "MANDATORY",
                    "isa_sheet": "study",
                },
            },
            {
                "term": "study identifier",
                "metadata": {
                    "name": "study identifier",
                    "requirement": "MANDATORY",
                    "isa_sheet": "study",
                },
            },
        ],
        "metadata_fields": [
            {
                "field_name": "study identifier",
                "value": "study_1",
                "confidence": 0.95,
                "isa_sheet": "study",
                "requirement": "MANDATORY",
            }
        ],
        "retrieval_telemetry": {
            "study title": {
                "lexical_hit_count": 0,
                "semantic_hit_count": 12,
                "prompt_mode": "auto_semantic_fallback",
                "retrieval_mode": "auto",
            }
        },
        "artifacts": {"metadata_json": json.dumps(metadata_payload)},
    }


def _add_study_title_candidate(state):
    state["section_field_candidates"] = [
        {
            "field_name": "study title",
            "field_candidate": "study title",
            "value": "Pea cold stress response",
            "evidence": (
                "source_001:10-40 [role=primary] (Methods): "
                "Study Title: Pea cold stress response"
            ),
            "source_id": "source_001",
            "source_role": "primary",
            "char_start": 10,
            "char_end": 40,
            "confidence": 0.82,
            "retrieval_method": "section_map_reduce",
            "provenance": {"agent": "section_map_reduce"},
        }
    ]
    return state


def test_generate_auto_repair_trace_identifies_semantic_gap():
    from fairifier.services.auto_repair import generate_auto_repair_trace

    trace = generate_auto_repair_trace(_state_for_auto_repair())
    assert trace["summary"]["metadata_mutated"] is False
    assert trace["summary"]["candidate_count"] == 1
    candidate = trace["candidates"][0]
    assert candidate["field"] == "study title"
    assert candidate["decision"] == "semantic_repair"
    assert candidate["accept_patch"] is False
    assert candidate["lexical_hit_count"] == 0
    assert candidate["semantic_hit_count"] == 12


@pytest.mark.asyncio
async def test_auto_repair_node_adds_trace_without_exact_candidate_mutation():
    from fairifier.graph.nodes import AutoRepairNode

    state = _state_for_auto_repair()
    before = state["artifacts"]["metadata_json"]
    result = await AutoRepairNode()(state)

    assert result["artifacts"]["metadata_json"] == before
    assert "auto_repair_trace" in result
    assert "auto_repair_trace" in result["artifacts"]
    sidecar = json.loads(result["artifacts"]["auto_repair_trace"])
    assert sidecar["summary"]["candidate_count"] == 1
    assert sidecar["summary"]["accepted_patch_count"] == 0


@pytest.mark.asyncio
async def test_auto_repair_node_injects_compact_metadata_summary_after_patch():
    from fairifier.graph.nodes import AutoRepairNode
    from fairifier.validation.metadata_json_format import check_metadata_json_output

    state = _add_study_title_candidate(_state_for_auto_repair())
    result = await AutoRepairNode()(state)

    metadata_json = json.loads(result["artifacts"]["metadata_json"])
    summary = metadata_json["auto_repair_summary"]
    assert summary["accepted_patch_count"] == 1
    assert summary["metadata_mutated"] is True
    assert summary["trace_artifact"] == "auto_repair_trace.json"
    assert summary["accepted_fields"] == [
        {
            "field": "study title",
            "isa_sheet": "study",
            "field_action": "appended",
            "post_patch_validation": "passed",
        }
    ]
    assert "accepted_patches" not in summary

    validation = check_metadata_json_output(
        metadata_json,
        selected_fields=[
            {
                "name": "study identifier",
                "isa_sheet": "study",
                "data_type": "string",
                "requirement": "MANDATORY",
            },
            {
                "name": "study title",
                "isa_sheet": "study",
                "data_type": "string",
                "requirement": "MANDATORY",
            },
        ],
    )
    assert validation["is_valid"] is True
    assert validation["errors"] == []


def test_generate_auto_repair_trace_applies_exact_candidate_patch():
    from fairifier.services.auto_repair import generate_auto_repair_trace

    state = _add_study_title_candidate(_state_for_auto_repair())
    trace = generate_auto_repair_trace(state)

    assert trace["summary"]["metadata_mutated"] is True
    assert trace["summary"]["accepted_patch_count"] == 1
    accepted = trace["accepted_patches"][0]
    assert accepted["field"] == "study title"
    assert accepted["decision"] == "deterministic_patch"
    assert accepted["field_action"] == "appended"
    assert accepted["post_patch_validation"] == "passed"

    patched_field = next(
        field for field in state["metadata_fields"]
        if field["field_name"] == "study title"
    )
    assert patched_field["value"] == "Pea cold stress response"
    assert patched_field["origin"] == "auto_repair"
    assert patched_field["status"] == "confirmed"

    metadata_json = json.loads(state["artifacts"]["metadata_json"])
    study_fields = metadata_json["isa_structure"]["study"]["fields"]
    assert any(
        field["field_name"] == "study title"
        for field in study_fields
    )

    assert (
        metadata_json["isa_structure"]["study"]["rows"][0]["study title"]
        == "Pea cold stress response"
    )
    assert (
        metadata_json["isa_values"]["study"]["rows"][0]["study title"]
        == "Pea cold stress response"
    )
    assert metadata_json["statistics"]["total_fields"] == 2


def test_generate_auto_repair_trace_records_classifier_shadow_prediction_only():
    from fairifier.services.auto_repair import generate_auto_repair_trace

    state = _add_study_title_candidate(_state_for_auto_repair())
    trace = generate_auto_repair_trace(
        state,
        classifier_shadow_predictions={
            "study title": {
                "decision": "accept_patch",
                "probability": 0.91,
                "threshold": 0.75,
                "model_version": "prototype-v0",
                "unsafe_extra": "not serialized",
            }
        },
    )

    accepted = trace["accepted_patches"][0]
    assert accepted["decision"] == "deterministic_patch"
    assert accepted["accept_patch"] is True
    assert accepted["classifier_shadow_prediction"] == {
        "decision": "accept_patch",
        "probability": 0.91,
        "threshold": 0.75,
        "model_version": "prototype-v0",
    }
    assert trace["summary"]["classifier_shadow_prediction_count"] == 1


def test_generate_auto_repair_trace_rolls_back_invalid_patch_result():
    from fairifier.services.auto_repair import generate_auto_repair_trace

    state = _add_study_title_candidate(_state_for_auto_repair())
    metadata_payload = json.loads(state["artifacts"]["metadata_json"])
    metadata_payload.pop("document_source")
    state["artifacts"]["metadata_json"] = json.dumps(metadata_payload)
    before_json = state["artifacts"]["metadata_json"]
    before_fields = list(state["metadata_fields"])

    trace = generate_auto_repair_trace(state)

    assert trace["summary"]["metadata_mutated"] is False
    assert trace["summary"]["accepted_patch_count"] == 0
    assert trace["summary"]["rejected_patch_count"] == 1
    rejected = trace["rejected_patches"][0]
    assert rejected["field"] == "study title"
    assert rejected["post_patch_validation"] == "failed"
    assert any(
        "Missing required top-level field: document_source" in failure
        for failure in rejected["patch_guard_failures"]
    )
    assert state["artifacts"]["metadata_json"] == before_json
    assert state["metadata_fields"] == before_fields


def test_generate_auto_repair_trace_supports_trace_only_fallback():
    from fairifier.services.auto_repair import generate_auto_repair_trace

    state = _add_study_title_candidate(_state_for_auto_repair())
    before_json = state["artifacts"]["metadata_json"]
    before_fields = list(state["metadata_fields"])

    trace = generate_auto_repair_trace(state, apply_patches=False)

    assert trace["summary"]["metadata_mutated"] is False
    assert trace["summary"]["apply_patches"] is False
    assert trace["summary"]["accepted_patch_count"] == 0
    assert trace["candidates"][0]["decision"] == "trace_only_candidate"
    assert state["artifacts"]["metadata_json"] == before_json
    assert state["metadata_fields"] == before_fields


def test_auto_repair_patch_output_passes_metadata_format_check():
    from fairifier.services.auto_repair import generate_auto_repair_trace
    from fairifier.validation.metadata_json_format import check_metadata_json_output

    state = _add_study_title_candidate(_state_for_auto_repair())
    generate_auto_repair_trace(state)
    metadata_json = json.loads(state["artifacts"]["metadata_json"])
    selected_fields = [
        {
            "name": "study identifier",
            "isa_sheet": "study",
            "data_type": "string",
            "requirement": "MANDATORY",
        },
        {
            "name": "study title",
            "isa_sheet": "study",
            "data_type": "string",
            "requirement": "MANDATORY",
        },
    ]

    result = check_metadata_json_output(
        metadata_json,
        selected_fields=selected_fields,
    )

    assert result["is_valid"] is True
    assert result["errors"] == []
    assert result["source_grounding"]["source_grounded_fields"] >= 1


def test_generate_auto_repair_trace_rejects_linkage_field_patch():
    from fairifier.services.auto_repair import generate_auto_repair_trace

    state = _state_for_auto_repair()
    state["retrieved_knowledge"] = [
        {
            "term": "sample identifier",
            "metadata": {
                "name": "sample identifier",
                "requirement": "MANDATORY",
                "isa_sheet": "sample",
            },
        }
    ]
    state["section_field_candidates"] = [
        {
            "field_name": "sample identifier",
            "field_candidate": "sample identifier",
            "value": "sample_001",
            "evidence": "src1:50-70 [role=primary] sample identifier: sample_001",
            "source_id": "src1",
            "char_start": 50,
            "char_end": 70,
            "confidence": 0.9,
            "provenance": {"agent": "section_map_reduce"},
        }
    ]

    trace = generate_auto_repair_trace(state)

    assert trace["summary"]["metadata_mutated"] is False
    assert trace["summary"]["accepted_patch_count"] == 0
    assert trace["summary"]["rejected_patch_count"] == 1
    rejected = trace["rejected_patches"][0]
    assert rejected["field"] == "sample identifier"
    assert "linkage_field_guard" in rejected["patch_guard_failures"]
    assert not any(
        field["field_name"] == "sample identifier"
        for field in state["metadata_fields"]
    )


def test_generate_auto_repair_trace_rejects_multi_row_sheet_patch():
    from fairifier.services.auto_repair import generate_auto_repair_trace

    state = _state_for_auto_repair()
    state["retrieved_knowledge"] = [
        {
            "term": "organism",
            "metadata": {
                "name": "organism",
                "requirement": "MANDATORY",
                "isa_sheet": "sample",
            },
        }
    ]
    state["section_field_candidates"] = [
        {
            "field_name": "organism",
            "field_candidate": "organism",
            "value": "Pisum sativum",
            "evidence": "src1:50-70 [role=primary] organism: Pisum sativum",
            "source_id": "src1",
            "char_start": 50,
            "char_end": 70,
            "confidence": 0.9,
            "provenance": {"agent": "section_map_reduce"},
        }
    ]
    before_json = state["artifacts"]["metadata_json"]
    before_fields = list(state["metadata_fields"])

    trace = generate_auto_repair_trace(state)

    assert trace["summary"]["metadata_mutated"] is False
    assert trace["summary"]["accepted_patch_count"] == 0
    assert trace["summary"]["rejected_patch_count"] == 1
    rejected = trace["rejected_patches"][0]
    assert rejected["field"] == "organism"
    assert "multi_row_sheet_guard" in rejected["patch_guard_failures"]
    assert state["artifacts"]["metadata_json"] == before_json
    assert state["metadata_fields"] == before_fields


def test_auto_repair_env_overrides(monkeypatch):
    from fairifier.config import FAIRifierConfig, apply_env_overrides

    monkeypatch.setenv("FAIRIFIER_AUTO_REPAIR_ENABLED", "false")
    monkeypatch.setenv("FAIRIFIER_AUTO_REPAIR_APPLY_PATCHES", "false")
    monkeypatch.setenv("FAIRIFIER_AUTO_REPAIR_MIN_CANDIDATE_CONFIDENCE", "0.72")
    monkeypatch.setenv("FAIRIFIER_AUTO_REPAIR_CLASSIFIER_SHADOW_ENABLED", "false")

    cfg = FAIRifierConfig()
    apply_env_overrides(cfg)

    assert cfg.auto_repair_enabled is False
    assert cfg.auto_repair_apply_patches is False
    assert cfg.auto_repair_min_candidate_confidence == 0.72
    assert cfg.auto_repair_classifier_shadow_enabled is False
