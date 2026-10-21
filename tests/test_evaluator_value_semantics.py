"""Generic regression checks for units and document-local ISA identifiers."""

from copy import deepcopy

import pytest

from evaluation.evaluators import _value_matching as matching
from evaluation.evaluators.structural_evaluator import StructuralEvaluator
from evaluation.evaluators.value_accuracy_evaluator import ValueAccuracyEvaluator


@pytest.fixture(autouse=True)
def offline_similarity(monkeypatch):
    monkeypatch.setattr(matching, "_ST_DISABLED", True)


@pytest.mark.parametrize("pred, gt", [
    ("1 mM", "1 M"), ("1 mL", "1 L"), ("1 U/mg", "1 U/g"),
    ("1 m", "1 M"), ("1", "1 mg"), ("1 widget", "1 gadget"),
    ("1 to 20 mg", "1 to 200 mg"),
])
def test_numeric_match_does_not_discard_units_or_later_numbers(pred, gt):
    assert matching.numeric_tolerance_match(pred, gt) == 0.0


@pytest.mark.parametrize("pred, gt", [
    ("1000 mM", "1 M"), ("1000 mL", "1 L"),
    ("1 U/mg", "1000 U/g"), ("1 mg mL^-1", "1 g/L"),
    ("1 µM", "1 uM"), ("1 widget", "1 widget"),
])
def test_equivalent_quantities_match(pred, gt):
    assert matching.numeric_tolerance_match(pred, gt) == 1.0


def test_repeated_tokens_match_themselves():
    assert matching.token_f1("enzyme enzyme activity", "enzyme enzyme activity") == (1, 1, 1)
    assert matching.token_f1("enzyme", "enzyme enzyme")[2] < 1


def test_standalone_unit_symbols_preserve_case():
    assert matching.match_value("m", "M", field_name="measurement unit") == 0
    assert matching.match_value("µM", "uM", field_name="measurement unit") == 1


def test_missing_identifier_has_no_containment_credit():
    assert matching.identifier_match("", "ABC123") == 0


def test_unknown_compound_units_require_same_expression():
    assert matching.numeric_tolerance_match("1 mg tissue", "0.001 g tissue") == 0


def test_partial_gt_does_not_invent_missing_entity_definitions():
    gt = {"isa_sheets": {"sample": {"expected_rows": [{"sample name": "alpha", "study identifier": "external-study"}]}}}
    pred = {"isa_values": {"sample": {"columns": ["sample name", "study identifier"], "rows": [["alpha", "external-study"]]}}}
    assert _scores(gt, pred) == (1, 1, 1)


def _documents():
    sheets = {
        "sample": [
            {"sample identifier": "S1", "sample name": "alpha", "accession": "AB123"},
            {"sample identifier": "S2", "sample name": "beta", "accession": "CD456"},
        ],
        "observationunit": [
            {"observation unit identifier": "O1", "observation unit name": "vessel alpha", "enzyme material identifier": "S1"},
            {"observation unit identifier": "O2", "observation unit name": "vessel beta", "substrate material identifier": "S2"},
        ],
        "assay": [
            {"assay identifier": "A1", "assay name": "growth assay alpha", "sample identifier": "S1", "observation unit identifier": "O1", "result material identifier": "S1", "measurement value": "40", "study doi": "10.1234/alpha"},
            {"assay identifier": "A2", "assay name": "growth assay beta", "sample identifier": "S2", "observation unit identifier": "O2", "result material identifier": "S2", "measurement value": "50", "study doi": "10.1234/beta"},
        ],
    }
    gt = {"isa_sheets": {s: {"expected_rows": r} for s, r in sheets.items()}}
    pred = {"isa_values": {s: {"columns": list({k for row in r for k in row}), "rows": deepcopy(r)} for s, r in sheets.items()}}
    return gt, pred


def _scores(gt, pred):
    value = ValueAccuracyEvaluator().evaluate(pred, gt)["summary_metrics"]["value_mean_score"]
    structural = StructuralEvaluator().evaluate(pred, gt)["summary_metrics"]
    return value, structural["row_alignment_f1"], structural["value_accuracy_given_correct_structure"]


def test_renaming_all_local_ids_and_reordering_rows_preserves_scores():
    gt, pred = _documents()
    original = _scores(gt, pred)
    mapping = {key: f"local-{i}" for i, key in enumerate(["S1", "S2", "O1", "O2", "A1", "A2"])}
    for sheet in pred["isa_values"].values():
        sheet["rows"].reverse()
        for row in sheet["rows"]:
            for field, value in row.items():
                row[field] = mapping.get(value, value)
    assert original == (1, 1, 1)
    assert _scores(gt, pred) == original


@pytest.mark.parametrize("failure", ["duplicate", "broken", "swapped", "alias"])
def test_invalid_entity_links_remain_penalized(failure):
    gt, pred = _documents()
    if failure == "duplicate":
        pred["isa_values"]["sample"]["rows"][1]["sample identifier"] = "S1"
    elif failure == "alias":
        pred["isa_values"]["observationunit"]["rows"][0]["enzyme material identifier"] = "S2"
    else:
        pred["isa_values"]["assay"]["rows"][0]["sample identifier"] = "missing" if failure == "broken" else "S2"
    values, rows, _ = _scores(gt, pred)
    assert values < 1
    assert rows < 1


@pytest.mark.parametrize("sheet, field, replacement", [
    ("sample", "accession", "ZZ999"),
    ("assay", "study doi", "10.9876/unrelated"),
])
def test_external_identifiers_are_still_scored(sheet, field, replacement):
    gt, pred = _documents()
    pred["isa_values"][sheet]["rows"][0][field] = replacement
    assert _scores(gt, pred)[0] < 1


def test_ids_alone_cannot_prove_entity_alignment():
    gt = {"isa_sheets": {"sample": {"expected_rows": [{"sample identifier": "S1"}]}}}
    pred = {"isa_values": {"sample": {"columns": ["sample identifier"], "rows": [["S1"]]}}}
    values, rows, _ = _scores(gt, pred)
    assert values < 1
    assert rows == 0


def test_equal_content_rows_use_aligned_parent_links_to_break_ties():
    gt, pred = _documents()
    for row in gt["isa_sheets"]["assay"]["expected_rows"]:
        row["assay name"] = "growth"
        row["measurement value"] = "40"
        row["study doi"] = "10.1234/shared"
    pred["isa_values"]["assay"]["rows"] = deepcopy(gt["isa_sheets"]["assay"]["expected_rows"])[::-1]
    for row in pred["isa_values"]["assay"]["rows"]:
        row["assay identifier"] = "renamed-" + row["assay identifier"]
    assert _scores(gt, pred) == (1, 1, 1)


@pytest.mark.parametrize("value, unit, expected", [("1", "M", 0), ("1000", "mM", 1)])
def test_separate_measurement_value_and_unit_are_scored_as_a_quantity(value, unit, expected):
    gt = {"isa_sheets": {"assay": {"expected_rows": [{"measurement value": "1", "measurement unit": "mM" if expected == 0 else "M"}]}}}
    pred = {"isa_values": {"assay": {"columns": ["measurement value", "measurement unit"], "rows": [[value, unit]]}}}
    assert _scores(gt, pred)[0] == expected


def test_incoming_assay_links_disambiguate_identical_samples():
    gt, pred = _documents()
    for document_rows in (gt["isa_sheets"]["sample"]["expected_rows"], pred["isa_values"]["sample"]["rows"]):
        for row in document_rows:
            row["sample name"] = "same material"
            row["accession"] = "AB123"
    pred["isa_values"]["sample"]["rows"].reverse()
    assert _scores(gt, pred) == (1, 1, 1)


def test_cyclic_links_disambiguate_content_ties_without_using_id_text():
    rows = {
        "sample": [{"sample identifier": f"S{i}", "sample name": "same enzyme", "observation unit identifier": f"O{i}"} for i in range(3)],
        "observationunit": [{"observation unit identifier": f"O{i}", "observation unit name": "same vessel", "sample identifier": f"S{(i + 1) % 3}"} for i in range(3)],
    }
    gt = {"isa_sheets": {sheet: {"expected_rows": data} for sheet, data in rows.items()}}
    pred = {"isa_values": {sheet: {"columns": list(data[0]), "rows": deepcopy(data)} for sheet, data in rows.items()}}
    pred["isa_values"]["sample"]["rows"].reverse()
    assert _scores(gt, pred) == (1, 1, 1)


def test_sheet_entrypoint_has_the_same_local_id_semantics():
    result = ValueAccuracyEvaluator().evaluate_sheet(
        "sample", [{"sample identifier": "s1", "sample name": "alpha"}],
        [{"sample identifier": "xyz", "sample name": "alpha"}],
    )
    assert result["mean_score"] == 1


@pytest.mark.parametrize("adapter", ["matrix", "fields", "metadata_fields"])
def test_null_values_are_absent_in_all_input_forms(adapter):
    gt = {"isa_sheets": {"sample": {"expected_rows": [{"sample name": "alpha", "notes": None}]}}}
    fields = [{"field_name": "sample name", "value": "alpha", "isa_sheet": "sample"}, {"field_name": "notes", "value": None, "isa_sheet": "sample"}]
    if adapter == "matrix":
        pred = {"isa_values": {"sample": {"columns": ["sample name", "notes"], "rows": [["alpha", None]]}}}
    elif adapter == "fields":
        pred = {"isa_structure": {"sample": {"fields": fields}}}
    else:
        pred = {"metadata_fields": fields}
    result = ValueAccuracyEvaluator().evaluate(pred, gt)
    assert result["summary_metrics"]["n_gt_populated_fields"] == 1
    assert _scores(gt, pred) == (1, 1, 1)
    assert "notes" not in ValueAccuracyEvaluator().load_pred_sheets(pred)["sample"][0]


@pytest.mark.parametrize("prefix", ["doi:", "DOI: ", "https://doi.org/"])
def test_external_doi_in_primary_identifier_is_not_renamed(prefix):
    gt = {"isa_sheets": {"study": {"expected_rows": [{"study identifier": prefix + "10.1234/alpha", "study title": "same title"}]}}}
    pred = {"isa_values": {"study": {"columns": ["study identifier", "study title"], "rows": [[prefix + "10.9876/wrong", "same title"]]}}}
    assert _scores(gt, pred)[0] < 1


def test_structural_sheet_entrypoint_penalizes_duplicate_ids():
    gt = [{"sample identifier": "s1", "sample name": "alpha"}, {"sample identifier": "s2", "sample name": "beta"}]
    pred = [{"sample identifier": "same", "sample name": "alpha"}, {"sample identifier": "same", "sample name": "beta"}]
    assert StructuralEvaluator().evaluate_row_alignment("sample", gt, pred)["row_alignment_f1"] < 1


@pytest.mark.parametrize("failure", ["missing_study", "wrong_study", "broken_link", "wrong_link"])
def test_unrelated_errors_do_not_change_tie_scores_when_rows_are_reordered(failure):
    rows = {
        "sample": [{"sample identifier": f"S{i}", "sample name": "same material"} for i in range(2)],
        "assay": [{"assay identifier": f"A{i}", "assay name": name, "sample identifier": f"S{i}"} for i, name in enumerate(["alpha", "beta"])],
    }
    predicted = deepcopy(rows)
    if failure.endswith("study"):
        rows["study"] = [{"study identifier": "T1", "study title": "gamma"}]
        if failure == "wrong_study":
            predicted["study"] = [{"study identifier": "X1", "study title": "delta"}]
    else:
        extra = {"assay identifier": "A2", "assay name": "gamma", "sample identifier": "S0"}
        rows["assay"].append(extra)
        predicted["assay"].append({**extra, "sample identifier": "missing" if failure == "broken_link" else "S1"})
    gt = {"isa_sheets": {sheet: {"expected_rows": data} for sheet, data in rows.items()}}
    pred = {"isa_values": {sheet: {"columns": list(data[0]), "rows": data} for sheet, data in predicted.items()}}
    before = _scores(gt, pred)
    pred["isa_values"]["sample"]["rows"].reverse()
    assert _scores(gt, pred) == before
    assert before[0] < 1
    if failure.endswith("link"):
        assert before[1] < 1


@pytest.mark.parametrize("pred, gt", [("1 pM", "0 pM"), ("0.5 ng", "0 ng"), ("1e-12", "0")])
def test_nonzero_quantities_never_match_zero_without_absolute_tolerance(pred, gt):
    assert matching.numeric_tolerance_match(pred, gt) == 0


@pytest.mark.parametrize("pred, gt", [("1 ug^-1000", "1 ug^-999"), ("1e400 M", "1 M"), ("1 ug^1000", "0 ug^999")])
def test_unrepresentable_numeric_quantities_do_not_crash_or_match(pred, gt):
    assert matching.numeric_tolerance_match(pred, gt) == 0


@pytest.mark.parametrize("scope", ["sheet", "global"])
def test_explicit_identifier_override_precedes_automatic_local_id_scoring(scope):
    gt = {"isa_sheets": {"sample": {"expected_rows": [{"sample identifier": "S1", "sample name": "alpha"}]}}}
    override = {"sample identifier": "categorical"}
    if scope == "sheet":
        gt["isa_sheets"]["sample"]["match_type_overrides"] = override
    evaluator = ValueAccuracyEvaluator(override if scope == "global" else None)
    pred = {"isa_values": {"sample": {"columns": ["sample identifier", "sample name"], "rows": [["S2", "alpha"]]}}}
    assert evaluator.evaluate(pred, gt)["summary_metrics"]["value_mean_score"] == 0.5
    structure = StructuralEvaluator(evaluator).evaluate(pred, gt)["summary_metrics"]
    assert structure["row_alignment_f1"] == 1
    assert structure["value_accuracy_given_correct_structure"] == 0.5


def test_tie_reassignment_keeps_identifier_mapping_one_to_one():
    rows = {
        "sample": [{"sample identifier": "S1", "sample name": "same material"}],
        "assay": [{"assay identifier": f"A{i}", "assay name": name, "sample identifier": "S1"} for i, name in enumerate(["alpha", "beta", "gamma"])],
    }
    gt = {"isa_sheets": {sheet: {"expected_rows": data} for sheet, data in rows.items()}}
    pred = {"isa_values": {sheet: {"columns": list(data[0]), "rows": deepcopy(data)} for sheet, data in rows.items()}}
    pred["isa_values"]["sample"]["rows"] = [{"sample identifier": key, "sample name": "same material"} for key in ["X1", "X2"]]
    for i, row in enumerate(pred["isa_values"]["assay"]["rows"]):
        row["sample identifier"] = "X2" if i < 2 else "X1"
    assert _scores(gt, pred)[0] < 1
