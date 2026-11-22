"""Bounded mapping schedules and identity-safe sparse matrix assembly."""

from collections import Counter
from copy import deepcopy

import pytest

from fairifier.utils.isa_mapping_batches import (
    MAX_BATCH_ENTITIES,
    MAX_BATCH_OUTPUT_CHARS,
    merge_mapping_batch,
    plan_mapping_batches,
    seed_mapping_matrix,
)


def _plan(assays=35):
    levels = []
    for level, prefix, parent, count in (
        ("investigation", "inv", None, 1),
        ("study", "stu", "inv", 1),
        ("observationunit", "obs", "stu", 2),
        ("sample", "sam", "obs", 4),
        ("assay", "ass", "sam", assays),
    ):
        entities = []
        for index in range(count):
            parent_index = index % 4 if level == "assay" else index % 2 if level == "sample" else 0
            entities.append({
                "row_id": f"{prefix}_{index}",
                "parent_row_id": f"{parent}_{parent_index}" if parent else None,
                "external_identifier": f"SOURCE_{prefix}_{index}",
                "source_group": f"branch_{index % 2}" if level in {"sample", "assay"} else "root",
                "label": f"Source label {prefix} {index}",
                "attributes": [{"dimension_name": "material", "value": f"material {index}", "origin": "explicit"}],
            })
        levels.append({"level": level, "cardinality": count, "entities": entities})
    return {
        "levels": levels,
        "investigation_contacts": [{"firstname": "A", "lastname": "One"}, {"firstname": "B", "lastname": "Two"}],
    }


def _fields(count=25):
    return {"assay": [{
        "field_name": f"attribute {index}", "value": f"reported value {index}",
        "entity_id": "ass_0", "value_scope": "entity", "status": "confirmed",
    } for index in range(count)]}


def _entities(plan, level="assay"):
    return next(item["entities"] for item in plan["levels"] if item["level"] == level)


def _single_batch(plan=None):
    plan = plan or _plan(2)
    fields = _fields(2)
    return plan, fields, plan_mapping_batches(fields, plan)[0]


def test_batches_cover_each_entity_field_once_within_all_limits():
    plan, fields = _plan(), _fields()
    before = deepcopy((plan, fields))
    batches = plan_mapping_batches(fields, plan)
    scheduled = Counter()
    for batch in batches:
        assert batch["target_level"] == "assay"
        assert len(batch["row_ids"]) <= MAX_BATCH_ENTITIES
        assert len(batch["field_names"]) <= 12
        assert batch["estimated_output_chars"] <= MAX_BATCH_OUTPUT_CHARS
        assert {"assay identifier", "sample identifier"} <= set(batch["field_names"])
        for row_id in batch["row_ids"]:
            for name in batch["field_names"]:
                if name not in {"assay identifier", "sample identifier"}:
                    scheduled[(row_id, name)] += 1
    expected = {(row["row_id"], field["field_name"]) for row in _entities(plan) for field in fields["assay"]}
    assert set(scheduled) == expected
    assert set(scheduled.values()) == {1}
    assert (plan, fields) == before


def test_sliced_plan_keeps_actual_ancestors_full_attributes_and_contacts():
    plan, fields = _plan(3), _fields(1)
    batch = plan_mapping_batches(fields, plan, max_entities=1)[1]
    sliced = {item["level"]: item["entities"] for item in batch["entity_plan"]["levels"]}
    assert sliced["assay"] == [_entities(plan)[1]]
    assert sliced["sample"] == [_entities(plan, "sample")[1]]
    assert sliced["observationunit"] == [_entities(plan, "observationunit")[1]]
    assert len(sliced["study"]) == len(sliced["investigation"]) == 1
    assert batch["entity_plan"]["investigation_contacts"] == plan["investigation_contacts"]


def test_large_values_split_fields_and_rows_without_clipping_proposals():
    plan, fields = _plan(3), _fields(2)
    for field in fields["assay"]:
        field["value"] = "x" * (MAX_BATCH_OUTPUT_CHARS * 9 // 16)
        field["entity_id"] = "unresolved_record"
    batches = plan_mapping_batches(fields, plan)
    assert len(batches) == 6
    assert all(batch["estimated_output_chars"] <= MAX_BATCH_OUTPUT_CHARS for batch in batches)
    assert all(len(batch["fields_by_level"]["assay"][0]["value"]) == MAX_BATCH_OUTPUT_CHARS * 9 // 16 for batch in batches)


def test_unrepresentable_single_cell_budget_fails_explicitly():
    fields = _fields(1)
    fields["assay"][0]["value"] = "x" * (MAX_BATCH_OUTPUT_CHARS * 5 // 4)
    with pytest.raises(ValueError, match="budget"):
        plan_mapping_batches(fields, _plan(1))


def test_unknown_and_wrong_level_proposals_remain_unbound_context():
    plan, fields = _plan(2), _fields(2)
    fields["assay"][0]["entity_id"] = "unknown_source_record"
    fields["assay"][1]["entity_id"] = "sam_0"
    batch = plan_mapping_batches(fields, plan)[0]
    assert batch["fields_by_level"] == fields
    matrix = seed_mapping_matrix(fields, plan)
    assert all(row["attribute 0"] == row["attribute 1"] == "" for row in matrix["assay"]["rows"])
    issues = merge_mapping_batch(matrix, {"assay": {"rows": [{"attribute 0": "unsupported broadcast"}]}}, batch, plan)
    assert issues
    assert all(row["attribute 0"] == "" for row in matrix["assay"]["rows"])


def test_roots_are_not_scheduled_or_seeded_as_duplicate_contact_entities():
    fields = {**_fields(1), "investigation": [{"field_name": "firstname", "value": "A"}]}
    plan = _plan(2)
    assert all(batch["target_level"] not in {"investigation", "study"} for batch in plan_mapping_batches(fields, plan))
    assert "investigation" not in seed_mapping_matrix(fields, plan)


def test_merge_reordered_sparse_rows_normalizes_keys_and_preserves_zero():
    plan, fields, batch = _single_batch()
    matrix = seed_mapping_matrix(fields, plan)
    issues = merge_mapping_batch(matrix, {"assay": {"rows": [
        {" Assay Identifier ": "ass_1", "ATTRIBUTE 1": 0},
        {"assay identifier": "ass_0", "attribute 0": "source fact"},
    ]}}, batch, plan)
    assert issues == []
    rows = matrix["assay"]["rows"]
    assert rows[0]["attribute 0"] == "source fact"
    assert rows[1]["attribute 1"] == "0"
    assert rows[0]["sample identifier"] == "sam_0"
    assert rows[1]["sample identifier"] == "sam_1"


@pytest.mark.parametrize("alias", [False, True])
def test_merge_accepts_unique_canonical_or_external_id_with_compatible_parent(alias):
    plan, fields, batch = _single_batch()
    matrix = seed_mapping_matrix(fields, plan)
    response = {"assay": {"rows": [{
        "assay identifier": row["external_identifier"] if alias else row["row_id"],
        "sample identifier": f"SOURCE_sam_{index}" if alias else row["parent_row_id"],
        "attribute 0": str(index),
    } for index, row in enumerate(_entities(plan))]}}
    assert merge_mapping_batch(matrix, response, batch, plan) == []
    assert [row["attribute 0"] for row in matrix["assay"]["rows"]] == ["0", "1"]


def test_external_alias_uniqueness_uses_full_plan_not_current_chunk():
    plan, fields = _plan(2), _fields(1)
    for row in _entities(plan):
        row["external_identifier"] = "shared_alias"
    batch = plan_mapping_batches(fields, plan, max_entities=1)[0]
    matrix = seed_mapping_matrix(fields, plan)
    issues = merge_mapping_batch(matrix, {"assay": {"rows": [{
        "assay identifier": "shared_alias", "attribute 0": "wrong scope",
    }]}}, batch, plan)
    assert issues
    assert all(row["attribute 0"] == "" for row in matrix["assay"]["rows"])


def test_unique_canonical_id_survives_duplicate_external_aliases():
    plan, fields = _plan(2), _fields(1)
    for row in _entities(plan):
        row["external_identifier"] = "shared_alias"
    batch = plan_mapping_batches(fields, plan, max_entities=1)[0]
    matrix = seed_mapping_matrix(fields, plan)
    issues = merge_mapping_batch(matrix, {"assay": {"rows": [{
        "assay identifier": "ass_0", "attribute 0": "bound fact",
    }]}}, batch, plan)
    assert issues == []
    assert matrix["assay"]["rows"][0]["attribute 0"] == "bound fact"
    assert matrix["assay"]["rows"][1]["attribute 0"] == ""


@pytest.mark.parametrize("bad_scope", [{"sample identifier": "sam_1"}, {"source_group": "wrong_branch"}])
def test_conflicting_parent_or_group_cannot_write_target_cell(bad_scope):
    plan, fields, batch = _single_batch()
    matrix = seed_mapping_matrix(fields, plan)
    issues = merge_mapping_batch(matrix, {"assay": {"rows": [
        {"assay identifier": "ass_0", "attribute 0": "wrong", **bad_scope},
        {"assay identifier": "ass_1"},
    ]}}, batch, plan)
    assert issues
    assert matrix["assay"]["rows"][0]["attribute 0"] == ""


def test_out_of_batch_and_cross_namespace_ids_never_write_cells():
    plan, fields = _plan(3), _fields(1)
    _entities(plan)[1]["external_identifier"] = "ass_0"
    batch = plan_mapping_batches(fields, plan, max_entities=1)[0]
    matrix = seed_mapping_matrix(fields, plan)
    issues = merge_mapping_batch(matrix, {"assay": {"rows": [
        {"assay identifier": "ass_0", "attribute 0": "ambiguous"},
        {"assay identifier": "ass_2", "attribute 0": "outside"},
    ]}}, batch, plan)
    assert issues
    assert all(row["attribute 0"] == "" for row in matrix["assay"]["rows"])


def test_duplicate_rows_do_not_pick_a_winner_or_erase_previous_scientific_value():
    plan, fields, batch = _single_batch()
    matrix = seed_mapping_matrix(fields, plan)
    matrix["assay"]["rows"][1]["attribute 0"] = "earlier verified value"
    issues = merge_mapping_batch(matrix, {"assay": {"rows": [
        {"assay identifier": "ass_0", "attribute 0": "first"},
        {"assay identifier": "SOURCE_ass_0", "attribute 0": "second"},
        {"assay identifier": "ass_1", "attribute 0": "conflicting later value"},
    ]}}, batch, plan)
    assert any("duplicate" in issue.lower() for issue in issues)
    assert any("conflict" in issue.lower() for issue in issues)
    assert matrix["assay"]["rows"][0]["attribute 0"] == ""
    assert matrix["assay"]["rows"][1]["attribute 0"] == "earlier verified value"


def test_missing_target_rows_report_issues_and_keep_full_seed():
    plan, fields, batch = _single_batch()
    matrix = seed_mapping_matrix(fields, plan)
    issues = merge_mapping_batch(matrix, {"assay": {"rows": [{"assay identifier": "ass_0"}]}}, batch, plan)
    assert any("missing" in issue.lower() and "ass_1" in issue for issue in issues)
    assert len(matrix["assay"]["rows"]) == 2
    assert set(matrix["assay"]["columns"]) == set(batch["field_names"])


def test_normalized_key_conflicts_and_unrequested_fields_are_not_written():
    plan, fields, batch = _single_batch()
    matrix = seed_mapping_matrix(fields, plan)
    issues = merge_mapping_batch(matrix, {"assay": {"rows": [
        {"assay identifier": "ass_0", "attribute 0": "first", " ATTRIBUTE 0 ": "second"},
        {"assay identifier": "ass_1", "unrequested": "not permitted"},
    ]}}, batch, plan)
    assert issues
    assert matrix["assay"]["rows"][0]["attribute 0"] == ""
    assert "unrequested" not in matrix["assay"]["columns"]


def test_duplicate_canonical_plan_ids_are_rejected_before_seeding():
    plan = _plan(2)
    _entities(plan)[1]["row_id"] = "ass_0"
    with pytest.raises(ValueError, match="unique"):
        seed_mapping_matrix(_fields(1), plan)


def test_batch_omits_only_uniquely_bound_proposals_for_other_chunks():
    plan = _plan(3)
    fields = {"assay": [
        {"field_name": "attribute 0", "entity_id": entity_id, "value": entity_id}
        for entity_id in ("ass_0", "SOURCE_ass_1", "unknown", "sam_0")
    ]}
    batches = plan_mapping_batches(fields, plan, max_entities=1)
    assert [field["entity_id"] for field in batches[0]["fields_by_level"]["assay"]] == [
        "ass_0", "unknown", "sam_0",
    ]
    assert [field["entity_id"] for field in batches[1]["fields_by_level"]["assay"]] == [
        "SOURCE_ass_1", "unknown", "sam_0",
    ]
    assert "attribute 0" in batches[2]["field_names"]


def test_malformed_duplicate_cannot_leave_another_row_as_winner():
    plan, fields, batch = _single_batch()
    matrix = seed_mapping_matrix(fields, plan)
    issues = merge_mapping_batch(matrix, {"assay": {"rows": [
        {"assay identifier": "ass_0", "attribute 0": "first"},
        {"assay identifier": "SOURCE_ass_0", "attribute 0": "second", " ATTRIBUTE 0 ": "third"},
        {"assay identifier": "ass_1"},
    ]}}, batch, plan)
    assert any("duplicate" in issue.lower() for issue in issues)
    assert matrix["assay"]["rows"][0]["attribute 0"] == ""


def test_row_id_echo_binds_a_row_whose_identifiers_are_model_labels():
    """The prompt asks for the canonical row_id; an invented ISA label claims nothing."""
    plan, fields, batch = _single_batch()
    matrix = seed_mapping_matrix(fields, plan)
    issues = merge_mapping_batch(matrix, {"assay": {"rows": [
        {"row_id": "ass_0", "assay identifier": "assay_013",
         "sample identifier": "sample_007", "attribute 0": "7.3 s^-1"},
        {"row_id": "ass_1", "assay identifier": "ass_0", "attribute 0": "conflict"},
    ]}}, batch, plan)
    assert matrix["assay"]["rows"][0]["attribute 0"] == "7.3 s^-1"
    assert matrix["assay"]["rows"][1]["attribute 0"] == ""   # row_id vs a known other id
    assert "Conflicting row_id and identifier in assay batch row" in issues
    assert not any(issue.startswith("Unrequested") for issue in issues)
