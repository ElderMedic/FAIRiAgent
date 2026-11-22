"""Record-level resolution of partially populated per-record ISA columns."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest

from fairifier.utils.record_value_resolution import (
    apply_resolutions,
    build_record_payloads,
    build_source_context,
    collect_candidates,
    find_partial_columns,
    record_group_values,
)

DOCUMENT = (
    "All libraries of the time course series were prepared with MethodA. "
    "For the dilution comparison we used either the KitX Ultra Low Input kit "
    "or the KitY Pico system; library names start with the kit name."
)


def _assay(row_id, identifier, group, extra=()):
    return {
        "row_id": row_id,
        "label": identifier,
        "parent_row_id": None,
        "external_identifier": identifier,
        "source_group": group,
        "attributes": [
            {"dimension_name": "run", "field_name": "run number", "value": f"R{row_id}"},
            *extra,
        ],
    }


PLAN = {
    "levels": [
        {
            "level": "assay",
            "entities": [
                _assay("a1", "ts_1", "time_course_series"),
                _assay("a2", "ts_2", "time_course_series"),
                _assay("a3", "kitx.5ng", "dilution_series"),
                _assay("a4", "kity.5ng", "dilution_series"),
            ],
        }
    ]
}

FIELDS = {
    "assay": [
        {"field_name": "protocol", "value": "MethodA", "confidence": 0.9,
         "evidence": "time course libraries were prepared with MethodA"},
        {"field_name": "facility", "value": "Core", "confidence": 0.9},
        {"field_name": "run number", "value": "", "confidence": 0.9},
        {"field_name": "assay identifier", "value": "", "confidence": 0.9},
    ]
}


def _matrix(protocols=("MethodA", "", "", "")):
    return {
        "assay": {
            "columns": ["assay identifier", "protocol", "facility", "run number"],
            "rows": [
                {
                    "assay identifier": identifier,
                    "protocol": protocol,
                    "facility": "Core" if index == 0 else "",
                    "run number": f"Ra{index + 1}",
                }
                for index, (identifier, protocol) in enumerate(
                    zip(["ts_1", "ts_2", "kitx.5ng", "kity.5ng"], protocols)
                )
            ],
        }
    }


def _resolve(matrix, decisions, columns=("protocol",)):
    rows = matrix["assay"]["rows"]
    columns = list(columns)
    candidates = {c: collect_candidates(rows, c, FIELDS["assay"]) for c in columns}
    records = build_record_payloads("assay", PLAN, rows, columns)
    context = build_source_context(
        "assay", columns, candidates, FIELDS["assay"], PLAN, DOCUMENT,
        group_values=record_group_values(records),
    )
    response = {
        "records": [
            {"record_id": record_id, "values": {"protocol": decision}}
            for record_id, decision in decisions.items()
        ]
    }
    return apply_resolutions(
        "assay", rows, records, columns, candidates, [response], context, DOCUMENT
    )


def _supported(value, attribute, quote):
    return {
        "value": value,
        "status": "supported",
        "record_attribute": attribute,
        "source_quote": quote,
    }


@pytest.mark.parametrize("value", ["0.30 ± 0.04", "13", "-0.07", "<0.1", "2.5e-3"])
def test_new_numeric_result_requires_own_record_quote(value):
    quote = f"Specimen alpha had a reported response of {value}."
    rows = [{"response": ""}]
    records = [{"record_id": "a1", "identifier": "alpha", "source_group": "study"}]
    apply_resolutions(
        "assay", rows, records, ["response"], {"response": []},
        [{"records": [{"record_id": "a1", "values": {
            "response": _supported(value, "identifier=alpha", quote),
        }}]}], "", quote,
    )
    assert rows[0]["response"] == value


@pytest.mark.parametrize(("value", "reported", "material"), [
    ("3", "13", "alpha"), ("0.07", "-0.07", "alpha"),
    ("0.1", "<0.1", "alpha"), ("0.30", "0.30 ± 0.04", "alpha"),
    ("0.04", "0.30 ± 0.04", "alpha"), ("2.5", "2.5e-3", "alpha"),
    ("13", "13", "beta"),
])
def test_new_numeric_result_cannot_drop_qualifiers_or_use_another_record(value, reported, material):
    quote = f"Specimen {material} had a reported response of {reported}."
    rows = [{"response": ""}]
    records = [{"record_id": "a1", "identifier": "alpha", "source_group": "study"}]
    apply_resolutions(
        "assay", rows, records, ["response"], {"response": []},
        [{"records": [{"record_id": "a1", "values": {
            "response": _supported(value, "identifier=alpha", quote),
        }}]}], "", quote,
    )
    assert rows[0]["response"] == ""


@pytest.mark.parametrize("filled,candidate", [
    (False, "fluorometry"), (True, "fluorometry"), (False, "fluorescence"),
])
@pytest.mark.parametrize("status", ["provisional", "confirmed"])
def test_source_reviewed_vocabulary_survives_later_literal_and_column_checks(filled, status, candidate):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    plan = {"levels": [{"level": "assay", "entities": [
        _assay("a1", "measurement_A", "series_A"),
        _assay("a2", "measurement_B", "series_B"),
    ]}]}
    matrix = {"assay": {
        "columns": ["assay identifier", "signal mode"],
        "rows": [
            {"assay identifier": "measurement_A", "signal mode": candidate if filled else ""},
            {"assay identifier": "measurement_B", "signal mode": candidate if filled else ""},
        ],
    }}
    fields = {"assay": [{
        "field_name": "signal mode", "value": candidate, "status": status,
        "confidence": 0.8, "requirement": "OPTIONAL",
        "evidence": "For measurement_A, fluorescence was recorded at 425 nm.",
    }]}
    document = "For measurement_A, fluorescence was recorded at 425 nm. No method was given for measurement_B."
    response = {"records": [
        {"record_id": "a1", "values": {"signal mode": _supported(
            candidate, "identifier=measurement_A",
            "For measurement_A, fluorescence was recorded at 425 nm.",
        )}},
        {"record_id": "a2", "values": {"signal mode": {
            "status": "unsupported", "value": "",
        }}},
    ]}
    agent = ISAValueMapperAgent.__new__(ISAValueMapperAgent)
    agent.logger = Mock()
    llm = Mock(); llm._call_llm = AsyncMock(return_value=SimpleNamespace(
        content=json.dumps(response), response_metadata={"finish_reason": "stop"},
    ))
    agent._get_llm = Mock(return_value=llm)
    verified = {}
    matrix, _ = asyncio.run(agent._resolve_partial_record_values(
        matrix, fields, plan, document, {}, verified_cells=verified,
    ))
    llm._call_llm.assert_awaited_once()
    matrix, _ = ISAValueMapperAgent._clear_unverified_provisional_values(
        matrix, fields, plan, document, verified_cells=verified,
    )
    matrix, removed = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix, fields, plan, source_text=document, verified_cells=verified,
    )
    assert removed == {}
    assert [row["signal mode"] for row in matrix["assay"]["rows"]] == [candidate, ""]
    assert set(verified["assay"]) == {(0, "signal mode")}
    assert all(set(row) == {"assay identifier", "signal mode"} for row in matrix["assay"]["rows"])


def test_verified_record_value_cannot_authorize_another_cell_or_replacement():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {"assay": {"columns": ["signal mode"], "rows": [
        {"signal mode": "chromatography"}, {"signal mode": "fluorometry"},
    ]}}
    fields = {"assay": [{"field_name": "signal mode", "status": "provisional", "requirement": "OPTIONAL"}]}
    verified = {"assay": {(0, "signal mode"): "fluorometry"}}
    matrix, issues = ISAValueMapperAgent._clear_unverified_provisional_values(
        matrix, fields, {}, "A source passage.", verified_cells=verified,
    )
    assert [row["signal mode"] for row in matrix["assay"]["rows"]] == ["", ""]
    assert len(issues) == 2


@pytest.mark.parametrize("fault", ["invented_quote", "wrong_record", "conflicting_value"])
def test_rejected_record_decisions_never_produce_verification_receipts(fault):
    matrix = _matrix()
    rows = matrix["assay"]["rows"]
    records = build_record_payloads("assay", PLAN, rows, ["protocol"])
    decision = _supported(
        "MethodA", "identifier=ts_2",
        "All libraries of the time course series were prepared with MethodA.",
    )
    if fault == "invented_quote":
        decision["source_quote"] = "This quotation does not occur in the document."
    elif fault == "wrong_record":
        decision["record_attribute"] = "identifier=another_record"
    items = [{"record_id": "a2", "values": {"protocol": decision}}]
    if fault == "conflicting_value":
        items.append({"record_id": "a2", "values": {"protocol": {
            **decision, "value": "MethodB",
        }}})
    verified = {(1, "protocol"): "stale value"}
    _, stats = apply_resolutions(
        "assay", rows, records, ["protocol"], {"protocol": ["MethodA", "MethodB"]},
        [{"records": items}], "", DOCUMENT, verified_cells=verified,
    )
    assert verified == {}
    assert stats["rejected"] >= 1
    assert rows[1]["protocol"] == ""


def test_reviewed_vocabulary_retains_declared_canonical_casing():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {"assay": {"columns": ["signal mode"], "rows": [
        {"signal mode": "fluorometry"}, {"signal mode": "fluorometry"},
    ]}}
    fields = {"assay": [{"field_name": "signal mode", "requirement": "OPTIONAL"}]}
    verified = {"assay": {(0, "signal mode"): "FLUOROMETRY", (1, "signal mode"): "FLUOROMETRY"}}
    contract = {("assay", "signal mode"): {"pattern": "^(fluorometry|absorbance)$"}}
    matrix, removed = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix, fields, {}, source_text="Source uses a different term.",
        verified_cells=verified, value_contracts=contract,
    )
    assert removed == {}
    assert matrix["assay"]["columns"] == ["signal mode"]


def _apply_items(matrix, items, *, document_text=DOCUMENT, source_context="", candidates=None):
    rows = matrix["assay"]["rows"]
    records = build_record_payloads("assay", PLAN, rows, ["protocol"])
    return apply_resolutions(
        "assay", rows, records, ["protocol"],
        {"protocol": ["MethodA"]} if candidates is None else candidates,
        [{"records": items}], source_context, document_text,
    )


@pytest.mark.parametrize("origin", ["extracted protocol evidence", "design group series"])
def test_generated_context_cannot_authorize_a_quote(origin):
    matrix = _matrix()
    invented_quote = "The ts_2 library was prepared with MethodA"
    _, stats = _apply_items(
        matrix,
        [{"record_id": "a2", "values": {
            "protocol": _supported("MethodA", "ts_2", invented_quote),
        }}],
        source_context=f"[{origin}] {invented_quote}",
    )
    assert matrix["assay"]["rows"][1]["protocol"] == ""
    assert stats["rejected"] == 1


def test_generated_context_cannot_authorize_a_new_value():
    matrix = _matrix()
    _, stats = _apply_items(
        matrix,
        [{"record_id": "a2", "values": {
            "protocol": _supported(
                "MethodB", "ts_2",
                "All libraries of the time course series were prepared with MethodA",
            ),
        }}],
        source_context="[extracted protocol evidence] The ts_2 library used MethodB.",
    )
    assert matrix["assay"]["rows"][1]["protocol"] == ""
    assert stats["rejected"] == 1


@pytest.mark.parametrize("status", ["unsupported", "contradicted"])
def test_non_supported_status_never_writes_a_nonblank_value(status):
    matrix = _matrix()
    decision = _supported(
        "MethodA", "source_group=time_course_series",
        "All libraries of the time course series were prepared with MethodA",
    )
    decision["status"] = status
    _, stats = _apply_items(
        matrix, [{"record_id": "a2", "values": {"protocol": decision}}],
    )
    assert matrix["assay"]["rows"][1]["protocol"] == ""
    assert stats["filled"] == 0


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("current", ["", "KitY Pico system"])
def test_conflicting_cell_decisions_with_different_attributes_are_rejected(reverse, current):
    matrix = _matrix(protocols=("MethodA", "", current, ""))
    items = [
        {"record_id": "a3", "values": {"protocol": _supported(
            "KitX Ultra Low Input kit", "identifier=kitx.5ng",
            "library names start with the kit name",
        )}},
        {"record_id": "a3", "values": {"protocol": _supported(
            "KitY Pico system", "source_group=dilution_series",
            "For the dilution comparison we used either the KitX Ultra Low Input kit",
        )}},
    ]
    if reverse:
        items.reverse()
    issues, stats = _apply_items(matrix, items)
    assert matrix["assay"]["rows"][2]["protocol"] == current
    assert stats["rejected"] == 2
    assert stats["filled"] == stats["replaced"] == stats["cleared"] == 0
    if current:
        assert any(
            "conflicting" in issue.lower()
            and "assay.protocol" in issue
            and "kitx.5ng" in issue
            for issue in issues
        )


def test_reordered_rows_resolve_by_unique_identifier():
    matrix = _matrix()
    matrix["assay"]["rows"].reverse()
    _, stats = _resolve(matrix, {
        "a2": _supported(
            "MethodA", "source_group=time_course_series",
            "All libraries of the time course series were prepared with MethodA",
        ),
    })
    rows = {row["assay identifier"]: row for row in matrix["assay"]["rows"]}
    assert rows["ts_2"]["protocol"] == "MethodA"
    assert rows["kitx.5ng"]["protocol"] == ""
    assert stats["filled"] == 1


@pytest.mark.parametrize("invalid_identifier", ["unknown_record", "ts_1", ""])
def test_partial_columns_require_unambiguous_row_identity(invalid_identifier):
    matrix = _matrix()
    matrix["assay"]["rows"][1]["assay identifier"] = invalid_identifier
    assert find_partial_columns(matrix, PLAN, FIELDS) == {}


def test_duplicate_plan_identifiers_do_not_authorize_resolution():
    plan = deepcopy(PLAN)
    plan["levels"][0]["entities"][1]["external_identifier"] = "ts_1"
    assert find_partial_columns(_matrix(), plan, FIELDS) == {}


def test_distinct_internal_ids_resolve_despite_shared_external_aliases():
    plan = deepcopy(PLAN)
    matrix = _matrix()
    matrix["assay"]["_shared_columns"] = ["facility"]
    for index in (0, 1):
        plan["levels"][0]["entities"][index]["external_identifier"] = "shared_library"
        matrix["assay"]["rows"][index]["assay identifier"] = f"a{index + 1}"
    matrix["assay"]["rows"].reverse()
    assert find_partial_columns(matrix, plan, FIELDS) == {"assay": ["protocol"]}
    rows = matrix["assay"]["rows"]
    records = build_record_payloads("assay", plan, rows, ["protocol"])
    assert [record["record_id"] for record in records] == ["a4", "a3", "a2", "a1"]
    _, stats = apply_resolutions(
        "assay", rows, records, ["protocol"], {"protocol": ["MethodA"]},
        [{"records": [{"record_id": "a2", "values": {"protocol": _supported(
            "MethodA", "source_group=time_course_series",
            "All libraries of the time course series were prepared with MethodA",
        )}}]}], "", DOCUMENT,
    )
    values = {row["assay identifier"]: row["protocol"] for row in rows}
    assert values == {"a1": "MethodA", "a2": "MethodA", "kitx.5ng": "", "kity.5ng": ""}
    assert stats["filled"] == 1


def test_shared_external_row_ids_remain_ambiguous():
    plan = deepcopy(PLAN)
    matrix = _matrix()
    for index in (0, 1):
        plan["levels"][0]["entities"][index]["external_identifier"] = "shared_library"
        matrix["assay"]["rows"][index]["assay identifier"] = "shared_library"
    assert find_partial_columns(matrix, plan, FIELDS) == {}
    assert build_record_payloads("assay", plan, matrix["assay"]["rows"], ["protocol"]) == []


def test_numeric_zero_marks_a_column_as_partially_filled():
    matrix = _matrix(protocols=(0, "", "", ""))
    matrix["assay"]["_shared_columns"] = ["facility"]
    assert find_partial_columns(matrix, PLAN, FIELDS) == {"assay": ["protocol"]}


@pytest.mark.parametrize("from_field", [False, True])
def test_numeric_zero_is_retained_as_a_candidate(from_field):
    rows = [] if from_field else [{"protocol": 0}]
    fields = [{"field_name": "protocol", "value": 0, "confidence": 0.9}] if from_field else []
    assert collect_candidates(rows, "protocol", fields) == ["0"]


def test_numeric_zero_is_retained_in_record_payloads():
    plan = deepcopy(PLAN)
    plan["levels"][0]["entities"][0]["attributes"].append({
        "dimension_name": "dose", "field_name": "dose", "value": 0,
    })
    records = build_record_payloads(
        "assay", plan, _matrix(protocols=(0, "", "", ""))["assay"]["rows"], ["protocol"],
    )
    assert records[0]["current"]["protocol"] == "0"
    assert "dose=0" in records[0]["attributes"]


def test_supported_numeric_zero_is_written():
    matrix = _matrix()
    document = "The protocol code for ts_2 was 0."
    _, stats = _apply_items(
        matrix, [{"record_id": "a2", "values": {
            "protocol": _supported(0, "ts_2", document),
        }}],
        document_text=document, candidates={"protocol": ["0"]},
    )
    assert matrix["assay"]["rows"][1]["protocol"] == "0"
    assert stats["filled"] == 1


@pytest.mark.parametrize(("document", "quote"), [
    ("The temperature was -5 C.", "The temperature was 5 C."),
    ("The ratio was 1.5 to 1.", "The ratio was 1 5 to 1."),
])
def test_quote_matching_preserves_scientific_punctuation(document, quote):
    matrix = _matrix()
    _, stats = _apply_items(
        matrix, [{"record_id": "a2", "values": {
            "protocol": _supported("MethodA", "ts_2", quote),
        }}], document_text=document,
    )
    assert matrix["assay"]["rows"][1]["protocol"] == ""
    assert stats["rejected"] == 1


def test_quote_matching_accepts_whitespace_and_typographic_minus_variants():
    matrix = _matrix()
    _, stats = _apply_items(
        matrix, [{"record_id": "a2", "values": {
            "protocol": _supported(
                "MethodA", "ts_2", "The ts_2 library used MethodA at -5 C.",
            ),
        }}], document_text="The ts_2 library\nused MethodA at \u22125 C.",
    )
    assert matrix["assay"]["rows"][1]["protocol"] == "MethodA"
    assert stats["filled"] == 1


@pytest.mark.parametrize(("document", "quote"), [
    ("-5 C was used for sample A.", "5 C was used for sample A."),
    ("+5 C was used for sample A.", "5 C was used for sample A."),
    ("1.5 mg was used for sample A.", "5 mg was used for sample A."),
    ("Sample A was incubated at 5.3 C.", "Sample A was incubated at 5"),
])
def test_quote_boundaries_cannot_split_signed_or_decimal_numbers(document, quote):
    matrix = _matrix()
    _, stats = _apply_items(
        matrix, [{"record_id": "a2", "values": {
            "protocol": _supported("MethodA", "ts_2", quote),
        }}], document_text=document,
    )
    assert matrix["assay"]["rows"][1]["protocol"] == ""
    assert stats["rejected"] == 1


def test_quote_can_end_before_a_sentence_period_after_a_number():
    matrix = _matrix()
    _, stats = _apply_items(
        matrix, [{"record_id": "a2", "values": {
            "protocol": _supported(
                "MethodA", "ts_2", "The ts_2 library used MethodA at pH 5",
            ),
        }}], document_text="The ts_2 library used MethodA at pH 5.",
    )
    assert matrix["assay"]["rows"][1]["protocol"] == "MethodA"
    assert stats["filled"] == 1


@pytest.mark.parametrize(("quoted_unit", "accepted"), [("MM", False), ("mM", True)])
def test_quote_authentication_preserves_unit_case(quoted_unit, accepted):
    matrix = _matrix()
    _, stats = _apply_items(
        matrix, [{"record_id": "a2", "values": {
            "protocol": _supported(
                "MethodA", "ts_2", f"The ts_2 library used MethodA with 5 {quoted_unit} buffer.",
            ),
        }}], document_text="The ts_2 library used MethodA with 5 mM buffer.",
    )
    assert matrix["assay"]["rows"][1]["protocol"] == ("MethodA" if accepted else "")
    assert stats["filled"] == int(accepted)
    assert stats["rejected"] == int(not accepted)


@pytest.mark.parametrize(("document", "quote", "accepted"), [
    (
        "The ts_2 library used MethodA with fragmenta-\ntion before sequencing.",
        "The ts_2 library used MethodA with fragmentation before sequencing.",
        True,
    ),
    (
        r"The ts_2 library used MethodA with 1 $\mu$ mol reagent.",
        "The ts_2 library used MethodA with 1 μmol reagent.",
        True,
    ),
    (
        r"The ts_2 library used MethodA with 1 $\mu$ mol reagent.",
        "The ts_2 library used MethodA with 1 µmol reagent.",
        True,
    ),
    (
        r"The ts_2 library used MethodA with 1 $\mu$ mol reagent.",
        "The ts_2 library used MethodA with 1 mmol reagent.",
        False,
    ),
    (
        r"The ts_2 library used MethodA with 1 $\mu$ M reagent.",
        "The ts_2 library used MethodA with 1 μm reagent.",
        False,
    ),
    (
        "The ts_2 library used MethodA with Sample-\nAB material.",
        "The ts_2 library used MethodA with SampleAB material.",
        False,
    ),
    (
        "The ts_2 library used MethodA with Sample-\nmaterial code.",
        "The ts_2 library used MethodA with Samplematerial code.",
        False,
    ),
    (
        "The ts_2 library used MethodA with fragmenta-tion before sequencing.",
        "The ts_2 library used MethodA with fragmentation before sequencing.",
        False,
    ),
])
def test_quote_authentication_handles_pdf_layout_without_changing_units(
    document, quote, accepted,
):
    matrix = _matrix()
    _, stats = _apply_items(
        matrix, [{"record_id": "a2", "values": {
            "protocol": _supported("MethodA", "ts_2", quote),
        }}], document_text=document,
    )
    assert matrix["assay"]["rows"][1]["protocol"] == ("MethodA" if accepted else "")
    assert stats["filled"] == int(accepted)
    assert stats["rejected"] == int(not accepted)


def test_partial_columns_exclude_identity_plan_owned_and_shared_columns():
    matrix = _matrix()
    matrix["assay"]["_shared_columns"] = ["facility"]
    partial = find_partial_columns(matrix, PLAN, FIELDS)
    # facility is level-wide by declaration, run number is plan-owned, and the
    # identifier is structural: only the row-varying protocol needs judging.
    assert partial == {"assay": ["protocol"]}

    complete = _matrix(protocols=("MethodA",) * 4)
    complete["assay"]["_shared_columns"] = ["facility"]
    assert find_partial_columns(complete, PLAN, FIELDS) == {}


def test_partial_columns_require_rows_aligned_with_plan():
    matrix = _matrix()
    matrix["assay"]["rows"] = matrix["assay"]["rows"][:2]
    assert find_partial_columns(matrix, PLAN, FIELDS) == {}


def test_sibling_filled_only_with_own_record_citation_and_verbatim_quote():
    matrix = _matrix()
    issues, stats = _resolve(
        matrix,
        {
            "a2": _supported(
                "MethodA",
                "source_group=time_course_series",
                "All libraries of the time course series were prepared with MethodA",
            ),
            # Cites an attribute that belongs to a different record.
            "a3": _supported(
                "MethodA",
                "source_group=time_course_series",
                "All libraries of the time course series were prepared with MethodA",
            ),
        },
    )
    rows = matrix["assay"]["rows"]
    assert rows[1]["protocol"] == "MethodA"
    assert rows[2]["protocol"] == ""
    assert stats["filled"] == 1
    assert stats["rejected"] == 1
    assert issues == []


def test_invented_value_and_paraphrased_quote_are_rejected():
    matrix = _matrix()
    _, stats = _resolve(
        matrix,
        {
            "a2": _supported(
                "MethodB", "ts_2",
                "All libraries of the time course series were prepared with MethodA",
            ),
            "a3": _supported(
                "MethodA", "kitx.5ng", "the kitx samples were made using method a",
            ),
        },
    )
    rows = matrix["assay"]["rows"]
    assert rows[1]["protocol"] == "" and rows[2]["protocol"] == ""
    assert stats == {"filled": 0, "replaced": 0, "cleared": 0, "rejected": 2}


def test_literal_source_value_outside_candidates_is_accepted():
    matrix = _matrix()
    _, stats = _resolve(
        matrix,
        {
            "a3": _supported(
                "KitX Ultra Low Input kit",
                "kitx.5ng",
                "library names start with the kit name",
            ),
        },
    )
    assert matrix["assay"]["rows"][2]["protocol"] == "KitX Ultra Low Input kit"
    assert stats["filled"] == 1


def test_non_discriminating_parent_group_never_propagates_and_clears_its_guess():
    # The representative row kity.5ng got its value from the group; the judge
    # cites only the shared group for two different values -> both rejected,
    # and the current value resting on that citation is cleared.
    matrix = _matrix(protocols=("MethodA", "", "", "KitY Pico system"))
    quote = "For the dilution comparison we used either the KitX Ultra Low Input kit"
    issues, stats = _resolve(
        matrix,
        {
            "a3": _supported("KitX Ultra Low Input kit", "source_group=dilution_series", quote),
            "a4": _supported("KitY Pico system", "source_group=dilution_series", quote),
        },
    )
    rows = matrix["assay"]["rows"]
    assert rows[2]["protocol"] == ""
    assert rows[3]["protocol"] == ""
    assert stats["rejected"] == 2 and stats["cleared"] == 1
    assert any("cleared" in issue for issue in issues)


@pytest.mark.parametrize(("first_group", "second_group", "accepted"), [
    ("rna_profile", "metabolite_profile", True),
    ("combined_study", "combined_study", False),
    ("rna_profile", "", False),
    ("rna_profile", "unknown", False),
    ("", "", False),
])
def test_same_donor_can_have_different_protocols_in_distinct_planned_experiments(
    first_group, second_group, accepted,
):
    plan = deepcopy(PLAN)
    for index, group in enumerate([first_group, second_group]):
        entity = plan["levels"][0]["entities"][index]
        entity["source_group"] = group
        entity["attributes"].append({"dimension_name": "donor", "value": "A"})
    rows = _matrix(protocols=("", "", "", ""))["assay"]["rows"]
    records = build_record_payloads("assay", plan, rows, ["protocol"])
    quotes = [
        "RNA profiling of donor A used MethodA.",
        "Metabolite profiling of donor A used MethodB.",
    ]
    response = {"records": [
        {"record_id": f"a{index+1}", "source_group": f"untrusted_group_{index}",
         "values": {"protocol": _supported(method, "donor=A", quote)}}
        for index, (method, quote) in enumerate(zip(["MethodA", "MethodB"], quotes))
    ]}
    _, stats = apply_resolutions(
        "assay", rows, records, ["protocol"],
        {"protocol": ["MethodA", "MethodB"]}, [response], "", " ".join(quotes),
    )
    # Scope comes from the locked plan, never a response-supplied group.
    assert [row["protocol"] for row in rows] == (
        ["MethodA", "MethodB", "", ""] if accepted else ["", "", "", ""]
    )
    assert stats["filled"] == (2 if accepted else 0)
    assert stats["rejected"] == (0 if accepted else 2)


def test_unsupported_current_value_is_cleared_and_undetermined_is_kept():
    matrix = _matrix(protocols=("MethodA", "", "KitY Pico system", ""))
    issues, stats = _resolve(
        matrix,
        {
            "a1": {"value": "", "status": "undetermined"},
            "a3": {"value": "", "status": "unsupported"},
        },
    )
    rows = matrix["assay"]["rows"]
    assert rows[0]["protocol"] == "MethodA"
    assert rows[2]["protocol"] == ""
    assert stats["cleared"] == 1
    assert len(issues) == 1


def test_wrong_representative_value_is_replaced_by_record_evidence():
    matrix = _matrix(protocols=("MethodA", "", "KitY Pico system", ""))
    issues, stats = _resolve(
        matrix,
        {
            "a3": _supported(
                "KitX Ultra Low Input kit", "kitx.5ng", "library names start with the kit name"
            ),
        },
    )
    assert matrix["assay"]["rows"][2]["protocol"] == "KitX Ultra Low Input kit"
    assert stats["replaced"] == 1
    assert "replaced" in issues[0]


def test_source_context_includes_passages_for_group_labels():
    records = build_record_payloads("assay", PLAN, _matrix()["assay"]["rows"], ["protocol"])
    groups = record_group_values(records)
    assert "time_course_series" in groups
    # Unique identifiers are not group labels.
    assert "ts_1" not in groups
    context = build_source_context(
        "assay", ["protocol"], {"protocol": []}, [], PLAN, DOCUMENT, group_values=groups
    )
    assert "time course series were prepared with MethodA" in context


def test_source_context_reserves_original_passages_before_many_generated_hints():
    fields = [
        {"field_name": "protocol", "evidence": f"Proposal {i}: " + "unverified hint " * 40}
        for i in range(50)
    ]
    context = build_source_context(
        "assay", ["protocol"], {"protocol": ["MethodA"]}, fields, {}, DOCUMENT,
    )
    assert context.startswith("[source passage]")
    assert "All libraries of the time course series were prepared with MethodA" in context
    assert len(context) <= 14000


def test_source_context_balances_early_and_late_requested_fields():
    methods = [f"AlphaMethod{i:02d}" for i in range(32)]
    early = "".join(f"The procedure was {method}. " + "Background context. " * 60 for method in methods)
    late = "The final calibration used BetaStandard for detector measurements."
    context = build_source_context(
        "assay", ["protocol", "calibration"],
        {"protocol": methods, "calibration": ["BetaStandard"]},
        [], {}, early + late,
    )
    assert "AlphaMethod" in context
    assert late in context
    assert len(context) <= 14000


class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    async def _call_llm(self, messages, operation_name="", **_kwargs):
        self.prompts.append(messages[-1].content)

        class _Response:
            content = json.dumps(self.payload)

        return _Response()


@pytest.mark.parametrize("response_column", ["protocol", "Protocol"])
def test_agent_pass_queries_every_record_and_writes_only_validated_values(monkeypatch, response_column):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    agent = ISAValueMapperAgent()
    llm = _FakeLLM(
        {
            "records": [
                {
                    "record_id": "a2",
                    "values": {
                        response_column: _supported(
                            "MethodA",
                            "source_group=time_course_series",
                            "All libraries of the time course series were prepared with MethodA",
                        )
                    },
                },
                {
                    "record_id": "a4",
                    "values": {
                        "protocol": _supported("KitY Pico system", "kity.5ng", "not in the source at all")
                    },
                },
            ]
        }
    )
    monkeypatch.setattr(agent, "_get_llm", lambda _state: llm)
    matrix = _matrix(protocols=("MethodA", "", "", ""))
    result, issues = asyncio.run(
        agent._resolve_partial_record_values(
            deepcopy(matrix), FIELDS, PLAN, DOCUMENT, {}
        )
    )
    assert [row["protocol"] for row in result["assay"]["rows"]] == [
        "MethodA", "MethodA", "", ""
    ]
    assert issues == []
    assert len(llm.prompts) == 1
    for identifier in ("ts_1", "ts_2", "kitx.5ng", "kity.5ng"):
        assert identifier in llm.prompts[0]


def test_agent_pass_makes_no_llm_call_without_partial_columns(monkeypatch):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    agent = ISAValueMapperAgent()

    def fail(_state):
        raise AssertionError("no LLM call expected")

    monkeypatch.setattr(agent, "_get_llm", fail)
    matrix = _matrix(protocols=("MethodA",) * 4)
    result, issues = asyncio.run(
        agent._resolve_partial_record_values(matrix, FIELDS, PLAN, DOCUMENT, {})
    )
    assert result is matrix and issues == []


def test_wide_record_review_bounds_each_call_and_visits_every_cell(monkeypatch):
    from fairifier.agents.isa_value_mapper import (
        _REVIEW_CELLS_PER_CALL, _REVIEW_COLUMNS_PER_CALL, ISAValueMapperAgent,
    )
    from fairifier.config import config

    monkeypatch.setattr(config, "record_value_resolution_batch_size", 25)
    monkeypatch.setattr(config, "record_value_resolution_max_records", 0)
    columns = [f"parameter {i}" for i in range(17)]
    entities = [_assay(f"a{i}", f"specimen_{i}", "branch") for i in range(40)]
    plan = {"levels": [{"level": "assay", "entities": entities}]}
    rows = [
        {"assay identifier": e["row_id"], **{column: "MethodA" if i == 0 else "" for column in columns}}
        for i, e in enumerate(entities)
    ]
    matrix = {"assay": {"columns": ["assay identifier", *columns], "rows": rows}}
    fields = {"assay": [{"field_name": column, "value": "MethodA"} for column in columns]}
    visited = []

    class Judge:
        async def _call_llm(self, messages, **kwargs):
            prompt = messages[-1].content
            candidates = json.loads(prompt.split("Columns and candidate values:\n", 1)[1].split("\n\n", 1)[0])
            records = json.loads(prompt.split("\n\nRecords:\n", 1)[1])
            assert len(records) * len(candidates) <= _REVIEW_CELLS_PER_CALL
            assert len(candidates) <= _REVIEW_COLUMNS_PER_CALL
            for record in records:
                assert set(record["current"]) == set(candidates)
                visited.extend((record["record_id"], column) for column in candidates)
            payload = {"records": [
                {"record_id": record["record_id"], "values": {
                    column: {"status": "undetermined", "value": ""} for column in candidates
                }} for record in records
            ]}
            return type("Response", (), {"content": json.dumps(payload)})()

    agent = ISAValueMapperAgent()
    monkeypatch.setattr(agent, "_get_llm", lambda _: Judge())
    result, issues = asyncio.run(agent._resolve_partial_record_values(
        deepcopy(matrix), fields, plan, DOCUMENT, {},
    ))
    expected = {(entity["row_id"], column) for entity in entities for column in columns}
    assert set(visited) == expected
    assert len(visited) == len(expected)
    assert result == matrix
    assert not issues


@pytest.mark.parametrize("reason_key", ["finish_reason", "done_reason"])
def test_truncated_record_review_cannot_clear_existing_values(monkeypatch, reason_key):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    class Judge:
        async def _call_llm(self, *args, **kwargs):
            return type("Response", (), {
                "response_metadata": {reason_key: "length"},
                "content": json.dumps({"records": [{"record_id": "a1", "values": {
                    "protocol": {"status": "unsupported", "value": ""},
                }}]}),
            })()

    agent = ISAValueMapperAgent()
    monkeypatch.setattr(agent, "_get_llm", lambda _: Judge())
    matrix = _matrix()
    result, issues = asyncio.run(agent._resolve_partial_record_values(
        deepcopy(matrix), FIELDS, PLAN, DOCUMENT, {},
    ))
    assert result == matrix
    assert any("truncated" in issue.lower() for issue in issues)


def test_record_review_stops_after_service_failure_and_retains_completed_work(monkeypatch):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.config import config

    monkeypatch.setattr(config, "record_value_resolution_batch_size", 1)
    calls = []

    class Judge:
        async def _call_llm(self, messages, **kwargs):
            calls.append(messages[-1].content)
            if len(calls) > 1:
                raise ConnectionError("service disconnected")
            return type("Response", (), {"content": json.dumps({"records": [{
                "record_id": "a1", "values": {"protocol": _supported(
                    "MethodA", "source_group=time_course_series",
                    "All libraries of the time course series were prepared with MethodA",
                )},
            }]})})()

    agent = ISAValueMapperAgent()
    monkeypatch.setattr(agent, "_get_llm", lambda _: Judge())
    matrix = _matrix(protocols=("KitY Pico system", "", "", ""))
    result, issues = asyncio.run(agent._resolve_partial_record_values(
        matrix, FIELDS, PLAN, DOCUMENT, {},
    ))
    assert len(calls) == 2
    assert result["assay"]["rows"][0]["protocol"] == "MethodA"
    assert any("service failure" in issue.lower() for issue in issues)


def test_record_review_ignores_decisions_outside_current_batch(monkeypatch):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.config import config

    monkeypatch.setattr(config, "record_value_resolution_batch_size", 1)
    calls = []

    class Judge:
        async def _call_llm(self, messages, **kwargs):
            calls.append(messages[-1].content)
            records = [] if len(calls) > 1 else [
                {"record_id": "a2", "values": {"protocol": {"status": "unsupported", "value": ""}}},
                {"record_id": "a1", "values": {"facility": {"status": "unsupported", "value": ""}}},
            ]
            return type("Response", (), {"content": json.dumps({"records": records})})()

    matrix = _matrix(protocols=("", "MethodA", "", ""))
    for row in matrix["assay"]["rows"]:
        row["facility"] = "Core"
    agent = ISAValueMapperAgent()
    monkeypatch.setattr(agent, "_get_llm", lambda _: Judge())
    result, issues = asyncio.run(agent._resolve_partial_record_values(
        deepcopy(matrix), FIELDS, PLAN, DOCUMENT, {},
    ))
    assert result == matrix
    assert len(issues) == 2
    assert all("out-of-scope" in issue.lower() for issue in issues)


def test_pivoted_table_value_is_citable_from_derived_header_labelled_row():
    """The enzyme name lives only in the column header of a pivoted table."""
    from fairifier.services.publication_tables import with_derived_table_rows

    source = with_derived_table_rows(
        "Table 2 Kinetic parameters.\n"
        "<table><tr><td rowspan=\"2\">Substrates</td><td colspan=\"2\">Km (mM)</td></tr>"
        "<tr><td>EnzA</td><td>EnzB</td></tr>"
        "<tr><td>BHET</td><td>16.78 ± 2.95</td><td>25.82 ± 2.31</td></tr></table>"
    )
    quote = "Substrates = BHET; Km (mM) | EnzA = 16.78 ± 2.95"
    assert quote in source
    rows = [{"response": ""}]
    records = [{"record_id": "a1", "identifier": "a1", "source_group": "kinetics",
                "attributes": ["enzyme=EnzA", "substrate=BHET"]}]
    apply_resolutions(
        "assay", rows, records, ["response"], {"response": []},
        [{"records": [{"record_id": "a1", "values": {
            "response": _supported("16.78 ± 2.95", "enzyme=EnzA", quote),
        }}]}], "", source,
    )
    assert rows[0]["response"] == "16.78 ± 2.95"


def test_concurrent_record_review_matches_serial_result(monkeypatch):
    """Concurrent calls finishing out of order give the serial outcome."""
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.config import config

    monkeypatch.setattr(config, "record_value_resolution_batch_size", 1)

    def run(concurrency):
        monkeypatch.setattr(config, "llm_batch_concurrency", concurrency)
        state = {"active": 0, "peak": 0, "n": 0}

        class Judge:
            async def _call_llm(self, messages, **kwargs):
                state["n"] += 1
                order = state["n"]
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
                await asyncio.sleep(0.01 * (5 - order % 5))  # later calls finish first
                state["active"] -= 1
                records = json.loads(messages[-1].content.split("\n\nRecords:\n", 1)[1])
                payload = {"records": [
                    {"record_id": r["record_id"], "values": {
                        "protocol": {"status": "undetermined", "value": ""},
                    }} for r in records
                ]}
                return type("Response", (), {"content": json.dumps(payload)})()

        agent = ISAValueMapperAgent()
        monkeypatch.setattr(agent, "_get_llm", lambda _: Judge())
        result = asyncio.run(agent._resolve_partial_record_values(
            deepcopy(_matrix()), FIELDS, PLAN, DOCUMENT, {},
        ))
        return result, state["peak"]

    serial, serial_peak = run(1)
    concurrent, concurrent_peak = run(4)
    assert serial_peak == 1
    assert concurrent_peak > 1
    assert concurrent == serial


def test_repair_planner_keeps_only_existing_columns_and_rows(monkeypatch):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {"assay": {
        "columns": ["assay identifier", "michaelis constant km", "protocol"],
        "rows": [{"assay identifier": "a1"}, {"assay identifier": "a2"}],
    }}

    class Planner:
        async def _call_llm(self, messages, **kwargs):
            return type("R", (), {"content": json.dumps({"targets": [
                {"level": "assay", "columns": ["Michaelis constant Km", "no such column"],
                 "row_ids": ["a2", "zz"], "instruction": "add the mM unit"},
                {"level": "assay", "columns": ["assay identifier"], "row_ids": []},
            ], "not_cell_level": ["missing assay rows"]})})()

    agent = ISAValueMapperAgent()
    monkeypatch.setattr(agent, "_get_llm", lambda _: Planner())
    targets = asyncio.run(agent._plan_targeted_repair(
        matrix, {"issues": ["Km lacks units"]}, {},
    ))
    assert targets == [{"level": "assay", "columns": ["michaelis constant km"],
                        "row_ids": ["a2"], "instruction": "add the mM unit"}]


def test_repair_planner_drops_a_whole_sheet_rereview(monkeypatch):
    """Every row of a wide column set repeats the first pass; it is no repair."""
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    columns = [f"parameter {i}" for i in range(12)]
    matrix = {"assay": {"columns": ["assay identifier", *columns],
                        "rows": [{"assay identifier": "a1"}]}}

    class Planner:
        async def _call_llm(self, messages, **kwargs):
            return type("R", (), {"content": json.dumps({"targets": [
                {"level": "assay", "columns": columns, "row_ids": [], "instruction": "fill gaps"},
                {"level": "assay", "columns": columns, "row_ids": ["a1"], "instruction": "fix a1"},
                {"level": "assay", "columns": columns[:2], "row_ids": [], "instruction": "units"},
            ]})})()

    agent = ISAValueMapperAgent()
    monkeypatch.setattr(agent, "_get_llm", lambda _: Planner())
    targets = asyncio.run(agent._plan_targeted_repair(matrix, {"issues": ["gaps"]}, {}))
    assert [target["instruction"] for target in targets] == ["fix a1", "units"]


def test_targeted_review_sends_only_target_rows_and_keeps_other_verifications(monkeypatch):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.config import config

    monkeypatch.setattr(config, "record_value_resolution_batch_size", 25)
    sent = []

    class Judge:
        async def _call_llm(self, messages, **kwargs):
            prompt = messages[-1].content
            assert "Reviewer feedback to address" in prompt
            records = json.loads(prompt.split("\n\nRecords:\n", 1)[1])
            sent.extend(record["record_id"] for record in records)
            return type("R", (), {"content": json.dumps({"records": [
                {"record_id": r["record_id"], "values": {"protocol": {"status": "undetermined", "value": ""}}}
                for r in records
            ]})})()

    agent = ISAValueMapperAgent()
    monkeypatch.setattr(agent, "_get_llm", lambda _: Judge())
    matrix = _matrix()
    rows = matrix["assay"]["rows"]
    target_id = rows[-1]["assay identifier"]
    verified = {"assay": {(0, "protocol"): "kept"}}
    asyncio.run(agent._resolve_partial_record_values(
        deepcopy(matrix), FIELDS, PLAN, DOCUMENT, {}, verified_cells=verified,
        forced_targets=[{"level": "assay", "columns": ["protocol"], "row_ids": [target_id],
                         "instruction": "check protocol"}],
        keep_verified=True,
    ))
    assert len(sent) == 1
    if len(rows) > 1:
        assert verified["assay"].get((0, "protocol")) == "kept"


def test_record_review_respects_the_per_level_call_budget(monkeypatch):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.config import config

    monkeypatch.setattr(config, "record_value_resolution_batch_size", 25)
    monkeypatch.setattr(config, "record_value_resolution_max_records", 0)
    monkeypatch.setattr(config, "record_value_resolution_max_calls_per_level", 4)
    columns = [f"parameter {i}" for i in range(17)]
    entities = [_assay(f"a{i}", f"specimen_{i}", "branch") for i in range(40)]
    plan = {"levels": [{"level": "assay", "entities": entities}]}
    rows = [{"assay identifier": e["row_id"], **{c: "MethodA" if i == 0 else "" for c in columns}}
            for i, e in enumerate(entities)]
    matrix = {"assay": {"columns": ["assay identifier", *columns], "rows": rows}}
    fields = {"assay": [{"field_name": c, "value": "MethodA"} for c in columns]}
    calls = []

    class Judge:
        async def _call_llm(self, messages, **kwargs):
            calls.append(1)
            records = json.loads(messages[-1].content.split("\n\nRecords:\n", 1)[1])
            return type("R", (), {"content": json.dumps({"records": [
                {"record_id": r["record_id"], "values": {}} for r in records]})})()

    agent = ISAValueMapperAgent()
    monkeypatch.setattr(agent, "_get_llm", lambda _: Judge())
    _, issues = asyncio.run(agent._resolve_partial_record_values(
        deepcopy(matrix), fields, plan, DOCUMENT, {},
    ))
    assert len(calls) == 4
    assert any("limited to 4 of" in issue for issue in issues)


def test_compact_unit_citations_pass_the_same_quote_checks():
    from fairifier.utils.record_value_resolution import (
        expand_compact_response, segment_source_units,
    )

    source = ("Methods. Enzymes were assayed at 40 °C.\n"
              "Specimen alpha had a reported response of 0.30 ± 0.04. Specimen beta was not tested.")
    units = segment_source_units(source)
    alpha_unit = next(i for i, u in enumerate(units, start=1) if "alpha" in u)
    other_unit = next(i for i, u in enumerate(units, start=1) if "40 °C" in u)
    records = [{"record_id": "a1", "identifier": "alpha", "source_group": "study"}]

    def run(unit_id):
        rows = [{"response": ""}]
        decisions = expand_compact_response({"records": [{"record_id": "a1", "values": {
            "response": {"value": "0.30 ± 0.04", "units": [f"S{unit_id}"], "attribute": "identifier=alpha"},
        }}]}, units)
        apply_resolutions("assay", rows, records, ["response"], {"response": []},
                          [decisions], "", source)
        return rows[0]["response"]

    assert run(alpha_unit) == "0.30 ± 0.04"
    assert run(other_unit) == ""  # cited unit does not contain the value


@pytest.mark.parametrize(("attribute", "written"), [
    ("enzyme=IsPETase, substrate=BHET", "40.3"),
    ("enzyme=IsPETase; substrate=BHET", "40.3"),
    ("enzyme=IsPETase, substrate=pN-C2", ""),  # not this record's substrate
    ("enzyme=IsPETase, buffer=HEPES", ""),     # not an entry of this record
])
def test_citation_may_combine_several_own_attributes(attribute, written):
    quote = "Kinetic analysis on BHET gave IsPETase a kcat of 40.3 s-1 at 40 °C."
    rows = [{"kcat": ""}]
    records = [{
        "record_id": "a1", "identifier": "a1", "source_group": "kinetics",
        "attributes": ["enzyme=IsPETase", "substrate=BHET"],
    }]
    apply_resolutions(
        "assay", rows, records, ["kcat"], {"kcat": []},
        [{"records": [{"record_id": "a1", "values": {
            "kcat": _supported("40.3", attribute, quote),
        }}]}], "", quote,
    )
    assert rows[0]["kcat"] == written


KINETICS_ROW = (
    r"Substrates = BHET; \( K_m \) (mM) | BhrPETase = 16.78 ± 2.95; "
    r"\( K_m \) (mM) | LCC = 25.82 ± 2.31; "
    r"\( k_{cat} \) (\( sec^{-1} \)) | BhrPETase = 7.3; "
    r"\( k_{cat} \) (\( sec^{-1} \)) | LCC = 8.3"
)


@pytest.mark.parametrize(("record", "column", "value", "written"), [
    ("LCC|BHET", "kcat", "8.3 s⁻¹", "8.3 s⁻¹"),          # own sub-column, header unit
    ("LCC|BHET", "km", "25.82 ± 2.31 mM", "25.82 ± 2.31 mM"),
    ("LCC|BHET", "km", "25.82 mM", "25.82 ± 2.31 mM"),   # mean of the cell keeps its error
    ("LCC|BHET", "km", "25.82", "25.82"),                # a bare number stays bare
    ("LCC|BHET", "km", "2.31", ""),                      # uncertainty fragment
    ("LCC|BHET", "km", "8.3 mM", ""),                    # header unit is s-1
    ("BhrPETase|BHET", "kcat", "8.3", ""),               # LCC's sub-column
    ("LCC|pN-C2", "kcat", "8.3", ""),                    # row is another substrate
    ("BhrPETase|BHET", "kcat", "7.3", "7.3"),
])
def test_table_row_binds_a_cell_to_its_own_record(record, column, value, written):
    """The table's row label and sub-column decide the record, whatever is cited."""
    records = [
        {"record_id": f"{enzyme}|{substrate}", "identifier": f"{enzyme}|{substrate}",
         "source_group": "kinetics",
         "attributes": [f"enzyme={enzyme}", f"substrate={substrate}"]}
        for enzyme in ("BhrPETase", "LCC") for substrate in ("BHET", "pN-C2")
    ]
    rows = [{"kcat": "", "km": ""} for _ in records]
    apply_resolutions(
        "assay", rows, records, ["kcat", "km"], {},
        [{"records": [{"record_id": record, "values": {
            column: _supported(value, "kcat | LCC = 8.3", KINETICS_ROW),
        }}]}], "", KINETICS_ROW,
    )
    index = [item["record_id"] for item in records].index(record)
    assert rows[index][column] == written


KINETICS_TABLE = (
    '<table><tr><td rowspan="2">Substrates</td><td colspan="2">\\( K_m \\) (mM)</td>'
    '<td colspan="2">\\( k_{cat} \\) (\\( sec^{-1} \\))</td></tr>'
    "<tr><td>BhrPETase</td><td>LCC</td><td>BhrPETase</td><td>LCC</td></tr>"
    "<tr><td>pN-C2</td><td>1.15 ± 0.01</td><td>1.82 ± 0.04</td><td>130.9</td><td>178.2</td></tr>"
    "<tr><td>BHET</td><td>16.78 ± 2.95</td><td>25.82 ± 2.31</td><td>7.3</td><td>8.3</td></tr></table>"
)


@pytest.mark.parametrize(("record", "column", "value", "written"), [
    ("BhrPETase|BHET", "kcat", "7.3 s^-1", "7.3 s^-1"),
    ("BhrPETase|BHET", "km", "16.78 ± 2.95 mM", "16.78 ± 2.95 mM"),
    ("LCC|pN-C2", "kcat", "178.2 s^-1", "178.2 s^-1"),
    ("BhrPETase|BHET", "kcat", "8.3 s^-1", ""),     # LCC's sub-column
    ("LCC|pN-C2", "km", "25.82 mM", ""),            # the BHET row's value
])
def test_raw_table_citation_binds_through_its_rendered_rows(record, column, value, written):
    """Citing the raw HTML table is the same evidence as citing its derived row."""
    records = [
        {"record_id": f"{enzyme}|{substrate}", "identifier": f"{enzyme}|{substrate}",
         "source_group": "kinetics",
         "attributes": [f"enzyme={enzyme}", f"substrate={substrate}"]}
        for enzyme in ("BhrPETase", "LCC") for substrate in ("BHET", "pN-C2")
    ]
    rows = [{"kcat": "", "km": ""} for _ in records]
    apply_resolutions(
        "assay", rows, records, ["kcat", "km"], {},
        [{"records": [{"record_id": record, "values": {
            column: _supported(value, f"enzyme={record.split('|')[0]}", KINETICS_TABLE),
        }}]}], "", "Table 2 kinetics.\n" + KINETICS_TABLE,
    )
    index = [item["record_id"] for item in records].index(record)
    assert rows[index][column] == written


@pytest.mark.parametrize(("record", "cell", "kept"), [
    ("LCC|BHET", {"km": "25.82 ± 2.31 mM"}, True),
    ("LCC|BHET", {"measurement value": "7.3", "measurement unit": "s-1"}, False),  # BhrPETase's kcat
    ("LCC|BHET", {"measurement value": "8.3", "measurement unit": "s-1"}, True),   # its own kcat
    ("LCC|BHET", {"km": "16.78 mM"}, False),
    ("LCC|BHET", {"km": "16.78"}, True),          # bare and no unit column: quantity unknown
    ("LCC|BHET", {"tm": "7.3 °C"}, True),         # unit of another quantity
    ("LCC|pN-C2", {"km": "25.82 mM"}, False),     # the BHET row's value
    ("LCC|BHET", {"km": "99 mM"}, True),          # not in any table: left to other checks
])
def test_table_value_of_another_record_is_cleared(record, cell, kept):
    """A mapped quantity that the source table gives only to a sibling is a row copy."""
    from fairifier.services.publication_tables import DERIVED_TABLE_ROWS_HEADER
    from fairifier.utils.record_value_resolution import align_cells_with_source_tables

    names = [f"{e}|{s}" for e in ("BhrPETase", "LCC") for s in ("BHET", "pN-C2")]
    plan = {"levels": [{"level": "assay", "entities": [
        {"row_id": name, "attributes": [
            {"dimension_name": "enzyme", "value": name.split("|")[0]},
            {"dimension_name": "substrate", "value": name.split("|")[1]},
        ]} for name in names
    ]}]}
    rows = [{"assay identifier": name, **(cell if name == record else {})} for name in names]
    source = f"Table 2 kinetics.\n\n{DERIVED_TABLE_ROWS_HEADER}\n[table 1]\n{KINETICS_ROW}\n"
    issues = align_cells_with_source_tables("assay", plan, rows, source)
    row = rows[names.index(record)]
    column = next(name for name in cell if name != "measurement unit")
    assert (row[column] == cell[column]) is kept
    assert len(issues) == (0 if kept else 1)


def test_own_table_mean_regains_its_reported_error():
    from fairifier.services.publication_tables import DERIVED_TABLE_ROWS_HEADER
    from fairifier.utils.record_value_resolution import align_cells_with_source_tables

    plan = {"levels": [{"level": "assay", "entities": [
        {"row_id": e, "attributes": [{"dimension_name": "enzyme", "value": e},
                                     {"dimension_name": "substrate", "value": "BHET"}]}
        for e in ("BhrPETase", "LCC")
    ]}]}
    rows = [{"assay identifier": "BhrPETase", "km": "16.78 mM", "kcat": "7.3 s-1"},
            {"assay identifier": "LCC", "km": "25.82 mM"}]
    source = f"x\n\n{DERIVED_TABLE_ROWS_HEADER}\n[table 1]\n{KINETICS_ROW}\n"
    align_cells_with_source_tables("assay", plan, rows, source)
    assert [rows[0]["km"], rows[0]["kcat"], rows[1]["km"]] == [
        "16.78 ± 2.95 mM", "7.3 s-1", "25.82 ± 2.31 mM"]


@pytest.mark.parametrize(("cells", "kept"), [
    ({"km": "25.82 mM"}, True),    # own Km cell reports ± 2.31 (restored first)
    ({}, False),                   # nothing makes 2.31 this record's: pN-C2's Km
])
def test_own_error_term_is_not_another_records_mean(cells, kept):
    from fairifier.services.publication_tables import DERIVED_TABLE_ROWS_HEADER
    from fairifier.utils.record_value_resolution import align_cells_with_source_tables

    plan = {"levels": [{"level": "assay", "entities": [
        {"row_id": s, "attributes": [{"dimension_name": "enzyme", "value": "LCC"},
                                     {"dimension_name": "substrate", "value": s}]}
        for s in ("BHET", "pN-C2")
    ]}]}
    rows = [{"assay identifier": "BHET", "measurement uncertainty value": "2.31",
             "measurement unit": "mM", **cells},
            {"assay identifier": "pN-C2"}]
    source = (f"x\n\n{DERIVED_TABLE_ROWS_HEADER}\n[table 1]\n"
              r"Substrates = BHET; \( K_m \) (mM) | LCC = 25.82 ± 2.31" "\n"
              r"Substrates = pN-C2; \( K_m \) (mM) | LCC = 2.31 ± 0.01" "\n")
    align_cells_with_source_tables("assay", plan, rows, source)
    assert (rows[0]["measurement uncertainty value"] == "2.31") is kept
