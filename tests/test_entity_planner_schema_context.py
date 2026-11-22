"""Selected schema semantics must reach planning before rows are proposed."""

import json
from unittest.mock import MagicMock

import pytest

from fairifier.agents import entity_structure_planner as planner_module
from fairifier.agents.entity_structure_planner import EntityStructurePlannerAgent
from fairifier.agents.response_models import EntityDesignClaimsResponse
from fairifier.utils.entity_plan import materialize_entity_claims


MATERIAL_DEFINITION = (
    "Class of physical material represented by this sample record; "
    "the category does not identify an individual preparation."
)
REFERENCE_DEFINITION = (
    "Identifier of the physical sample used as input to this measurement; "
    "the referenced sample must be established by the source."
)
MATERIAL_ENUM = "(aqueous preparation|solid support)"
SOURCE = (
    "A named specimen was measured at two time points. The report does not "
    "state whether the second measurement used the same preparation."
)


def test_planner_contract_accepts_reported_result_without_underlying_run_count():
    parsed = EntityDesignClaimsResponse.model_validate({
        "reported_assays": [{
            "record_id": "fit_alpha", "sample_row_id": "material_alpha",
            "record_kind": "fitted_result", "source_subject": "alpha",
            "source_quote": "For alpha the fitted coefficient was 0.7.",
            "label": "Coefficient for alpha", "source_group": "fitting",
            "attributes": [{"field_name": "coefficient", "value": "0.7"}],
            "unreported_design": ["The number of underlying measurements is unknown."],
        }],
    })
    result = parsed.model_dump()["reported_assays"][0]
    assert result["record_kind"] == "fitted_result"
    assert "level_count" not in result
    assert result["sample_row_id"] == "material_alpha"


@pytest.mark.parametrize("change", [{"record_kind": "individual_replicate"}, {"sample_row_id": ""}])
def test_reported_result_contract_requires_supported_grain_and_material_reference(change):
    from pydantic import ValidationError
    record = {
        "record_id": "fit_alpha", "sample_row_id": "material_alpha",
        "record_kind": "fitted_result", "source_subject": "alpha",
        "source_quote": "For alpha the fitted coefficient was 0.7.",
        "label": "Coefficient for alpha", "source_group": "fitting",
        "attributes": [{"field_name": "coefficient", "value": "0.7"}],
        **change,
    }
    with pytest.raises(ValidationError):
        EntityDesignClaimsResponse.model_validate({"reported_assays": [record]})


@pytest.fixture
def planner_context(monkeypatch):
    # Prompt construction is isolated from model/service initialization and
    # external table reads. All field semantics come from selected packages.
    monkeypatch.setattr(planner_module, "metadata_table_profiles", lambda *_: [])
    monkeypatch.setattr(
        planner_module, "metadata_table_profiles_for_document_datasets", lambda *_: []
    )
    planner = object.__new__(EntityStructurePlannerAgent)
    contracts = [
        {
            "term": "material category",
            "definition": MATERIAL_DEFINITION,
            "metadata": {
                "isa_sheet": "sample",
                "definition": MATERIAL_DEFINITION,
                "syntax": MATERIAL_ENUM,
                "regex": MATERIAL_ENUM,
                "requirement": "RECOMMENDED",
                "package": "synthetic_measurements",
            },
        },
        {
            "term": "input specimen identifier",
            "definition": REFERENCE_DEFINITION,
            "metadata": {
                "isa_sheet": "assay",
                "definition": REFERENCE_DEFINITION,
                "syntax": "{text}",
                "regex": ".*",
                "requirement": "MANDATORY",
                "package": "synthetic_measurements",
            },
        },
    ]
    state = {
        "document_content": SOURCE,
        "retrieved_knowledge": [],
        "api_capabilities": {
            "selected_package_field_contracts": contracts,
            "unselected_package_field_contracts": [{
                "term": "unselected field", "definition": "UNSELECTED_CONTRACT",
                "metadata": {"isa_sheet": "sample"},
            }],
        },
    }
    return planner, state


def _prompts(planner_context):
    planner, state = planner_context
    knowledge = planner._planning_knowledge(state)
    return {
        "draft": planner._prompt(state),
        "audit": planner._scope_audit_prompt(
            {"design_groups": []},
            planner._field_catalog(knowledge),
            planner._field_contract_catalog(knowledge),
            [],
            source_text=SOURCE,
        ),
    }


def test_draft_receives_contract_definitions_and_enums_from_selected_package_only(
    planner_context,
):
    prompt = _prompts(planner_context)["draft"]
    heading = "Live FAIR-DS field definitions and value contracts:"
    assert heading in prompt
    catalog, _ = json.JSONDecoder().raw_decode(prompt.split(heading, 1)[1].lstrip())

    material = catalog["sample"][0]
    assert material["field_name"] == "material category"
    assert material["definition"] == MATERIAL_DEFINITION
    assert material["regex"] == MATERIAL_ENUM
    assert material["syntax"] == MATERIAL_ENUM
    assert catalog["assay"][0]["definition"] == REFERENCE_DEFINITION
    assert "UNSELECTED_CONTRACT" not in prompt


@pytest.mark.parametrize("stage", ["draft", "audit"])
def test_schema_roles_and_reference_definitions_reach_both_planning_stages(
    planner_context, stage,
):
    prompt = _prompts(planner_context)[stage]
    assert MATERIAL_DEFINITION in prompt
    assert REFERENCE_DEFINITION in prompt
    assert MATERIAL_ENUM in prompt
    assert SOURCE in prompt
    assert "UNSELECTED_CONTRACT" not in prompt


@pytest.mark.parametrize("stage", ["draft", "audit"])
def test_schema_semantics_do_not_authorize_invented_physical_entities_or_links(
    planner_context, stage,
):
    prompt = " ".join(_prompts(planner_context)[stage].lower().split())

    assert "schema defines record roles and allowed values" in prompt
    assert "source defines actual identities, counts, and relationships" in prompt
    assert "a material category does not establish a distinct physical preparation" in prompt
    assert "repeated measurements do not by themselves establish new material" in prompt
    assert "reference endpoints require source evidence" in prompt
    assert "keep the physical relation unknown" in prompt


def test_schema_delivery_preserves_factorial_and_source_evidence_constraints(planner_context):
    prompt = _prompts(planner_context)["draft"]
    assert "Parent dimensions" in prompt and "subset of child dimensions" in prompt
    assert "full_factorial_evidence" in prompt
    assert "every combination was run" in prompt
    assert "external_identifier" in prompt and "source explicitly supplies that identifier" in prompt
    assert "absence of reuse evidence does not establish distinct material" in prompt


def test_planner_prompt_explains_unknown_counts_and_string_summary_items(planner_context):
    prompt = " ".join(_prompts(planner_context)["draft"].lower().split())

    assert "level_count" in prompt and "positive integer" in prompt
    assert "level_count=null" in prompt
    assert "do not replace an unknown count with 0 or 1" in prompt
    assert "design_summary and unresolved_ambiguities are lists of strings" in prompt


@pytest.mark.parametrize("on_disk", [False, True])
def test_initial_planning_receives_late_source_design_before_scope_audit(
    planner_context, tmp_path, on_disk,
):
    planner, state = planner_context
    late_design = (
        "In the final experiment, specimen Z was measured at 6 h and 12 h. "
        "Both measurements used the same identified specimen."
    )
    document = "Opening context. " * 1300 + "\n" + late_design
    state["document_content"] = document
    if on_disk:
        source = tmp_path / "working_source.md"
        source.write_text(document, encoding="utf-8")
        state["document_text_path"] = str(source)
        state["document_content"] = "Stale in-memory prefix."

    prompt = planner._prompt(state)

    assert document in prompt
    assert late_design in prompt
    assert "Stale in-memory prefix." not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("thinking", [True, False])
async def test_planner_retries_receive_concrete_schema_errors_without_extra_calls(
    planner_context, monkeypatch, thinking,
):
    planner, state = planner_context
    planner.llm_helper = MagicMock()
    planner.logger = MagicMock()
    monkeypatch.setattr(planner, "log_execution", lambda *args: None)
    monkeypatch.setattr(planner, "update_confidence", lambda *args: None)
    monkeypatch.setattr(planner, "_source_contacts", lambda *args: [])
    monkeypatch.setattr(planner_module.config, "entity_plan_max_attempts", 2)
    monkeypatch.setattr(planner_module.config, "llm_enable_thinking", thinking)
    prompts = []
    specific_error = (
        "design_groups.0.dimensions.0.level_count [greater_than_equal]: "
        "Input should be greater than or equal to 1"
    )

    async def invalid_output(helper, messages, schema_model, **kwargs):
        assert kwargs["max_tokens"] == (65536 if thinking else 32768)
        prompts.append(messages[-1].content)
        if kwargs.get("validation_errors") is not None:
            kwargs["validation_errors"].append(specific_error)
        return None

    monkeypatch.setattr(planner_module, "invoke_structured_output", invalid_output)
    result = await planner.execute(state)

    assert len(prompts) == 2
    assert specific_error not in prompts[0]
    assert specific_error in prompts[1]
    assert specific_error in result["entity_plan_validation"]["errors"]
    assert result["entity_plan_validation"]["passed"] is False
    assert result["entity_plan"] == {}
    assert result["needs_human_review"] is True


def test_unknown_dimension_count_is_noted_and_not_expanded():
    claims = EntityDesignClaimsResponse.model_validate({
        "design_groups": [{
            "group_id": "branch_a", "label": "Source branch",
            "study_row_id": "study_a", "evidence": "An unspecified number of specimens.",
            "dimensions": [{
                "name": "specimen", "level_count": None,
                "explicit_values": [], "origin": "derived", "applies_to": ["sample", "assay"],
            }],
        }],
        "unresolved_ambiguities": ["The source does not report the number of specimens."],
    }).model_dump()

    assert claims["design_groups"][0]["dimensions"][0]["level_count"] is None
    plan = materialize_entity_claims(claims)
    # not expanded into an invented "specimen 01" level, recorded as a note
    rows = [row for level in plan["levels"] for row in level["entities"]
            if row.get("source_group") == "branch_a"]
    assert rows and not any(a["dimension_name"] == "specimen" for row in rows for a in row["attributes"])
    assert any("specimen" in note for note in plan["unresolved_ambiguities"])


@pytest.mark.asyncio
@pytest.mark.parametrize("latest_count", [1, 25])
async def test_planner_retry_feedback_replaces_resolved_earlier_errors(
    planner_context, monkeypatch, latest_count,
):
    planner, state = planner_context
    planner.llm_helper = MagicMock()
    planner.logger = MagicMock()
    monkeypatch.setattr(planner, "log_execution", lambda *args: None)
    monkeypatch.setattr(planner, "update_confidence", lambda *args: None)
    monkeypatch.setattr(planner, "_source_contacts", lambda *args: [])
    monkeypatch.setattr(planner_module.config, "entity_plan_max_attempts", 3)
    earlier = [f"Missing required material property {index}." for index in range(25)]
    latest = [f"Unresolved measurement parent {index}." for index in range(latest_count)]
    prompts = []

    async def invalid_output(helper, messages, schema_model, **kwargs):
        if schema_model.__name__ == "MaterialInventoryResponse":
            return None  # the separate material inventory call is not a plan attempt
        prompts.append(messages[-1].content)
        kwargs["validation_errors"].extend(earlier if len(prompts) == 1 else latest)
        return None

    monkeypatch.setattr(planner_module, "invoke_structured_output", invalid_output)

    result = await planner.execute(state)

    assert len(prompts) == 3
    assert earlier[0] in prompts[1]
    assert all(error in prompts[2] for error in latest[:20])
    assert all(error not in prompts[2] for error in earlier)
    assert result["entity_plan_validation"]["errors"] == latest
    assert result["entity_plan_validation"]["passed"] is False


@pytest.mark.asyncio
async def test_planner_retries_a_truncated_answer_and_keeps_thinking(planner_context, monkeypatch):
    from fairifier.utils.llm_helper import effective_thinking
    from fairifier.utils.structured_output import TRUNCATED_ANSWER_MARKER

    planner, state = planner_context
    planner.llm_helper = MagicMock()
    planner.logger = MagicMock()
    monkeypatch.setattr(planner, "log_execution", lambda *args: None)
    monkeypatch.setattr(planner, "update_confidence", lambda *args: None)
    monkeypatch.setattr(planner, "_source_contacts", lambda *args: [])
    monkeypatch.setattr(planner_module.config, "entity_plan_max_attempts", 2)
    monkeypatch.setattr(planner_module.config, "llm_enable_thinking", True)
    thinking = []

    async def truncated_then_empty(helper, messages, schema_model, **kwargs):
        if schema_model.__name__ == "MaterialInventoryResponse":
            return None
        thinking.append(effective_thinking())
        if len(thinking) == 1:
            kwargs["validation_errors"].append(TRUNCATED_ANSWER_MARKER)
        return None

    monkeypatch.setattr(planner_module, "invoke_structured_output", truncated_then_empty)
    await planner.execute(state)
    assert thinking == [True, True]
