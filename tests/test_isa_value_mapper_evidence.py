"""Tests for ISAValueMapper EvidenceStore integration (Plan §4.1)."""

from __future__ import annotations

import json
from pathlib import Path


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
