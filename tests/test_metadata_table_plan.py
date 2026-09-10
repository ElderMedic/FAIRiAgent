"""Tests for source-grounded metadata-table entity materialization."""

from __future__ import annotations

import json

from fairifier.utils.metadata_table_plan import (
    materialize_record_table_plans,
    metadata_table_profiles,
    metadata_table_profiles_for_record_plans,
    normalized_table_rows,
)


def _workspace(tmp_path, rows):
    table_dir = tmp_path / "tables"
    table_dir.mkdir()
    table_path = table_dir / "source_001_01.jsonl"
    table_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    manifest = {
        "sources": [
            {
                "source_id": "source_001",
                "path": "metadata.xlsx",
                "source_role": "metadata_table",
                "tables": [
                    {"name": "Sample metadata", "path": "tables/source_001_01.jsonl"}
                ],
            }
        ]
    }
    return {"root_dir": str(tmp_path), "manifest": manifest}, table_path


def _raw_rows():
    return [
        {
            "All records in the study": "Comment",
            "Unnamed: 1": "",
            "Unnamed: 2": "",
            "Unnamed: 3": "",
        },
        {
            "All records in the study": "sample label",
            "Unnamed: 1": "project",
            "Unnamed: 2": "run",
            "Unnamed: 3": "condition",
        },
        {
            "All records in the study": "sample-a",
            "Unnamed: 1": "study-1",
            "Unnamed: 2": "run-a",
            "Unnamed: 3": "control",
        },
        {
            "All records in the study": "sample-b",
            "Unnamed: 1": "study-1",
            "Unnamed: 2": "run-b",
            "Unnamed: 3": "treated",
        },
        {
            "All records in the study": "sample-c",
            "Unnamed: 1": "study-2",
            "Unnamed: 2": "run-c",
            "Unnamed: 3": "control",
        },
    ]


def _root_levels():
    return {
        "investigation": {
            "entities": [
                {
                    "row_id": "investigation_001",
                    "label": "Investigation",
                    "parent_row_id": None,
                    "external_identifier": None,
                    "source_group": "root",
                    "attributes": [],
                }
            ]
        },
        "study": {
            "entities": [
                {
                    "row_id": "study_001",
                    "label": "Study",
                    "parent_row_id": "investigation_001",
                    "external_identifier": None,
                    "source_group": "root",
                    "attributes": [],
                }
            ]
        },
    }


def _record_plan():
    return {
        "source_id": "source_001",
        "table_name": "Sample metadata",
        "study_row_id": "study_001",
        "study_identifier_value": "study-1",
        "covers_complete_focal_study": True,
        "filters": [{"column": "project", "value": "study-1"}],
        "sample_identifier_column": "sample label",
        "assay_identifier_column": "run",
        "observation_unit_columns": ["condition"],
        "expected_observation_unit_count": 2,
        "expected_sample_count": 2,
        "expected_assay_count": 2,
        "group_column": None,
        "description_columns": ["condition"],
        "column_mappings": [],
        "evidence": "The table enumerates all records in the study.",
    }


def test_promotes_embedded_header_and_profiles_table(tmp_path):
    workspace, table_path = _workspace(tmp_path, _raw_rows())

    columns, records, header_index = normalized_table_rows(table_path)
    profiles = metadata_table_profiles(workspace)

    assert header_index == 1
    assert columns == ["sample label", "project", "run", "condition"]
    assert len(records) == 3
    assert profiles[0]["record_count"] == 3
    project = next(
        item
        for item in profiles[0]["column_distributions"]
        if item["column"] == "project"
    )
    assert project["top_values"][0] == {"value": "study-1", "count": 2}
    assert project["list_like_count"] == 0
    assert project["globally_scalar_unique"] is False
    assert profiles[0]["globally_scalar_unique_columns"] == [
        "sample label",
        "run",
    ]


def test_record_plan_profile_uses_only_exactly_filtered_focal_rows(tmp_path):
    workspace, _ = _workspace(tmp_path, _raw_rows())

    profiles = metadata_table_profiles_for_record_plans(
        workspace,
        [_record_plan()],
    )

    assert len(profiles) == 1
    profile = profiles[0]
    assert profile["record_count"] == 2
    assert profile["unfiltered_record_count"] == 3
    assert profile["applied_filters"] == [
        {"column": "project", "value": "study-1"}
    ]
    condition = next(
        item
        for item in profile["column_distributions"]
        if item["column"] == "condition"
    )
    assert condition["top_values"] == [
        {"value": "control", "count": 1},
        {"value": "treated", "count": 1},
    ]
    assert {row["sample label"] for row in profile["example_rows"]} == {
        "sample-a",
        "sample-b",
    }


def test_keeps_real_physical_headers(tmp_path):
    workspace, table_path = _workspace(
        tmp_path,
        [
            {"sample": "sample-a", "project": "study-1", "run": "run-a"},
            {"sample": "sample-b", "project": "study-1", "run": "run-b"},
        ],
    )

    columns, records, header_index = normalized_table_rows(table_path)

    assert workspace
    assert header_index == -1
    assert columns == ["sample", "project", "run"]
    assert len(records) == 2


def test_materializes_exact_filtered_records_and_links(tmp_path):
    workspace, _ = _workspace(tmp_path, _raw_rows())

    plan, errors = materialize_record_table_plans(
        [_record_plan()],
        workspace=workspace,
        root_levels=_root_levels(),
        field_catalog={},
    )

    assert errors == []
    levels = {item["level"]: item for item in plan["levels"]}
    assert levels["study"]["entities"][0]["external_identifier"] == "study-1"
    assert levels["observationunit"]["cardinality"] == 2
    assert [item["external_identifier"] for item in levels["sample"]["entities"]] == [
        "sample-a",
        "sample-b",
    ]
    assert [item["external_identifier"] for item in levels["assay"]["entities"]] == [
        "run-a",
        "run-b",
    ]
    sample_rows = {item["row_id"]: item for item in levels["sample"]["entities"]}
    assert all(
        item["parent_row_id"] in sample_rows for item in levels["assay"]["entities"]
    )


def test_reconciles_authoritative_grouping_with_audited_design_scopes(tmp_path):
    workspace, _ = _workspace(
        tmp_path,
        [
            {
                "sample": "a-1",
                "project": "study-1",
                "run": "run-a-1",
                "branch": "development_time_series",
                "coarse tissue": "embryo",
                "time point": "day 1",
            },
            {
                "sample": "a-2",
                "project": "study-1",
                "run": "run-a-2",
                "branch": "development_time_series",
                "coarse tissue": "embryo",
                "time point": "day 2",
            },
            {
                "sample": "b-1",
                "project": "study-1",
                "run": "run-b-1",
                "branch": "method_comparison",
                "coarse tissue": "embryo",
                "time point": "day 3",
            },
            {
                "sample": "b-2",
                "project": "study-1",
                "run": "run-b-2",
                "branch": "method_comparison",
                "coarse tissue": "embryo",
                "time point": "day 3",
            },
        ],
    )
    plan = {
        "source_id": "source_001",
        "table_name": "Sample metadata",
        "study_row_id": "study_001",
        "study_identifier_value": "study-1",
        "covers_complete_focal_study": True,
        "filters": [{"column": "project", "value": "study-1"}],
        "sample_identifier_column": "sample",
        "assay_identifier_column": "run",
        "observation_unit_columns": ["coarse tissue"],
        "expected_observation_unit_count": 4,
        "expected_sample_count": 4,
        "expected_assay_count": 4,
        "group_column": "branch",
        "description_columns": ["coarse tissue", "time point"],
        "column_mappings": [],
        "derived_mappings": [],
        "source_extension_mappings": [],
        "excluded_columns": [],
    }
    design_groups = [
        {
            "group_id": "group_001",
            "label": "Development time series",
            "evidence": "Two developmental stages were observed.",
            "dimensions": [
                {
                    "name": "stage",
                    "explicit_values": ["day 1", "day 2"],
                    "semantic_role": "observation_condition",
                    "applies_to": ["observationunit", "sample", "assay"],
                }
            ],
        },
        {
            "group_id": "group_002",
            "label": "Method comparison",
            "evidence": "Prepared inputs were compared from one observed condition.",
            "dimensions": [
                {
                    "name": "method",
                    "explicit_values": ["A", "B"],
                    "semantic_role": "assay_process",
                    "applies_to": ["sample", "assay"],
                }
            ],
        },
    ]

    result, errors = materialize_record_table_plans(
        [plan],
        workspace=workspace,
        root_levels=_root_levels(),
        field_catalog={},
        design_groups=design_groups,
    )

    assert errors == []
    levels = {item["level"]: item for item in result["levels"]}
    assert levels["observationunit"]["cardinality"] == 3
    assert "['time point'] / 3" in result["materialization_notes"][0]


def test_retains_list_like_assay_ids_as_context_without_splitting(tmp_path):
    rows = _raw_rows()
    rows[2]["Unnamed: 2"] = "run-a, run-a2"
    workspace, _ = _workspace(tmp_path, rows)

    plan, errors = materialize_record_table_plans(
        [_record_plan()],
        workspace=workspace,
        root_levels=_root_levels(),
        field_catalog={},
    )

    assert errors == []
    levels = {item["level"]: item for item in plan["levels"]}
    assert [item["external_identifier"] for item in levels["assay"]["entities"]] == [
        "sample-a",
        "sample-b",
    ]
    first_attributes = levels["assay"]["entities"][0]["attributes"]
    assert first_attributes[0]["dimension_name"] == "run"
    assert first_attributes[0]["value"] == "run-a, run-a2"
    assert len(plan["materialization_notes"]) == 1


def test_rejects_list_like_sample_identifiers(tmp_path):
    rows = _raw_rows()
    rows[2]["All records in the study"] = "sample-a, sample-a2"
    workspace, _ = _workspace(tmp_path, rows)

    plan, errors = materialize_record_table_plans(
        [_record_plan()],
        workspace=workspace,
        root_levels=_root_levels(),
        field_catalog={},
    )

    assert plan is None
    assert any("list-like sample IDs" in error for error in errors)


def test_refines_observation_grouping_to_preserve_declared_conditions(tmp_path):
    workspace, _ = _workspace(
        tmp_path,
        [
            {
                "sample": "sample-a",
                "project": "study-1",
                "run": "run-a",
                "tissue": "embryo",
                "time": "early",
            },
            {
                "sample": "sample-b",
                "project": "study-1",
                "run": "run-b",
                "tissue": "embryo",
                "time": "early",
            },
            {
                "sample": "sample-c",
                "project": "study-1",
                "run": "run-c",
                "tissue": "embryo",
                "time": "late",
            },
            {
                "sample": "sample-d",
                "project": "study-1",
                "run": "run-d",
                "tissue": "embryo",
                "time": "late",
            },
        ],
    )
    roots = _root_levels()
    roots["observationunit"] = {"cardinality": 2, "entities": []}
    record_plan = {
        **_record_plan(),
        "sample_identifier_column": "sample",
        "assay_identifier_column": "run",
        "observation_unit_columns": ["tissue"],
        "description_columns": ["time"],
        "expected_observation_unit_count": 2,
        "expected_sample_count": 4,
        "expected_assay_count": 4,
    }

    plan, errors = materialize_record_table_plans(
        [record_plan],
        workspace=workspace,
        root_levels=roots,
        field_catalog={},
    )

    assert errors == []
    levels = {item["level"]: item for item in plan["levels"]}
    assert levels["observationunit"]["cardinality"] == 2
    assert "refined observation-unit grouping" in plan["materialization_notes"][0]


def test_materializes_standard_mappings_and_source_extensions_not_in_descriptions(
    tmp_path,
):
    workspace, _ = _workspace(
        tmp_path,
        [
            {
                "sample": "sample-a",
                "project": "study-1",
                "run": "run-a",
                "condition": "control",
                "tissue": "leaf",
                "read count": 101,
            },
            {
                "sample": "sample-b",
                "project": "study-1",
                "run": "run-b",
                "condition": "treated",
                "tissue": "root",
                "read count": 202,
            },
        ],
    )
    record_plan = {
        **_record_plan(),
        "sample_identifier_column": "sample",
        "assay_identifier_column": "run",
        "column_mappings": [
            {
                "column": "tissue",
                "level": "sample",
                "field_name": "organism part",
            }
        ],
        "source_extension_mappings": [
            {
                "column": "read count",
                "level": "assay",
                "data_type": "integer",
                "definition": "Number of input reads recorded by the source.",
            }
        ],
    }

    plan, errors = materialize_record_table_plans(
        [record_plan],
        workspace=workspace,
        root_levels=_root_levels(),
        field_catalog={"sample": ["organism part"]},
    )

    assert errors == []
    levels = {item["level"]: item for item in plan["levels"]}
    assert levels["sample"]["entities"][0]["attributes"][-1] == {
        "dimension_name": "tissue",
        "field_name": "organism part",
        "value": "leaf",
        "origin": "explicit",
    }
    assert levels["assay"]["entities"][0]["attributes"] == [
        {
            "dimension_name": "read count",
            "field_name": "read count",
            "value": "101",
            "origin": "explicit",
        }
    ]
    assert plan["source_extension_fields"][0]["field_name"] == "read count"
    assert plan["source_coverage"]["complete"] is True


def test_reports_unmapped_source_columns_in_coverage_ledger(tmp_path):
    workspace, _ = _workspace(
        tmp_path,
        [
            {
                "sample": "sample-a",
                "project": "study-1",
                "run": "run-a",
                "condition": "control",
                "unreviewed metric": 101,
            },
            {
                "sample": "sample-b",
                "project": "study-1",
                "run": "run-b",
                "condition": "treated",
                "unreviewed metric": 202,
            },
        ],
    )
    record_plan = {
        **_record_plan(),
        "sample_identifier_column": "sample",
        "assay_identifier_column": "run",
    }

    plan, errors = materialize_record_table_plans(
        [record_plan],
        workspace=workspace,
        root_levels=_root_levels(),
        field_catalog={},
    )

    assert errors == []
    assert plan["source_coverage"]["complete"] is False
    assert plan["source_coverage"]["tables"][0]["unmapped_columns"] == [
        "unreviewed metric"
    ]


def test_derives_source_backed_row_values_with_declarative_rules(tmp_path):
    workspace, _ = _workspace(
        tmp_path,
        [
            {
                "sample": "sample_rep1",
                "project": "study-1",
                "run": "run-a",
                "condition": "control",
            },
            {
                "sample": "sample_rep2",
                "project": "study-1",
                "run": "run-b",
                "condition": "treated",
            },
        ],
    )
    record_plan = {
        **_record_plan(),
        "sample_identifier_column": "sample",
        "assay_identifier_column": "run",
        "derived_mappings": [
            {
                "source_column": "sample",
                "level": "sample",
                "field_name": "replicate",
                "rules": [
                    {"match_type": "suffix", "pattern": "rep1", "value": "1"},
                    {"match_type": "suffix", "pattern": "rep2", "value": "2"},
                ],
                "expected_nonblank_count": 2,
                "evidence": "The source defines the rep suffix as replicate number.",
            },
            {
                "source_column": "condition",
                "level": "sample",
                "field_name": "condition class",
                "source_extension": True,
                "data_type": "string",
                "definition": "Normalized condition class defined by the source.",
                "rules": [
                    {"match_type": "exact", "pattern": "control", "value": "C"},
                    {"match_type": "exact", "pattern": "treated", "value": "T"},
                ],
                "expected_nonblank_count": 2,
                "evidence": "The source defines the two condition classes.",
            },
        ],
    }

    plan, errors = materialize_record_table_plans(
        [record_plan],
        workspace=workspace,
        root_levels=_root_levels(),
        field_catalog={"sample": ["replicate"]},
    )

    assert errors == []
    sample_entities = next(
        item for item in plan["levels"] if item["level"] == "sample"
    )["entities"]
    assert [entity["attributes"][-2]["value"] for entity in sample_entities] == [
        "1",
        "2",
    ]
    assert sample_entities[0]["attributes"][-2]["origin"] == "derived"
    assert sample_entities[0]["attributes"][-1]["field_name"] == "condition class"
    assert any(
        field["field_name"] == "condition class"
        for field in plan["source_extension_fields"]
    )


def test_uses_audited_derived_value_for_observation_grouping(tmp_path):
    workspace, _ = _workspace(
        tmp_path,
        [
            {
                "sample": "early_rep1",
                "project": "study-1",
                "run": "run-a",
                "tissue": "embryo",
            },
            {
                "sample": "early_rep2",
                "project": "study-1",
                "run": "run-b",
                "tissue": "embryo",
            },
            {
                "sample": "late_rep1",
                "project": "study-1",
                "run": "run-c",
                "tissue": "embryo",
            },
            {
                "sample": "late_rep2",
                "project": "study-1",
                "run": "run-d",
                "tissue": "embryo",
            },
        ],
    )
    record_plan = {
        **_record_plan(),
        "sample_identifier_column": "sample",
        "assay_identifier_column": "run",
        "observation_unit_columns": ["tissue"],
        "expected_observation_unit_count": 2,
        "expected_sample_count": 4,
        "expected_assay_count": 4,
        "derived_mappings": [
            {
                "source_column": "sample",
                "level": "observationunit",
                "field_name": "stage",
                "source_extension": True,
                "use_for_observation_unit_grouping": True,
                "rules": [
                    {"match_type": "prefix", "pattern": "early_", "value": "early"},
                    {"match_type": "prefix", "pattern": "late_", "value": "late"},
                ],
                "expected_nonblank_count": 4,
                "evidence": "The source defines early_ and late_ as stage prefixes.",
            }
        ],
    }

    plan, errors = materialize_record_table_plans(
        [record_plan],
        workspace=workspace,
        root_levels=_root_levels(),
        field_catalog={},
    )

    assert errors == []
    levels = {item["level"]: item for item in plan["levels"]}
    assert levels["observationunit"]["cardinality"] == 2
    assert [
        entity["attributes"][-1]["value"]
        for entity in levels["observationunit"]["entities"]
    ] == ["early", "late"]
    assert all(
        entity["parent_row_id"] in {
            item["row_id"] for item in levels["observationunit"]["entities"]
        }
        for entity in levels["sample"]["entities"]
    )


def test_allows_fully_derived_observation_grouping_without_raw_group_column(tmp_path):
    workspace, _ = _workspace(
        tmp_path,
        [
            {"sample": "early_rep1", "project": "study-1", "run": "run-a"},
            {"sample": "early_rep2", "project": "study-1", "run": "run-b"},
            {"sample": "late_rep1", "project": "study-1", "run": "run-c"},
            {"sample": "late_rep2", "project": "study-1", "run": "run-d"},
        ],
    )
    record_plan = {
        **_record_plan(),
        "sample_identifier_column": "sample",
        "assay_identifier_column": "run",
        "observation_unit_columns": [],
        "expected_observation_unit_count": 2,
        "expected_sample_count": 4,
        "expected_assay_count": 4,
        "derived_mappings": [
            {
                "source_column": "sample",
                "level": "observationunit",
                "field_name": "stage",
                "source_extension": True,
                "use_for_observation_unit_grouping": True,
                "rules": [
                    {"match_type": "prefix", "pattern": "early_", "value": "early"},
                    {"match_type": "prefix", "pattern": "late_", "value": "late"},
                ],
                "expected_nonblank_count": 4,
                "evidence": "The source defines early_ and late_ as stage prefixes.",
            }
        ],
    }

    plan, errors = materialize_record_table_plans(
        [record_plan],
        workspace=workspace,
        root_levels=_root_levels(),
        field_catalog={},
    )

    assert errors == []
    levels = {item["level"]: item for item in plan["levels"]}
    assert levels["observationunit"]["cardinality"] == 2
    assert [
        entity["label"] for entity in levels["observationunit"]["entities"]
    ] == ["early", "late"]
    sample_roles = next(
        item
        for item in plan["source_coverage"]["tables"][0]["column_roles"]
        if item["column"] == "sample"
    )["roles"]
    assert sample_roles == ["derivation_input", "sample_identity"]


def test_scopes_derivation_to_exact_branch_and_resolves_regex_capture(tmp_path):
    workspace, _ = _workspace(
        tmp_path,
        [
            {
                "sample": "bc_1",
                "project": "study-1",
                "run": "run-a",
                "condition": "time_series",
            },
            {
                "sample": "bc_2.5ng",
                "project": "study-1",
                "run": "run-b",
                "condition": "dilution",
            },
        ],
    )
    record_plan = {
        **_record_plan(),
        "sample_identifier_column": "sample",
        "assay_identifier_column": "run",
        "expected_sample_count": 2,
        "expected_assay_count": 2,
        "derived_mappings": [
            {
                "source_column": "sample",
                "level": "sample",
                "field_name": "dose",
                "filters": [{"column": "condition", "value": "dilution"}],
                "rules": [
                    {
                        "match_type": "regex",
                        "pattern": r"^bc_\d\.(\d+ng)$",
                        "value": "$1",
                    }
                ],
                "expected_nonblank_count": 1,
                "evidence": "Only dilution rows encode dose after the dot.",
            }
        ],
    }

    plan, errors = materialize_record_table_plans(
        [record_plan],
        workspace=workspace,
        root_levels=_root_levels(),
        field_catalog={"sample": ["dose"]},
    )

    assert errors == []
    samples = next(item for item in plan["levels"] if item["level"] == "sample")
    derived = [
        attribute["value"]
        for entity in samples["entities"]
        for attribute in entity["attributes"]
        if attribute.get("field_name") == "dose"
    ]
    assert derived == ["5ng"]
    assert plan["source_coverage"]["complete"] is True


def test_omits_unsafe_optional_derivation_without_erasing_entity_rows(tmp_path):
    workspace, _ = _workspace(
        tmp_path,
        [
            {
                "sample": "shared_prefix_a",
                "project": "study-1",
                "run": "run-a",
                "condition": "control",
            },
            {
                "sample": "shared_prefix_b",
                "project": "study-1",
                "run": "run-b",
                "condition": "treated",
            },
        ],
    )
    record_plan = {
        **_record_plan(),
        "sample_identifier_column": "sample",
        "assay_identifier_column": "run",
        "derived_mappings": [
            {
                "source_column": "sample",
                "level": "sample",
                "field_name": "replicate",
                "rules": [
                    {
                        "match_type": "prefix",
                        "pattern": "shared_prefix_",
                        "value": "1",
                    }
                ],
                "expected_nonblank_count": 1,
                "evidence": "The proposed convention is ambiguous.",
            }
        ],
    }

    plan, errors = materialize_record_table_plans(
        [record_plan],
        workspace=workspace,
        root_levels=_root_levels(),
        field_catalog={"sample": ["replicate"]},
    )

    assert errors == []
    levels = {item["level"]: item for item in plan["levels"]}
    assert levels["sample"]["cardinality"] == 2
    assert all(
        attribute.get("field_name") != "replicate"
        for entity in levels["sample"]["entities"]
        for attribute in entity["attributes"]
    )
    assert "omitted unsafe optional derivation" in plan["materialization_notes"][0]


def test_rejects_atomic_record_plan_when_grouping_derivation_fails(tmp_path):
    workspace, _ = _workspace(
        tmp_path,
        [
            {"sample": "early_rep1", "project": "study-1", "run": "run-a"},
            {"sample": "late_rep1", "project": "study-1", "run": "run-b"},
        ],
    )
    record_plan = {
        **_record_plan(),
        "sample_identifier_column": "sample",
        "assay_identifier_column": "run",
        "observation_unit_columns": [],
        "expected_observation_unit_count": 2,
        "derived_mappings": [
            {
                "source_column": "sample",
                "level": "observationunit",
                "field_name": "stage",
                "source_extension": True,
                "use_for_observation_unit_grouping": True,
                "rules": [
                    {"match_type": "prefix", "pattern": "early_", "value": "early"}
                ],
                "expected_nonblank_count": 2,
                "evidence": "The source defines the stage prefix convention.",
            }
        ],
    }

    plan, errors = materialize_record_table_plans(
        [record_plan],
        workspace=workspace,
        root_levels=_root_levels(),
        field_catalog={},
    )

    assert plan is None
    assert any("expected 2 values but produced 1" in error for error in errors)
