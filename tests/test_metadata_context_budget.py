import asyncio
import json
from types import SimpleNamespace

import pytest

from fairifier.utils.llm_helper import LLMHelper


def test_metadata_generation_does_not_hard_truncate_short_context_below_config_budget():
    helper = object.__new__(LLMHelper)

    long_text = "A" * 7000 + "KEEP_THIS_TAIL"
    prepared = helper._prepare_metadata_document_context(
        long_text,
        [{"field_name": "study_location", "isa_sheet": "study"}],
    )

    assert prepared == long_text
    assert prepared.endswith("KEEP_THIS_TAIL")


def test_metadata_generation_budget_uses_configurable_start_and_tail_context(monkeypatch):
    helper = object.__new__(LLMHelper)
    monkeypatch.setattr("fairifier.utils.llm_helper.config.metadata_max_context_chars_per_field", 100)

    prepared = helper._prepare_metadata_document_context(
        "A" * 200 + "TAIL",
        [{"field_name": "study_location", "isa_sheet": "study"}],
    )

    assert len(prepared) > 100
    assert "metadata context budget omitted" in prepared
    assert prepared.endswith("TAIL")


def _fields(*names):
    return [{"name": name, "isa_sheet": "assay", "description": name} for name in names]


def test_batch_evidence_has_fair_bounded_shares_and_preserves_table_context(monkeypatch):
    helper = object.__new__(LLMHelper)
    monkeypatch.setattr("fairifier.utils.llm_helper.config.metadata_max_context_chars_per_field", 1200)
    table = (
        "- source_001 table table_002 row 3: specimen B7, rate 0; "
        "table_context: caption=Initial rates at 30 C; footnote=mmol/L/h; "
        "source_row_index=3; manifest_path=/source/source_manifest.json"
    )
    prepared = helper._prepare_metadata_document_context(
        "SHARED_START " + "shared " * 2000 + " SHARED_END",
        _fields("early field", "late rate"),
        field_evidence_by_name={
            "early field": ["- source_001:0-90000 EARLY " + "large " * 2000],
            "late rate": [table],
            "unselected": ["UNSELECTED_EVIDENCE"],
        },
    )

    assert "EARLY" in prepared and table in prepared
    assert "UNSELECTED_EVIDENCE" not in prepared
    assert "SHARED_START" in prepared and "SHARED_END" in prepared
    assert "truncated" in prepared.lower() or "omitted" in prepared.lower()
    assert len(prepared) <= helper._metadata_context_budget(2)


def test_single_field_evidence_context_and_plain_context_are_supported(monkeypatch):
    helper = object.__new__(LLMHelper)
    monkeypatch.setattr("fairifier.utils.llm_helper.config.metadata_max_context_chars_per_field", 1200)
    shared = "The source reports a measurement."
    assert helper._prepare_metadata_document_context(shared, _fields("rate")) == shared
    prepared = helper._prepare_metadata_document_context(
        shared, _fields("rate"),
        field_evidence_by_name={"rate": ["- source_001:120-150 RATE_EVIDENCE 0 mmol/L/h"]},
    )
    assert shared in prepared and "RATE_EVIDENCE" in prepared
    assert len(prepared) <= 1200


@pytest.mark.parametrize("split_after_failure", [False, True])
def test_generation_batches_receive_only_their_own_field_evidence(monkeypatch, split_after_failure):
    helper = object.__new__(LLMHelper)
    helper.provider = "deepseek"
    helper.model = "test-model"
    monkeypatch.setattr(helper, "_metadata_generation_batch_size", lambda: 2 if split_after_failure else 1)
    monkeypatch.setattr("fairifier.utils.llm_helper.config.metadata_max_context_chars_per_field", 1200)
    prompts = []
    failed = False

    async def call(messages, **kwargs):
        nonlocal failed
        prompt = messages[-1].content
        if split_after_failure and not failed:
            failed = True
            raise ValueError("Synthetic batch failure")
        prompts.append(prompt)
        return SimpleNamespace(content='{"fields": []}')

    monkeypatch.setattr(helper, "_call_llm", call)
    result = asyncio.run(helper.generate_complete_metadata(
        {}, _fields("first attribute", "second attribute"), "Shared source context.",
        field_evidence_by_name={
            "first attribute": ["- source_001:10-20 FIRST_ONLY_VALUE 17"],
            "second attribute": ["- source_001:30-40 SECOND_ONLY_VALUE 29"],
        },
    ))

    assert len(prompts) == 2
    assert "FIRST_ONLY_VALUE" in prompts[0] and "SECOND_ONLY_VALUE" not in prompts[0]
    assert "SECOND_ONLY_VALUE" in prompts[1] and "FIRST_ONLY_VALUE" not in prompts[1]
    assert [item["field_name"] for item in result] == ["first attribute", "second attribute"]


def test_assay_extraction_prompt_accepts_reported_results_and_tables():
    helper = object.__new__(LLMHelper)
    messages = helper._build_metadata_generation_messages(
        {}, _fields("initial rate"), "Table 2 reports the initial rate for specimen B7."
    )
    prompt = messages[-1].content
    assay_rule = next(line for line in prompt.splitlines() if "**Assay-level fields**" in line)
    assert "results" in assay_rule.lower() and "tables" in assay_rule.lower()
    assert "condition" in assay_rule.lower() and "entit" in assay_rule.lower()
    system_assay_rule = next(
        line for line in messages[0].content.splitlines() if "**Assay-level fields**" in line
    )
    assert "results" in system_assay_rule.lower() and "tables" in system_assay_rule.lower()
    assert "condition" in system_assay_rule.lower() and "entit" in system_assay_rule.lower()


def _large_entity_plan(count=96):
    levels = []
    for level, prefix, parent_prefix, size in (
        ("investigation", "INV", None, 1),
        ("study", "STU", "INV", 1),
        ("observationunit", "OBS", "STU", 2),
        ("sample", "SAM", "OBS", count),
        ("assay", "ASS", "SAM", count),
    ):
        entities = []
        for index in range(size):
            parent_index = index if level == "assay" else index % 2 if level == "sample" else 0
            entities.append({
                "row_id": f"{prefix}_{index:03d}",
                "parent_row_id": f"{parent_prefix}_{parent_index:03d}" if parent_prefix else None,
                "external_identifier": f"SOURCE-{prefix}-{index:03d}",
                "source_group": "source_branch",
                "label": f"Source record {prefix} {index}",
                "attributes": [{
                    "dimension_name": "elapsed time", "field_name": "elapsed time",
                    "value": f"{index} h", "origin": "explicit",
                }],
                "evidence": "LONG_PLAN_NARRATIVE_DO_NOT_REPEAT " * 100,
            })
        levels.append({"level": level, "cardinality": size, "entities": entities})
    return {"levels": levels, "design_summary": ["LONG_DESIGN_SUMMARY " * 100]}


def _identity_payload(prompt):
    start = prompt.split("Authoritative entity identities (complete for this batch):\n", 1)[1]
    payload, _ = json.JSONDecoder().raw_decode(start)
    return {item["level"]: item["entities"] for item in payload["levels"]}


def test_metadata_generation_preserves_complete_large_plan_outside_source_budget(monkeypatch):
    helper = object.__new__(LLMHelper)
    monkeypatch.setattr("fairifier.utils.llm_helper.config.metadata_max_context_chars_per_field", 1200)
    plan = _large_entity_plan()
    prompt = helper._build_metadata_generation_messages(
        {}, _fields("rate"), "SOURCE_BEGIN " + "source " * 10000 + " SOURCE_END",
        entity_plan=plan,
    )[-1].content

    identities = _identity_payload(prompt)
    for level in plan["levels"]:
        actual = identities[level["level"]]
        assert len(actual) == level["cardinality"]
        for expected, row in zip(level["entities"], actual):
            for key in ("row_id", "parent_row_id", "external_identifier", "source_group", "label", "attributes"):
                assert row[key] == expected[key]
    assert "ASS_095" in prompt and "SAM_095" in prompt
    assert "LONG_PLAN_NARRATIVE_DO_NOT_REPEAT" not in prompt
    assert "LONG_DESIGN_SUMMARY" not in prompt
    source_excerpt = prompt.split("Document excerpt:\n", 1)[1].split("\n\nMetadata fields to populate", 1)[0]
    assert "SOURCE_BEGIN" in source_excerpt and "SOURCE_END" in source_excerpt
    assert len(source_excerpt) <= 1400
    assert len(json.dumps(identities)) > 14000


@pytest.mark.parametrize("sheet,expected_levels", [
    ("sample", {"investigation", "study", "observationunit", "sample"}),
    ("study", {"investigation", "study"}),
])
def test_identity_context_contains_current_levels_and_actual_ancestors_only(sheet, expected_levels):
    helper = object.__new__(LLMHelper)
    prompt = helper._build_metadata_generation_messages(
        {}, [{"name": "description", "isa_sheet": sheet}], "Source text",
        entity_plan=_large_entity_plan(),
    )[-1].content
    identities = _identity_payload(prompt)
    assert set(identities) == expected_levels
    assert "ASS_095" not in prompt
    if sheet == "study":
        assert "SAM_095" not in prompt


@pytest.mark.parametrize("split_after_failure", [False, True])
def test_every_generation_batch_and_recursive_child_retains_plan_identities(monkeypatch, split_after_failure):
    helper = object.__new__(LLMHelper)
    helper.provider = "deepseek"
    helper.model = "test-model"
    monkeypatch.setattr(helper, "_metadata_generation_batch_size", lambda: 2 if split_after_failure else 1)
    monkeypatch.setattr("fairifier.utils.llm_helper.config.metadata_max_context_chars_per_field", 1200)
    prompts = []
    failed = False

    async def call(messages, **kwargs):
        nonlocal failed
        prompt = messages[-1].content
        if split_after_failure and not failed:
            failed = True
            raise ValueError("Synthetic batch failure")
        prompts.append(prompt)
        return SimpleNamespace(content='{"fields": []}')

    monkeypatch.setattr(helper, "_call_llm", call)
    result = asyncio.run(helper.generate_complete_metadata(
        {}, _fields("first attribute", "second attribute"), "source " * 10000,
        entity_plan=_large_entity_plan(),
        field_evidence_by_name={
            "first attribute": ["source_001 FIRST_SOURCE_FACT"],
            "second attribute": ["source_001 SECOND_SOURCE_FACT"],
        },
    ))
    assert len(prompts) == 2
    for prompt in prompts:
        identities = _identity_payload(prompt)
        assert len(identities["assay"]) == 96
        assert identities["assay"][-1]["row_id"] == "ASS_095"
        assert identities["assay"][-1]["parent_row_id"] == "SAM_095"
        assert identities["sample"][-1]["parent_row_id"] == "OBS_001"
    assert "FIRST_SOURCE_FACT" in prompts[0] and "SECOND_SOURCE_FACT" not in prompts[0]
    assert "SECOND_SOURCE_FACT" in prompts[1] and "FIRST_SOURCE_FACT" not in prompts[1]
    assert len(result) == 2


def test_authoritative_plan_excludes_prior_model_invented_entity_labels():
    helper = object.__new__(LLMHelper)
    prior = {"assay": {"INVENTED_ASSAY": {"rate": "999"}}}
    prompt = helper._build_metadata_generation_messages(
        {}, _fields("rate"), "Source text", established_entities=prior,
        entity_plan=_large_entity_plan(),
    )[-1].content
    assert "INVENTED_ASSAY" not in prompt
    assert "Known entities from prior batches" not in prompt
    assert len(_identity_payload(prompt)["assay"]) == 96


def test_no_plan_generation_keeps_legacy_prior_entity_context():
    helper = object.__new__(LLMHelper)
    prompt = helper._build_metadata_generation_messages(
        {}, _fields("rate"), "Source text",
        established_entities={"assay": {"EARLIER_ASSAY": {"rate": "0"}}},
    )[-1].content
    assert "Known entities from prior batches" in prompt and "EARLIER_ASSAY" in prompt
