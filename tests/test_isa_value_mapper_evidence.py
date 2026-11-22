"""Tests for ISAValueMapper EvidenceStore integration (Plan §4.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _large_schema_contract():
    return [
        {
            "term": f"measurement attribute {index:03d}",
            "metadata": {
                "isa_sheet": "assay", "definition": f"Definition {index}",
                "syntax": "{number}", "preferred_unit": "mmol/L",
            },
        }
        for index in range(101)
    ]


def test_mapping_virtual_knowledge_keeps_all_selected_contracts(monkeypatch):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    agent = object.__new__(ISAValueMapperAgent)
    monkeypatch.setattr(agent, "_maybe_create_file_data", lambda text: text)
    knowledge = _large_schema_contract()
    files = agent._build_ivm_seed_files(
        fields_by_level={}, knowledge_items=knowledge,
        source_workspace={}, document_context="",
    )

    assert json.loads(files["/workspace/retrieved_knowledge.json"]) == knowledge


def test_mapping_prompt_keeps_late_field_contracts_and_preferred_units(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    captured = {}

    async def call(messages, **kwargs):
        captured["messages"] = messages
        return SimpleNamespace(content='{"assay": {"columns": [], "rows": []}}')

    agent = object.__new__(ISAValueMapperAgent)
    monkeypatch.setattr(agent, "_get_llm", lambda state: SimpleNamespace(_call_llm=call))
    knowledge = _large_schema_contract()
    asyncio.run(agent._build_matrix_with_llm(
        {"assay": [{"field_name": item["term"]} for item in knowledge]},
        knowledge, "", None, None, None, {},
    ))
    prompt = captured["messages"][-1].content
    definitions = json.loads(prompt.split("FAIR-DS field definitions:\n", 1)[1])

    assert [item["term"] for item in definitions] == [item["term"] for item in knowledge]
    assert all(item["preferred_unit"] == "mmol/L" for item in definitions)


@pytest.mark.parametrize("unit_key", ["preferred_unit", "preferredUnit"])
def test_serialized_field_retains_unit_contract_without_filling_value(unit_key):
    from fairifier.agents.json_generator import JSONGeneratorAgent
    from fairifier.models import MetadataField

    agent = object.__new__(JSONGeneratorAgent)
    field = MetadataField(
        field_name="concentration", isa_sheet="assay", value=None,
        metadata={"syntax": "{number}", unit_key: "mmol/L"},
    )
    result = agent._field_to_dict(field)

    assert result["preferred_unit"] == "mmol/L"
    assert result["value"] is None


def test_extraction_prompt_exposes_preferred_unit_as_schema_not_source(monkeypatch):
    from fairifier.utils.llm_helper import LLMHelper

    helper = object.__new__(LLMHelper)
    monkeypatch.setattr(helper, "_prepare_metadata_document_context", lambda text, fields: text)
    messages = helper._build_metadata_generation_messages(
        {}, [{"name": "concentration", "isa_sheet": "assay",
              "metadata": {"syntax": "{number}", "preferred_unit": "mmol/L"}}],
        "No concentration was reported.",
    )
    prompt = messages[-1].content
    schema = prompt.split("Metadata fields to populate (TOTAL: 1 fields):\n", 1)[1]
    fields = json.loads(schema.split("\n\nFields by ISA hierarchy:", 1)[0])

    assert fields[0]["preferred_unit"] == "mmol/L"
    assert "No concentration was reported." in prompt


def _make_evidence_store(tmp_path: Path, records: list) -> dict:
    jsonl_path = tmp_path / "source_workspace" / "evidence_store.jsonl"
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return {"jsonl_path": str(jsonl_path), "record_count": len(records)}


def test_build_evidence_store_summary_loads_and_groups_by_field(tmp_path):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    records = [
        {"field_name": "organism", "value": "Lumbricus terrestris", "confidence": 0.9,
         "retrieval_method": "section_map_reduce", "source_id": "source_001", "section": "Methods"},
        {"field_name": "organism", "value": "Earthworm", "confidence": 0.5,
         "retrieval_method": "section_map_reduce", "source_id": "source_001", "section": "Abstract"},
        {"field_name": "sample type", "value": "RNA", "confidence": 0.85,
         "retrieval_method": "section_map_reduce", "source_id": "source_001", "section": "Methods"},
    ]
    meta = _make_evidence_store(tmp_path, records)
    summary = ISAValueMapperAgent._build_evidence_store_summary(meta)

    assert summary is not None
    assert summary["field_count"] == 2
    assert summary["fields"]["organism"][0]["value"] == "Lumbricus terrestris"
    assert "sample type" in summary["fields"]


def test_build_evidence_store_summary_caps_per_field(tmp_path):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    records = [
        {"field_name": "ph", "value": str(i), "confidence": float(i) / 10,
         "retrieval_method": "section_map_reduce", "source_id": "s1", "section": ""}
        for i in range(10)
    ]
    meta = _make_evidence_store(tmp_path, records)
    summary = ISAValueMapperAgent._build_evidence_store_summary(meta, max_candidates_per_field=3)

    assert summary is not None
    assert len(summary["fields"]["ph"]) == 3
    assert float(summary["fields"]["ph"][0]["confidence"]) >= float(summary["fields"]["ph"][1]["confidence"])


def test_build_evidence_store_summary_returns_none_when_missing():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    assert ISAValueMapperAgent._build_evidence_store_summary({}) is None
    assert ISAValueMapperAgent._build_evidence_store_summary({"jsonl_path": "/nonexistent/path.jsonl"}) is None


def test_build_evidence_store_summary_skips_empty_values(tmp_path):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    records = [
        {"field_name": "organism", "value": "", "confidence": 0.9,
         "retrieval_method": "grep", "source_id": "s1", "section": ""},
        {"field_name": "organism", "value": "Lumbricus", "confidence": 0.7,
         "retrieval_method": "grep", "source_id": "s1", "section": ""},
    ]
    meta = _make_evidence_store(tmp_path, records)
    summary = ISAValueMapperAgent._build_evidence_store_summary(meta)

    assert summary is not None
    assert len(summary["fields"]["organism"]) == 1
    assert summary["fields"]["organism"][0]["value"] == "Lumbricus"


def test_build_matrix_heuristic_backfills_empty_cells_from_evidence():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    evidence_summary = {
        "fields": {
            "organism": [{"value": "Lumbricus terrestris", "confidence": 0.9,
                          "retrieval_method": "section_map_reduce", "source_id": "s1", "section": ""}],
            "collection site": [{"value": "Wageningen", "confidence": 0.8,
                                 "retrieval_method": "section_map_reduce", "source_id": "s1", "section": ""}],
        },
        "field_count": 2,
    }
    fields_by_level = {
        "investigation": [], "study": [], "observationunit": [],
        "sample": [
            {"field_name": "organism", "value": "", "isa_sheet": "sample", "entity_id": "sample_1"},
            {"field_name": "collection site", "value": "", "isa_sheet": "sample", "entity_id": "sample_1"},
            {"field_name": "sample name", "value": "S1", "isa_sheet": "sample", "entity_id": "sample_1"},
        ],
        "assay": [],
    }
    agent = ISAValueMapperAgent.__new__(ISAValueMapperAgent)
    matrix = agent._build_matrix_heuristic(fields_by_level, evidence_summary)

    row = matrix["sample"]["rows"][0]
    assert row.get("organism") == "Lumbricus terrestris"
    assert row.get("collection site") == "Wageningen"
    assert row.get("sample name") == "S1"


def test_build_matrix_heuristic_does_not_overwrite_existing_values():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    evidence_summary = {
        "fields": {
            "organism": [{"value": "Wrong value", "confidence": 0.95,
                          "retrieval_method": "section_map_reduce", "source_id": "s1", "section": ""}],
        },
        "field_count": 1,
    }
    fields_by_level = {
        "investigation": [], "study": [], "observationunit": [],
        "sample": [
            {"field_name": "organism", "value": "Correct value", "isa_sheet": "sample", "entity_id": "s1"},
        ],
        "assay": [],
    }
    agent = ISAValueMapperAgent.__new__(ISAValueMapperAgent)
    matrix = agent._build_matrix_heuristic(fields_by_level, evidence_summary)

    assert matrix["sample"]["rows"][0]["organism"] == "Correct value"


def _heuristic_identity_plan():
    return {"levels": [
        {"level": level, "cardinality": 2, "entities": [
            {
                "row_id": f"{level}_{suffix}",
                "parent_row_id": f"{parent}_{suffix}",
                "source_group": f"group_{suffix}",
                "attributes": [],
            }
            for suffix in ("a", "b")
        ]}
        for level, parent in (("sample", "unit"), ("assay", "sample"))
    ]}


def _complete_heuristic_identity_plan():
    plan = _heuristic_identity_plan()
    plan["levels"] = [
        {"level": "investigation", "cardinality": 1, "entities": [
            {"row_id": "investigation_a", "parent_row_id": None, "attributes": []},
        ]},
        {"level": "study", "cardinality": 1, "entities": [
            {"row_id": "study_a", "parent_row_id": "investigation_a", "attributes": []},
        ]},
        {"level": "observationunit", "cardinality": 2, "entities": [
            {"row_id": f"unit_{suffix}", "parent_row_id": "study_a", "attributes": []}
            for suffix in ("a", "b")
        ]},
        *plan["levels"],
    ]
    return plan


@pytest.mark.parametrize("level,field_name,values,parent_field,parents", [
    ("sample", "sample property", ["cold", "warm"],
     "observation unit identifier", ["unit_a", "unit_b"]),
    ("assay", "measurement value", ["2.5", "7.5"],
     "sample identifier", ["sample_a", "sample_b"]),
])
@pytest.mark.parametrize("reverse_fields", [False, True])
def test_heuristic_fallback_preserves_canonical_entity_associations_through_projection(
    level, field_name, values, parent_field, parents, reverse_fields,
):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.entity_plan import project_matrix_onto_entity_plan

    fields = {level: [
        {"field_name": field_name, "value": value, "entity_id": f"{level}_{suffix}"}
        for suffix, value in zip(("a", "b"), values)
    ]}
    if reverse_fields:
        fields[level].reverse()
    plan = _heuristic_identity_plan()
    agent = ISAValueMapperAgent.__new__(ISAValueMapperAgent)

    matrix = agent._build_matrix_heuristic(fields)
    matrix = agent._ensure_core_linkage_fields(matrix, {"entity_plan": plan})
    projected = project_matrix_onto_entity_plan(matrix, plan)

    assert [row[field_name] for row in projected[level]["rows"]] == values
    assert [row[f"{level} identifier"] for row in projected[level]["rows"]] == [
        f"{level}_a", f"{level}_b",
    ]
    assert [row[parent_field] for row in projected[level]["rows"]] == parents


@pytest.mark.parametrize("entity_prefix", ["sample", "unplanned"])
def test_heuristic_fallback_does_not_broadcast_wrong_or_unmatched_entity_ids(entity_prefix):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.entity_plan import project_matrix_onto_entity_plan

    fields = {"assay": [
        {"field_name": "measurement value", "value": "2.5",
         "entity_id": f"{entity_prefix}_{suffix}"}
        for suffix in ("a", "b")
    ]}
    plan = _heuristic_identity_plan()
    agent = ISAValueMapperAgent.__new__(ISAValueMapperAgent)

    matrix = agent._build_matrix_heuristic(fields)
    matrix = agent._ensure_core_linkage_fields(matrix, {"entity_plan": plan})
    projected = project_matrix_onto_entity_plan(matrix, plan)

    assert [row["measurement value"] for row in projected["assay"]["rows"]] == ["", ""]


def test_heuristic_fallback_does_not_turn_anonymous_group_key_into_an_identifier():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    fields = {"assay": [{"field_name": "measurement value", "value": "2.5"}]}
    agent = ISAValueMapperAgent.__new__(ISAValueMapperAgent)

    matrix = agent._build_matrix_heuristic(fields)

    assert "assay identifier" not in matrix["assay"]["columns"]
    assert matrix["assay"]["rows"] == [{"measurement value": "2.5"}]


def test_heuristic_fallback_rejects_conflicting_identifiers_without_losing_other_rows(caplog):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.entity_plan import project_matrix_onto_entity_plan

    fields = {"assay": [
        {"field_name": "measurement value", "value": "2.5", "entity_id": "assay_a"},
        {"field_name": "assay identifier", "value": "assay_b", "entity_id": "assay_a"},
        {"field_name": "measurement value", "value": "7.5", "entity_id": "assay_b"},
        {"field_name": "assay identifier", "value": "assay_b", "entity_id": "assay_b"},
    ]}
    plan = _complete_heuristic_identity_plan()
    agent = ISAValueMapperAgent.__new__(ISAValueMapperAgent)

    with caplog.at_level("WARNING"):
        matrix = agent._build_matrix_heuristic(fields, entity_plan=plan)
    matrix = agent._ensure_core_linkage_fields(matrix, {"entity_plan": plan})
    projected = project_matrix_onto_entity_plan(matrix, plan)

    assert [row["measurement value"] for row in projected["assay"]["rows"]] == ["", "7.5"]
    assert any("identifier" in record.message and "assay_a" in record.message for record in caplog.records)
    assert fields["assay"][1]["value"] == "assay_b"


def test_heuristic_fallback_accepts_canonical_and_source_alias_for_the_same_planned_entity():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.entity_plan import project_matrix_onto_entity_plan

    plan = _complete_heuristic_identity_plan()
    for level in plan["levels"]:
        if level["level"] == "assay":
            for entity in level["entities"]:
                entity["external_identifier"] = "source_" + entity["row_id"]
    fields = {"assay": [
        {"field_name": "measurement value", "value": "2.5", "entity_id": "assay_a"},
        {"field_name": "assay identifier", "value": "source_assay_a", "entity_id": "assay_a"},
        {"field_name": "measurement value", "value": "7.5", "entity_id": "assay_b"},
        {"field_name": "assay identifier", "value": "source_assay_b", "entity_id": "assay_b"},
    ]}
    agent = ISAValueMapperAgent.__new__(ISAValueMapperAgent)

    matrix = agent._build_matrix_heuristic(fields, entity_plan=plan)
    projected = project_matrix_onto_entity_plan(matrix, plan)

    assert [row["assay identifier"] for row in projected["assay"]["rows"]] == [
        "source_assay_a", "source_assay_b",
    ]
    assert [row["measurement value"] for row in projected["assay"]["rows"]] == ["2.5", "7.5"]


def test_typed_matrix_sanitizer_uses_schema_type_not_field_name_patterns():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "sample": {
            "columns": ["arbitrary count", "missing measure", "description"],
            "rows": [
                {
                    "arbitrary count": "three replicates",
                    "missing measure": "not specified",
                    "description": "three replicates",
                }
            ],
        }
    }
    fields = {
        "sample": [
            {"field_name": "arbitrary count", "data_type": "integer"},
            {"field_name": "missing measure", "data_type": "number"},
            {"field_name": "description", "data_type": "text"},
        ]
    }

    sanitized, issues = ISAValueMapperAgent._sanitize_typed_matrix_values(
        matrix, fields
    )

    row = sanitized["sample"]["rows"][0]
    assert row["arbitrary count"] == ""
    assert row["missing measure"] == "not specified"
    assert row["description"] == "three replicates"
    assert len(issues) == 1


@pytest.mark.parametrize(("value", "syntax"), [
    ("2 h", r"{number}\s+\S.*"),
    ("1.5 mg", "{number} {unit}"),
    ("0 h", "{number} h"),
])
def test_composite_quantity_survives_a_stale_inferred_numeric_type(value, syntax):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {"assay": {"columns": ["reported quantity"], "rows": [{"reported quantity": value}]}}
    fields = {"assay": [{
        "field_name": "reported quantity", "data_type": "number", "syntax": syntax,
    }]}
    result, issues = ISAValueMapperAgent._sanitize_typed_matrix_values(matrix, fields)
    assert result["assay"]["rows"][0]["reported quantity"] == value
    assert issues == []


@pytest.mark.parametrize(("value", "expected"), [
    (0, 0),
    ("0", "0"),
    ("1.5", "1.5"),
    ("many", ""),
    ("2 h", ""),
    ("1.2.3", ""),
])
def test_scalar_numeric_contract_still_rejects_malformed_values(value, expected):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {"assay": {"columns": ["scalar amount"], "rows": [{"scalar amount": value}]}}
    fields = {"assay": [{
        "field_name": "scalar amount", "data_type": "number", "syntax": "{number}",
        "preferred_unit": "h",
    }]}
    result, issues = ISAValueMapperAgent._sanitize_typed_matrix_values(matrix, fields)
    assert result["assay"]["rows"][0]["scalar amount"] == expected
    assert bool(issues) == (expected == "")


def test_composite_numeric_sanitization_keeps_explicit_regex_enforcement():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.fairds_value_contracts import build_contract_index

    field = {
        "field_name": "reported quantity", "isa_sheet": "assay", "data_type": "number",
        "syntax": r"{number}\s+\S.*", "regex": r"^[+-]?\d+(?:\.\d+)?\s+mg$",
    }
    matrix = {"assay": {
        "columns": ["reported quantity"],
        "rows": [{"reported quantity": "1.5 mg"}, {"reported quantity": "1.5 h"}],
    }}
    contracts = build_contract_index([{"term": "reported quantity", "metadata": field}])
    matrix, contract_issues = ISAValueMapperAgent._enforce_fairds_value_contracts(matrix, contracts)
    result, type_issues = ISAValueMapperAgent._sanitize_typed_matrix_values(
        matrix, {"assay": [field]},
    )
    assert [row["reported quantity"] for row in result["assay"]["rows"]] == ["1.5 mg", ""]
    assert len(contract_issues) == 1
    assert type_issues == []


def test_field_selector_value_is_not_broadcast_across_multi_entity_rows():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.fairds_value_contracts import build_contract_index

    matrix = {
        "sample": {
            "columns": ["design variable selector"],
            "rows": [
                {"design variable selector": ""},
                {"design variable selector": "dose"},
            ],
        }
    }
    fields = {
        "sample": [
            {
                "field_name": "design variable selector",
                "value": "dose",
                "confidence": 0.95,
                "status": "confirmed",
                "evidence": "source_001:1-20",
            },
            {"field_name": "dose"},
            {"field_name": "replicate"},
        ]
    }
    contracts = build_contract_index(
        [
            {
                "term": "design variable selector",
                "metadata": {
                    "isa_sheet": "sample",
                    "regex": "(dose|replicate|dev_stage)",
                },
            }
        ]
    )

    restored = ISAValueMapperAgent._restore_high_confidence_shared_values(
        matrix, fields, contracts
    )

    assert restored["sample"]["rows"] == [
        {"design variable selector": ""},
        {"design variable selector": "dose"},
    ]


def test_selected_field_columns_are_preserved_even_when_values_are_missing():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "sample": {
            "columns": ["sample identifier"],
            "rows": [{"sample identifier": "sample_001"}],
        }
    }
    fields = {
        "sample": [
            {"field_name": "sample identifier"},
            {"field_name": "geographic location (latitude)"},
        ]
    }

    result = ISAValueMapperAgent._ensure_selected_field_columns(matrix, fields)

    assert result["sample"]["columns"] == [
        "sample identifier",
        "geographic location (latitude)",
    ]
    assert result["sample"]["rows"][0]["geographic location (latitude)"] == ""


def test_empty_optional_columns_are_pruned_by_requirement_not_field_pattern():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "sample": {
            "columns": [
                "sample identifier",
                "arbitrary optional term",
                "mandatory but missing",
                "planned factor",
            ],
            "rows": [
                {
                    "sample identifier": "sample_001",
                    "arbitrary optional term": "not specified",
                    "mandatory but missing": "",
                    "planned factor": "condition_a",
                }
            ],
        }
    }
    fields = {
        "sample": [
            {"field_name": "arbitrary optional term", "requirement": "OPTIONAL"},
            {"field_name": "mandatory but missing", "requirement": "MANDATORY"},
            {"field_name": "planned factor", "requirement": "OPTIONAL"},
        ]
    }
    plan = {
        "levels": [
            {
                "level": "sample",
                "entities": [
                    {
                        "attributes": [
                            {"field_name": "planned factor", "value": "condition_a"}
                        ]
                    }
                ],
            }
        ]
    }

    pruned_matrix, removed = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix, fields, plan
    )

    assert removed == {"sample": ["arbitrary optional term"]}
    assert pruned_matrix["sample"]["columns"] == [
        "sample identifier",
        "mandatory but missing",
        "planned factor",
    ]


@pytest.mark.asyncio
async def test_mapping_deliverable_retains_selected_schema_without_unsupported_values(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from fairifier.agents import json_generator as generator_module
    from fairifier.agents import isa_value_mapper as mapper_module
    from fairifier.agents.base import BaseAgent

    monkeypatch.setattr(mapper_module.config, "enable_deep_agents", False)
    monkeypatch.setattr(generator_module, "JSONGeneratorAgent", lambda: SimpleNamespace(
        _build_source_workspace_context=lambda *_: "",
        _build_field_source_evidence_context=lambda *_, **__: ("", {}),
    ))
    agent = object.__new__(mapper_module.ISAValueMapperAgent)
    BaseAgent.__init__(agent, "ISAValueMapper")
    monkeypatch.setattr(agent, "_build_matrix_with_llm", AsyncMock(return_value={
        "sample": {
            "columns": ["sample identifier", "concentration", "collection time", "material label"],
            "rows": [{"sample identifier": "sample_001", "concentration": "2 mM",
                      "collection time": "", "material label": "alpha"}],
        },
    }))
    fields = [
        {"field_name": "sample identifier", "requirement": "MANDATORY", "value": "sample_001"},
        {"field_name": "concentration", "requirement": "OPTIONAL", "value": "2 mM"},
        {"field_name": "collection time", "requirement": "RECOMMENDED", "value": ""},
        {"field_name": "material label", "requirement": "OPTIONAL", "value": "alpha"},
    ]
    for field in fields:
        field.update(isa_sheet="sample", status="provisional", confidence=0.5)
    state = {"metadata_fields": fields,
             "document_content": "Material alpha was measured at 12 mM.",
             "artifacts": {"metadata_json": json.dumps({"isa_structure": {}})}}
    result = await agent.execute(state)
    matrix = json.loads(result["artifacts"]["isa_values"])
    metadata = json.loads(result["artifacts"]["metadata_json"])

    assert {field["field_name"] for field in fields}.issubset(matrix["sample"]["columns"])
    assert len(matrix["sample"]["rows"]) == 1
    row = matrix["sample"]["rows"][0]
    assert row["sample identifier"] == "sample_001"
    assert row["concentration"] == ""  # 2 mM is not supported by 12 mM.
    assert row["collection time"] == ""
    assert row["material label"] == "alpha"
    assert metadata["isa_values"] == matrix


def test_informative_optional_column_requires_confirmed_source_evidence():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "assay": {
            "columns": [
                "assay identifier",
                "provisional optional",
                "confirmed optional",
            ],
            "rows": [
                {
                    "assay identifier": "assay_001",
                    "provisional optional": "a plausible prose guess",
                    "confirmed optional": "source value",
                }
            ],
        }
    }
    fields = {
        "assay": [
            {
                "field_name": "provisional optional",
                "requirement": "OPTIONAL",
                "status": "provisional",
                "evidence": "source_001",
            },
            {
                "field_name": "confirmed optional",
                "requirement": "OPTIONAL",
                "status": "confirmed",
                "evidence": "source_001:10-30",
            },
        ]
    }

    pruned, removed = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix, fields, {"levels": []}
    )

    assert removed == {"assay": ["provisional optional"]}
    assert pruned["assay"]["columns"] == [
        "assay identifier",
        "confirmed optional",
    ]


def test_confirmed_shared_value_survives_row_mapping_without_overwriting_identity():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "sample": {
            "columns": ["sample name", "scientific name"],
            "rows": [
                {"sample name": "sample a", "scientific name": ""},
                {"sample name": "sample b", "scientific name": ""},
            ],
        }
    }
    fields = {
        "sample": [
            {
                "field_name": "sample name",
                "value": "collapsed mapper name",
                "confidence": 1.0,
                "status": "confirmed",
                "evidence": "source:1-2",
            },
            {
                "field_name": "scientific name",
                "value": "Arabidopsis thaliana",
                "confidence": 1.0,
                "status": "confirmed",
                "evidence": "source: organism header",
                "value_scope": "level",
            },
        ]
    }

    restored = ISAValueMapperAgent._restore_high_confidence_shared_values(
        matrix,
        fields,
    )

    assert [row["sample name"] for row in restored["sample"]["rows"]] == [
        "sample a",
        "sample b",
    ]
    assert {
        row["scientific name"] for row in restored["sample"]["rows"]
    } == {"Arabidopsis thaliana"}


@pytest.mark.parametrize("entity_id,expected", [
    ("sample_a", ""),
    ("unknown_record", ""),
    (None, "25 °C"),
    ("assay_a", "25 °C"),
])
def test_shared_restoration_requires_compatible_declared_entity_scope(entity_id, expected):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    plan = _complete_heuristic_identity_plan()
    matrix = {"assay": {
        "columns": ["assay identifier", "temperature"],
        "rows": [
            {"assay identifier": f"assay_{suffix}", "temperature": ""}
            for suffix in ("a", "b")
        ],
    }}
    fields = {"assay": [{
        "field_name": "temperature", "value": "25 °C", "confidence": 0.95,
        "status": "confirmed", "evidence": "source_001: both assays used 25 °C",
        "value_scope": "level", "entity_id": entity_id,
    }]}
    original_fields = json.loads(json.dumps(fields))

    restored = ISAValueMapperAgent._restore_high_confidence_shared_values(
        matrix, fields, entity_plan=plan,
    )

    assert [row["temperature"] for row in restored["assay"]["rows"]] == [expected, expected]
    assert fields == original_fields
    assert ("temperature" in restored["assay"].get("_shared_columns", [])) is bool(expected)


def test_optional_value_is_not_pruned_as_substring_of_another_field():
    """Distinct FAIR-DS terms remain distinct even when their words overlap."""
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "sample": {
            "columns": [
                "sample identifier",
                "organism part",
                "sampling strategy",
            ],
            "rows": [
                {
                    "sample identifier": "sample_001",
                    "organism part": "embryo",
                    "sampling strategy": "50 embryos",
                }
            ],
        }
    }
    fields = {
        "sample": [
            {
                "field_name": "organism part",
                "requirement": "OPTIONAL",
                "status": "confirmed",
                "value": "embryo",
                "evidence": "The sample is an embryo.",
            },
            {
                "field_name": "sampling strategy",
                "requirement": "OPTIONAL",
                "status": "confirmed",
                "value": "50 embryos",
                "evidence": "Pools of 50 embryos were sampled.",
            },
        ]
    }
    entity_plan = {
        "levels": [
            {
                "level": "sample",
                "entities": [
                    {
                        "source_group": "group_001",
                        "attributes": [
                            {
                                "dimension_name": "material_spec",
                                "field_name": "sampling strategy",
                                "value": "50 embryos",
                                "origin": "explicit",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    result, pruned = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix,
        fields,
        entity_plan,
        source_text="Pools of 50 embryos were sampled; the sample is an embryo.",
    )

    assert "organism part" in result["sample"]["columns"]
    assert result["sample"]["rows"][0]["organism part"] == "embryo"
    assert "organism part" not in pruned.get("sample", [])


def test_missing_planned_level_gets_neutral_seed_for_confirmed_shared_values():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "assay": {
            "columns": ["assay identifier", "library strategy"],
            "rows": [],
        }
    }
    plan = {
        "levels": [
            {
                "level": "assay",
                "entities": [
                    {"row_id": "assay_001"},
                    {"row_id": "assay_002"},
                ],
            }
        ]
    }
    fields = {
        "assay": [
            {
                "field_name": "library strategy",
                "value": "RNA-Seq",
                "confidence": 0.95,
                "status": "confirmed",
                "evidence": "source_001: explicit sequencing strategy",
                "value_scope": "level",
            }
        ]
    }

    seeded = ISAValueMapperAgent._seed_missing_planned_levels(matrix, plan)
    restored = ISAValueMapperAgent._restore_high_confidence_shared_values(
        seeded, fields, entity_plan=plan
    )

    assert restored["assay"]["rows"] == [{"library strategy": "RNA-Seq"}]
    assert restored["assay"]["_shared_columns"] == ["library strategy"]


def test_claimed_level_value_is_not_broadcast_when_plan_maps_only_a_subset():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "sample": {
            "columns": ["dose"],
            "rows": [{"dose": ""}, {"dose": ""}],
        }
    }
    fields = {
        "sample": [
            {
                "field_name": "dose",
                "value": "1 ng",
                "confidence": 0.99,
                "status": "confirmed",
                "evidence": "source_001: benchmark group",
                "value_scope": "level",
            }
        ]
    }
    plan = {
        "levels": [
            {
                "level": "sample",
                "entities": [
                    {"row_id": "sample_001", "attributes": []},
                    {
                        "row_id": "sample_002",
                        "attributes": [{"field_name": "dose", "value": "1 ng"}],
                    },
                ],
            }
        ]
    }

    restored = ISAValueMapperAgent._restore_high_confidence_shared_values(
        matrix, fields, entity_plan=plan
    )

    assert restored["sample"]["rows"] == [{"dose": ""}, {"dose": ""}]
    assert "_shared_columns" not in restored["sample"]


def test_confirmed_mandatory_level_value_survives_incomplete_plan_mapping():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "sample": {
            "columns": ["scientific name"],
            "rows": [{"scientific name": ""}, {"scientific name": ""}],
        }
    }
    fields = {
        "sample": [
            {
                "field_name": "scientific name",
                "value": "Arabidopsis thaliana",
                "confidence": 1.0,
                "status": "confirmed",
                "evidence": "source_001: organism header",
                "value_scope": "level",
                "requirement": "MANDATORY",
            }
        ]
    }
    plan = {
        "levels": [
            {
                "level": "sample",
                "entities": [
                    {
                        "row_id": "sample_001",
                        "attributes": [
                            {
                                "field_name": "scientific name",
                                "value": "Arabidopsis thaliana",
                            }
                        ],
                    },
                    {"row_id": "sample_002", "attributes": []},
                ],
            }
        ]
    }

    restored = ISAValueMapperAgent._restore_high_confidence_shared_values(
        matrix, fields, entity_plan=plan
    )
    cleaned, cleared = ISAValueMapperAgent._clear_values_outside_plan_field_scope(
        restored, plan
    )

    assert [row["scientific name"] for row in cleaned["sample"]["rows"]] == [
        "Arabidopsis thaliana",
        "Arabidopsis thaliana",
    ]
    assert cleared == {}


def test_level_value_is_limited_to_design_groups_with_literal_evidence():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "sample": {
            "columns": ["strain", "scientific name"],
            "rows": [
                {"strain": "Line-A", "scientific name": "Species globalis"},
                {"strain": "Line-A", "scientific name": "Species globalis"},
            ],
        }
    }
    fields = {
        "sample": [
            {
                "field_name": "strain",
                "value": "Line-A",
                "status": "confirmed",
                "value_scope": "level",
            },
            {
                "field_name": "scientific name",
                "value": "Species globalis",
                "status": "confirmed",
                "value_scope": "level",
            },
        ]
    }
    plan = {
        "design_spec": {
            "design_groups": [
                {"group_id": "group_a", "evidence": "samples from Line-A"},
                {"group_id": "group_b", "evidence": "samples from a second line"},
            ]
        },
        "levels": [
            {
                "level": "sample",
                "entities": [
                    {"row_id": "s1", "source_group": "group_a"},
                    {"row_id": "s2", "source_group": "group_b"},
                ],
            }
        ],
    }

    cleaned, issues = (
        ISAValueMapperAgent._clear_values_outside_group_evidence_scope(
            matrix, fields, plan
        )
    )

    assert [row["strain"] for row in cleaned["sample"]["rows"]] == [
        "Line-A",
        "",
    ]
    # A value not mentioned by any group may come from document-global
    # metadata and is therefore not cleared by this group-level arbitration.
    assert {
        row["scientific name"] for row in cleaned["sample"]["rows"]
    } == {"Species globalis"}
    assert len(issues) == 1


def test_numeric_only_level_value_is_not_scoped_by_incidental_count_match():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "sample": {
            "columns": ["numeric field"],
            "rows": [{"numeric field": "50"}, {"numeric field": "50"}],
        }
    }
    fields = {
        "sample": [
            {
                "field_name": "numeric field",
                "value": "50",
                "status": "confirmed",
                "value_scope": "level",
            }
        ]
    }
    plan = {
        "design_spec": {
            "design_groups": [
                {"group_id": "group_a", "evidence": "a pool of 50 units"},
                {"group_id": "group_b", "evidence": "another experiment"},
            ]
        },
        "levels": [
            {
                "level": "sample",
                "entities": [
                    {"source_group": "group_a"},
                    {"source_group": "group_b"},
                ],
            }
        ],
    }

    cleaned, issues = (
        ISAValueMapperAgent._clear_values_outside_group_evidence_scope(
            matrix, fields, plan
        )
    )

    assert [row["numeric field"] for row in cleaned["sample"]["rows"]] == [
        "50",
        "50",
    ]
    assert issues == []


def test_react_mapping_is_reserved_for_tables_or_multi_source_workspaces():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    abstract_workspace = {
        "manifest": {
            "sources": [
                {
                    "content_type": "markdown",
                    "source_role": "main_manuscript",
                    "tables": [],
                }
            ]
        },
        "table_paths": {},
    }
    table_workspace = {
        "manifest": {
            "sources": [
                {"content_type": "table", "source_role": "table", "tables": []}
            ]
        },
        "table_paths": {"source_001:samples": "/tmp/samples.jsonl"},
    }

    assert ISAValueMapperAgent._needs_tool_mapping(abstract_workspace) is False
    assert ISAValueMapperAgent._needs_tool_mapping(table_workspace) is True


def test_invalid_upstream_controlled_phrase_cannot_overwrite_canonical_mapper_value():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.fairds_value_contracts import build_contract_index

    matrix = {
        "assay": {
            "columns": ["library strategy"],
            "rows": [{"library strategy": "RNA-Seq"}],
        }
    }
    fields = {
        "assay": [
            {
                "field_name": "library strategy",
                "value": "descriptive source phrase",
                "confidence": 0.95,
                "status": "confirmed",
                "evidence": "source_001:1-20",
            }
        ]
    }
    contracts = build_contract_index(
        [
            {
                "term": "library strategy",
                "metadata": {
                    "isa_sheet": "assay",
                    "regex": "(WGS|RNA-Seq|AMPLICON)",
                },
            }
        ]
    )

    restored = ISAValueMapperAgent._restore_high_confidence_shared_values(
        matrix, fields, contracts
    )

    assert restored["assay"]["rows"][0]["library strategy"] == "RNA-Seq"


def test_fairds_value_contract_boundary_canonicalizes_case_and_clears_invalid_values():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.fairds_value_contracts import build_contract_index

    matrix = {
        "assay": {
            "columns": ["library strategy"],
            "rows": [
                {"library strategy": "rna-seq"},
                {"library strategy": "descriptive source phrase"},
            ],
        }
    }
    contracts = build_contract_index(
        [
            {
                "term": "library strategy",
                "metadata": {
                    "isa_sheet": "assay",
                    "regex": "(WGS|RNA-Seq|AMPLICON)",
                },
            }
        ]
    )

    cleaned, issues = ISAValueMapperAgent._enforce_fairds_value_contracts(
        matrix, contracts
    )

    assert cleaned["assay"]["rows"] == [
        {"library strategy": "RNA-Seq"},
        {"library strategy": ""},
    ]
    assert len(issues) == 1


def test_short_source_labels_use_plan_ids_without_breaking_assay_links():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.fairds_value_contracts import build_contract_index

    def entity(row_id, label, parent=None, external=None):
        return {
            "row_id": row_id,
            "label": label,
            "parent_row_id": parent,
            "external_identifier": external,
            "source_group": "table",
            "attributes": [],
        }

    plan = {
        "levels": [
            {"level": "investigation", "entities": [entity("investigation_001", "I")]},
            {"level": "study", "entities": [entity("study_001", "S", "investigation_001")]},
            {
                "level": "observationunit",
                "entities": [entity("observationunit_001", "O", "study_001")],
            },
            {
                "level": "sample",
                "entities": [entity("sample_0001", "s_1", "observationunit_001", "s_1")],
            },
            {
                "level": "assay",
                "entities": [entity("assay_0001", "a_1", "sample_0001", "a_1")],
            },
        ]
    }
    matrix = {
        "investigation": {
            "columns": ["investigation identifier"],
            "rows": [{"investigation identifier": "investigation_001"}],
        },
        "study": {
            "columns": ["study identifier", "investigation identifier"],
            "rows": [{"study identifier": "study_001", "investigation identifier": "investigation_001"}],
        },
        "observationunit": {
            "columns": ["observation unit identifier", "study identifier"],
            "rows": [{"observation unit identifier": "observationunit_001", "study identifier": "study_001"}],
        },
        "sample": {
            "columns": ["sample identifier", "sample name", "observation unit identifier"],
            "rows": [{"sample identifier": "s_1", "sample name": "s_1", "observation unit identifier": "observationunit_001"}],
        },
        "assay": {
            "columns": ["assay identifier", "assay description", "sample identifier"],
            "rows": [{"assay identifier": "a_1", "assay description": "Assay for sample s_1", "sample identifier": "s_1"}],
        },
    }
    contracts = build_contract_index(
        [
            {
                "term": field,
                "metadata": {"isa_sheet": level, "regex": "^[a-zA-Z0-9-_.]{5,50}$"},
            }
            for level, field in (
                ("sample", "sample identifier"),
                ("assay", "assay identifier"),
                ("assay", "sample identifier"),
            )
        ]
    )

    cleaned, issues = ISAValueMapperAgent._canonicalize_structural_identifiers(
        matrix, plan, contracts
    )

    assert cleaned["sample"]["rows"][0]["sample identifier"] == "sample_0001"
    assert cleaned["sample"]["rows"][0]["sample name"] == "s_1"
    assert cleaned["assay"]["rows"][0]["assay identifier"] == "assay_0001"
    assert cleaned["assay"]["rows"][0]["sample identifier"] == "sample_0001"
    assert "sample_0001" in cleaned["assay"]["rows"][0]["assay description"]
    assert plan["levels"][3]["entities"][0]["external_identifier"] == "sample_0001"
    assert len([item for item in issues if "deterministic plan identifiers" in item]) == 2


def test_invalid_plan_field_mapping_is_demoted_but_kept_in_description():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.fairds_value_contracts import build_contract_index

    attribute = {
        "dimension_name": "adapter.trim",
        "field_name": "sample preparation",
        "value": "none",
        "origin": "explicit",
    }
    plan = {
        "levels": [
            {
                "level": "assay",
                "entities": [
                    {
                        "row_id": "assay_0001",
                        "label": "source assay",
                        "parent_row_id": "sample_0001",
                        "external_identifier": "assay_0001",
                        "source_group": "table",
                        "attributes": [attribute],
                    }
                ],
            }
        ]
    }
    matrix = {
        "assay": {
            "columns": ["assay description", "sample identifier", "sample preparation"],
            "rows": [
                {
                    "assay description": "Assay for sample sample_0001",
                    "sample identifier": "sample_0001",
                    "sample preparation": "none",
                }
            ],
        }
    }
    contracts = build_contract_index(
        [
            {
                "term": "sample preparation",
                "metadata": {
                    "isa_sheet": "assay",
                    "regex": "^(Nextera|TruSeq)$",
                },
            }
        ]
    )

    cleaned, issues = ISAValueMapperAgent._demote_invalid_plan_attribute_mappings(
        matrix, plan, contracts
    )

    assert cleaned["assay"]["rows"][0]["sample preparation"] == ""
    assert "adapter.trim=none" in cleaned["assay"]["rows"][0]["assay description"]
    assert attribute["field_name"] is None
    assert len(issues) == 1


def test_mapper_cannot_upgrade_provisional_paraphrase_to_level_wide_fact():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "assay": {
            "columns": ["protocol", "library strategy"],
            "rows": [
                {
                    "protocol": "Synthesized protocol summary",
                    "library strategy": "RNA-Seq",
                },
                {
                    "protocol": "Synthesized protocol summary",
                    "library strategy": "RNA-Seq",
                },
            ],
        }
    }
    fields = {
        "assay": [
            {
                "field_name": "protocol",
                "status": "provisional",
                "confidence": 0.6,
            },
            {
                "field_name": "library strategy",
                "status": "confirmed",
                "confidence": 0.95,
            },
        ]
    }

    cleaned, issues = ISAValueMapperAgent._clear_unverified_provisional_values(
        matrix,
        fields,
        {"levels": []},
        "The source states that RNA sequencing was performed.",
    )

    assert [row["protocol"] for row in cleaned["assay"]["rows"]] == ["", ""]
    assert [row["library strategy"] for row in cleaned["assay"]["rows"]] == [
        "RNA-Seq",
        "RNA-Seq",
    ]
    assert len(issues) == 1


def test_provisional_value_is_retained_when_literal_or_plan_mapped():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "sample": {
            "columns": ["treatment", "condition"],
            "rows": [{"treatment": "cold exposure", "condition": "5 ng"}],
        }
    }
    fields = {
        "sample": [
            {"field_name": "treatment", "status": "provisional"},
            {"field_name": "condition", "status": "provisional"},
        ]
    }
    plan = {
        "levels": [
            {
                "level": "sample",
                "entities": [
                    {
                        "attributes": [
                            {"field_name": "condition", "value": "5 ng"}
                        ]
                    }
                ],
            }
        ]
    }

    cleaned, issues = ISAValueMapperAgent._clear_unverified_provisional_values(
        matrix,
        fields,
        plan,
        "Samples received cold exposure before collection.",
    )

    assert cleaned["sample"]["rows"] == [
        {"treatment": "cold exposure", "condition": "5 ng"}
    ]
    assert issues == []


def _optional_scientific_value(value, field_name="concentration"):
    return (
        {"assay": {"columns": [field_name], "rows": [{field_name: value}]}},
        {"assay": [{
            "field_name": field_name, "status": "provisional",
            "requirement": "OPTIONAL", "value": value,
        }]},
    )


@pytest.mark.parametrize("stage", ["provisional", "optional"])
@pytest.mark.parametrize("source,value,expected", [
    (
        "Concentrations use millimolar (mM). A was measured at 2.5 millimolar.",
        "2.5 millimolar", "2.5 mM",
    ),
    ("A had signal −0.025 mM.", "-0.025 mM", "-0.025 mM"),
    ("A was measured at 2.5mM.", "2.5 mM", "2.5 mM"),
    ("A was measured at 1e-3mM.", "1e-3 mM", "1e-3 mM"),
])
def test_source_supported_scientific_value_survives_clearing_and_pruning(
    stage, source, value, expected,
):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix, fields = _optional_scientific_value(value)
    matrix = ISAValueMapperAgent._normalize_source_measurement_units(matrix, source)
    if stage == "provisional":
        matrix, issues = ISAValueMapperAgent._clear_unverified_provisional_values(
            matrix, fields, {}, source,
        )
        assert issues == []
    else:
        matrix, removed = ISAValueMapperAgent._prune_uninformative_optional_columns(
            matrix, fields, {}, source_text=source,
        )
        assert removed == {}

    assert matrix["assay"]["columns"] == ["concentration"]
    assert matrix["assay"]["rows"] == [{"concentration": expected}]


@pytest.mark.parametrize("stage", ["provisional", "optional"])
@pytest.mark.parametrize("source,value", [
    ("A was measured at 12 mM.", "2 mM"),
    ("A was measured at -2 mM.", "2 mM"),
    ("A was measured at 2 mM.", "-2 mM"),
    ("A was measured at 2 mm.", "2 mM"),
    ("A was measured at 1e-3 mM.", "1e3 mM"),
    ("A was measured at 0.12 mM.", "12 mM"),
    ("A was measured at 2.5 millimolar.", "2.5 mM"),
])
def test_scientific_source_matching_rejects_distinct_quantities(stage, source, value):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix, fields = _optional_scientific_value(value)
    if stage == "provisional":
        matrix, issues = ISAValueMapperAgent._clear_unverified_provisional_values(
            matrix, fields, {}, source,
        )
        assert matrix["assay"]["rows"] == [{"concentration": ""}]
        assert len(issues) == 1
    else:
        matrix, removed = ISAValueMapperAgent._prune_uninformative_optional_columns(
            matrix, fields, {}, source_text=source,
        )
        assert removed == {"assay": ["concentration"]}
        assert matrix["assay"]["columns"] == []


@pytest.mark.parametrize("stage", ["provisional", "optional"])
@pytest.mark.parametrize("source,value,supported", [
    ("A was measured at 2mg/mL.", "2 mg", False),
    ("A was measured at 2mM/s.", "2 mM", False),
    ("A covered 2cm^2.", "2 cm", False),
    ("A covered 2 cm².", "2 cm", False),
    ("A was measured at 2mg/mL.", "2 mg/mL", True),
])
def test_scientific_source_matching_requires_complete_compound_units(
    stage, source, value, supported,
):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix, fields = _optional_scientific_value(value)
    if stage == "provisional":
        matrix, issues = ISAValueMapperAgent._clear_unverified_provisional_values(
            matrix, fields, {}, source,
        )
        assert matrix["assay"]["rows"] == [{"concentration": value if supported else ""}]
        assert bool(issues) is not supported
    else:
        matrix, removed = ISAValueMapperAgent._prune_uninformative_optional_columns(
            matrix, fields, {}, source_text=source,
        )
        assert bool(removed) is not supported
        assert matrix["assay"]["columns"] == (["concentration"] if supported else [])


@pytest.mark.parametrize("stage", ["provisional", "optional"])
@pytest.mark.parametrize("value,supported", [("2 mg", False), ("2 mg mL-1", True)])
def test_scientific_source_matching_preserves_reciprocal_unit_continuation(
    stage, value, supported,
):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    source = "A used 2mg mL−1."
    matrix, fields = _optional_scientific_value(value)
    if stage == "provisional":
        matrix, issues = ISAValueMapperAgent._clear_unverified_provisional_values(
            matrix, fields, {}, source,
        )
        assert matrix["assay"]["rows"] == [{"concentration": value if supported else ""}]
        assert bool(issues) is not supported
    else:
        matrix, removed = ISAValueMapperAgent._prune_uninformative_optional_columns(
            matrix, fields, {}, source_text=source,
        )
        assert bool(removed) is not supported
        assert matrix["assay"]["columns"] == (["concentration"] if supported else [])


@pytest.mark.parametrize("stage", ["provisional", "optional"])
@pytest.mark.parametrize("field_name,source,value,supported", [
    ("measurement unit", "The unit was mm.", "mM", False),
    ("measurement unit", "The unit was mM.", "mM", True),
    ("medium", "A used mm buffer.", "mM buffer", False),
    ("medium", "A used mM buffer.", "mM buffer", True),
    ("treatment", "Samples received cold exposure.", "cold exposure", True),
])
def test_scientific_source_matching_preserves_case_without_inferred_unit_types(
    stage, field_name, source, value, supported,
):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix, fields = _optional_scientific_value(value, field_name)
    if stage == "provisional":
        matrix, issues = ISAValueMapperAgent._clear_unverified_provisional_values(
            matrix, fields, {}, source,
        )
        assert matrix["assay"]["rows"] == [{field_name: value if supported else ""}]
        assert bool(issues) is not supported
    else:
        matrix, removed = ISAValueMapperAgent._prune_uninformative_optional_columns(
            matrix, fields, {}, source_text=source,
        )
        assert bool(removed) is not supported
        assert matrix["assay"]["columns"] == ([field_name] if supported else [])


def _group_scientific_value_case(second_evidence, *, value="20 mM"):
    matrix = {"assay": {
        "columns": ["concentration"],
        "rows": [{"concentration": value}, {"concentration": value}],
    }}
    fields = {"assay": [{
        "field_name": "concentration", "value": value,
        "status": "confirmed", "value_scope": "level",
    }]}
    plan = {
        "design_spec": {"design_groups": [
            {"group_id": "a", "evidence": f"Concentration unit is millimolar (mM). A used {value}."},
            {"group_id": "b", "evidence": second_evidence},
        ]},
        "levels": [{"level": "assay", "entities": [
            {"row_id": "assay_a", "source_group": "a", "attributes": []},
            {"row_id": "assay_b", "source_group": "b", "attributes": []},
        ]}],
    }
    return matrix, fields, plan


@pytest.mark.parametrize("second_evidence", ["B used 20mM.", "B used 20 millimolar."])
def test_group_scope_keeps_equivalent_source_quantities(second_evidence):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix, fields, plan = _group_scientific_value_case(second_evidence)
    matrix, issues = ISAValueMapperAgent._clear_values_outside_group_evidence_scope(
        matrix, fields, plan,
    )

    assert matrix["assay"]["rows"] == [{"concentration": "20 mM"}] * 2
    assert issues == []


@pytest.mark.parametrize("second_evidence", [
    "B used 12 mM.", "B used -2 mM.", "B used 2 mm.", "B used 2e1 mM.",
])
def test_group_scope_rejects_distinct_source_quantities(second_evidence):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix, fields, plan = _group_scientific_value_case(second_evidence, value="2 mM")
    matrix, issues = ISAValueMapperAgent._clear_values_outside_group_evidence_scope(
        matrix, fields, plan,
    )

    assert matrix["assay"]["rows"] == [
        {"concentration": "2 mM"}, {"concentration": ""},
    ]
    assert len(issues) == 1


@pytest.mark.parametrize("planned_value,expected", [("20 mM", "20 mM"), ("40 mM", "")])
def test_group_scope_protects_only_the_same_row_plan_mapped_value(planned_value, expected):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix, fields, plan = _group_scientific_value_case("B used the second protocol.")
    plan["levels"][0]["entities"][1]["attributes"] = [{
        "field_name": "concentration", "value": planned_value, "origin": "explicit",
    }]
    plan["design_spec"]["design_groups"].append({
        "group_id": "c", "evidence": "C used a third protocol.",
    })
    plan["levels"][0]["entities"].append({
        "row_id": "assay_c", "source_group": "c", "attributes": [],
    })
    matrix["assay"]["rows"].append({"concentration": "20 mM"})

    matrix, _ = ISAValueMapperAgent._clear_values_outside_group_evidence_scope(
        matrix, fields, plan,
    )

    assert matrix["assay"]["rows"] == [
        {"concentration": "20 mM"}, {"concentration": expected}, {"concentration": ""},
    ]


def _capture_mapping_prompts(monkeypatch, fields, entity_plan=None, document_context=""):
    import asyncio
    import logging
    from types import SimpleNamespace

    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    captured = {}

    async def capture_call(messages, **kwargs):
        captured["messages"] = messages
        return SimpleNamespace(
            content=json.dumps({"assay": {"columns": [], "rows": []}})
        )

    agent = ISAValueMapperAgent.__new__(ISAValueMapperAgent)
    agent.logger = logging.getLogger("test_mapping_prompt")
    monkeypatch.setattr(
        agent, "_get_llm", lambda state: SimpleNamespace(_call_llm=capture_call)
    )
    asyncio.run(
        agent._build_matrix_with_llm(
            fields_by_level=fields,
            knowledge_items=[],
            document_context=document_context,
            critic_feedback=None,
            planner_instruction=None,
            prior_memory_context=None,
            state={"entity_plan": entity_plan or {}},
        )
    )
    return captured["messages"]


def test_mapping_source_evidence_is_not_displaced_by_duplicate_large_plan(monkeypatch):
    from fairifier.utils.entity_plan import render_entity_plan_for_prompt

    plan = {"levels": [{"level": "assay", "entities": [{
        "row_id": "assay_a", "parent_row_id": "sample_a",
        "label": "A source-defined entity " * 600,
    }]}]}
    identity_context = render_entity_plan_for_prompt(plan)
    source_context = "source_001:120 The measured concentration was 2.5 mM."
    assert len(identity_context) > 8000
    messages = _capture_mapping_prompts(
        monkeypatch, {}, plan, identity_context + "\n\n" + source_context,
    )
    prompt = messages[-1].content

    assert source_context in prompt
    assert prompt.count("AUTHORITATIVE FIVE-LEVEL ISOSA PLAN") == 1


def test_mapping_virtual_files_keep_complete_plan_separate_from_source(monkeypatch):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.entity_plan import render_entity_plan_for_prompt

    plan = {"levels": [{"level": "assay", "entities": [
        {"row_id": f"assay_{i}", "parent_row_id": f"sample_{i}",
         "label": "Source-defined material " * 30}
        for i in range(30)
    ]}]}
    source_context = "source_001:120 The measured concentration was 2.5 mM."
    agent = object.__new__(ISAValueMapperAgent)
    monkeypatch.setattr(agent, "_maybe_create_file_data", lambda text: text)

    files = agent._build_ivm_seed_files(
        fields_by_level={}, knowledge_items=[], source_workspace={},
        document_context=render_entity_plan_for_prompt(plan) + "\n\n" + source_context,
        entity_plan=plan,
    )

    assert json.loads(files["/workspace/entity_plan.json"]) == plan
    assert source_context in files["/workspace/ivm_context.md"]
    assert "AUTHORITATIVE FIVE-LEVEL ISOSA PLAN" not in files["/workspace/ivm_context.md"]


@pytest.mark.parametrize("done_reason", ["length", "stop"])
def test_bounded_mapping_handles_ollama_completion_reason(monkeypatch, done_reason):
    import asyncio
    from types import SimpleNamespace
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    payload = {"assay": {"rows": [{"assay identifier": "assay_a"}]}}

    async def call(messages, **kwargs):
        return SimpleNamespace(content=json.dumps(payload), response_metadata={"done_reason": done_reason})

    agent = object.__new__(ISAValueMapperAgent)
    monkeypatch.setattr(agent, "_get_llm", lambda state: SimpleNamespace(_call_llm=call))
    batch = {"target_level": "assay", "row_ids": ["assay_a"],
             "field_names": ["assay identifier", "sample identifier"]}
    invocation = agent._build_matrix_with_llm_single({}, [], "", None, None, None, {}, batch=batch)
    if done_reason == "length":
        with pytest.raises(ValueError, match="truncated"):
            asyncio.run(invocation)
    else:
        assert asyncio.run(invocation)["assay"]["rows"] == payload["assay"]["rows"]


@pytest.mark.parametrize("failure", [
    "malformed_root", "malformed_root_rows", "malformed_root_columns", "malformed_root_column_names",
    "service_failure", "value_error_service_failure",
    "service_failure_after_batch", "value_error_service_failure_after_batch",
])
def test_bounded_root_failure_keeps_explicit_review_and_correct_batch_scope(monkeypatch, failure):
    import asyncio
    import logging
    from types import SimpleNamespace
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    levels = ["investigation", "study", "observationunit", "sample", "assay"]
    plan = {"levels": [{"level": level, "entities": [{
        "row_id": f"{level}_a", "parent_row_id": f"{levels[index - 1]}_a" if index else None,
        "attributes": [], "source_group": "group_a",
    }]} for index, level in enumerate(levels)]}
    field_count = 21 if failure.endswith("after_batch") else 11
    fields = {
        "investigation": [{"field_name": "investigation title", "value": "Source title"}],
        "assay": [{"field_name": f"measurement {index}", "value": "source fact"} for index in range(field_count)],
    }
    calls = []

    async def call(messages, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            if failure.endswith("after_batch"):
                return SimpleNamespace(content='{"investigation": {"rows": []}}', response_metadata={})
            if failure == "malformed_root_rows":
                return SimpleNamespace(content='{"investigation": {"rows": [null, "bad"]}}', response_metadata={})
            if failure in {"malformed_root_columns", "malformed_root_column_names"}:
                columns = "bad" if failure == "malformed_root_columns" else ["investigation title", None]
                return SimpleNamespace(content=json.dumps({"investigation": {
                    "columns": columns, "rows": [{"investigation title": "Source title"}],
                }}), response_metadata={})
            if failure == "service_failure":
                raise RuntimeError("Service unavailable")
            if failure == "value_error_service_failure":
                raise ValueError("Provider returned no response")
            return SimpleNamespace(content='{"investigation": []}', response_metadata={})
        if len(calls) == 3 and failure.endswith("after_batch"):
            error_type = ValueError if failure.startswith("value_error") else RuntimeError
            raise error_type("Provider unavailable during later batch")
        scope, _ = json.JSONDecoder().raw_decode(messages[-1].content.split("Mapping batch scope:\n", 1)[1])
        system_text = " ".join(str(getattr(m, "content", "")) for m in messages[:-1])
        assert f'"assay identifier": "{scope["row_ids"][0]}"' in system_text
        assert "Never write '' cells" in system_text
        assert "using '' when there is no value" not in system_text
        payload = {"assay": {"rows": [{
            "assay identifier": row_id,
            **{name: "source fact" for name in scope["field_names"] if name.startswith("measurement")},
        } for row_id in scope["row_ids"]]}}
        return SimpleNamespace(content=json.dumps(payload), response_metadata={})

    agent = object.__new__(ISAValueMapperAgent)
    agent.logger = logging.getLogger("test_bounded_root_failure")
    monkeypatch.setattr(agent, "_get_llm", lambda state: SimpleNamespace(_call_llm=call))
    state = {"entity_plan": plan}
    matrix = asyncio.run(agent._build_matrix_with_llm(fields, [], "", None, None, None, state))
    report = json.loads(state["artifacts"]["isa_mapping_batches"])
    assert report["issues"]
    assert state["needs_human_review"] is True
    assert not matrix["investigation"]["rows"]
    if failure.startswith("malformed_root"):
        assert len(calls) == 3
        assert matrix["assay"]["rows"][0]["measurement 10"] == "source fact"
    elif failure.endswith("after_batch"):
        assert len(calls) == 3
        assert matrix["assay"]["rows"][0]["measurement 0"] == "source fact"
        assert matrix["assay"]["rows"][0]["measurement 20"] == ""
        assert report["batches"][-1]["status"] == "failed"
    else:
        assert len(calls) == 1
        assert all(matrix["assay"]["rows"][0][f"measurement {index}"] == "" for index in range(11))


def test_mapping_prompt_preserves_entity_scope_for_distinct_measurements(monkeypatch):
    fields = {
        "assay": [
            {
                "field_name": "measurement value",
                "value": "2.5",
                "entity_id": "assay_a",
                "value_scope": "entity",
                "evidence": "Table 1: specimen A yielded 2.5 mM.",
                "confidence": 0.95,
                "status": "confirmed",
            },
            {
                "field_name": "measurement value",
                "value": "7.5",
                "entity_id": "assay_b",
                "value_scope": "entity",
                "evidence": "Table 1: specimen B yielded 7.5 mM.",
                "confidence": 0.95,
                "status": "confirmed",
            },
            {
                "field_name": "measurement unit",
                "value": "mM",
                "entity_id": None,
                "value_scope": "level",
                "evidence": "All concentrations are reported in mM.",
                "confidence": 0.95,
                "status": "confirmed",
            },
            {
                "field_name": "buffer",
                "value": "phosphate",
                "evidence": "A phosphate buffer is mentioned without a specimen link.",
                "confidence": 0.5,
                "status": "provisional",
            },
        ]
    }
    prompt = _capture_mapping_prompts(monkeypatch, fields)[-1].content
    summary, _ = json.JSONDecoder().raw_decode(
        prompt.split("Extracted metadata fields:\n", 1)[1]
    )
    actual = summary["assay"]["fields"]
    assert len(actual) == 4
    for extracted, supplied in zip(actual, fields["assay"]):
        assert extracted["value"] == supplied["value"]
        assert extracted["evidence"] == supplied["evidence"]
        assert "entity_id" in extracted
        assert "value_scope" in extracted
        assert extracted["entity_id"] == supplied.get("entity_id")
        assert extracted["value_scope"] == supplied.get("value_scope")


def test_mapping_prompt_keeps_numeric_zero_distinct_from_missing(monkeypatch):
    fields = {
        "assay": [
            {"field_name": "measurement value", "value": value}
            for value in (0, 0.0, None)
        ]
    }
    prompt = _capture_mapping_prompts(monkeypatch, fields)[-1].content
    summary, _ = json.JSONDecoder().raw_decode(
        prompt.split("Extracted metadata fields:\n", 1)[1]
    )

    assert [field["value"] for field in summary["assay"]["fields"]] == [
        "0", "0.0", ""
    ]


def test_mapping_prompt_uses_authoritative_identifiers_without_invention(monkeypatch):
    plan = {
        "levels": [
            {
                "level": "sample",
                "entities": [
                    {
                        "row_id": "canonical_sample_a",
                        "external_identifier": "source-specimen-A",
                        "parent_row_id": "planned_observation_a",
                    },
                    {
                        "row_id": "canonical_sample_b",
                        "parent_row_id": "planned_observation_a",
                    },
                ],
            }
        ]
    }
    messages = _capture_mapping_prompts(monkeypatch, {}, plan)
    identifier_rule = messages[0].content.split("4. ", 1)[1].split("5. ", 1)[0].lower()

    assert "authoritative" in identifier_rule and "plan" in identifier_rule
    assert "row_id" in identifier_rule
    assert "external_identifier" in identifier_rule
    assert "do not invent" in identifier_rule
    for identifier in (
        "canonical_sample_a", "canonical_sample_b", "source-specimen-A",
        "planned_observation_a",
    ):
        assert identifier in messages[-1].content


def test_optional_field_survives_equal_value_in_a_different_planned_field():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "assay": {
            "columns": ["assay identifier", "temperature", "duration"],
            "rows": [
                {"assay identifier": "assay_a", "temperature": "30", "duration": "30"}
            ],
        }
    }
    fields = {
        "assay": [
            {
                "field_name": "temperature",
                "value": "30",
                "requirement": "OPTIONAL",
                "status": "confirmed",
                "evidence": "The reaction ran at 30 degrees C.",
            },
            {
                "field_name": "duration",
                "value": "30",
                "requirement": "OPTIONAL",
                "status": "confirmed",
                "evidence": "The reaction ran for 30 minutes.",
            },
        ]
    }
    plan = {
        "levels": [
            {
                "level": "assay",
                "entities": [
                    {
                        "row_id": "assay_a",
                        "attributes": [
                            {
                                "field_name": "temperature",
                                "value": "30",
                                "origin": "explicit",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    result, removed = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix, fields, plan,
        source_text="The reaction ran at 30 degrees C for 30 minutes.",
    )

    assert "duration" in result["assay"]["columns"]
    assert result["assay"]["rows"][0]["duration"] == "30"
    assert removed == {}


def test_supported_numeric_zero_is_retained_in_optional_measurement_column():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent, _is_missing_cell

    assert not _is_missing_cell(0)
    assert not _is_missing_cell(0.0)
    matrix = {
        "assay": {
            "columns": ["assay identifier", "measurement"],
            "rows": [{"assay identifier": "assay_a", "measurement": 0}],
        }
    }
    fields = {
        "assay": [
            {
                "field_name": "measurement",
                "value": 0,
                "requirement": "OPTIONAL",
                "status": "confirmed",
                "confidence": 0.95,
                "evidence": "The measured concentration was 0 mM.",
            }
        ]
    }

    result, removed = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix, fields, {"levels": []},
        source_text="The measured concentration was 0 mM.",
    )

    assert "measurement" in result["assay"]["columns"]
    assert result["assay"]["rows"][0]["measurement"] == 0
    assert removed == {}


@pytest.mark.parametrize("left,right,expected", [
    ("7.2", None, "7.2"),
    ("7.2", "", "7.2"),
    ("", "7.2", "7.2"),
    ("7.2", "7.2", "7.2"),
    ("7.2", "8.1", ""),
    ("1 mM", "1 Mm", ""),
    (0, 0, 0),
])
def test_selected_columns_preserve_case_variant_values_without_conflict_winner(left, right, expected):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    row = {"Assay Identifier": "assay_a", "solution pH": left}
    if right is not None:
        row["solution ph"] = right
    matrix = {"assay": {"columns": list(row), "rows": [row]}}
    fields = {"assay": [{"field_name": "assay identifier"}, {"field_name": "solution pH"}]}

    result = ISAValueMapperAgent._ensure_selected_field_columns(matrix, fields)

    assert result["assay"]["rows"] == [{"assay identifier": "assay_a", "solution ph": expected}]
    assert result["assay"]["columns"] == ["assay identifier", "solution ph"]


def test_selected_columns_reject_case_conflicting_identity_rows(caplog):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {"assay": {"columns": ["assay identifier", "Assay Identifier", "solution pH"], "rows": [
        {"assay identifier": "assay_a", "Assay Identifier": "assay_b", "solution pH": "7.2"},
    ]}}

    result = ISAValueMapperAgent._ensure_selected_field_columns(matrix, {"assay": []})

    assert result["assay"]["rows"] == []
    assert "conflict" in caplog.text.lower()


@pytest.mark.parametrize("field_name,ada_value,ben_value", [
    ("firstname", "Ada", "Ben"),
    ("lastname", "One", "Two"),
    ("email address", "ada@example.test", ""),
    ("email address", "ada@example.test", "ben@example.test"),
    ("orcid", "0000-0001-1111-1111", "0000-0002-2222-2222"),
    ("organization", "Institute A", "Institute B"),
    ("department", "Department A", "Department B"),
])
@pytest.mark.parametrize("value_scope", ["entity", "level"])
def test_root_restoration_keeps_contact_values_bound_through_projection(
    field_name, ada_value, ben_value, value_scope,
):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.entity_plan import project_matrix_onto_entity_plan

    contacts = [{"firstname": "Ada", "lastname": "One"},
                {"firstname": "Ben", "lastname": "Two"}]
    plan = {
        "levels": [{"level": "investigation", "entities": [
            {"row_id": "investigation_a", "label": "Shared research study", "attributes": []},
        ]}],
        "investigation_contacts": contacts,
    }
    matrix = {"investigation": {
        "columns": list(dict.fromkeys([
            "investigation identifier", "investigation title", "firstname", "lastname", field_name,
        ])),
        "rows": [
            {"investigation identifier": "investigation_a", "investigation title": "",
             **contact, field_name: value}
            for contact, value in zip(contacts, (ada_value, ben_value))
        ],
    }}
    fields = {"investigation": [
        {"field_name": field_name, "value": ada_value, "confidence": 0.95,
         "status": "confirmed", "entity_id": "Ada One", "value_scope": value_scope,
         "evidence": f"Contact Ada One: {ada_value}."},
        {"field_name": "investigation title", "value": "Shared research study",
         "confidence": 0.95, "status": "confirmed", "value_scope": "level",
         "evidence": "Publication title: Shared research study."},
    ]}

    restored = ISAValueMapperAgent._restore_high_confidence_shared_values(
        matrix, fields, entity_plan=plan, allow_multi_entity_broadcast=False,
    )

    assert [row[field_name] for row in restored["investigation"]["rows"]] == [ada_value, ben_value]
    assert [row["investigation title"] for row in restored["investigation"]["rows"]] == ["Shared research study"] * 2
    projected = project_matrix_onto_entity_plan(restored, plan)
    rows = projected["investigation"]["rows"]
    assert [row[field_name] for row in rows] == [ada_value, ben_value]
    assert [row["investigation title"] for row in rows] == ["Shared research study"] * 2


def test_root_contact_details_from_plan_remain_available_without_global_restoration():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.utils.entity_plan import project_matrix_onto_entity_plan

    plan = {
        "levels": [{"level": "investigation", "entities": [
            {"row_id": "investigation_a", "attributes": []},
        ]}],
        "investigation_contacts": [
            {"firstname": "Ada", "lastname": "One", "email address": "ada@example.test"},
            {"firstname": "Ben", "lastname": "Two"},
        ],
    }
    matrix = {"investigation": {"columns": [], "rows": [{}]}}
    fields = {"investigation": [
        {"field_name": "email address", "value": "ada@example.test", "confidence": 0.95,
         "status": "confirmed", "evidence": "Contact Ada One: ada@example.test."},
    ]}

    restored = ISAValueMapperAgent._restore_high_confidence_shared_values(
        matrix, fields, entity_plan=plan,
    )
    rows = project_matrix_onto_entity_plan(restored, plan)["investigation"]["rows"]

    assert [row["email address"] for row in rows] == ["ada@example.test", ""]


def test_optional_pruning_is_per_cell_not_per_column():
    """One unsupported cell must not erase source-quoted siblings in its column."""
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    matrix = {
        "assay": {
            "columns": ["assay identifier", "measurement value"],
            "rows": [
                {"assay identifier": "a1", "measurement value": "5.28 ± 0.19"},
                {"assay identifier": "a2", "measurement value": "2.31 ± 0.01"},
                {"assay identifier": "a3", "measurement value": "roughly optimal"},
            ],
        }
    }
    fields = {"assay": [{"field_name": "measurement value", "requirement": "OPTIONAL"}]}
    source = "<td>Km</td><td>5.28 ± 0.19</td><td>2.31 ± 0.01</td>"

    matrix, removed = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix, fields, {}, source_text=source,
    )

    assert removed == {}
    assert [row["measurement value"] for row in matrix["assay"]["rows"]] == [
        "5.28 ± 0.19", "2.31 ± 0.01", "",
    ]


def test_plan_determined_fields_are_those_fixed_on_every_entity():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    plan = {"levels": [{"level": "assay", "entities": [
        {"row_id": "a1", "attributes": [
            {"field_name": "reaction temperature", "value": "40"},
            {"field_name": "reaction pH", "value": "8"}]},
        {"row_id": "a2", "attributes": [
            {"field_name": "reaction temperature", "value": "60"},
            {"field_name": "reaction pH", "value": ""}]},
    ]}]}
    assert ISAValueMapperAgent._plan_determined_fields(plan) == {"assay": {"reaction temperature"}}


@pytest.mark.parametrize(("value", "kept"), [
    ("40.3 s^-1", True),
    ("9.98 ± 0.49 mM", True),
    ("9.98 mM", True),                      # mean without its ± term
    ("87.9 µmol·min^-1·mg^-1", True),
    ("87.9 umol min^-1 mg^-1", True),       # ASCII micro prefix
    ("87.9 ± 0.8 µmol/min/mg", True),       # solidus division
    ("87.9 umol/mg", False),                # a different unit
    ("40.3 mM", False),                    # unit of another column
    ("41.3 s^-1", False),                   # number not in the table
    ("0.49 mM", False),                     # error term is not the value
])
def test_provisional_quantity_may_take_its_unit_from_the_table_header(value, kept):
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.services.publication_tables import DERIVED_TABLE_ROWS_HEADER

    source = (
        "Kinetic parameters are listed in Table 2.\n" + DERIVED_TABLE_ROWS_HEADER + "\n"
        r"Substrates = BHET; \( V_{max} \) (\( \mu mol·min^{-1}·mg^{-1} \)) | IsPETase = 87.9 ± 0.8; "
        r"\( K_m \) (mM) | IsPETase = 9.98 ± 0.49; \( k_{cat} \) (\( sec^{-1} \)) | IsPETase = 40.3"
    )
    matrix = {"assay": {"columns": ["result"], "rows": [{"result": value}]}}
    fields = {"assay": [{"field_name": "result", "status": "provisional"}]}
    cleaned, _ = ISAValueMapperAgent._clear_unverified_provisional_values(
        matrix, fields, {"levels": []}, source,
    )
    assert (cleaned["assay"]["rows"][0]["result"] == value) is kept
