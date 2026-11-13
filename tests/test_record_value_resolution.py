"""Record-level resolution of partially populated per-record ISA columns."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy

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


class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    async def _call_llm(self, messages, operation_name="", **_kwargs):
        self.prompts.append(messages[-1].content)

        class _Response:
            content = json.dumps(self.payload)

        return _Response()


def test_agent_pass_queries_every_record_and_writes_only_validated_values(monkeypatch):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    agent = ISAValueMapperAgent()
    llm = _FakeLLM(
        {
            "records": [
                {
                    "record_id": "a2",
                    "values": {
                        "protocol": _supported(
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
