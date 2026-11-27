import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

import fairifier.agents.entity_structure_planner as entity_planner_module
from fairifier.agents.entity_structure_planner import EntityStructurePlannerAgent
from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
from fairifier.agents.response_models import (
    EntityPlanRecordColumnAuditResponse,
    EntityPlanScopeAuditResponse,
)
from fairifier.graph.excel import _generate_xlsx_local
from fairifier.graph.nodes import OrchestrateNode
from fairifier.utils.entity_plan import (
    contacts_from_source_text,
    materialize_entity_claims,
    normalize_claim_measurement_units,
    normalize_source_measurement_value,
    normalize_entity_plan,
    project_matrix_onto_entity_plan,
    render_entity_plan_for_prompt,
    validate_entity_matrix_against_plan,
)
from fairifier.utils.isa_matrix_projection import apply_matrix_to_metadata


MICHAEL_SOURCE = """Contributor(s)\tNodine M, Hofmann F, Schon M
Citation(s)\tHofmann F, Schon MA, Nodine MD (2019) RNA-seq analysis.
Overall design\tEight stages of embryo development with three biological
replicates. Bent cotyledon RNA was tested at four input amounts with three
library preparation methods.
"""


def test_entity_planner_reuses_provider_configured_model_without_local_binding(
    monkeypatch,
):
    class ProviderConfiguredModel:
        def bind(self, **kwargs):
            raise AssertionError(f"agent-local sampler binding is forbidden: {kwargs}")

    class SharedHelper:
        def __init__(self):
            self.model = ProviderConfiguredModel()
            self.llm = self.model
            self.llm_responses = []

        def get_llm(self):
            return self.model

    shared_helper = SharedHelper()
    monkeypatch.setattr(
        entity_planner_module, "get_llm_helper", lambda: shared_helper
    )

    planner = EntityStructurePlannerAgent()

    assert planner.llm_helper.llm is shared_helper.model
    assert planner.llm_helper.llm_responses is shared_helper.llm_responses


def _embryo_study_claims():
    stages = [
        "pre-globular",
        "globular",
        "heart",
        "torpedo",
        "bent cotyledon",
        "mature green",
        "post-mature green",
        "dry seed",
    ]
    return {
        "investigations": [
            {
                "row_id": "investigation_001",
                "label": "GSE126024",
                "parent_row_id": None,
                "external_identifier": "GSE126024",
                "evidence": "GEO series GSE126024",
            }
        ],
        "studies": [
            {
                "row_id": "study_001",
                "label": "Arabidopsis embryo RNA-seq",
                "parent_row_id": "investigation_001",
                "external_identifier": None,
                "evidence": "Overall design",
            }
        ],
        "design_groups": [
            {
                "group_id": "development",
                "study_row_id": "study_001",
                "evidence": "Eight stages with three biological replicates",
                "dimensions": [
                    {
                        "name": "developmental_stage",
                        "level_count": 8,
                        "explicit_values": stages,
                        "origin": "explicit",
                        "field_name": "developmental stage",
                        "applies_to": ["observationunit", "sample", "assay"],
                    },
                    {
                        "name": "biological_replicate",
                        "level_count": 3,
                        "explicit_values": [],
                        "origin": "derived",
                        "field_name": "biological replicate",
                        "applies_to": ["sample", "assay"],
                    },
                ],
                "unresolved_ambiguities": [],
            },
            {
                "group_id": "low_input",
                "study_row_id": "study_001",
                "evidence": "Four input amounts crossed with three methods",
                "dimensions": [
                    {
                        "name": "source_stage",
                        "level_count": 1,
                        "explicit_values": ["bent cotyledon"],
                        "origin": "explicit",
                        "field_name": "developmental stage",
                        "applies_to": ["observationunit", "sample", "assay"],
                    },
                    {
                        "name": "input_amount",
                        "level_count": 4,
                        "explicit_values": ["5 ng", "1 ng", "0.5 ng", "0.1 ng"],
                        "origin": "explicit",
                        "field_name": "input amount",
                        "applies_to": ["sample", "assay"],
                    },
                    {
                        "name": "library_method",
                        "level_count": 3,
                        "explicit_values": [],
                        "origin": "derived",
                        "field_name": "library preparation method",
                        "applies_to": ["sample", "assay"],
                    },
                ],
                "unresolved_ambiguities": ["Method names are not in the abstract."],
            },
        ],
        "design_summary": [],
        "unresolved_ambiguities": [],
        "confidence": 0.9,
    }


def _embryo_study_plan():
    contacts = contacts_from_source_text(MICHAEL_SOURCE)
    return normalize_entity_plan(
        materialize_entity_claims(_embryo_study_claims()),
        investigation_contacts=contacts,
    )


def test_contacts_use_parser_identities_and_enrich_only_explicit_details():
    source = """Authors: Alice M. Example $^{1}$ and Bob Tester $^{1}$

Affiliations: $^{1}$ Example Research Institute, Example City

Corresponding author: Alice M. Example (email: alice.example@institute.test)
"""

    contacts = contacts_from_source_text(
        source,
        fallback_names=["Alice M. Example", "Bob Tester"],
    )

    assert [(row["firstname"], row["lastname"]) for row in contacts] == [
        ("Alice M.", "Example"),
        ("Bob", "Tester"),
    ]
    assert contacts[0]["email address"] == "alice.example@institute.test"
    assert contacts[1]["email address"] == ""
    assert {row["organization"] for row in contacts} == {
        "Example Research Institute, Example City"
    }


def test_contacts_do_not_guess_organization_from_competing_affiliations():
    source = """Authors: Alice Example and Bob Tester
Affiliations: First University; Second Research Institute
"""

    contacts = contacts_from_source_text(
        source,
        fallback_names=["Alice Example", "Bob Tester"],
    )

    assert all(row["organization"] == "" for row in contacts)


def _seed_matrix():
    return {
        "investigation": {
            "columns": [
                "investigation identifier",
                "investigation title",
                "investigation description",
                "firstname",
                "lastname",
                "email address",
                "orcid",
                "organization",
                "department",
            ],
            "rows": [{"investigation identifier": "GSE126024"}],
            "fields": [
                {
                    "field_name": "investigation identifier",
                    "package_source": "default",
                    "requirement": "MANDATORY",
                }
            ],
        },
        "study": {
            "columns": ["study identifier", "study title", "investigation identifier"],
            "rows": [{"study identifier": "GSE126024"}],
            "fields": [{"field_name": "study identifier", "package_source": "default"}],
        },
        "observationunit": {
            "columns": [
                "observation unit identifier",
                "observation unit name",
                "study identifier",
                "developmental stage",
            ],
            "rows": [{"observation unit identifier": "collapsed stages"}],
            "fields": [
                {"field_name": "observation unit identifier", "package_source": "default"}
            ],
        },
        "sample": {
            "columns": [
                "sample identifier",
                "sample name",
                "observation unit identifier",
                "developmental stage",
                "biological replicate",
                "input amount",
            ],
            "rows": [{"sample identifier": "sample_a, sample_b"}],
            "fields": [
                {
                    "field_name": "sample identifier",
                    "package_source": "Crop Plant sample enhanced annotation checklist",
                }
            ],
        },
        "assay": {
            "columns": ["assay identifier", "assay description", "sample identifier"],
            "rows": [{"assay identifier": "GSE126024"}],
            "fields": [{"field_name": "assay identifier", "package_source": "default"}],
        },
    }


def test_embryo_study_design_materializes_fairds_cardinalities_and_links():
    plan = _embryo_study_plan()
    counts = {level["level"]: level["cardinality"] for level in plan["levels"]}

    assert counts == {
        "investigation": 1,
        "study": 1,
        "observationunit": 9,
        "sample": 36,
        "assay": 36,
    }
    assert plan["materialization_errors"] == []
    samples = next(
        level["entities"] for level in plan["levels"] if level["level"] == "sample"
    )
    assays = next(
        level["entities"] for level in plan["levels"] if level["level"] == "assay"
    )
    sample_ids = {entity["row_id"] for entity in samples}
    assert all(entity["parent_row_id"] in sample_ids for entity in assays)


def test_source_declared_unit_symbol_normalizes_standalone_quantities():
    source = "Inputs ranged from 0.1 to 5 nanograms (ng) of total RNA."

    assert normalize_source_measurement_value("5 nanograms", source) == "5 ng"
    assert normalize_source_measurement_value("0.1 nanograms", source) == "0.1 ng"
    assert normalize_source_measurement_value("1 nanogram", source) == "1 ng"
    assert normalize_source_measurement_value("five nanograms", source) == (
        "five nanograms"
    )
    assert normalize_source_measurement_value("5 nanograms total RNA", source) == (
        "5 nanograms total RNA"
    )


def test_claim_quantities_use_source_declared_unit_symbol():
    claims = {
        "design_groups": [
            {
                "dimensions": [
                    {
                        "explicit_values": ["5 nanograms", "1 nanograms"],
                        "known_values": [
                            {"position": 1, "value": "0.5 nanograms"}
                        ],
                    }
                ]
            }
        ]
    }

    normalized = normalize_claim_measurement_units(
        claims, "nanograms (ng)"
    )

    dimension = normalized["design_groups"][0]["dimensions"][0]
    assert dimension["explicit_values"] == ["5 ng", "1 ng"]
    assert dimension["known_values"][0]["value"] == "0.5 ng"


def test_unnamed_derived_singleton_does_not_pollute_entity_labels():
    claims = _embryo_study_claims()
    claims["design_groups"][0]["dimensions"].append(
        {
            "name": "unnamed_method",
            "level_count": 1,
            "explicit_values": [],
            "known_values": [],
            "origin": "derived",
            "field_mappings": [],
            "applies_to": ["sample", "assay"],
        }
    )

    plan = materialize_entity_claims(claims)
    samples = next(
        item["entities"]
        for item in plan["levels"]
        if item["level"] == "sample"
    )

    assert len(samples) == 36
    assert all("unnamed method" not in entity["label"] for entity in samples)
    assert all(
        all(
            attribute["dimension_name"] != "unnamed_method"
            for attribute in entity["attributes"]
        )
        for entity in samples
    )
    sample_level = next(
        item for item in plan["levels"] if item["level"] == "sample"
    )
    assert any(
        "one unnamed derived level" in ambiguity
        for ambiguity in sample_level["unresolved_ambiguities"]
    )


def test_child_links_on_shared_dimensions_when_parent_has_level_only_constant():
    claims = _embryo_study_claims()
    for group in claims["design_groups"]:
        group["dimensions"].append(
            {
                "name": "sample_only_property",
                "level_count": 1,
                "explicit_values": ["source-literal"],
                "origin": "explicit",
                "field_name": "sampling strategy",
                "applies_to": ["sample"],
            }
        )

    materialized = materialize_entity_claims(claims)

    assert materialized["materialization_errors"] == []
    assays = next(
        level["entities"]
        for level in materialized["levels"]
        if level["level"] == "assay"
    )
    assert all(entity["parent_row_id"] for entity in assays)


def test_parent_level_factor_is_propagated_to_child_levels():
    """A factor that splits samples must split their assays too (one parent each)."""
    claims = _embryo_study_claims()
    baseline = materialize_entity_claims(deepcopy(claims))
    claims["design_groups"][0]["dimensions"].append(
        {
            "name": "parent_factor",
            "level_count": 2,
            "explicit_values": ["left", "right"],
            "origin": "explicit",
            "field_name": "sampling strategy",
            "applies_to": ["sample"],
        }
    )

    materialized = materialize_entity_claims(claims)

    assert not any("sample parents" in e for e in materialized["materialization_errors"])
    count = lambda plan, level: len(next(l for l in plan["levels"] if l["level"] == level)["entities"])
    assert count(materialized, "assay") > count(baseline, "assay")


def test_contacts_repeat_in_investigation_without_person_level():
    plan = _embryo_study_plan()
    matrix = project_matrix_onto_entity_plan(_seed_matrix(), plan)
    validation = validate_entity_matrix_against_plan(matrix, plan)

    assert validation["passed"] is True
    assert validation["investigation_contact_count"] == 3
    assert "person" not in matrix
    assert [
        (row["firstname"], row["lastname"])
        for row in matrix["investigation"]["rows"]
    ] == [("MD", "Nodine"), ("F", "Hofmann"), ("MA", "Schon")]
    assert validation["row_counts"] == {
        "investigation": 3,
        "study": 1,
        "observationunit": 9,
        "sample": 36,
        "assay": 36,
    }
    assert all(
        "," not in row["sample identifier"] for row in matrix["sample"]["rows"]
    )
    assert "assay name" not in matrix["assay"]["columns"]


def test_selected_assay_name_is_compiled_from_each_planned_entity():
    seed = _seed_matrix()
    seed["assay"]["columns"].append("assay name")
    seed["assay"]["rows"][0]["assay name"] = "one broadcast example"

    plan = _embryo_study_plan()
    matrix = project_matrix_onto_entity_plan(seed, plan)
    validation = validate_entity_matrix_against_plan(matrix, plan)
    assay_entities = next(
        level["entities"] for level in plan["levels"] if level["level"] == "assay"
    )

    assert validation["passed"] is True
    assert [row["assay name"] for row in matrix["assay"]["rows"]] == [
        entity["label"] for entity in assay_entities
    ]


def test_empty_mapper_level_retains_confirmed_shared_fields_after_plan_projection():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent

    seed = _seed_matrix()
    seed["assay"]["columns"].append("library strategy")
    seed["assay"]["rows"] = []
    plan = _embryo_study_plan()
    fields = {
        "assay": [
            {
                "field_name": "library strategy",
                "value": "RNA-Seq",
                "confidence": 0.95,
                "status": "confirmed",
                "evidence": "source_001 explicitly states mRNA sequencing",
                "value_scope": "level",
            }
        ]
    }

    seed = ISAValueMapperAgent._seed_missing_planned_levels(seed, plan)
    seed = ISAValueMapperAgent._restore_high_confidence_shared_values(
        seed, fields, entity_plan=plan
    )
    matrix = project_matrix_onto_entity_plan(seed, plan)

    assert len(matrix["assay"]["rows"]) == 36
    assert {
        row["library strategy"] for row in matrix["assay"]["rows"]
    } == {"RNA-Seq"}


def test_materialized_plan_retains_unmapped_design_dimensions_in_every_entity():
    claims = _embryo_study_claims()
    claims["design_groups"][0]["dimensions"][1]["field_name"] = None

    plan = normalize_entity_plan(materialize_entity_claims(claims))
    samples = next(
        level["entities"] for level in plan["levels"] if level["level"] == "sample"
    )
    development = [row for row in samples if row["source_group"] == "development"]

    assert len(development) == 24
    assert all(
        any(
            attribute["dimension_name"] == "biological_replicate"
            and attribute["field_name"] is None
            for attribute in row["attributes"]
        )
        for row in development
    )


def test_source_native_name_need_not_repeat_dimension_present_in_description():
    plan = _embryo_study_plan()
    samples = next(
        level["entities"] for level in plan["levels"] if level["level"] == "sample"
    )
    samples[0]["label"] = "source-native-sample-id"
    samples[0]["external_identifier"] = "source-native-sample-id"
    samples[0]["attributes"].append(
        {
            "dimension_name": "source series",
            "field_name": None,
            "value": "developmental time course",
            "origin": "explicit",
        }
    )

    matrix = project_matrix_onto_entity_plan(_seed_matrix(), plan)
    validation = validate_entity_matrix_against_plan(matrix, plan)

    first = matrix["sample"]["rows"][0]
    assert first["sample name"] == "source-native-sample-id"
    assert "developmental time course" in first["sample description"]
    assert validation["passed"] is True


def test_ordinal_placeholders_do_not_populate_semantic_fairds_terms():
    claims = _embryo_study_claims()
    claims["design_groups"][1]["dimensions"][2]["field_mappings"] = [
        {"level": "assay", "field_name": "protocol"}
    ]

    plan = materialize_entity_claims(
        claims,
        field_catalog={"assay": ["protocol"]},
    )
    assays = next(
        level["entities"] for level in plan["levels"] if level["level"] == "assay"
    )
    low_input = [row for row in assays if row["source_group"] == "low_input"]

    assert low_input
    assert all(
        any(
            attribute["dimension_name"] == "library_method"
            and attribute["origin"] == "derived"
            and attribute["field_name"] is None
            for attribute in row["attributes"]
        )
        for row in low_input
    )


def test_partial_factor_labels_preserve_declared_cardinality():
    claims = _embryo_study_claims()
    stage = claims["design_groups"][0]["dimensions"][0]
    stage["explicit_values"] = []
    stage["known_values"] = [
        {"position": 1, "value": "8-cell/16-cell"},
        {"position": 8, "value": "mature green"},
    ]
    stage["origin"] = "derived"

    plan = materialize_entity_claims(claims)
    counts = {item["level"]: item["cardinality"] for item in plan["levels"]}
    stage_entities = [
        row
        for item in plan["levels"]
        if item["level"] == "observationunit"
        for row in item["entities"]
        if row["source_group"] == "development"
    ]

    assert plan["materialization_errors"] == []
    assert counts == {
        "investigation": 1,
        "study": 1,
        "observationunit": 9,
        "sample": 36,
        "assay": 36,
    }
    assert len(stage_entities) == 8
    stage_attributes = [
        next(
            attribute
            for attribute in row["attributes"]
            if attribute["dimension_name"] == "developmental_stage"
        )
        for row in stage_entities
    ]
    assert stage_attributes[0] == {
        "dimension_name": "developmental_stage",
        "field_name": "developmental stage",
        "value": "8-cell/16-cell",
        "origin": "explicit",
    }
    assert stage_attributes[-1]["value"] == "mature green"
    assert stage_attributes[-1]["origin"] == "explicit"
    assert all(item["origin"] == "derived" for item in stage_attributes[1:-1])
    assert all(item["field_name"] is None for item in stage_attributes[1:-1])


def test_dimension_terms_are_validated_separately_for_each_isa_level():
    claims = _embryo_study_claims()
    claims["design_groups"][0]["dimensions"][0]["field_mappings"] = [
        {"level": "observationunit", "field_name": "study treatment"},
        {"level": "sample", "field_name": "study treatment"},
        {"level": "assay", "field_name": "study treatment"},
    ]
    claims["design_groups"][0]["dimensions"][0]["field_name"] = None
    catalog = {
        "observationunit": ["study treatment"],
        "sample": ["sample treatment"],
        "assay": ["protocol"],
    }

    plan = normalize_entity_plan(
        materialize_entity_claims(claims, field_catalog=catalog)
    )
    by_level = {
        level["level"]: level["entities"] for level in plan["levels"]
    }

    assert any(
        attribute["field_name"] == "study treatment"
        for attribute in by_level["observationunit"][0]["attributes"]
    )
    assert all(
        attribute["field_name"] is None
        for entity in by_level["sample"]
        if entity["source_group"] == "development"
        for attribute in entity["attributes"]
        if attribute["dimension_name"] == "developmental_stage"
    )
    assert all(
        attribute["field_name"] is None
        for entity in by_level["assay"]
        if entity["source_group"] == "development"
        for attribute in entity["attributes"]
        if attribute["dimension_name"] == "developmental_stage"
    )


def test_design_dimensions_cannot_overwrite_reserved_identity_fields():
    claims = _embryo_study_claims()
    dimension = claims["design_groups"][0]["dimensions"][1]
    dimension["field_name"] = None
    dimension["field_mappings"] = [
        {"level": "sample", "field_name": "sample name"}
    ]

    plan = normalize_entity_plan(
        materialize_entity_claims(
            claims,
            field_catalog={
                "observationunit": ["observation unit name"],
                "sample": ["sample name"],
                "assay": ["assay description"],
            },
        )
    )
    samples = next(
        level["entities"]
        for level in plan["levels"]
        if level["level"] == "sample"
    )

    assert all(
        attribute["field_name"] is None
        for entity in samples
        if entity["source_group"] == "development"
        for attribute in entity["attributes"]
        if attribute["dimension_name"] == "biological_replicate"
    )


def test_design_group_label_replaces_internal_group_id_in_entity_names():
    claims = _embryo_study_claims()
    claims["design_groups"][0]["label"] = "developmental-stage series"

    plan = normalize_entity_plan(materialize_entity_claims(claims))
    observations = next(
        level["entities"]
        for level in plan["levels"]
        if level["level"] == "observationunit"
    )

    assert observations[0]["label"].startswith("developmental-stage series")
    assert not observations[0]["label"].startswith("development observationunit")


def test_entity_planner_prompt_renders_level_specific_field_mapping_example():
    planner = object.__new__(EntityStructurePlannerAgent)

    prompt = planner._prompt(
        {
            "document_content": "A two-condition experiment.",
            "document_info": {"title": "Test"},
            "retrieved_knowledge": [],
        }
    )

    assert '"field_mappings"' in prompt
    assert '"level": "observationunit"' in prompt


def test_scope_audit_restores_exact_constant_condition_without_changing_cardinality():
    claims = {
        "design_groups": [
            {
                "group_id": "group_002",
                "evidence": "RNA from bent-cotyledon embryos was diluted to 1 ng.",
                "dimensions": [
                    {
                        "name": "dose",
                        "level_count": 1,
                        "explicit_values": ["1 ng"],
                        "known_values": [],
                    }
                ],
            }
        ]
    }
    audit = {
        "missing_conditions": [
            {
                "group_id": "group_002",
                "dimension_name": "developmental_stage",
                "source_value": "bent-cotyledon",
                "level": "sample",
                "field_name": "dev_stage",
            }
        ]
    }

    added = EntityStructurePlannerAgent._apply_scope_audit_findings(
        claims, audit, {"sample": ["dev_stage"]}
    )

    assert added == ["group_002:sample.dev_stage=bent-cotyledon"]
    restored = claims["design_groups"][0]["dimensions"][-1]
    assert restored["level_count"] == 1
    assert restored["explicit_values"] == ["bent-cotyledon"]
    assert restored["applies_to"] == ["sample", "assay"]


def test_scope_audit_rejects_values_not_verbatim_in_group_evidence():
    claims = {
        "design_groups": [
            {"group_id": "group_001", "evidence": "control samples", "dimensions": []}
        ]
    }
    audit = {
        "missing_conditions": [
            {
                "group_id": "group_001",
                "dimension_name": "genotype",
                "source_value": "invented mutant",
                "level": "sample",
                "field_name": "genotype",
            }
        ]
    }

    added = EntityStructurePlannerAgent._apply_scope_audit_findings(
        claims, audit, {"sample": ["genotype"]}
    )

    assert added == []
    assert claims["design_groups"][0]["dimensions"] == []


def test_plan_validation_rejects_many_assays_per_sample_without_reuse_evidence():
    plan = _embryo_study_plan()
    plan["design_claims"] = {
        "design_groups": [
            {
                "group_id": "low_input",
                "evidence": "Four inputs were prepared with three methods.",
                "reuse_same_sample_for_multiple_assays": False,
                "sample_reuse_evidence": None,
            }
        ]
    }
    sample_level = next(
        item for item in plan["levels"] if item["level"] == "sample"
    )
    assay_level = next(
        item for item in plan["levels"] if item["level"] == "assay"
    )
    sample_level["entities"] = [
        entity
        for entity in sample_level["entities"]
        if entity.get("source_group") != "low_input" or entity["row_id"].endswith("_01")
    ]
    sample_level["cardinality"] = len(sample_level["entities"])

    errors = EntityStructurePlannerAgent._plan_errors(plan)

    assert any("without an explicit source quote" in error for error in errors)


def test_plan_validation_allows_many_assays_when_reuse_quote_is_verbatim():
    plan = _embryo_study_plan()
    plan["design_claims"] = {
        "design_groups": [
            {
                "group_id": "low_input",
                "evidence": "The same identified RNA sample was measured three times.",
                "reuse_same_sample_for_multiple_assays": True,
                "sample_reuse_evidence": "same identified RNA sample",
            }
        ]
    }
    sample_level = next(
        item for item in plan["levels"] if item["level"] == "sample"
    )
    sample_level["entities"] = [
        entity
        for entity in sample_level["entities"]
        if entity.get("source_group") != "low_input" or entity["row_id"].endswith("_01")
    ]
    sample_level["cardinality"] = len(sample_level["entities"])

    errors = EntityStructurePlannerAgent._plan_errors(plan)

    assert not any("without an explicit source quote" in error for error in errors)


def test_plan_validation_rejects_incomplete_authoritative_table_coverage():
    plan = _embryo_study_plan()
    plan["source_coverage"] = {
        "complete": False,
        "tables": [
            {
                "source_path": "metadata.xlsx",
                "table_name": "records",
                "unmapped_columns": ["read count"],
            }
        ],
    }

    errors = EntityStructurePlannerAgent._plan_errors(plan)

    assert any("coverage is incomplete" in error for error in errors)


def test_projection_does_not_broadcast_one_entity_narrative_to_siblings():
    seed = _seed_matrix()
    seed["sample"]["columns"].extend(["sample description", "sampling timepoint"])
    seed["sample"]["rows"] = [
        {
            "sample identifier": "example",
            "sample description": "pre-globular biological replicate 1",
            "sampling timepoint": "pre-globular",
        }
    ]

    matrix = project_matrix_onto_entity_plan(seed, _embryo_study_plan())
    sample_rows = matrix["sample"]["rows"]

    assert len({row["sample description"] for row in sample_rows}) == 36
    assert all(
        "pre-globular" not in row["sampling timepoint"]
        for row in sample_rows
        if "pre-globular" not in row["sample name"]
    )
    assert {
        row["developmental stage"]
        for row in sample_rows
        if row["sample identifier"].startswith("development_")
    } == {
        "pre-globular",
        "globular",
        "heart",
        "torpedo",
        "bent cotyledon",
        "mature green",
        "post-mature green",
        "dry seed",
    }
    assert all(
        row["assay description"] == f"Assay for sample {row['sample identifier']}"
        for row in matrix["assay"]["rows"]
    )


def _two_assay_matrix_and_plan():
    plan = {
        "levels": [
            {
                "level": "sample",
                "entities": [
                    {
                        "row_id": f"sample_{suffix}",
                        "parent_row_id": f"unit_{suffix}",
                        "source_group": f"group_{suffix}",
                        "attributes": [],
                    }
                    for suffix in ("a", "b")
                ],
            },
            {
                "level": "assay",
                "entities": [
                    {
                        "row_id": f"assay_{suffix}",
                        "parent_row_id": f"sample_{suffix}",
                        "source_group": f"group_{suffix}",
                        "attributes": [],
                    }
                    for suffix in ("a", "b")
                ],
            },
        ]
    }
    matrix = {
        "assay": {
            "columns": [
                "assay identifier", "sample identifier",
                "measurement value", "measurement unit",
            ],
            "rows": [
                {
                    "assay identifier": f"assay_{suffix}",
                    "sample identifier": f"sample_{suffix}",
                    "measurement value": value,
                    "measurement unit": "mM",
                }
                for suffix, value in (("a", "2.5"), ("b", "7.5"))
            ],
        }
    }
    return matrix, plan


@pytest.mark.parametrize("reverse_rows", [False, True])
def test_projection_retains_distinct_values_by_planned_internal_id(reverse_rows):
    matrix, plan = _two_assay_matrix_and_plan()
    if reverse_rows:
        matrix["assay"]["rows"].reverse()
    original = deepcopy(matrix)

    projected = project_matrix_onto_entity_plan(matrix, plan)

    assert matrix == original
    assert [row["measurement value"] for row in projected["assay"]["rows"]] == [
        "2.5", "7.5",
    ]
    assert [row["sample identifier"] for row in projected["assay"]["rows"]] == [
        "sample_a", "sample_b",
    ]
    assert {row["measurement unit"] for row in projected["assay"]["rows"]} == {"mM"}
    assert project_matrix_onto_entity_plan(projected, plan) == projected


def test_projection_internal_id_accepts_resolved_external_parent_identifier():
    matrix, plan = _two_assay_matrix_and_plan()
    for suffix, entity, row in zip(
        ("a", "b"), plan["levels"][0]["entities"], matrix["assay"]["rows"]
    ):
        entity["external_identifier"] = f"source_sample_{suffix}"
        row["sample identifier"] = entity["external_identifier"]

    rows = project_matrix_onto_entity_plan(matrix, plan)["assay"]["rows"]

    assert [row["measurement value"] for row in rows] == ["2.5", "7.5"]
    assert [row["sample identifier"] for row in rows] == [
        "source_sample_a", "source_sample_b",
    ]


@pytest.mark.parametrize("parent_value", [None, ""])
def test_projection_canonical_id_recovers_omitted_parent_from_authoritative_plan(
    parent_value,
):
    matrix, plan = _two_assay_matrix_and_plan()
    for suffix, entity, row in zip(
        ("a", "b"), plan["levels"][0]["entities"], matrix["assay"]["rows"]
    ):
        entity["external_identifier"] = f"source_sample_{suffix}"
        if parent_value is None:
            row.pop("sample identifier")
        else:
            row["sample identifier"] = parent_value
    original = deepcopy(matrix)

    projected = project_matrix_onto_entity_plan(matrix, plan)
    rows = projected["assay"]["rows"]

    assert matrix == original
    assert [row["measurement value"] for row in rows] == ["2.5", "7.5"]
    assert [row["measurement unit"] for row in rows] == ["mM", "mM"]
    assert [row["sample identifier"] for row in rows] == [
        "source_sample_a", "source_sample_b",
    ]
    assert project_matrix_onto_entity_plan(projected, plan) == projected


@pytest.mark.parametrize("omit_parent", [False, True])
def test_projection_unique_canonical_ids_survive_duplicate_external_aliases(omit_parent):
    matrix, plan = _two_assay_matrix_and_plan()
    for entity in plan["levels"][1]["entities"]:
        entity["external_identifier"] = "reused_source_label"
    if omit_parent:
        for row in matrix["assay"]["rows"]:
            row.pop("sample identifier")

    projected = project_matrix_onto_entity_plan(matrix, plan)
    rows = projected["assay"]["rows"]

    assert [row["measurement value"] for row in rows] == ["2.5", "7.5"]
    assert [row["measurement unit"] for row in rows] == ["mM", "mM"]
    assert [row["assay identifier"] for row in rows] == ["assay_a", "assay_b"]
    assert [row["sample identifier"] for row in rows] == ["sample_a", "sample_b"]
    assert project_matrix_onto_entity_plan(projected, plan) == projected


def test_projection_ambiguous_external_aliases_cannot_supply_entity_values():
    matrix, plan = _two_assay_matrix_and_plan()
    for entity in plan["levels"][1]["entities"]:
        entity["external_identifier"] = "reused_source_label"
    for row in matrix["assay"]["rows"]:
        row["assay identifier"] = "reused_source_label"
        row["measurement value"] = "2.5"

    rows = project_matrix_onto_entity_plan(matrix, plan)["assay"]["rows"]

    assert [row["measurement value"] for row in rows] == ["", ""]


def test_validator_checks_mapped_values_after_duplicate_alias_projection():
    matrix, plan = _two_assay_matrix_and_plan()
    for level in plan["levels"]:
        level["cardinality"] = len(level["entities"])
    for entity, duration in zip(plan["levels"][1]["entities"], ("24 h", "48 h")):
        entity["external_identifier"] = "reused_source_label"
        entity["attributes"] = [{
            "dimension_name": "incubation_time",
            "field_name": "incubation time",
            "value": duration,
        }]
    projected = project_matrix_onto_entity_plan(matrix, plan)
    projected["assay"]["rows"][0]["incubation time"] = "48 h"

    validation = validate_entity_matrix_against_plan(projected, plan)

    assert validation["mapped_attribute_errors"] == [
        "assay row assay_a does not preserve mapped dimension incubation time='24 h'.",
    ]
    assert validation["semantic_metrics"]["assay"]["unique_identity_stripped_signatures"] == 2


@pytest.mark.parametrize("conflict", ["wrong_parent", "wrong_group"])
def test_projection_rejects_conflicting_internal_id_scope(conflict):
    matrix, plan = _two_assay_matrix_and_plan()
    rows = matrix["assay"]["rows"]
    # Identical magnitudes must not let the shared-value fallback bypass an
    # explicit identity conflict.
    rows[1]["measurement value"] = "2.5"
    if conflict == "wrong_parent":
        rows[0]["sample identifier"] = "sample_b"
    else:
        rows[0]["source_group"] = "group_b"

    projected = project_matrix_onto_entity_plan(matrix, plan)["assay"]["rows"]

    assert projected[0]["measurement value"] == ""
    assert projected[1]["measurement value"] == "2.5"


@pytest.mark.parametrize("bad_identity", ["duplicate", "unknown", "wrong_level"])
def test_projection_does_not_broadcast_identified_rows_with_unresolved_identity(
    bad_identity,
):
    matrix, plan = _two_assay_matrix_and_plan()
    rows = matrix["assay"]["rows"]
    for row in rows:
        row["measurement value"] = "2.5"
        row["assay identifier"] = {
            "duplicate": "assay_a",
            "unknown": "unplanned_assay",
            "wrong_level": "sample_a",
        }[bad_identity]

    projected = project_matrix_onto_entity_plan(matrix, plan)["assay"]["rows"]

    assert [row["measurement value"] for row in projected] == ["", ""]


def test_projection_rejects_internal_external_identifier_collision():
    matrix, plan = _two_assay_matrix_and_plan()
    plan["levels"][1]["entities"][0]["external_identifier"] = "assay_b"

    rows = project_matrix_onto_entity_plan(matrix, plan)["assay"]["rows"]

    assert [row["measurement value"] for row in rows] == ["", ""]


def test_projection_external_identifiers_are_scoped_to_their_isa_level():
    matrix, plan = _two_assay_matrix_and_plan()
    plan["levels"][0]["entities"][0]["external_identifier"] = "source_001"
    plan["levels"][1]["entities"][0]["external_identifier"] = "source_001"
    matrix["assay"]["rows"][0]["assay identifier"] = "source_001"
    matrix["assay"]["rows"][0]["sample identifier"] = "source_001"

    rows = project_matrix_onto_entity_plan(matrix, plan)["assay"]["rows"]

    assert [row["measurement value"] for row in rows] == ["2.5", "7.5"]
    assert rows[0]["assay identifier"] == rows[0]["sample identifier"] == "source_001"


@pytest.mark.parametrize("scope", ["identified", "shared"])
def test_projection_retains_numeric_zero_values(scope):
    matrix, plan = _two_assay_matrix_and_plan()
    matrix["assay"]["rows"][0]["measurement value"] = 0
    expected = [0, "7.5"]
    if scope == "shared":
        for row in matrix["assay"]["rows"]:
            row.pop("assay identifier")
            row["measurement value"] = 0
        expected = [0, 0]

    rows = project_matrix_onto_entity_plan(matrix, plan)["assay"]["rows"]

    assert [row["measurement value"] for row in rows] == expected


@pytest.mark.parametrize(
    "scope", ["valid_parent", "missing_parent", "wrong_parent", "wrong_group"]
)
def test_projection_checks_scope_of_id_free_singleton_row(scope):
    matrix, plan = _two_assay_matrix_and_plan()
    for level in plan["levels"]:
        level["entities"] = level["entities"][:1]
    matrix["assay"]["rows"] = matrix["assay"]["rows"][:1]
    row = matrix["assay"]["rows"][0]
    row.pop("assay identifier")
    if scope == "missing_parent":
        row.pop("sample identifier")
    elif scope == "wrong_parent":
        row["sample identifier"] = "sample_b"
    elif scope == "wrong_group":
        row["source_group"] = "group_b"

    rows = project_matrix_onto_entity_plan(matrix, plan)["assay"]["rows"]

    expected = "" if scope in {"wrong_parent", "wrong_group"} else "2.5"
    assert rows[0]["measurement value"] == expected


def test_projection_preserves_common_investigation_values_across_contact_rows():
    plan = {
        "levels": [
            {
                "level": "investigation",
                "entities": [{"row_id": "investigation_a", "attributes": []}],
            }
        ],
        "investigation_contacts": [
            {"firstname": "Alice", "lastname": "Example"},
            {"firstname": "Bob", "lastname": "Tester"},
        ],
    }
    matrix = {
        "investigation": {
            "columns": [
                "investigation identifier", "submission date", "public release date",
                "firstname", "lastname", "email address",
            ],
            "rows": [
                {
                    "investigation identifier": "investigation_a",
                    "submission date": "2025-01-01",
                    "public release date": "2025-02-01",
                    "firstname": "Alice",
                    "lastname": "Example",
                    "email address": "alice@example.test",
                },
                {
                    "investigation identifier": "investigation_a",
                    "submission date": "2025-01-01",
                    "public release date": "2025-03-01",
                    "firstname": "Bob",
                    "lastname": "Tester",
                    "email address": "bob@example.test",
                },
            ],
        }
    }

    rows = project_matrix_onto_entity_plan(matrix, plan)["investigation"]["rows"]

    assert [row["submission date"] for row in rows] == ["2025-01-01"] * 2
    assert [row["public release date"] for row in rows] == [""] * 2
    assert [(row["firstname"], row["email address"]) for row in rows] == [
        ("Alice", "alice@example.test"), ("Bob", "bob@example.test"),
    ]


def test_entity_prompt_preserves_complete_identity_graph_when_budget_is_small():
    plan = _embryo_study_plan()
    for level in plan["levels"]:
        level["evidence"] = ["Repeated explanatory narrative. " * 100]
    original = deepcopy(plan)

    prompt = render_entity_plan_for_prompt(plan, max_chars=500)
    rendered = json.loads(prompt.split("\n", 1)[1])

    assert plan == original
    assert "entity plan truncated" not in prompt
    assert [level["level"] for level in rendered["levels"]] == [
        level["level"] for level in plan["levels"]
    ]
    expected = {
        (level["level"], row["row_id"]): row
        for level in plan["levels"]
        for row in level["entities"]
    }
    actual = {
        (level["level"], row["row_id"]): row
        for level in rendered["levels"]
        for row in level["entities"]
    }
    assert actual.keys() == expected.keys()
    for key, entity in expected.items():
        for identity_key in ("parent_row_id", "external_identifier", "source_group"):
            assert actual[key].get(identity_key) == entity.get(identity_key)
        assert actual[key]["attributes"] == entity["attributes"]


def test_validation_rejects_collapsed_mapped_dimension_values():
    plan = _embryo_study_plan()
    matrix = project_matrix_onto_entity_plan(_seed_matrix(), plan)
    for row in matrix["sample"]["rows"]:
        if row["sample identifier"].startswith("development_"):
            row["developmental stage"] = "pre-globular"

    validation = validate_entity_matrix_against_plan(matrix, plan)

    assert validation["passed"] is False
    assert validation["mapped_attribute_errors"]
    assert any(
        "does not preserve mapped dimension" in error
        for error in validation["errors"]
    )


def test_matrix_projection_removes_legacy_person_level_from_metadata():
    payload = {
        "isa_structure": {
            "investigation": {"fields": []},
            "person": {"fields": [{"field_name": "person name"}]},
        }
    }
    matrix = project_matrix_onto_entity_plan(_seed_matrix(), _embryo_study_plan())

    updated = apply_matrix_to_metadata(payload, matrix)

    assert "person" not in updated["isa_structure"]
    assert "person" not in updated["isa_values"]


def test_contact_details_stay_with_the_matching_investigation_row():
    seed = _seed_matrix()
    seed["investigation"]["rows"] = [
        {
            "investigation identifier": "GSE126024",
            "firstname": "F",
            "lastname": "Hofmann",
            "email address": "hofmann@example.org",
        },
        {
            "investigation identifier": "GSE126024",
            "firstname": "MA",
            "lastname": "Schon",
            "email address": "schon@example.org",
        },
    ]

    rows = project_matrix_onto_entity_plan(seed, _embryo_study_plan())["investigation"]["rows"]

    assert rows[0]["email address"] == ""
    assert rows[1]["email address"] == "hofmann@example.org"
    assert rows[2]["email address"] == "schon@example.org"


def test_document_info_authors_are_contact_fallback_when_no_author_line_exists():
    contacts = EntityStructurePlannerAgent._source_contacts(
        {
            "document_content": "An abstract without an author header.",
            "document_info": {"authors": ["Hofmann F", "Schon MA", "Nodine MD"]},
        }
    )

    assert [(item["firstname"], item["lastname"]) for item in contacts] == [
        ("F", "Hofmann"),
        ("MA", "Schon"),
        ("MD", "Nodine"),
    ]


def test_local_excel_uses_five_package_qualified_sheets_and_raw_headers():
    seed = _seed_matrix()
    matrix = project_matrix_onto_entity_plan(seed, _embryo_study_plan())
    for level_name, block in matrix.items():
        block["fields"] = seed[level_name].get("fields", [])
    workbook = load_workbook(BytesIO(_generate_xlsx_local(matrix)), data_only=True)

    assert all("person" not in name.lower() for name in workbook.sheetnames)
    assert workbook.sheetnames[:5] == [
        "investigation - default",
        "study - default",
        "observationunit - default",
        "sample - Crop Plant sample enha",
        "assay - default",
    ]
    for worksheet in workbook.worksheets[:5]:
        headers = [
            worksheet.cell(1, column).value
            for column in range(1, worksheet.max_column + 1)
        ]
        assert all(not str(header).endswith(("(M)", "(R)", "(O)")) for header in headers)
    investigation = workbook["investigation - default"]
    assert [investigation.cell(row, 4).value for row in range(2, 5)] == ["MD", "F", "MA"]


def test_human_gold_workbooks_define_the_same_five_level_contract():
    root = Path(__file__).resolve().parents[1]
    gold_paths = [
        root / "evaluation/datasets/raw/biorem/BIOREM_Metadata.xlsx",
        root / "evaluation/datasets/raw/biosensor/Whole-cell_biosensor_metadata.xlsx",
        root / "evaluation/datasets/raw/earthworm/Diagonal_RNAseq_Earthworms.xlsx",
    ]
    investigation_rows = []
    for path in gold_paths:
        workbook = load_workbook(path, read_only=True, data_only=True)
        assert all("person" not in name.lower() for name in workbook.sheetnames)
        data_sheets = [name for name in workbook.sheetnames if name.lower() != "help"]
        assert len(data_sheets) >= 5
        for sheet_name in data_sheets:
            worksheet = workbook[sheet_name]
            headers = [cell.value for cell in next(worksheet.iter_rows(min_row=1, max_row=1))]
            assert all(not str(header).endswith(("(M)", "(R)", "(O)")) for header in headers)
        investigation = next(
            workbook[name]
            for name in workbook.sheetnames
            if name.lower().startswith("investigation - ")
        )
        investigation_rows.append(investigation.max_row - 1)

    assert investigation_rows == [7, 1, 16]


def test_structure_planner_catalog_excludes_field_selectors_but_keeps_value_fields():
    knowledge = [
        {
            "term": "design variable selector",
            "metadata": {
                "isa_sheet": "sample",
                "regex": "(dose|replicate|dev_stage)",
            },
        },
        {"term": "dose", "metadata": {"isa_sheet": "sample", "regex": ".*"}},
        {
            "term": "replicate",
            "metadata": {"isa_sheet": "sample", "regex": ".*"},
        },
        {
            "term": "dev_stage",
            "metadata": {"isa_sheet": "sample", "regex": ".*"},
        },
    ]

    catalog = EntityStructurePlannerAgent._field_catalog(knowledge)

    assert "design variable selector" not in catalog["sample"]
    assert {"dose", "replicate", "dev_stage"}.issubset(catalog["sample"])


def test_structure_planner_drops_dimension_mapping_that_violates_field_contract():
    plan = {
        "levels": [
            {
                "level": "assay",
                "entities": [
                    {
                        "source_group": "developmental_profile",
                        "attributes": [
                            {
                                "dimension_name": "developmental stage",
                                "field_name": "library source",
                                "value": "mature green",
                                "origin": "explicit",
                            }
                        ],
                    }
                ],
            }
        ],
        "unresolved_ambiguities": [],
    }
    knowledge = [
        {
            "term": "library source",
            "metadata": {
                "isa_sheet": "assay",
                "regex": "(GENOMIC|TRANSCRIPTOMIC|METAGENOMIC|SYNTHETIC)",
            },
        }
    ]

    result = EntityStructurePlannerAgent._enforce_dimension_field_contracts(
        plan, knowledge
    )

    attribute = result["levels"][0]["entities"][0]["attributes"][0]
    assert attribute["field_name"] is None
    assert attribute["value"] == "mature green"
    assert "do not satisfy" in result["unresolved_ambiguities"][0]


def test_contract_rejection_preserves_source_coverage_when_column_has_other_role():
    plan = {
        "levels": [
            {
                "level": "assay",
                "entities": [
                    {
                        "source_group": "profile",
                        "attributes": [
                            {
                                "dimension_name": "method",
                                "field_name": "library source",
                                "value": "unsupported method",
                                "origin": "explicit",
                            }
                        ],
                    }
                ],
            }
        ],
        "source_coverage": {
            "complete": True,
            "tables": [
                {
                    "coverage_complete": True,
                    "unmapped_columns": [],
                    "fairds_mappings": [
                        {
                            "level": "assay",
                            "column": "method",
                            "field_name": "library source",
                        }
                    ],
                    "column_roles": [
                        {
                            "column": "method",
                            "roles": ["assay_context", "fairds_mapping:assay"],
                        }
                    ],
                }
            ],
        },
        "unresolved_ambiguities": [],
    }
    knowledge = [
        {
            "term": "library source",
            "metadata": {
                "isa_sheet": "assay",
                "regex": "(GENOMIC|TRANSCRIPTOMIC)",
            },
        }
    ]

    result = EntityStructurePlannerAgent._enforce_dimension_field_contracts(
        plan, knowledge
    )

    coverage = result["source_coverage"]
    assert coverage["complete"] is True
    assert coverage["tables"][0]["unmapped_columns"] == []
    assert coverage["tables"][0]["column_roles"] == [
        {"column": "method", "roles": ["assay_context"]}
    ]


def test_contract_rejection_demotes_uncovered_source_column_to_extension():
    plan = {
        "levels": [
            {
                "level": "assay",
                "entities": [
                    {
                        "source_group": "profile",
                        "attributes": [
                            {
                                "dimension_name": "estimated.size",
                                "field_name": "insert size",
                                "value": "84.7",
                                "origin": "explicit",
                            }
                        ],
                    }
                ],
            }
        ],
        "source_coverage": {
            "complete": True,
            "tables": [
                {
                    "source_id": "source_001",
                    "source_path": "metadata.xlsx",
                    "table_name": "records",
                    "columns": ["estimated.size"],
                    "coverage_complete": True,
                    "unmapped_columns": [],
                    "fairds_mappings": [
                        {
                            "level": "assay",
                            "column": "estimated.size",
                            "field_name": "insert size",
                        }
                    ],
                    "column_roles": [
                        {
                            "column": "estimated.size",
                            "roles": ["fairds_mapping:assay"],
                        }
                    ],
                }
            ],
        },
        "source_extension_fields": [],
        "unresolved_ambiguities": [],
    }
    knowledge = [
        {
            "term": "insert size",
            "metadata": {"isa_sheet": "assay", "regex": r"[0-9]+ bp"},
        }
    ]

    result = EntityStructurePlannerAgent._enforce_dimension_field_contracts(
        plan, knowledge
    )

    attribute = result["levels"][0]["entities"][0]["attributes"][0]
    assert attribute["field_name"] == "estimated size"
    assert result["source_coverage"]["complete"] is True
    assert result["source_coverage"]["tables"][0]["unmapped_columns"] == []
    assert result["source_extension_fields"][0]["data_type"] == "number"
    assert result["source_extension_fields"][0]["demoted_from_fairds_mapping"] == (
        "insert size"
    )


def test_candidate_rank_prefers_authoritative_materialization_over_error_count():
    fallback = {"levels": [{"level": "sample", "entities": [{}]}]}
    authoritative = {
        "levels": [{"level": "sample", "entities": [{}]}],
        "source_coverage": {"tables": [{}], "complete": True},
    }

    fallback_rank = EntityStructurePlannerAgent._candidate_rank(
        fallback,
        ["one error"],
        used_authoritative_records=False,
    )
    authoritative_rank = EntityStructurePlannerAgent._candidate_rank(
        authoritative,
        ["one error", "second error"],
        used_authoritative_records=True,
    )

    assert authoritative_rank > fallback_rank


def test_record_column_audit_replaces_loose_mapping_with_typed_extension():
    claims = {
        "record_table_plans": [
            {
                "source_id": "source_001",
                "table_name": "records",
                "covers_complete_focal_study": True,
                "filters": [{"column": "project", "value": "study-1"}],
                "sample_identifier_column": "sample",
                "assay_identifier_column": "run",
                "observation_unit_columns": ["condition"],
                "column_mappings": [
                    {
                        "column": "adapter class",
                        "level": "assay",
                        "field_name": "sample preparation",
                    }
                ],
                "source_extension_mappings": [],
                "excluded_columns": [],
            }
        ]
    }
    audit = {
        "record_column_decisions": [
            {
                "source_id": "source_001",
                "table_name": "records",
                "column": column,
                "disposition": "structural_only",
            }
            for column in ("sample", "project", "run")
        ]
        + [
            {
                "source_id": "source_001",
                "table_name": "records",
                "column": "condition",
                "disposition": "source_extension",
                "level": "sample",
                "rationale": "Source-defined condition label.",
            },
            {
                "source_id": "source_001",
                "table_name": "records",
                "column": "adapter class",
                "disposition": "source_extension",
                "level": "assay",
                "data_type": "string",
                "rationale": "Adapter annotation, not a preparation protocol.",
            },
        ]
    }
    profiles = [
        {
            "source_id": "source_001",
            "table_name": "records",
            "columns": ["sample", "project", "run", "condition", "adapter class"],
        }
    ]

    applied, errors = EntityStructurePlannerAgent._apply_record_column_audit(
        claims,
        audit,
        {"assay": ["sample preparation"]},
        profiles,
    )

    assert errors == []
    record_plan = claims["record_table_plans"][0]
    assert record_plan["column_mappings"] == []
    assert record_plan["source_extension_mappings"] == [
        {
            "column": "condition",
            "level": "sample",
            "data_type": "string",
            "definition": "Source-defined condition label.",
        },
        {
            "column": "adapter class",
            "level": "assay",
            "data_type": "string",
            "definition": "Adapter annotation, not a preparation protocol.",
        },
    ]
    assert "source_001:adapter class->assay.source_extension" in applied


def test_scope_audit_accepts_semantic_decision_alias_and_advisory_extras():
    parsed = EntityPlanScopeAuditResponse.model_validate(
        {
            "missing_conditions": [
                {
                    "group_id": "group_001",
                    "dimension_name": "condition",
                    "source_value": "treated",
                    "level": "sample",
                    "field_name": "treatment",
                    "rationale": "Provider explanation",
                    "suggested_level": "sample",
                }
            ],
            "record_column_decisions": [
                {
                    "column": "adapter class",
                    "decision": "source_extension",
                    "level": "assay",
                }
            ],
        }
    ).model_dump()

    assert parsed["record_column_decisions"][0]["disposition"] == "source_extension"
    assert parsed["record_column_decisions"][0]["source_id"] == ""


def test_focused_record_column_audit_has_single_purpose_contract():
    parsed = EntityPlanRecordColumnAuditResponse.model_validate(
        {
            "record_column_decisions": [
                {
                    "source_id": "source_001",
                    "table_name": "Sample information",
                    "column": "developmental.age",
                    "disposition": "fairds_mapping",
                    "level": "sample",
                    "field_name": "dev_stage",
                    "data_type": "string",
                    "rationale": "Developmental labels match the field semantics.",
                }
            ]
        }
    ).model_dump()

    assert parsed["record_column_decisions"][0]["field_name"] == "dev_stage"
    with pytest.raises(Exception):
        EntityPlanRecordColumnAuditResponse.model_validate(
            {
                "record_column_decisions": [],
                "mapping_corrections": [],
            }
        )


def test_design_dimension_accepts_local_ambiguity_without_discarding_plan():
    from fairifier.agents.response_models import EntityDesignClaimsResponse

    parsed = EntityDesignClaimsResponse.model_validate(
        {
            "investigations": [],
            "studies": [],
            "design_groups": [
                {
                    "group_id": "group_001",
                    "label": "uneven design",
                    "study_row_id": "study_001",
                    "evidence": "The source reports an incomplete factor series.",
                    "dimensions": [
                        {
                            "name": "input amount",
                            "level_count": 4,
                            "explicit_values": [],
                            "origin": "derived",
                            "semantic_role": "material_path",
                            "known_values": [],
                            "field_mappings": [],
                            "field_name": None,
                            "applies_to": ["sample", "assay"],
                            "unresolved_ambiguities": [
                                "The complete enumeration is not stated."
                            ],
                        }
                    ],
                    "unresolved_ambiguities": [],
                }
            ],
            "record_table_plans": [],
            "design_summary": [],
            "unresolved_ambiguities": [],
            "confidence": 0.5,
        }
    )

    assert parsed.design_groups[0].dimensions[0].unresolved_ambiguities == [
        "The complete enumeration is not stated."
    ]


def test_planner_requires_strong_focal_table_candidate_to_be_addressed():
    profile = {
        "source_id": "source_001",
        "table_name": "Samples",
        "record_count": 6,
        "applied_filters": [{"column": "project", "value": "study-1"}],
        "focal_evidence_score": 4,
    }

    errors = EntityStructurePlannerAgent._candidate_record_plan_errors(
        {"record_table_plans": []}, [profile]
    )
    assert len(errors) == 1
    assert "project=study-1" in errors[0]

    errors = EntityStructurePlannerAgent._candidate_record_plan_errors(
        {
            "record_table_plans": [
                {
                    "source_id": "source_001",
                    "table_name": "Samples",
                    "filters": [{"column": "project", "value": "study-1"}],
                }
            ]
        },
        [profile],
    )
    assert len(errors) == 1
    assert "marked incomplete" in errors[0]

    errors = EntityStructurePlannerAgent._candidate_record_plan_errors(
        {
            "record_table_plans": [
                {
                    "source_id": "source_001",
                    "table_name": "Samples",
                    "covers_complete_focal_study": True,
                    "filters": [{"column": "project", "value": "study-1"}],
                }
            ]
        },
        [profile],
    )
    assert errors == []


def test_planner_recovers_focal_dataset_evidence_from_full_source_text():
    profiles = [
        {
            "source_id": "source_001",
            "table_name": "Samples",
            "applied_filters": [{"column": "project", "value": "study-1"}],
            "focal_evidence_score": 0,
        },
        {
            "source_id": "source_001",
            "table_name": "Samples",
            "applied_filters": [{"column": "project", "value": "study-2"}],
            "focal_evidence_score": 0,
        },
    ]

    preferred = EntityStructurePlannerAgent._preferred_dataset_profiles(
        profiles,
        "All sequencing data generated in this study were submitted under "
        "accession study-2. Study-1 was used as a reference dataset.",
    )

    assert len(preferred) == 1
    assert preferred[0]["applied_filters"][0]["value"] == "study-2"
    assert preferred[0]["focal_evidence_score"] > 0


def test_record_column_audit_infers_omitted_table_context_only_when_unique():
    claims = {
        "record_table_plans": [
            {
                "source_id": "source_001",
                "table_name": "records",
                "covers_complete_focal_study": True,
                "filters": [],
                "sample_identifier_column": "sample",
                "assay_identifier_column": "run",
                "group_column": "branch",
                "column_mappings": [],
                "source_extension_mappings": [],
                "excluded_columns": [],
            }
        ]
    }
    audit = {
        "record_column_decisions": [
            {"column": "sample", "disposition": "structural_only"},
            {"column": "run", "disposition": "structural_only"},
            {"column": "branch", "disposition": "structural_only"},
            {
                "column": "adapter class",
                "disposition": "source_extension",
                "level": "assay",
            },
        ]
    }
    profiles = [
        {
            "source_id": "source_001",
            "table_name": "records",
            "columns": ["sample", "run", "branch", "adapter class"],
        }
    ]

    _, errors = EntityStructurePlannerAgent._apply_record_column_audit(
        claims, audit, {}, profiles
    )

    assert errors == []
    assert claims["record_table_plans"][0]["source_extension_mappings"][0][
        "column"
    ] == "adapter class"


def test_record_column_audit_retains_populated_focal_metadata_when_excluded():
    claims = {
        "record_table_plans": [
            {
                "source_id": "source_001",
                "table_name": "records",
                "covers_complete_focal_study": True,
                "filters": [],
                "sample_identifier_column": "sample",
                "assay_identifier_column": "run",
                "observation_unit_columns": [],
                "column_mappings": [],
                "source_extension_mappings": [],
                "excluded_columns": [],
            }
        ]
    }
    audit = {
        "record_column_decisions": [
            {
                "source_id": "source_001",
                "table_name": "records",
                "column": "sample",
                "disposition": "structural_only",
            },
            {
                "source_id": "source_001",
                "table_name": "records",
                "column": "run",
                "disposition": "structural_only",
            },
            {
                "source_id": "source_001",
                "table_name": "records",
                "column": "source category",
                "disposition": "excluded",
                "rationale": "Not used in the primary analysis.",
            },
        ]
    }
    profiles = [
        {
            "source_id": "source_001",
            "table_name": "records",
            "columns": ["sample", "run", "source category"],
            "column_distributions": [
                {"column": "source category", "nonblank": 12}
            ],
        }
    ]

    applied, errors = EntityStructurePlannerAgent._apply_record_column_audit(
        claims, audit, {}, profiles
    )

    assert errors == []
    assert claims["record_table_plans"][0]["excluded_columns"] == []
    assert claims["record_table_plans"][0]["source_extension_mappings"] == [
        {
            "column": "source category",
            "level": "sample",
            "data_type": "string",
            "definition": (
                "Populated source-record metadata retained instead of the proposed "
                "exclusion: Not used in the primary analysis."
            ),
        }
    ]
    assert applied[-1] == "source_001:source category->sample.source_extension"


def test_structure_planner_promotes_mapped_field_from_selected_package_contract():
    selected = {
        "term": "sample name",
        "metadata": {"isa_sheet": "sample", "package": "default"},
    }
    dose = {
        "term": "dose",
        "metadata": {
            "isa_sheet": "sample",
            "package": "Lean Plant Contract",
            "regex": ".*",
        },
    }
    state = {
        "retrieved_knowledge": [selected],
        "api_capabilities": {"selected_package_field_contracts": [dose]},
    }
    plan = {
        "levels": [
            {
                "level": "sample",
                "entities": [
                    {
                        "attributes": [
                            {
                                "dimension_name": "input amount",
                                "field_name": "dose",
                                "value": "0.1 ng",
                                "origin": "explicit",
                            }
                        ]
                    }
                ],
            }
        ]
    }

    planning = EntityStructurePlannerAgent._planning_knowledge(state)
    promoted = EntityStructurePlannerAgent._promote_planned_fields(
        state, plan, planning
    )

    assert "dose" in EntityStructurePlannerAgent._field_catalog(planning)["sample"]
    assert promoted == ["sample.dose"]
    assert [item["term"] for item in state["retrieved_knowledge"]] == [
        "sample name",
        "dose",
    ]


def test_mapping_audit_replaces_generic_description_with_specific_contract_field():
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "dimensions": [
                    {
                        "name": "input_amount",
                        "explicit_values": ["5 ng", "1 ng"],
                        "known_values": [],
                        "applies_to": ["sample", "assay"],
                        "field_mappings": [
                            {"level": "sample", "field_name": "sample description"}
                        ],
                    }
                ],
            }
        ]
    }
    audit = {
        "mapping_corrections": [
            {
                "group_id": "group_001",
                "dimension_name": "input_amount",
                "level": "sample",
                "field_name": "dose",
            }
        ]
    }
    knowledge = [
        {"term": "dose", "metadata": {"isa_sheet": "sample", "regex": ".*"}}
    ]

    applied = EntityStructurePlannerAgent._apply_mapping_audit_findings(
        claims,
        audit,
        {"sample": ["sample description", "dose"]},
        knowledge,
    )

    assert applied == ["group_001:input_amount->sample.dose"]
    assert claims["design_groups"][0]["dimensions"][0]["field_mappings"] == [
        {"level": "sample", "field_name": "dose"}
    ]


def test_complete_mapping_audit_requires_one_decision_per_dimension():
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "dimensions": [
                    {
                        "name": "input_amount",
                        "explicit_values": ["5 ng", "1 ng"],
                        "known_values": [],
                        "applies_to": ["sample", "assay"],
                        "field_mappings": [],
                    }
                ],
            }
        ]
    }

    applied, errors = EntityStructurePlannerAgent._apply_complete_mapping_audit(
        claims, {"mapping_decisions": []}, {"assay": ["sample preparation"]}, []
    )

    assert applied == []
    assert errors == [
        "Independent mapping audit omitted or duplicated group_001:input_amount."
    ]
    assert claims["design_groups"][0]["dimensions"][0]["field_mappings"] == []


def test_complete_mapping_audit_replaces_draft_mapping_with_validated_decision():
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "dimensions": [
                    {
                        "name": "input_amount",
                        "explicit_values": ["5 ng", "1 ng"],
                        "known_values": [],
                        "applies_to": ["sample", "assay"],
                        "field_mappings": [
                            {"level": "sample", "field_name": "dose"}
                        ],
                    }
                ],
            }
        ]
    }
    audit = {
        "mapping_decisions": [
            {
                "group_id": "group_001",
                "dimension_name": "input_amount",
                "mappings": [
                    {
                        "level": "assay",
                        "field_name": "sample preparation",
                    }
                ],
            }
        ]
    }
    knowledge = [
        {
            "term": "sample preparation",
            "metadata": {"isa_sheet": "assay", "regex": ".*"},
        }
    ]

    applied, errors = EntityStructurePlannerAgent._apply_complete_mapping_audit(
        claims,
        audit,
        {"sample": ["dose"], "assay": ["sample preparation"]},
        knowledge,
    )

    assert errors == []
    assert applied == [
        "group_001:input_amount->assay.sample preparation"
    ]
    assert claims["design_groups"][0]["dimensions"][0]["field_mappings"] == [
        {"level": "assay", "field_name": "sample preparation"}
    ]


def test_complete_mapping_audit_rejects_bad_target_but_keeps_cardinality_claim():
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "dimensions": [
                    {
                        "name": "input_amount",
                        "level_count": 2,
                        "explicit_values": ["5 ng", "1 ng"],
                        "known_values": [],
                        "applies_to": ["sample", "assay"],
                        "field_mappings": [
                            {"level": "sample", "field_name": "dose"}
                        ],
                    }
                ],
            }
        ]
    }
    audit = {
        "mapping_decisions": [
            {
                "group_id": "group_001",
                "dimension_name": "input_amount",
                "mappings": [
                    {"level": "assay", "field_name": "not in catalog"}
                ],
            }
        ]
    }

    applied, warnings = EntityStructurePlannerAgent._apply_complete_mapping_audit(
        claims, audit, {"sample": ["dose"], "assay": ["sample preparation"]}, []
    )

    assert applied == ["group_001:input_amount->unmapped"]
    assert warnings and "rejected mapping target" in warnings[0]
    dimension = claims["design_groups"][0]["dimensions"][0]
    assert dimension["level_count"] == 2
    assert dimension["field_mappings"] == []


@pytest.mark.anyio
async def test_orchestrator_still_generates_when_entity_plan_is_invalid(monkeypatch):
    calls = []

    class Planner:
        async def execute(self, state):
            state["entity_plan_validation"] = {
                "passed": False,
                "errors": ["sample parent is unresolved"],
            }
            return state

    class JSONGenerator:
        async def execute(self, state):
            calls.append("json")
            return state

    node = OrchestrateNode(
        document_parser=object(),
        knowledge_retriever=object(),
        entity_structure_planner=Planner(),
        json_generator=JSONGenerator(),
        max_step_retries=0,
        max_global_retries=0,
    )

    async def pass_through(state, agent, agent_name, check_output_fn):
        calls.append(agent_name)
        if agent_name == "DocumentParser":
            state["document_info"] = {"title": "source"}
        elif agent_name == "KnowledgeRetriever":
            state["retrieved_knowledge"] = [{"term": "study title"}]
        elif agent_name == "JSONGenerator":
            return await agent.execute(state)
        return state

    async def plan_workflow(state):
        return state

    monkeypatch.setattr(node, "_execute_agent_with_retry", pass_through)
    monkeypatch.setattr(node, "_plan_workflow_internal", plan_workflow)

    result = await node({"context": {}, "execution_history": [], "errors": []})

    assert calls[:2] == ["DocumentParser", "KnowledgeRetriever"]
    assert "JSONGenerator" in calls
    assert result["entity_plan_hard_gate_failed"] is True
    assert result["needs_human_review"] is True


def test_mapper_clears_broadcast_values_outside_plan_mapped_entities():
    matrix = {
        "sample": {
            "columns": ["sample identifier", "dose"],
            "rows": [
                {"sample identifier": "s1", "dose": "5 ng"},
                {"sample identifier": "s2", "dose": "0.1-5 ng"},
            ],
        }
    }
    plan = {
        "levels": [
            {
                "level": "sample",
                "entities": [
                    {
                        "row_id": "s1",
                        "attributes": [
                            {"field_name": "dose", "value": "5 ng"}
                        ],
                    },
                    {"row_id": "s2", "attributes": []},
                ],
            }
        ]
    }

    cleaned, counts = ISAValueMapperAgent._clear_values_outside_plan_field_scope(
        matrix, plan
    )

    assert cleaned["sample"]["rows"][0]["dose"] == "5 ng"
    assert cleaned["sample"]["rows"][1]["dose"] == ""
    assert counts == {"sample.dose": 1}


def test_mapper_prunes_sheet_wide_repeated_optional_narrative():
    matrix = {
        "assay": {
            "columns": ["assay identifier", "notes"],
            "rows": [
                {"assay identifier": "a1", "notes": "whole-study summary"},
                {"assay identifier": "a2", "notes": "whole-study summary"},
            ],
        }
    }
    fields = {
        "assay": [
            {
                "field_name": "notes",
                "requirement": "OPTIONAL",
                "status": "confirmed",
                "evidence": "abstract",
            }
        ]
    }

    cleaned, pruned = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix, fields, {"levels": []}
    )

    assert cleaned["assay"]["columns"] == ["assay identifier"]
    assert pruned == {"assay": ["notes"]}


def test_mapper_keeps_distinct_field_when_only_value_substring_overlaps_plan():
    matrix = {
        "sample": {
            "columns": ["sample identifier", "specific field", "broad field"],
            "rows": [
                {
                    "sample identifier": "s1",
                    "specific field": "Line-A (reference)",
                    "broad field": "Line-A",
                },
                {
                    "sample identifier": "s2",
                    "specific field": "",
                    "broad field": "",
                },
            ],
        }
    }
    fields = {
        "sample": [
            {
                "field_name": "specific field",
                "requirement": "OPTIONAL",
                "status": "confirmed",
                "evidence": "source",
            },
            {
                "field_name": "broad field",
                "requirement": "OPTIONAL",
                "status": "confirmed",
                "evidence": "source",
            },
        ]
    }
    plan = {
        "design_claims": {
            "design_groups": [
                {
                    "group_id": "g1",
                    "dimensions": [
                        {"name": "line", "applies_to": ["sample", "assay"]}
                    ],
                }
            ]
        },
        "levels": [
            {
                "level": "sample",
                "entities": [
                    {
                        "source_group": "g1",
                        "attributes": [
                            {
                                "dimension_name": "line",
                                "field_name": "specific field",
                                "value": "Line-A (reference)",
                                "origin": "explicit",
                            }
                        ],
                    },
                    {"source_group": "g2", "attributes": []},
                ],
            }
        ],
    }

    cleaned, pruned = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix, fields, plan, source_text="Line-A (reference)"
    )

    assert "specific field" in cleaned["sample"]["columns"]
    assert "broad field" in cleaned["sample"]["columns"]
    assert pruned == {}


def test_mapper_prunes_optional_cells_not_supported_by_confirmed_field_value():
    matrix = {
        "assay": {
            "columns": ["assay identifier", "optional label"],
            "rows": [
                {"assay identifier": "a1", "optional label": "derived label 01"},
                {"assay identifier": "a2", "optional label": "derived label 02"},
            ],
        }
    }
    fields = {
        "assay": [
            {
                "field_name": "optional label",
                "value": "source assay type",
                "requirement": "OPTIONAL",
                "status": "confirmed",
                "evidence": "source assay type",
            }
        ]
    }

    cleaned, pruned = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix, fields, {"levels": []}, source_text="source assay type"
    )

    assert cleaned["assay"]["columns"] == ["assay identifier"]
    assert pruned == {"assay": ["optional label"]}


def test_mapper_keeps_optional_values_verified_against_source_text():
    matrix = {
        "sample": {
            "columns": ["sample identifier", "specific factor"],
            "rows": [
                {"sample identifier": "s1", "specific factor": "condition alpha"},
                {"sample identifier": "s2", "specific factor": "condition alpha"},
            ],
        }
    }
    fields = {
        "sample": [
            {
                "field_name": "specific factor",
                "requirement": "OPTIONAL",
                "status": "provisional",
                "evidence": "",
            }
        ]
    }

    cleaned, pruned = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix,
        fields,
        {"levels": []},
        source_text="Samples were collected under condition alpha.",
    )

    assert cleaned["sample"]["columns"] == [
        "sample identifier",
        "specific factor",
    ]
    assert pruned == {}


def test_mapper_keeps_optional_values_verified_against_explicit_plan_values():
    matrix = {
        "assay": {
            "columns": ["assay identifier", "preparation amount"],
            "rows": [
                {"assay identifier": "a1", "preparation amount": "5 ng"},
                {"assay identifier": "a2", "preparation amount": "1 ng"},
            ],
        }
    }
    fields = {
        "assay": [
            {
                "field_name": "preparation amount",
                "requirement": "OPTIONAL",
                "status": "provisional",
                "evidence": "",
            }
        ]
    }
    plan = {
        "design_claims": {
            "design_groups": [
                {
                    "group_id": "g1",
                    "dimensions": [
                        {
                            "name": "amount",
                            "applies_to": ["sample", "assay"],
                        }
                    ],
                }
            ]
        },
        "levels": [
            {
                "level": "assay",
                "entities": [
                    {
                        "source_group": "g1",
                        "attributes": [
                            {
                                "dimension_name": "amount",
                                "field_name": None,
                                "value": "5 ng",
                                "origin": "explicit",
                            }
                        ],
                    },
                    {
                        "source_group": "g1",
                        "attributes": [
                            {
                                "dimension_name": "amount",
                                "field_name": None,
                                "value": "1 ng",
                                "origin": "explicit",
                            }
                        ],
                    },
                ],
            }
        ],
    }

    cleaned, pruned = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix, fields, plan
    )

    assert cleaned["assay"]["columns"] == [
        "assay identifier",
        "preparation amount",
    ]
    assert pruned == {}


def test_mapper_preserves_placeholder_shaped_value_owned_by_entity_plan():
    matrix = {
        "assay": {
            "columns": ["assay identifier", "adapter trim"],
            "rows": [
                {"assay identifier": "a1", "adapter trim": "none"},
                {"assay identifier": "a2", "adapter trim": "nextera"},
            ],
        }
    }
    fields = {
        "assay": [
            {
                "field_name": "adapter trim",
                "requirement": "OPTIONAL",
                "status": "confirmed",
                "evidence": "authoritative source table",
            }
        ]
    }
    plan = {
        "levels": [
            {
                "level": "assay",
                "entities": [
                    {
                        "attributes": [
                            {
                                "field_name": "adapter trim",
                                "value": "none",
                                "origin": "explicit",
                            }
                        ]
                    },
                    {
                        "attributes": [
                            {
                                "field_name": "adapter trim",
                                "value": "nextera",
                                "origin": "explicit",
                            }
                        ]
                    },
                ],
            }
        ]
    }

    cleaned, pruned = ISAValueMapperAgent._prune_uninformative_optional_columns(
        matrix, fields, plan
    )

    assert cleaned["assay"]["columns"] == ["assay identifier", "adapter trim"]
    assert [row["adapter trim"] for row in cleaned["assay"]["rows"]] == [
        "none",
        "nextera",
    ]
    assert pruned == {}


def test_mapper_restores_confirmed_level_value_despite_synthetic_entity_id():
    matrix = {
        "assay": {
            "columns": ["assay identifier", "library strategy"],
            "rows": [
                {"assay identifier": "a1", "library strategy": ""},
                {"assay identifier": "a2", "library strategy": ""},
            ],
        }
    }
    fields = {
        "assay": [
            {
                "field_name": "library strategy",
                "value": "RNA-Seq",
                "status": "confirmed",
                "confidence": 0.95,
                "evidence": "source_001: mRNA-seq",
                "value_scope": "level",
                "entity_id": "assay_001",
            }
        ]
    }

    restored = ISAValueMapperAgent._restore_high_confidence_shared_values(
        matrix, fields, entity_plan={"levels": []}
    )

    assert [row["library strategy"] for row in restored["assay"]["rows"]] == [
        "RNA-Seq",
        "RNA-Seq",
    ]


def test_reuse_audit_fails_closed_when_shared_pool_does_not_prove_reuse():
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "evidence": "RNA was diluted and prepared with three methods.",
                "reuse_same_sample_for_multiple_assays": True,
                "sample_reuse_evidence": "prepared with three methods",
            }
        ]
    }
    audit = {
        "reuse_validations": [
            {
                "group_id": "group_001",
                "approved": False,
                "evidence_quote": None,
                "rationale": "Distinct preparation paths are not explicit reuse.",
            }
        ]
    }

    rejected = EntityStructurePlannerAgent._enforce_independent_reuse_audit(
        claims, audit
    )

    assert rejected == ["group_001"]
    assert claims["design_groups"][0]["reuse_same_sample_for_multiple_assays"] is False
    assert claims["design_groups"][0]["sample_reuse_evidence"] is None


def test_reuse_audit_accepts_only_verbatim_independent_proof():
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "evidence": "The same identified sample was measured in two modalities.",
                "reuse_same_sample_for_multiple_assays": True,
                "sample_reuse_evidence": None,
            }
        ]
    }
    audit = {
        "reuse_validations": [
            {
                "group_id": "group_001",
                "approved": True,
                "evidence_quote": "same identified sample",
                "rationale": "Explicitly the same material.",
            }
        ]
    }

    rejected = EntityStructurePlannerAgent._enforce_independent_reuse_audit(
        claims, audit, source_text=claims["design_groups"][0]["evidence"]
    )

    assert rejected == []
    assert claims["design_groups"][0]["sample_reuse_evidence"] == "same identified sample"


def test_dimension_scope_audit_requires_consensus_before_changing_cardinality():
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "dimensions": [
                    {
                        "name": "input_amount",
                        "applies_to": ["observationunit", "sample", "assay"],
                    }
                ],
            }
        ]
    }
    audit = {
        "dimension_scopes": [
            {
                "group_id": "group_001",
                "dimension_name": "input_amount",
                "applies_to": ["sample", "assay"],
            }
        ]
    }

    applied, errors = EntityStructurePlannerAgent._apply_dimension_scope_audit(
        claims, audit
    )

    assert applied == []
    assert errors == [
        "Independent scope audit disagreed with the draft scope for "
        "group_001:input_amount: draft=['observationunit', 'sample', 'assay'], "
        "audit=['sample', 'assay']."
    ]
    assert claims["design_groups"][0]["dimensions"][0]["applies_to"] == [
        "observationunit",
        "sample",
        "assay",
    ]


def test_dimension_scope_audit_can_repair_disagreement_with_authoritative_records():
    claims = {
        "record_table_plans": [{"covers_complete_focal_study": True}],
        "design_groups": [
            {
                "group_id": "group_001",
                "reuse_same_sample_for_multiple_assays": False,
                "dimensions": [
                    {
                        "name": "input_amount",
                        "level_count": 5,
                        "semantic_role": "observation_condition",
                        "applies_to": ["observationunit", "sample", "assay"],
                    }
                ],
            }
        ],
    }
    audit = {
        "dimension_scopes": [
            {
                "group_id": "group_001",
                "dimension_name": "input_amount",
                "semantic_role": "material_path",
                "applies_to": ["sample", "assay"],
            }
        ]
    }

    applied, errors = EntityStructurePlannerAgent._apply_dimension_scope_audit(
        claims, audit
    )

    assert errors == []
    assert applied == [
        "group_001:input_amount.role=material_path",
        "group_001:input_amount=sample/assay",
    ]
    dimension = claims["design_groups"][0]["dimensions"][0]
    assert dimension["semantic_role"] == "material_path"
    assert dimension["applies_to"] == ["sample", "assay"]


def test_dimension_scope_audit_can_relocate_constant_without_changing_cardinality():
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "dimensions": [
                    {
                        "name": "material_state",
                        "level_count": 1,
                        "applies_to": ["sample", "assay"],
                    }
                ],
            }
        ]
    }
    audit = {
        "dimension_scopes": [
            {
                "group_id": "group_001",
                "dimension_name": "material_state",
                "applies_to": ["observationunit", "sample", "assay"],
            }
        ]
    }

    applied, errors = EntityStructurePlannerAgent._apply_dimension_scope_audit(
        claims, audit
    )

    assert errors == []
    assert applied == [
        "group_001:material_state=observationunit/sample/assay"
    ]
    assert claims["design_groups"][0]["dimensions"][0]["applies_to"] == [
        "observationunit",
        "sample",
        "assay",
    ]


def test_semantic_role_consensus_repairs_varying_condition_scope():
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "reuse_same_sample_for_multiple_assays": False,
                "dimensions": [
                    {
                        "name": "condition_axis",
                        "level_count": 8,
                        "semantic_role": "observation_condition",
                        "applies_to": ["sample", "assay"],
                    }
                ],
            }
        ]
    }
    audit = {
        "dimension_scopes": [
            {
                "group_id": "group_001",
                "dimension_name": "condition_axis",
                "semantic_role": "observation_condition",
                "applies_to": ["observationunit", "sample", "assay"],
            }
        ]
    }

    applied, errors = EntityStructurePlannerAgent._apply_dimension_scope_audit(
        claims, audit
    )

    assert errors == []
    assert applied == [
        "group_001:condition_axis=observationunit/sample/assay"
    ]
    assert claims["design_groups"][0]["dimensions"][0]["applies_to"] == [
        "observationunit",
        "sample",
        "assay",
    ]


def test_semantic_role_disagreement_blocks_scope_arbitration():
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "dimensions": [
                    {
                        "name": "factor_axis",
                        "level_count": 3,
                        "semantic_role": "observation_condition",
                        "applies_to": ["observationunit", "sample", "assay"],
                    }
                ],
            }
        ]
    }
    audit = {
        "dimension_scopes": [
            {
                "group_id": "group_001",
                "dimension_name": "factor_axis",
                "semantic_role": "material_path",
                "applies_to": ["sample", "assay"],
            }
        ]
    }

    applied, errors = EntityStructurePlannerAgent._apply_dimension_scope_audit(
        claims, audit
    )

    assert applied == []
    assert errors == [
        "Independent semantic-role audit disagreed with the draft for "
        "group_001:factor_axis: draft='observation_condition', "
        "audit='material_path'."
    ]


def test_scope_audit_schema_accepts_provider_dimension_aliases_and_redundant_context():
    from fairifier.agents.response_models import EntityPlanScopeAuditResponse

    parsed = EntityPlanScopeAuditResponse.model_validate(
        {
            "mapping_decisions": [
                {
                    "group_id": "group_001",
                    "dimension": "developmental_stage",
                    "mappings": [
                        {"level": "sample", "field_name": "dev_stage"}
                    ],
                    "applies_to": ["sample", "assay"],
                }
            ],
            "dimension_scopes": [
                {
                    "group_id": "group_001",
                    "dimension": "developmental_stage",
                    "applies_to": ["sample", "assay"],
                }
            ],
            "reuse_validations": [
                {
                    "group_id": "group_001",
                    "approved": False,
                    "evidence_quote": None,
                    "reasoning": "No explicit reuse evidence.",
                }
            ],
        }
    )

    payload = parsed.model_dump()
    assert payload["mapping_decisions"][0]["dimension_name"] == "developmental_stage"
    assert payload["dimension_scopes"][0]["dimension_name"] == "developmental_stage"
    assert payload["reuse_validations"][0]["rationale"] == "No explicit reuse evidence."


def test_scope_audit_keeps_core_decisions_when_optional_finding_is_incomplete():
    from fairifier.agents.response_models import EntityPlanScopeAuditResponse

    parsed = EntityPlanScopeAuditResponse.model_validate(
        {
            "missing_conditions": [
                {
                    "group_id": "group_001",
                    "source_value": "source-stated condition",
                    "level": "sample",
                    "field_name": "organism part",
                    "evidence": "Source sentence supporting the condition.",
                }
            ],
            "mapping_decisions": [
                {
                    "group_id": "group_001",
                    "dimension": "material_state",
                    "mappings": [],
                }
            ],
            "dimension_scopes": [
                {
                    "group_id": "group_001",
                    "dimension": "material_state",
                    "applies_to": ["sample", "assay"],
                }
            ],
        }
    ).model_dump()

    assert parsed["missing_conditions"][0]["dimension_name"] == ""
    assert parsed["missing_conditions"][0]["evidence"] == (
        "Source sentence supporting the condition."
    )
    assert parsed["mapping_decisions"][0]["dimension_name"] == "material_state"
    assert parsed["dimension_scopes"][0]["dimension_name"] == "material_state"


def test_design_claim_response_allows_unknown_contextual_dimension_count():
    from fairifier.agents.response_models import EntityDesignClaimsResponse

    parsed = EntityDesignClaimsResponse.model_validate(
        {
            "investigations": [],
            "studies": [],
            "design_groups": [
                {
                    "group_id": "context_group",
                    "study_row_id": "study_001",
                    "evidence": "Replicate count varies across reused datasets.",
                    "dimensions": [
                        {
                            "name": "replicate",
                            "level_count": None,
                            "origin": "derived",
                            "semantic_role": "sample_replicate",
                            "applies_to": ["sample"],
                        }
                    ],
                }
            ],
            "record_table_plans": [],
            "design_summary": [],
            "unresolved_ambiguities": [],
            "confidence": 0.5,
        }
    )

    assert parsed.design_groups[0].dimensions[0].level_count is None


def _partially_enumerated_design_claims(count=None, values=None, origin="derived"):
    return {
        "investigations": [{
            "row_id": "investigation_a", "label": "Synthetic experiment",
            "evidence": "Two independent experimental branches were reported.",
        }],
        "studies": [{
            "row_id": "study_a", "parent_row_id": "investigation_a",
            "label": "Material measurements", "evidence": "Two branches were measured.",
        }],
        "design_groups": [
            {
                "group_id": "known_branch", "label": "Known branch",
                "study_row_id": "study_a",
                "evidence": "Independent materials alpha and beta were measured.",
                "dimensions": [{
                    "name": "material", "level_count": 2,
                    "explicit_values": ["alpha", "beta"], "origin": "explicit",
                    "semantic_role": "material_path", "field_name": "material label",
                    "applies_to": ["observationunit", "sample", "assay"],
                }],
            },
            {
                "group_id": "unresolved_branch", "label": "Second branch",
                "study_row_id": "study_a",
                "evidence": "The second branch used a series whose total was not stated.",
                "dimensions": [{
                    "name": "series", "level_count": count,
                    "explicit_values": list(values or []), "origin": origin,
                    "semantic_role": "observation_condition", "field_name": "series label",
                    "applies_to": ["observationunit", "sample", "assay"],
                }],
                "unresolved_ambiguities": ["The source does not establish the full series count."],
            },
        ],
        "unresolved_ambiguities": [],
    }


@pytest.mark.parametrize("count", [None, 0])
def test_unknown_count_keeps_branch_without_expanding_the_factor(count):
    claims = _partially_enumerated_design_claims(count=count)
    original = deepcopy(claims)
    plan = materialize_entity_claims(claims)
    levels = {level["level"]: level for level in plan["levels"]}

    for level in ("observationunit", "sample", "assay"):
        rows = levels[level]["entities"]
        assert len([r for r in rows if r["source_group"] == "known_branch"]) == 2
        # the branch stays (its reported results need rows) but the factor with
        # an unstated level count is not expanded and carries no invented value
        unresolved = [r for r in rows if r["source_group"] == "unresolved_branch"]
        assert len(unresolved) == 1
        assert not any(a["dimension_name"] == "series" for a in unresolved[0]["attributes"])
    for parent, child in (("observationunit", "sample"), ("sample", "assay")):
        assert {row["parent_row_id"] for row in levels[child]["entities"]} <= {
            row["row_id"] for row in levels[parent]["entities"]
        }
    assert claims == original
    assert plan["design_claims"] == original
    assert any("unresolved_branch" in note and "series" in note
               for note in plan["unresolved_ambiguities"])


def test_null_count_uses_complete_source_explicit_enumeration_without_changing_claim():
    claims = _partially_enumerated_design_claims(values=["low", "high"], origin="explicit")
    claims["design_groups"][1]["evidence"] = "The complete second series comprised low and high."
    claims["design_groups"][1]["unresolved_ambiguities"] = []
    plan = materialize_entity_claims(claims)

    assert plan["materialization_errors"] == []
    for level in plan["levels"]:
        if level["level"] not in {"observationunit", "sample", "assay"}:
            continue
        rows = [row for row in level["entities"] if row["source_group"] == "unresolved_branch"]
        assert len(rows) == 2
        assert {row["attributes"][0]["value"] for row in rows} == {"low", "high"}
    assert plan["design_claims"]["design_groups"][1]["dimensions"][0]["level_count"] is None
    assert EntityStructurePlannerAgent._plan_errors(plan) == []


def test_source_explicit_constant_still_materializes_one_record_per_level():
    claims = _partially_enumerated_design_claims(count=1, values=["fixed"], origin="explicit")
    claims["design_groups"][1]["evidence"] = "The second branch used one fixed material."
    claims["design_groups"][1]["unresolved_ambiguities"] = []
    plan = materialize_entity_claims(claims)

    assert plan["materialization_errors"] == []
    for level in plan["levels"]:
        if level["level"] in {"observationunit", "sample", "assay"}:
            rows = [row for row in level["entities"] if row["source_group"] == "unresolved_branch"]
            assert len(rows) == 1
            assert rows[0]["attributes"][0]["value"] == "fixed"
    assert EntityStructurePlannerAgent._plan_errors(plan) == []


def test_unknown_count_cannot_be_inferred_from_partial_known_positions():
    claims = _partially_enumerated_design_claims()
    dimension = claims["design_groups"][1]["dimensions"][0]
    dimension["known_values"] = [{"position": 1, "value": "first reported condition"}]
    plan = materialize_entity_claims(claims)

    unresolved = [
        row for level in plan["levels"] for row in level["entities"]
        if row["source_group"] == "unresolved_branch"
    ]
    assert len(unresolved) == 3  # one per level, no series expansion
    assert all(a["value"] != "first reported condition"
               for row in unresolved for a in row["attributes"])
    assert plan["design_claims"]["design_groups"][1]["dimensions"][0] == dimension


def test_matrix_validation_cannot_override_retained_materialization_failure():
    claims = _partially_enumerated_design_claims(count=1, values=["fixed"], origin="explicit")
    claims["design_groups"][1]["unresolved_ambiguities"] = []
    plan = materialize_entity_claims(claims)
    plan["materialization_errors"] = ["A source branch has unresolved cardinality."]
    matrix = project_matrix_onto_entity_plan({}, plan)
    validation = validate_entity_matrix_against_plan(matrix, plan)

    assert validation["passed"] is False
    assert validation["submission_ready"] is False
    assert "A source branch has unresolved cardinality." in validation["errors"]


def _reported_fit_fixture():
    claims = _partially_enumerated_design_claims()
    claims["design_groups"] = claims["design_groups"][:1]
    plan = materialize_entity_claims(claims)
    sample = next(x for x in plan["levels"] if x["level"] == "sample")["entities"][0]
    source = "Material alpha was characterised. For alpha the fitted response was 0.7 using three replicates."
    record = {
        "record_id": "reported_fit_a", "sample_row_id": sample["row_id"],
        "record_kind": "fitted_result", "source_subject": "alpha",
        "source_quote": "For alpha the fitted response was 0.7 using three replicates.",
        "label": "Fitted response for alpha", "source_group": "fit_branch",
        "attributes": [{"field_name": "fitted response", "value": "0.7"}],
        "unreported_design": ["Underlying concentration count is not reported."],
    }
    return plan, record, source


def _reported_material_fixture():
    claims = _partially_enumerated_design_claims()
    claims["design_groups"] = []
    plan = materialize_entity_claims(claims)
    source = "Material alpha was purified before characterisation."
    records = [
        {"record_id": "prep_alpha", "level": "observationunit", "parent_row_id": "study_a",
         "record_kind": "material_preparation", "source_subject": "alpha", "source_quote": source,
         "label": "Alpha preparation", "source_group": "materials"},
        {"record_id": "material_alpha", "level": "sample", "parent_row_id": "prep_alpha",
         "record_kind": "material_identity", "source_subject": "alpha", "source_quote": source,
         "label": "Alpha material", "source_group": "materials"},
    ]
    return plan, records, source


def test_reported_material_inventory_does_not_create_unreported_assays():
    from fairifier.utils.entity_plan import materialize_reported_materials
    plan, records, source = _reported_material_fixture()
    result = materialize_reported_materials(plan, list(reversed(records)), source_text=source)
    levels = {level["level"]: level for level in result["levels"]}
    assert levels["observationunit"]["cardinality"] == 1
    assert levels["sample"]["cardinality"] == 1
    assert levels["assay"]["cardinality"] == 0
    assert levels["sample"]["entities"][0]["parent_row_id"] == "prep_alpha"
    assert levels["sample"]["entities"][0]["attributes"][0]["value"] == "alpha"
    assert plan["levels"][2]["cardinality"] == 0


@pytest.mark.parametrize("source_detail,quoted_detail,accepted", [
    (r"$60^{\circ}$ C", "60°C", True),
    (r"$-2.5^{\circ}$ C", "-2.5 °C", True),
    (r"$60^{\circ}$ C", "6°C", False),
    (r"$60^{\circ}$ C", "60°F", False),
    (r"$-2.5^{\circ}$ C", "2.5°C", False),
    (r"50 mg $_{protein}$ /L", "50 mg_protein/L", True),
    (r"50 mg $_{protein}$ /L", "50 mg/L", False),
    (r"50 mg $_{protein}$ /L", "50 mg_substrate/L", False),
    (r"50 mg $_{protein}$ /L", "5 mg_protein/L", False),
])
def test_material_quote_accepts_equivalent_math_markup_without_changing_quantities(
    source_detail, quoted_detail, accepted,
):
    from fairifier.utils.entity_plan import materialize_reported_materials
    plan, records, _ = _reported_material_fixture()
    source = f"Material alpha was purified at {source_detail} before characterisation."
    for record in records:
        record["source_quote"] = f"Material alpha was purified at {quoted_detail} before characterisation."
    result = materialize_reported_materials(plan, records, source_text=source)
    assert bool(result.get("materialization_errors")) is not accepted
    if not accepted:
        assert result["levels"] == plan["levels"]


@pytest.mark.parametrize("source_identifier", [r"alpha\_1", "alpha_1"])
def test_reported_material_accepts_escaped_markdown_identifier(source_identifier):
    from fairifier.utils.entity_plan import materialize_reported_materials

    plan, records, source = _reported_material_fixture()
    source = source.replace("alpha", source_identifier)
    for record in records:
        record["source_subject"] = "alpha_1"
        record["source_quote"] = "Material alpha_1 was purified before characterisation."
    result = materialize_reported_materials(plan, records, source_text=source)
    assert not result.get("materialization_errors")
    assert sum(len(level["entities"]) for level in result["levels"]) == 4

    # Display markup equivalence cannot merge distinct scientific identifiers.
    rejected = materialize_reported_materials(
        plan, records, source_text=source.replace(source_identifier, "alpha-1")
    )
    assert rejected.get("materialization_errors")
    assert rejected["levels"] == plan["levels"]


@pytest.mark.parametrize(
    "field,value,required_diagnostic",
    [
        ("parent_row_id", "study_a", ("parent_row_id", "observationunit")),
        ("source_subject", "purified alpha", ("source_subject", "source_quote")),
        ("source_quote", "Material alpha came from elsewhere.", ("source_quote", "source")),
    ],
)
def test_reported_material_rejection_identifies_the_failed_constraint(
    field, value, required_diagnostic
):
    from fairifier.utils.entity_plan import materialize_reported_materials

    plan, records, source = _reported_material_fixture()
    records[1][field] = value
    result = materialize_reported_materials(plan, records, source_text=source)
    assert result["levels"] == plan["levels"]
    diagnostic = " ".join(result["materialization_errors"])
    assert "material_alpha" in diagnostic
    assert all(term in diagnostic for term in required_diagnostic)


@pytest.mark.parametrize("problem", ["invented_material", "wrong_parent", "wrong_level", "duplicate", "invented_quote"])
def test_reported_material_inventory_rejects_ungrounded_records(problem):
    from fairifier.utils.entity_plan import materialize_reported_materials
    plan, records, source = _reported_material_fixture()
    if problem == "invented_material": records[1]["source_subject"] = "beta"
    if problem == "wrong_parent": records[1]["parent_row_id"] = "study_a"
    if problem == "wrong_level": records[1]["level"] = "assay"
    if problem == "duplicate": records.append(deepcopy(records[1]))
    if problem == "invented_quote": records[0]["source_quote"] = "Material alpha was isolated elsewhere."
    result = materialize_reported_materials(plan, records, source_text=source)
    assert result["levels"] == plan["levels"]
    assert result["materialization_errors"]


@pytest.mark.anyio
async def test_reviewed_material_and_fit_form_complete_isosa_without_raw_run_inventory(monkeypatch):
    plan, materials, source = _reported_material_fixture()
    _, record, fit_source = _reported_fit_fixture()
    record["sample_row_id"] = "material_alpha"
    source += " " + fit_source
    plan["design_claims"]["reported_materials"] = materials
    plan["design_claims"]["reported_assays"] = [record]
    async def review(*args, **kwargs):
        return {"decisions": [{"record_id": item["record_id"], "approved": True,
                               "evidence_quote": item["source_quote"], "rationale": "Supported source identity and grain."}
                              for item in [*materials, record]]}
    monkeypatch.setattr(entity_planner_module, "invoke_structured_output", review)
    planner = object.__new__(EntityStructurePlannerAgent)
    planner.llm_helper = object()
    knowledge = [{"term": "fitted response", "metadata": {"isa_sheet": "assay", "syntax": "{float}"}}]
    result = await planner._materialize_reviewed_results(plan, [record], knowledge, source, materials=materials)
    assert planner._plan_errors(result, source_text=source) == []
    assert [level["cardinality"] for level in result["levels"]] == [1, 1, 1, 1, 1]
    matrix = project_matrix_onto_entity_plan({}, result)
    assert validate_entity_matrix_against_plan(matrix, result)["passed"] is True
    assert "Fitted result" in matrix["assay"]["rows"][0]["assay description"]
    assert record["unreported_design"][0] in matrix["assay"]["rows"][0]["assay description"]
    matrix["assay"]["rows"][0]["assay description"] = "One individual experiment"
    restored = project_matrix_onto_entity_plan(matrix, result)
    assert "Fitted result" in restored["assay"]["rows"][0]["assay description"]
    altered = deepcopy(result)
    next(level for level in altered["levels"] if level["level"] == "observationunit")["entities"][0]["source_subject"] = "beta"
    assert planner._plan_errors(altered, source_text=source)


@pytest.mark.anyio
async def test_review_decision_for_an_unknown_record_does_not_discard_approved_records(monkeypatch):
    """The reviewer once answered for six ids nobody proposed (bit_27984) and the whole
    reviewed set, including five approved assays, was thrown away."""
    plan, materials, source = _reported_material_fixture()
    _, record, fit_source = _reported_fit_fixture()
    record["sample_row_id"] = "material_alpha"
    source += " " + fit_source

    async def review(*args, **kwargs):
        decisions = [{"record_id": item["record_id"], "approved": True,
                      "evidence_quote": item["source_quote"], "rationale": "Supported."}
                     for item in [*materials, record]]
        decisions.append({"record_id": "tbl_invented_row", "approved": False,
                          "evidence_quote": "", "rationale": "No such record was proposed."})
        return {"decisions": decisions}

    monkeypatch.setattr(entity_planner_module, "invoke_structured_output", review)
    planner = object.__new__(EntityStructurePlannerAgent)
    planner.llm_helper = object()
    knowledge = [{"term": "fitted response", "metadata": {"isa_sheet": "assay", "syntax": "{float}"}}]
    result = await planner._materialize_reviewed_results(plan, [record], knowledge, source, materials=materials)

    rows = {row["row_id"] for level in result["levels"] for row in level.get("entities") or []}
    assert {"prep_alpha", "material_alpha", record["record_id"]} <= rows
    assert any("referenced unknown reported record tbl_invented_row" in e
               for e in result["materialization_errors"])


@pytest.mark.anyio
async def test_misquoted_material_drops_alone_and_well_quoted_materials_keep_their_rows(monkeypatch):
    plan, materials, source = _reported_material_fixture()
    beta = "Material beta was synthesised in house."
    source += " " + beta
    materials += [
        {"record_id": "prep_beta", "level": "observationunit", "parent_row_id": "study_a",
         "record_kind": "material_preparation", "source_subject": "beta",
         "source_quote": "Material beta was bought commercially.",
         "label": "Beta preparation", "source_group": "materials"},
        {"record_id": "material_beta", "level": "sample", "parent_row_id": "prep_beta",
         "record_kind": "material_identity", "source_subject": "beta", "source_quote": beta,
         "label": "Beta material", "source_group": "materials"},
    ]
    reviewed = []

    async def review(*args, **kwargs):
        prompt = args[1][0].content
        decisions = [{"record_id": item["record_id"], "approved": True,
                      "evidence_quote": item["source_quote"], "rationale": "Supported."}
                     for item in materials if f'"{item["record_id"]}"' in prompt.split("Proposed materials:")[1]]
        reviewed.extend(item["record_id"] for item in decisions)
        return {"decisions": decisions}

    monkeypatch.setattr(entity_planner_module, "invoke_structured_output", review)
    planner = object.__new__(EntityStructurePlannerAgent)
    planner.llm_helper = object()
    result = await planner._materialize_reviewed_results(plan, [], [], source, materials=materials)

    rows = {row["row_id"] for level in result["levels"] for row in level.get("entities") or []}
    assert {"prep_alpha", "material_alpha"} <= rows
    assert not {"prep_beta", "material_beta"} & rows
    assert sorted(reviewed) == ["material_alpha", "prep_alpha"]
    diagnostic = " ".join(result["materialization_errors"])
    assert "prep_beta" in diagnostic and "source_quote" in diagnostic
    assert planner._blocking_plan_errors(result["materialization_errors"]) == []


@pytest.mark.anyio
@pytest.mark.parametrize("approved", [True, False])
async def test_reviewed_result_can_use_a_source_alias_of_its_material(monkeypatch, approved):
    from fairifier.utils.entity_plan import materialize_reported_assays, materialize_reported_materials

    plan, materials, source = _reported_material_fixture()
    _, record, _ = _reported_fit_fixture()
    alias_evidence = "Material alpha is labelled A in the results table."
    result_evidence = "For A the fitted response was 0.7 using three replicates."
    source += " " + alias_evidence + " " + result_evidence
    record.update(sample_row_id="material_alpha", source_subject="A", source_quote=result_evidence)
    plan["design_claims"].update(reported_materials=materials, reported_assays=[record])
    knowledge = [{"term": "fitted response", "metadata": {"isa_sheet": "assay", "syntax": "{float}"}}]

    # A quoted alias by itself does not verify which material it identifies.
    unreviewed = materialize_reported_assays(
        materialize_reported_materials(plan, materials, source_text=source),
        [record], source_text=source, field_catalog={"assay": ["fitted response"]},
    )
    assert unreviewed.get("materialization_errors")

    async def review(*args, **kwargs):
        return {"decisions": [
            {"record_id": item["record_id"], "approved": approved if item is record else True,
             "evidence_quote": alias_evidence if item is record else item["source_quote"],
             "rationale": "Source establishes the alias and planned material parent."
             if approved else "Material parent is not established."}
            for item in [*materials, record]
        ]}

    monkeypatch.setattr(entity_planner_module, "invoke_structured_output", review)
    planner = object.__new__(EntityStructurePlannerAgent)
    planner.llm_helper = object()
    result = await planner._materialize_reviewed_results(
        plan, [record], knowledge, source, materials=materials,
    )
    if not approved:
        assert planner._plan_errors(result, source_text=source)
        assert not next(level for level in result["levels"] if level["level"] == "assay")["entities"]
        assert "material_alpha" in result["reported_material_reviews"]
        return
    assert planner._plan_errors(result, source_text=source) == []
    assay = next(level for level in result["levels"] if level["level"] == "assay")["entities"][0]
    assert assay["parent_row_id"] == "material_alpha"
    assert assay["source_subject"] == "A"
    assert assay["attributes"][0]["value"] == "0.7"
    assert planner._plan_errors(result, source_text=source + " Revised source.")
    assay["parent_row_id"] = "different_material"
    assert planner._plan_errors(result, source_text=source)


@pytest.mark.parametrize("change", [None, "record", "parent", "source", "conflicting_identity", "physical_parent"])
def test_reviewed_alias_binding_is_specific_to_record_parent_and_source(change):
    from fairifier.utils.entity_plan import (
        materialize_reported_assays, materialize_reported_materials,
        reported_parent_binding_digest,
    )

    plan, materials, source = _reported_material_fixture()
    _, record, _ = _reported_fit_fixture()
    record.update(sample_row_id="material_alpha", source_subject="A",
                  source_quote="For A the fitted response was 0.7 using three replicates.")
    source += " Material alpha is labelled A in the results table. " + record["source_quote"]
    plan = materialize_reported_materials(plan, materials, source_text=source)
    samples = next(level for level in plan["levels"] if level["level"] == "sample")
    parent = samples["entities"][0]
    bindings = {record["record_id"]: reported_parent_binding_digest(record, parent, source)}
    if change == "record":
        record["label"] = "Revised claim"
    elif change == "parent":
        parent["label"] = "Revised material"
    elif change == "source":
        source += " Revised source."
    elif change == "conflicting_identity":
        other = deepcopy(parent)
        other.update(row_id="other_material", source_subject="A")
        other["attributes"][0]["value"] = "A"
        samples["entities"].append(other)
        samples["cardinality"] += 1
    elif change == "physical_parent":
        parent.pop("record_kind")
        bindings[record["record_id"]] = reported_parent_binding_digest(record, parent, source)
    result = materialize_reported_assays(
        plan, [record], source_text=source, field_catalog={"assay": ["fitted response"]},
        reviewed_parent_bindings=bindings,
    )
    assert bool(result.get("materialization_errors")) is (change is not None)
    # A binding is a scoped handoff, not a complete semantic-review receipt.
    assert EntityStructurePlannerAgent._plan_errors(result, source_text=source)


@pytest.mark.anyio
@pytest.mark.parametrize("problem", ["rejected_result", "rejected_parent", "invalid_value", "invalid_review_quote"])
async def test_reported_review_preserves_valid_records_without_accepting_failed_records(monkeypatch, problem):
    plan, materials, source = _reported_material_fixture()
    beta_materials = json.loads(json.dumps(materials).replace("alpha", "beta"))
    materials += beta_materials
    source += " Material beta was purified before characterisation."
    _, alpha, _ = _reported_fit_fixture()
    alpha["sample_row_id"] = "material_alpha"
    beta = json.loads(json.dumps(alpha).replace("alpha", "beta"))
    beta["record_id"] = "reported_fit_b"
    records = [alpha, beta]
    source += " " + alpha["source_quote"] + " " + beta["source_quote"]
    if problem == "invalid_value":
        beta["attributes"][0]["value"] = "0.8"
    plan["design_claims"].update(reported_materials=materials, reported_assays=records)
    original = deepcopy(plan)

    async def review(*args, **kwargs):
        decisions = []
        for item in [*materials, *records]:
            rejected = (problem == "rejected_result" and item is beta) or (
                problem == "rejected_parent" and item["record_id"] == "material_beta"
            )
            decisions.append({
                "record_id": item["record_id"], "approved": not rejected,
                "evidence_quote": "Evidence absent from source."
                if problem == "invalid_review_quote" and item is beta else item["source_quote"],
                "rationale": "Parent identity is not established." if rejected else "Source-supported record.",
            })
        return {"decisions": decisions}

    monkeypatch.setattr(entity_planner_module, "invoke_structured_output", review)
    planner = object.__new__(EntityStructurePlannerAgent)
    planner.llm_helper = object()
    result = await planner._materialize_reviewed_results(
        plan, records, [{"term": "fitted response", "metadata": {"isa_sheet": "assay", "syntax": "{float}"}}],
        source, materials=materials,
    )

    assays = next(level for level in result["levels"] if level["level"] == "assay")["entities"]
    assert [row["row_id"] for row in assays] == [alpha["record_id"]]
    assert assays[0]["parent_row_id"] == "material_alpha"
    assert alpha["record_id"] in result["reported_assay_reviews"]
    assert beta["record_id"] not in result["reported_assay_reviews"]
    errors = planner._plan_errors(result, source_text=source)
    assert errors and any(beta["record_id"] in error for error in errors)
    if problem != "invalid_value":
        assert result["reported_record_review"]["passed"] is False
    assert plan == original
    # The retained candidate must not be replaced by an unreviewed draft just
    # because the latter stopped earlier and accumulated fewer diagnostics.
    unreviewed = deepcopy(result)
    unreviewed.pop("reported_assay_reviews")
    rank = planner._candidate_rank(result, errors, used_authoritative_records=False)
    assert rank > planner._candidate_rank(
        unreviewed, ["Earlier draft failed source validation."], used_authoritative_records=False,
    )
    changed = deepcopy(result)
    next(level for level in changed["levels"] if level["level"] == "assay")["entities"][0]["label"] += " changed"
    assert planner._candidate_rank(changed, errors, used_authoritative_records=False) < rank


@pytest.mark.anyio
@pytest.mark.parametrize("approval", ["approved", "rejected", "missing", "invented_evidence", "invalid_contract"])
@pytest.mark.parametrize("thinking", [True, False])
async def test_reported_result_materialization_requires_independent_semantic_review(monkeypatch, approval, thinking):
    monkeypatch.setattr(entity_planner_module.config, "llm_enable_thinking", thinking)
    plan, record, source = _reported_fit_fixture()
    plan["design_claims"]["reported_assays"] = [record]
    async def review(*args, **kwargs):
        assert kwargs["max_tokens"] == (32768 if thinking else 8192)
        assert "0.7" in args[1][0].content
        return {"decisions": [] if approval == "missing" else [{
            "record_id": record["record_id"], "approved": approval != "rejected",
            "evidence_quote": "invented evidence" if approval == "invented_evidence" else record["source_quote"],
            "rationale": (
                "The fitted value belongs to a different material preparation."
                if approval == "rejected"
                else "The paper reports a fit for the named material, not individual replicates."
            ),
        }]}
    monkeypatch.setattr(entity_planner_module, "invoke_structured_output", review)
    planner = object.__new__(EntityStructurePlannerAgent)
    planner.llm_helper = object()
    knowledge = [{"term": "fitted response", "definition": "Source-reported fit coefficient.",
                  "metadata": {"isa_sheet": "assay", "syntax": "{float}"}}]
    if approval == "invalid_contract":
        knowledge[0]["metadata"].update({"syntax": "[0-9]+", "regex": "^[0-9]+$"})
    result = await planner._materialize_reviewed_results(plan, [record], knowledge, source)
    errors = planner._plan_errors(result, source_text=source)
    if approval == "approved":
        assert errors == []
        assert any(row["row_id"] == record["record_id"]
                   for level in result["levels"] for row in level["entities"])
        altered = deepcopy(result)
        assay = next(level for level in altered["levels"] if level["level"] == "assay")
        assay["entities"][-1]["attributes"][0]["value"] = "9.9"
        assert planner._plan_errors(altered, source_text=source)
        assert planner._plan_errors(result, source_text=source + " Changed source.")
    else:
        assert errors
        assert result["levels"] == plan["levels"]
        if approval == "rejected":
            assert any(
                record["record_id"] in error
                and "different material preparation" in error
                for error in errors
            )
        if approval == "invented_evidence":
            assert any(
                record["record_id"] in error and "evidence_quote" in error
                for error in errors
            )


def test_declared_reported_result_cannot_silently_disappear_from_plan():
    plan, record, source = _reported_fit_fixture()
    plan["design_claims"]["reported_assays"] = [record]
    assert any("reported" in error.lower()
               for error in EntityStructurePlannerAgent._plan_errors(plan, source_text=source))


def test_reported_result_can_cite_complete_compact_html_table_row():
    from fairifier.utils.entity_plan import materialize_reported_assays
    plan, record, _ = _reported_fit_fixture()
    record["source_quote"] = "<tr><td>alpha</td><td>0.7</td></tr>"
    source = "<table><tr><td>Material</td><td>Coefficient</td></tr>" + record["source_quote"] + "</table>"
    result = materialize_reported_assays(plan, [record], source_text=source,
                                        field_catalog={"assay": ["fitted response"]})
    assert not result.get("materialization_errors")
    assert next(level for level in result["levels"] if level["level"] == "assay")["cardinality"] == 3


PIVOTED_KINETICS = (
    "<table><tr><td rowspan=\"2\">Substrates</td><td colspan=\"2\">\\( K_m \\) (mM)</td>"
    "<td colspan=\"2\">\\( k_{cat} \\) (\\( sec^{-1} \\))</td></tr>"
    "<tr><td>BhrPETase</td><td>LCC</td><td>BhrPETase</td><td>LCC</td></tr>"
    "<tr><td>BHET</td><td>16.78 ± 2.95</td><td>25.82 ± 2.31</td><td>7.3</td><td>8.3</td></tr></table>"
)
BHET_ROW = "<tr><td>BHET</td><td>16.78 ± 2.95</td><td>25.82 ± 2.31</td><td>7.3</td><td>8.3</td></tr>"


@pytest.mark.parametrize("attributes,expected", [
    # The pivoted row names neither enzyme nor unit; its rendering does.
    ({"Michaelis constant Km": "25.82 ± 2.31 mM", "catalytic rate constant kcat": "8.3 sec−1"},
     [("michaelis constant km", "25.82 ± 2.31 mM"), ("catalytic rate constant kcat", "8.3 sec−1")]),
    # A bare mean keeps its unit and gains the cell's error.
    ({"Michaelis constant Km": "25.82 mM"}, [("michaelis constant km", "25.82 ± 2.31 mM")]),
    # BhrPETase's cell and a wrong unit are not LCC's values.
    ({"Michaelis constant Km": "16.78 ± 2.95 mM", "catalytic rate constant kcat": "8.3 mM"}, None),
])
def test_reported_result_reads_a_pivoted_table_row_through_its_rendered_columns(attributes, expected):
    from fairifier.utils.entity_plan import materialize_reported_assays

    plan, record, _ = _reported_fit_fixture()
    sample = next(level for level in plan["levels"] if level["level"] == "sample")["entities"][0]
    sample["attributes"] = [{"dimension_name": "source material", "value": "LCC"}]
    record.update(
        source_subject="LCC",
        # A caption and an annotation stitched to the row are not source text.
        source_quote="Table 2 Kinetic parameters. [Columns: Km then kcat] " + BHET_ROW,
        attributes=[{"field_name": name, "value": value} for name, value in attributes.items()],
    )
    result = materialize_reported_assays(
        plan, [record], source_text="Kinetics of LCC. " + PIVOTED_KINETICS,
        field_catalog={"assay": ["michaelis constant km", "catalytic rate constant kcat"]},
    )
    assay = next(level for level in result["levels"] if level["level"] == "assay")
    added = [row for row in assay["entities"] if row["row_id"] == record["record_id"]]
    if expected is None:
        assert not added
        return
    assert [(a["field_name"], a["value"]) for a in added[0]["attributes"]] == expected
    assert added[0]["source_quote"] == BHET_ROW


@pytest.mark.parametrize("case", ["material_identity", "duplicate_material_identity", "physical_replicate"])
def test_reported_result_distinguishes_material_identity_from_its_physical_replicates(case):
    from fairifier.utils.entity_plan import materialize_reported_assays, materialize_reported_materials

    plan, materials, source = _reported_material_fixture()
    _, record, fit_source = _reported_fit_fixture()
    source += " " + fit_source
    plan = materialize_reported_materials(plan, materials, source_text=source)
    samples = next(level for level in plan["levels"] if level["level"] == "sample")
    material = samples["entities"][0]
    for index in range(2):
        replicate = deepcopy(material)
        replicate["row_id"] = f"physical_sample_{index}"
        replicate.pop("record_kind")
        samples["entities"].append(replicate)
    if case == "duplicate_material_identity":
        duplicate = deepcopy(material)
        duplicate["row_id"] = "other_material_alpha"
        samples["entities"].append(duplicate)
    samples["cardinality"] = len(samples["entities"])
    record["sample_row_id"] = "physical_sample_0" if case == "physical_replicate" else "material_alpha"

    result = materialize_reported_assays(
        plan, [record], source_text=source, field_catalog={"assay": ["fitted response"]},
    )
    if case == "material_identity":
        assert not result.get("materialization_errors")
        assay = next(level for level in result["levels"] if level["level"] == "assay")
        assert len(assay["entities"]) == 1
        assert assay["entities"][0]["parent_row_id"] == "material_alpha"
        assert next(level for level in result["levels"] if level["level"] == "sample") == samples
        # Passing identity checks does not replace independent semantic review.
        assert EntityStructurePlannerAgent._plan_errors(result, source_text=source)
    else:
        assert result.get("materialization_errors")
        assert result["levels"] == plan["levels"]


@pytest.mark.parametrize("reported_value", ["0.7", 0])
def test_reported_fit_preserves_one_result_without_reconstructing_unknown_runs(reported_value):
    from fairifier.utils.entity_plan import materialize_reported_assays
    plan, record, source = _reported_fit_fixture()
    source = source.replace("0.7", str(reported_value))
    record["source_quote"] = record["source_quote"].replace("0.7", str(reported_value))
    record["attributes"][0]["value"] = reported_value
    original = deepcopy(plan)
    result = materialize_reported_assays(plan, [record], source_text=source,
                                        field_catalog={"assay": ["fitted response"]})
    assays = next(x for x in result["levels"] if x["level"] == "assay")
    assert assays["cardinality"] == 3  # Two existing records plus one reported fit.
    row = assays["entities"][-1]
    assert row["parent_row_id"] == record["sample_row_id"]
    assert row["record_kind"] == "fitted_result"
    assert row["attributes"][0]["value"] == str(reported_value)
    assert row["unreported_design"] == record["unreported_design"]
    assert plan == original


@pytest.mark.parametrize("problem", ["unknown_parent", "different_material", "invented_quote", "invented_value", "wrong_field", "duplicate", "ambiguous_material"])
def test_reported_fit_rejects_unverified_records_without_altering_existing_graph(problem):
    from fairifier.utils.entity_plan import materialize_reported_assays
    plan, record, source = _reported_fit_fixture()
    if problem == "unknown_parent": record["sample_row_id"] = "missing"
    if problem == "different_material": record["source_subject"] = "beta"
    if problem == "invented_quote": record["source_quote"] = "For alpha the fitted response was 0.8."
    if problem == "invented_value": record["attributes"][0]["value"] = "7"
    if problem == "wrong_field": record["attributes"][0]["field_name"] = "unselected field"
    if problem == "ambiguous_material":
        samples = next(x for x in plan["levels"] if x["level"] == "sample")
        samples["entities"][1]["attributes"] = deepcopy(samples["entities"][0]["attributes"])
    records = [record, record] if problem == "duplicate" else [record]
    result = materialize_reported_assays(plan, records, source_text=source,
                                        field_catalog={"assay": ["fitted response"]})
    assert result["levels"] == plan["levels"]
    assert result["materialization_errors"]


@pytest.mark.parametrize("audit_present", [True, False])
def test_rejected_reuse_keeps_varying_assay_scope_pending_source_review(audit_present):
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "evidence": "Signal was measured at three detector settings.",
                "reuse_same_sample_for_multiple_assays": True,
                "sample_reuse_evidence": "shared pool",
                "dimensions": [
                    {
                        "name": "detector_setting",
                        "level_count": 3,
                        "applies_to": ["assay"],
                    }
                ],
            }
        ]
    }
    audit = {
        "reuse_validations": [
            {
                "group_id": "group_001",
                "approved": False,
                "evidence_quote": None,
            }
        ]
    }

    rejected = EntityStructurePlannerAgent._enforce_independent_reuse_audit(
        claims, audit if audit_present else {}
    )

    assert rejected == ["group_001"]
    group = claims["design_groups"][0]
    assert group["reuse_same_sample_for_multiple_assays"] is False
    # Missing reuse proof does not establish distinct physical material.
    assert group["dimensions"][0]["applies_to"] == ["assay"]


def test_scope_disagreement_is_not_hidden_by_absent_reuse_proof():
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "reuse_same_sample_for_multiple_assays": False,
                "dimensions": [
                    {
                        "name": "preparation_method",
                        "level_count": 3,
                        "applies_to": ["sample", "assay"],
                    }
                ],
            }
        ]
    }
    audit = {
        "dimension_scopes": [
            {
                "group_id": "group_001",
                "dimension_name": "preparation_method",
                "applies_to": ["assay"],
            }
        ]
    }

    applied, errors = EntityStructurePlannerAgent._apply_dimension_scope_audit(
        claims, audit
    )

    assert applied == []
    # Do not rewrite the independent audit into agreement with the draft.
    assert any("disagreed" in error.lower() for error in errors)
    assert claims["design_groups"][0]["dimensions"][0]["applies_to"] == ["sample", "assay"]


def _physical_relation_claims(*, scope=("assay",), role="assay_process"):
    return {
        "investigations": [{"row_id": "inv_test", "label": "Synthetic investigation"}],
        "studies": [{"row_id": "study_test", "label": "Synthetic study", "parent_row_id": "inv_test"}],
        "design_groups": [{
            "group_id": "scope_group", "study_row_id": "study_test",
            "evidence": "Two detector settings were compared.",
            "reuse_same_sample_for_multiple_assays": True,
            "sample_reuse_evidence": None,
            "dimensions": [{
                "name": "readout", "level_count": 2, "explicit_values": ["A", "B"],
                "origin": "explicit", "semantic_role": role, "applies_to": list(scope),
            }],
        }],
    }


def test_unknown_physical_relation_requires_review_even_when_row_counts_match():
    claims = _physical_relation_claims(scope=("sample", "assay"))
    EntityStructurePlannerAgent._enforce_independent_reuse_audit(claims, {})
    plan = normalize_entity_plan(materialize_entity_claims(claims))
    counts = {level["level"]: len(level["entities"]) for level in plan["levels"]}
    assert counts["sample"] == counts["assay"] == 2
    errors = EntityStructurePlannerAgent._plan_errors(plan)
    assert any("physical" in error.lower() and "scope_group" in error for error in errors)


def test_reuse_quote_present_only_in_generated_claims_is_rejected():
    claims = _physical_relation_claims()
    group = claims["design_groups"][0]
    group["evidence"] = "The same identified sample was measured twice."
    audit = {"reuse_validations": [{
        "group_id": "scope_group", "approved": True,
        "evidence_quote": "same identified sample",
    }]}
    rejected = EntityStructurePlannerAgent._enforce_independent_reuse_audit(
        claims, audit, source_text="Two detector settings were compared; input identity was not reported.",
    )
    assert rejected == ["scope_group"]
    assert group["reuse_same_sample_for_multiple_assays"] is False
    assert group["sample_reuse_evidence"] is None
    assert group["dimensions"][0]["applies_to"] == ["assay"]


def test_source_reuse_quote_can_resolve_an_incomplete_draft_summary():
    claims = _physical_relation_claims()
    quote = "The same identified sample was measured twice."
    audit = {"reuse_validations": [{
        "group_id": "scope_group", "approved": True, "evidence_quote": quote,
    }]}
    rejected = EntityStructurePlannerAgent._enforce_independent_reuse_audit(
        claims, audit, source_text=f"Methods. {quote}",
    )
    assert rejected == []
    assert claims["design_groups"][0]["sample_reuse_evidence"] == quote


@pytest.mark.parametrize("scope", [("assay",), ("sample", "assay")])
def test_assay_process_with_unknown_input_relation_keeps_scope_and_requires_review(scope):
    claims = _physical_relation_claims(scope=scope)
    claims["design_groups"][0]["reuse_same_sample_for_multiple_assays"] = False
    audit = {"dimension_scopes": [{
        "group_id": "scope_group", "dimension_name": "readout",
        "semantic_role": "assay_process", "applies_to": list(scope),
        "sample_relation": "unknown", "evidence_quote": None,
    }]}
    applied, errors = EntityStructurePlannerAgent._apply_dimension_scope_audit(claims, audit)
    assert applied == []
    assert claims["design_groups"][0]["dimensions"][0]["applies_to"] == list(scope)
    assert any("physical" in error.lower() and "scope_group" in error for error in errors)


def test_explicit_distinct_material_evidence_retains_sample_scope():
    claims = _physical_relation_claims(scope=("sample", "assay"), role="material_path")
    group = claims["design_groups"][0]
    source = "Aliquots A and B were separately prepared for analysis."
    group["evidence"] = source
    group["reuse_same_sample_for_multiple_assays"] = False
    audit = {"dimension_scopes": [{
        "group_id": "scope_group", "dimension_name": "readout",
        "semantic_role": "material_path", "applies_to": ["sample", "assay"],
        "sample_relation": "distinct_samples", "evidence_quote": source,
    }]}
    _, errors = EntityStructurePlannerAgent._apply_dimension_scope_audit(
        claims, audit, source_text=source,
    )
    assert errors == []
    assert group["dimensions"][0]["applies_to"] == ["sample", "assay"]
    assert EntityStructurePlannerAgent._plan_errors(
        normalize_entity_plan(materialize_entity_claims(claims))
    ) == []


@pytest.mark.parametrize(("role", "relation", "quote_present", "valid"), [
    ("observation_condition", "distinct_samples", True, True),
    ("observation_condition", "distinct_samples", False, False),
    ("observation_condition", "same_sample", True, False),
    ("assay_process", "distinct_samples", True, False),
    ("material_path", "distinct_samples", True, False),
])
def test_distinct_observed_units_retain_their_sample_and_assay_branches(
    role, relation, quote_present, valid,
):
    scope = ["observationunit", "sample", "assay"]
    claims = _physical_relation_claims(scope=scope, role=role)
    group = claims["design_groups"][0]
    source = "Independently observed plots A and B each provided one specimen."
    group["evidence"] = source
    group["reuse_same_sample_for_multiple_assays"] = False
    audit = {"dimension_scopes": [{
        "group_id": "scope_group", "dimension_name": "readout",
        "semantic_role": role, "applies_to": scope,
        "sample_relation": relation,
        "evidence_quote": source if quote_present else None,
    }]}

    applied, errors = EntityStructurePlannerAgent._apply_dimension_scope_audit(
        claims, audit, source_text=source,
    )

    assert applied == []
    dimension = group["dimensions"][0]
    assert dimension["applies_to"] == scope
    plan = normalize_entity_plan(materialize_entity_claims(claims))
    if valid:
        assert errors == []
        assert dimension["sample_relation_source_verified"] is True
        assert EntityStructurePlannerAgent._plan_errors(plan, source_text=source) == []
        counts = {level["level"]: len(level["entities"]) for level in plan["levels"]}
        assert [counts[level] for level in scope] == [2, 2, 2]
    else:
        assert any("Unresolved physical sample relation" in error for error in errors)
        assert dimension["physical_relation_review_required"] is True
        assert EntityStructurePlannerAgent._plan_errors(plan, source_text=source)


def test_mixed_material_and_readout_axes_keep_independent_sample_relations():
    claims = _physical_relation_claims()
    group = claims["design_groups"][0]
    source = (
        "Two separately prepared aliquots, A and B, were each read in both detector modes "
        "without preparing new material."
    )
    group["evidence"] = source
    group["dimensions"].insert(0, {
        "name": "preparation", "level_count": 2, "explicit_values": ["A", "B"],
        "origin": "explicit", "semantic_role": "assay_process", "applies_to": ["assay"],
    })
    audit = {"dimension_scopes": [
        {"group_id": "scope_group", "dimension_name": "preparation",
         "semantic_role": "assay_process", "applies_to": ["sample", "assay"],
         "sample_relation": "distinct_samples", "evidence_quote": "Two separately prepared aliquots, A and B"},
        {"group_id": "scope_group", "dimension_name": "readout",
         "semantic_role": "assay_process", "applies_to": ["assay"],
         "sample_relation": "same_sample", "evidence_quote": "were each read in both detector modes without preparing new material"},
    ]}
    _, errors = EntityStructurePlannerAgent._apply_dimension_scope_audit(
        claims, audit, source_text=source,
    )
    assert errors == []
    scopes = {dimension["name"]: dimension["applies_to"] for dimension in group["dimensions"]}
    assert scopes == {"preparation": ["sample", "assay"], "readout": ["assay"]}
    plan = materialize_entity_claims(claims)
    counts = {level["level"]: len(level["entities"]) for level in plan["levels"]}
    assert counts["sample"] == 2 and counts["assay"] == 4


def test_scope_audit_schema_preserves_physical_relation_evidence():
    payload = EntityPlanScopeAuditResponse.model_validate({"dimension_scopes": [{
        "group_id": "scope_group", "dimension_name": "readout",
        "semantic_role": "assay_process", "applies_to": ["assay"],
        "sample_relation": "same_sample", "evidence_quote": "same identified sample",
    }]}).model_dump()
    assert payload["dimension_scopes"][0]["sample_relation"] == "same_sample"
    assert payload["dimension_scopes"][0]["evidence_quote"] == "same identified sample"


def test_scope_audit_receives_document_evidence_beyond_draft_prefix():
    claims = _physical_relation_claims()
    evidence = "Specimen Z was split into two separately prepared aliquots."
    source = ("Background text. " * 1200) + evidence
    assert source.index(evidence) > 18000
    assert evidence not in json.dumps(claims)
    agent = object.__new__(EntityStructurePlannerAgent)
    prompt = agent._scope_audit_prompt(claims, {}, {}, [], source_text=source)
    assert evidence in prompt


@pytest.mark.parametrize("duplicate", [False, True])
def test_missing_physical_scope_audit_is_hard_review_with_equal_counts(duplicate):
    claims = _physical_relation_claims(scope=("sample", "assay"), role="other")
    claims["design_groups"][0]["reuse_same_sample_for_multiple_assays"] = False
    finding = {
        "group_id": "scope_group", "dimension_name": "readout", "semantic_role": "other",
        "applies_to": ["sample", "assay"], "sample_relation": "unknown",
    }
    audit = {"dimension_scopes": [finding, deepcopy(finding)] if duplicate else []}
    _, audit_errors = EntityStructurePlannerAgent._apply_dimension_scope_audit(claims, audit)
    assert audit_errors
    plan = normalize_entity_plan(materialize_entity_claims(claims))
    counts = {level["level"]: len(level["entities"]) for level in plan["levels"]}
    assert counts["sample"] == counts["assay"] == 2
    errors = EntityStructurePlannerAgent._plan_errors(plan)
    assert any("physical" in error.lower() and "scope_group" in error for error in errors)


@pytest.mark.parametrize(("role", "scope"), [
    ("assay_process", ("sample", "assay")),
    ("other", ("sample", "assay")),
    ("other", ("assay",)),
])
def test_legacy_plans_with_unresolved_physical_axes_require_reaudit(role, scope):
    claims = _physical_relation_claims(scope=scope, role=role)
    claims["design_groups"][0]["reuse_same_sample_for_multiple_assays"] = False
    plan = normalize_entity_plan(materialize_entity_claims(claims))
    assert EntityStructurePlannerAgent._requires_physical_relation_reaudit(plan) is True


@pytest.mark.parametrize("case", ["material_path", "source_table", "current_policy"])
def test_physical_relation_cache_preserves_unaffected_or_verified_plans(case):
    claims = _physical_relation_claims(scope=("sample", "assay"))
    claims["design_groups"][0]["reuse_same_sample_for_multiple_assays"] = False
    if case == "material_path":
        claims["design_groups"][0]["dimensions"][0]["semantic_role"] = "material_path"
    plan = normalize_entity_plan(materialize_entity_claims(claims))
    if case == "source_table":
        plan["source_coverage"] = {
            "complete": True, "tables": [{"source_id": "source_records", "coverage_complete": True}],
        }
    elif case == "current_policy":
        plan["physical_relation_audit_version"] = entity_planner_module.PHYSICAL_RELATION_AUDIT_VERSION
    assert EntityStructurePlannerAgent._requires_physical_relation_reaudit(plan) is False


def test_dimension_scope_audit_fails_when_any_dimension_is_unreviewed():
    claims = {
        "design_groups": [
            {
                "group_id": "group_001",
                "dimensions": [
                    {"name": "condition", "applies_to": ["sample", "assay"]}
                ],
            }
        ]
    }

    applied, errors = EntityStructurePlannerAgent._apply_dimension_scope_audit(
        claims, {"dimension_scopes": []}
    )

    assert applied == []
    assert errors == [
        "Independent scope audit omitted or duplicated group_001:condition."
    ]


def _crossed_variant_plan(full_factorial_evidence=None):
    """Five variants x four temperatures x four times, all crossed to Assay."""
    evidence = (
        "Five PETase variants were incubated at four temperatures and sampled "
        "at four time points."
    )
    claims = {
        "investigations": [{"row_id": "investigation_001", "label": "PETase"}],
        "studies": [{"row_id": "study_001", "label": "PETase", "parent_row_id": "investigation_001"}],
        "design_groups": [
            {
                "group_id": "group_001",
                "study_row_id": "study_001",
                "evidence": evidence,
                "full_factorial_evidence": full_factorial_evidence,
                "dimensions": [
                    {"name": name, "level_count": count, "explicit_values": [], "origin": "derived",
                     "applies_to": scope}
                    for name, count, scope in (
                        ("variant", 5, ["observationunit", "sample", "assay"]),
                        ("temperature", 4, ["sample", "assay"]),
                        ("time", 4, ["sample", "assay"]),
                    )
                ],
            }
        ],
    }
    return normalize_entity_plan(materialize_entity_claims(claims))


def test_plan_validation_rejects_crossed_dimensions_without_full_factorial_quote():
    errors = EntityStructurePlannerAgent._plan_errors(_crossed_variant_plan())

    assert any("crosses variant (5) x temperature (4) x time (4) into 80 sample rows" in error for error in errors)


def test_plan_validation_allows_crossed_dimensions_with_verbatim_full_factorial_quote():
    errors = EntityStructurePlannerAgent._plan_errors(
        _crossed_variant_plan("incubated at four temperatures and sampled at four time points")
    )

    assert not any("crosses" in error for error in errors)


def _case_variant_column_plan():
    return {
        "levels": [{
            "level": "assay",
            "entities": [
                {
                    "row_id": f"assay_{suffix}",
                    "parent_row_id": f"sample_{suffix}",
                    "source_group": f"group_{suffix}",
                    "attributes": [],
                }
                for suffix in ("a", "b")
            ],
        }],
    }


def test_projection_preserves_case_variant_column_values_and_links():
    matrix = {
        "assay": {
            "columns": ["Assay Identifier", "Sample Identifier", "solution pH", "DNA concentration"],
            "rows": [
                {" Assay Identifier ": "assay_a", "Sample Identifier": "sample_a",
                 "solution pH": "7.2", "DNA concentration": "0.8 ng/uL"},
                {"assay identifier": "assay_b", "sample identifier": "sample_b",
                 "solution ph": "8.1", "dna concentration": 0},
            ],
        },
    }
    original = deepcopy(matrix)

    result = project_matrix_onto_entity_plan(matrix, _case_variant_column_plan())

    rows = result["assay"]["rows"]
    assert [row["solution ph"] for row in rows] == ["7.2", "8.1"]
    assert [row["dna concentration"] for row in rows] == ["0.8 ng/uL", 0]
    assert [row["sample identifier"] for row in rows] == ["sample_a", "sample_b"]
    assert len(result["assay"]["columns"]) == len(set(result["assay"]["columns"]))
    assert matrix == original


@pytest.mark.parametrize("left,right,expected", [
    ("", "7.2", "7.2"),
    ("7.2", "7.2", "7.2"),
    ("7.2", "8.1", ""),
    ("1 mM", "1 Mm", ""),
    (0, 0, 0),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_projection_merges_case_variant_cells_without_choosing_conflicts(left, right, expected, reverse):
    values = [("DNA concentration", left), ("dna concentration", right)]
    row = {"assay identifier": "assay_a", "sample identifier": "sample_a"}
    row.update(reversed(values) if reverse else values)
    matrix = {"assay": {"columns": list(row), "rows": [row]}}

    result = project_matrix_onto_entity_plan(matrix, _case_variant_column_plan())

    assert result["assay"]["rows"][0]["dna concentration"] == expected
    assert result["assay"]["rows"][1]["dna concentration"] == ""


@pytest.mark.parametrize("conflicting_key", ["assay identifier", "sample identifier", "source_group"])
def test_projection_rejects_case_conflicting_identity_rows(conflicting_key, caplog):
    row = {"assay identifier": "assay_a", "sample identifier": "sample_a",
           "source_group": "group_a", "measurement": "11"}
    row[conflicting_key.upper()] = "unrelated_identity"
    matrix = {"assay": {"columns": list(row), "rows": [
        row,
        {"assay identifier": "assay_b", "sample identifier": "sample_b", "measurement": "22"},
    ]}}

    result = project_matrix_onto_entity_plan(matrix, _case_variant_column_plan())

    assert [row["measurement"] for row in result["assay"]["rows"]] == ["", "22"]
    assert [row["sample identifier"] for row in result["assay"]["rows"]] == ["sample_a", "sample_b"]
    assert "conflict" in caplog.text.lower()


@pytest.mark.parametrize("conflicting_key", ["measurement", "assay identifier", "sample identifier"])
def test_row_normalization_preserves_case_conflict_before_projection(conflicting_key):
    row = {"assay identifier": "assay_a", "sample identifier": "sample_a", "measurement": "11"}
    row[conflicting_key.upper()] = "different"
    matrix = {"assay": {"columns": list(row), "rows": [
        row,
        {"assay identifier": "assay_b", "sample identifier": "sample_b", "measurement": "22"},
    ]}}
    agent = object.__new__(ISAValueMapperAgent)

    normalized = agent._normalize_row_columns(matrix)
    result = project_matrix_onto_entity_plan(normalized, _case_variant_column_plan())

    assert len(normalized["assay"]["rows"]) == (2 if conflicting_key == "measurement" else 1)
    assert [row["measurement"] for row in result["assay"]["rows"]] == ["", "22"]


def test_plan_scope_clearing_does_not_cross_design_groups():
    """A field mapped only in group B says nothing about group A's rows."""
    matrix = {
        "assay": {
            "columns": ["assay identifier", "substrate kind"],
            "rows": [
                {"assay identifier": "a1", "substrate kind": "proxy substrate"},
                {"assay identifier": "a2", "substrate kind": "actual PET"},
                {"assay identifier": "a3", "substrate kind": "actual PET"},
            ],
        }
    }
    plan = {
        "levels": [
            {
                "level": "assay",
                "entities": [
                    {"row_id": "a1", "source_group": "kinetics", "attributes": []},
                    {
                        "row_id": "a2",
                        "source_group": "hydrolysis",
                        "attributes": [
                            {"field_name": "substrate kind", "value": "actual PET"}
                        ],
                    },
                    {"row_id": "a3", "source_group": "hydrolysis", "attributes": []},
                ],
            }
        ]
    }

    cleaned, counts = ISAValueMapperAgent._clear_values_outside_plan_field_scope(
        matrix, plan
    )

    assert [r["substrate kind"] for r in cleaned["assay"]["rows"]] == [
        "proxy substrate", "actual PET", "",
    ]
    assert counts == {"assay.substrate kind": 1}


def test_unknown_count_with_reported_range_records_the_span_once():
    claims = _partially_enumerated_design_claims()
    claims["design_groups"][1]["dimensions"][0]["reported_range"] = "30–80 °C"
    plan = materialize_entity_claims(claims)

    assert plan["materialization_errors"] == []
    for level in plan["levels"]:
        if level["level"] not in {"observationunit", "sample", "assay"}:
            continue
        rows = [r for r in level["entities"] if r["source_group"] == "unresolved_branch"]
        assert len(rows) == 1
        series = [a for a in rows[0]["attributes"] if a["dimension_name"] == "series"]
        assert [(a["field_name"], a["value"], a["origin"]) for a in series] == [
            ("series label", "30–80 °C", "explicit")
        ]
    assert EntityStructurePlannerAgent._plan_errors(plan) == []


def test_paraphrased_material_quote_is_replaced_by_a_real_source_passage():
    from fairifier.utils.entity_plan import (
        materialize_reported_materials, repair_reported_material_quotes,
    )

    source = ("Methods. Variants were expressed in E. coli. The quadruple variant "
              "H218S-F243T-D238C-S283C hydrolyzed PET microparticles at 70 °C. Results follow.")
    records = [
        {"record_id": "ou_v", "level": "observationunit", "parent_row_id": "study_001",
         "record_kind": "material_preparation", "source_subject": "H218S-F243T-D238C-S283C",
         "source_quote": "Table S6: H218S-F243T-D238C-S283C gives 96% at 70 C", "label": "v"},
        {"record_id": "s_v", "level": "sample", "parent_row_id": "ou_v",
         "record_kind": "material_identity", "source_subject": "H218S-F243T-D238C-S283C",
         "source_quote": "paraphrase", "label": "v"},
        {"record_id": "ou_x", "level": "observationunit", "parent_row_id": "study_001",
         "record_kind": "material_preparation", "source_subject": "NotInPaper-9",
         "source_quote": "invented", "label": "x"},
    ]
    repaired = repair_reported_material_quotes(records, source_text=source)

    assert repaired[0]["source_quote"].startswith("The quadruple variant H218S-F243T-D238C-S283C")
    from fairifier.utils.document_text import normalize_source_evidence_text
    assert repaired[0]["source_quote"] in normalize_source_evidence_text(source)
    assert repaired[2]["source_quote"] == "invented"  # absent material stays ungrounded
    plan = {"levels": [{"level": "study", "entities": [{"row_id": "study_001"}]}]}
    result = materialize_reported_materials(plan, repaired[:2], source_text=source)
    assert not result.get("materialization_errors")
    sample_ids = [e["row_id"] for lv in result["levels"] if lv["level"] == "sample" for e in lv["entities"]]
    assert sample_ids == ["s_v"]


def test_material_inventory_adds_only_unrepresented_materials():
    claims = {
        "studies": [{"row_id": "study_001"}],
        "design_groups": [{"dimensions": [{"explicit_values": ["LCC ICCG"]}]}],
        "reported_materials": [{"record_id": "s1", "source_subject": "BhrPETase", "label": "BhrPETase"}],
    }
    inventory = [{"name": "BhrPETase", "role": "enzyme_or_protein"},
                 {"name": "LCC ICCG", "role": "enzyme_or_protein"},
                 {"name": "F243A", "role": "enzyme_or_protein"}]
    merged = EntityStructurePlannerAgent._with_material_inventory(claims, inventory)
    added = [r for r in merged["reported_materials"] if r["record_id"].startswith("inv")]
    assert [(r["level"], r["source_subject"], r["parent_row_id"]) for r in added] == [
        ("observationunit", "F243A", "study_001"), ("sample", "F243A", "inv_ou_f243a"),
    ]


def test_study_level_material_gets_its_own_preparation_and_aliases_count_as_represented():
    claims = {
        "studies": [{"row_id": "study_001"}],
        "reported_materials": [
            {"record_id": "mat_1", "level": "sample", "parent_row_id": "study_001",
             "record_kind": "material_identity", "label": "PET powder",
             "source_subject": "Amorphous polyethylene terephthalate pellets (PET, Cat#138)"},
            {"record_id": "mat_2", "level": "sample", "parent_row_id": "study_001",
             "record_kind": "material_identity", "label": "BHET", "source_subject": "BHET"},
            {"record_id": "mat_3", "level": "sample", "parent_row_id": "study_001",
             "record_kind": "material_identity", "label": "LCC ICCG", "source_subject": "LCC ICCG"},
        ],
    }
    inventory = [{"name": "Amorphous polyethylene terephthalate", "role": "substrate"},
                 {"name": "BHET (bis(2-hydroxyethyl) terephthalate)", "role": "substrate"},
                 {"name": "LCC", "role": "enzyme_or_protein"}]
    merged = EntityStructurePlannerAgent._with_material_inventory(claims, inventory)
    shape = [(r["record_id"], r["level"], r["parent_row_id"]) for r in merged["reported_materials"]]
    assert shape[:6] == [
        ("ou_mat_1", "observationunit", "study_001"), ("mat_1", "sample", "ou_mat_1"),
        ("ou_mat_2", "observationunit", "study_001"), ("mat_2", "sample", "ou_mat_2"),
        ("ou_mat_3", "observationunit", "study_001"), ("mat_3", "sample", "ou_mat_3"),
    ]
    # PET and BHET are already proposed; LCC is not the LCC ICCG variant.
    assert [r["source_subject"] for r in merged["reported_materials"][6:]] == ["LCC", "LCC"]


def test_ungrounded_material_is_dropped_and_its_children_keep_their_own_grounding():
    from fairifier.utils.entity_plan import (
        materialize_reported_materials, repair_reported_material_quotes,
    )

    source = ("In 2016, a PET-hydrolyzing enzyme (IsPETase) was isolated from Ideonella sakaiensis. "
              "Pellets were ground by the manufacturer. Activity of IsPETase on amorphous PET powder "
              "was measured at 30 to 80 °C.")
    claims = {"studies": [{"row_id": "study_001"}], "reported_materials": [
        {"record_id": "prep_enz", "level": "observationunit", "parent_row_id": "study_001",
         "record_kind": "material_preparation", "source_subject": "purified IsPETase, LCC",
         "source_quote": "All enzymes were purified."},
        {"record_id": "enz", "level": "sample", "parent_row_id": "prep_enz",
         "record_kind": "material_identity", "source_subject": "IsPETase",
         "source_quote": "a PET-hydrolyzing enzyme (IsPETase) was isolated from Ideonella sakaiensis"},
        # Real quote that does not name the subject; subject differs in case only.
        {"record_id": "prep_pet", "level": "observationunit", "parent_row_id": "study_001",
         "record_kind": "material_preparation", "source_subject": "Amorphous PET powder",
         "source_quote": "Pellets were ground by the manufacturer."},
    ]}
    merged = EntityStructurePlannerAgent._with_material_inventory(claims, [], source_text=source)
    assert merged["ungrounded_reported_materials"] == ["prep_enz"]
    records = repair_reported_material_quotes(merged["reported_materials"], source_text=source)
    assert [(r["record_id"], r["parent_row_id"]) for r in records] == [
        ("ou_enz", "study_001"), ("enz", "ou_enz"), ("prep_pet", "study_001")]
    assert "amorphous PET powder" in records[2]["source_quote"]
    plan = {"levels": [{"level": "study", "entities": [{"row_id": "study_001"}]}]}
    assert not materialize_reported_materials(plan, records, source_text=source).get(
        "materialization_errors")


def test_material_sample_hung_on_a_non_observation_unit_gets_its_own_preparation():
    from fairifier.agents.entity_structure_planner import EntityStructurePlannerAgent

    source = "Thc_Cut1 and Thc_Cut2 were expressed in E. coli."
    claims = {"investigations": [{"row_id": "inv_001"}], "studies": [{"row_id": "study_001"}],
              "reported_materials": [
                  {"record_id": "mat_001", "level": "sample", "parent_row_id": "inv_001",
                   "record_kind": "material_identity", "source_subject": "Thc_Cut1",
                   "source_quote": source},
                  {"record_id": "mat_002", "level": "sample", "parent_row_id": "nowhere",
                   "record_kind": "material_identity", "source_subject": "Thc_Cut2",
                   "source_quote": source}]}
    merged = EntityStructurePlannerAgent._with_material_inventory(claims, [], source_text=source)
    assert [(r["record_id"], r["parent_row_id"]) for r in merged["reported_materials"]] == [
        ("ou_mat_001", "study_001"), ("mat_001", "ou_mat_001"),
        ("ou_mat_002", "study_001"), ("mat_002", "ou_mat_002")]


def test_review_quote_accepts_retyped_quote_but_not_invented_text():
    from fairifier.agents.entity_structure_planner import _review_quote_in_source

    source = ("Kinetic analysis employing BHET indicated that BhrPETase possessed a similar "
              "turn over number ( $k_{cat}$ ) and a lower Km value than that of LCC (Table 2).")
    retyped = ("Kinetic analysis employing BHET indicated that BhrPETase possessed a similar "
               "turn over number (kcat) and a lower Km value than that of LCC (Table 2).")
    assert _review_quote_in_source(retyped, source)
    assert not _review_quote_in_source("invented evidence", source)
    assert not _review_quote_in_source(
        "BhrPETase showed the highest kcat on BHET of all enzymes tested at 70 °C.", source)


def test_record_review_errors_do_not_block_the_entity_plan():
    errors = [
        "Reported results lack complete source-backed independent approval.",
        "Reported record r1 review evidence_quote is not present in the source; copy ...",
        "Independent review rejected reported record r2: missing unit.",
        "Reported assay a1 has unverified identity, parent or evidence.",
        "Unresolved physical sample relation for group_001:enzyme; cardinality requires source review.",
    ]
    assert EntityStructurePlannerAgent._blocking_plan_errors(errors) == []
    structural = "Design group g1 assay row 1 matches 3 sample parents."
    assert EntityStructurePlannerAgent._blocking_plan_errors(errors + [structural]) == [structural]
    reuse = ("Design group g5 creates 6 assay rows from only 3 sample rows without an explicit "
             "source quote authorizing reuse of the same sample. Resolve the physical input "
             "relationship from source evidence; do not infer distinct Samples from missing "
             "reuse evidence.")
    assert EntityStructurePlannerAgent._blocking_plan_errors(errors + [reuse]) == []


def test_explicit_distinct_values_override_an_undercounted_level_count():
    claims = _partially_enumerated_design_claims(count=2, values=["a", "b", "c"], origin="explicit")
    plan = materialize_entity_claims(claims)
    assert plan["materialization_errors"] == []
    rows = [r for lv in plan["levels"] if lv["level"] == "assay"
            for r in lv["entities"] if r["source_group"] == "unresolved_branch"]
    assert len(rows) == 3


def test_duplicate_values_beyond_the_count_still_fail():
    claims = _partially_enumerated_design_claims(count=2, values=["a", "a", "b"], origin="explicit")
    plan = materialize_entity_claims(claims)
    assert any("declares 2 levels but supplies 3 values" in e for e in plan["materialization_errors"])


def test_unquoted_metadata_attribute_is_dropped_but_the_result_is_kept():
    from fairifier.utils.entity_plan import materialize_reported_assays

    plan, record, source = _reported_fit_fixture()
    record["attributes"].append({"field_name": "source doi", "value": "10.1000/xyz"})
    result = materialize_reported_assays(
        plan, [record], source_text=source,
        field_catalog={"assay": ["fitted response", "source doi"]},
    )
    assays = [e for lv in result["levels"] if lv["level"] == "assay" for e in lv["entities"]
              if e["row_id"] == "reported_fit_a"]
    assert len(assays) == 1
    assert [(a["field_name"], a["value"]) for a in assays[0]["attributes"]] == [("fitted response", "0.7")]
    assert any("dropped an unverified value or field: source doi" in e
               for e in result["materialization_errors"])


def test_two_factors_never_share_one_field_on_a_row():
    """Enzyme and substrate both mapped to 'experimental subject name': the first keeps it."""
    claims = _embryo_study_claims()
    group = claims["design_groups"][0]
    for name, values in (("enzyme", ["E1", "E2"]), ("substrate", ["S1", "S2"])):
        group["dimensions"].append({
            "name": name, "level_count": 2, "explicit_values": values, "origin": "explicit",
            "field_mappings": [{"level": "sample", "field_name": "sampling strategy"}],
            "applies_to": ["sample"],
        })
    plan = materialize_entity_claims(claims)
    samples = next(level["entities"] for level in plan["levels"] if level["level"] == "sample")
    mapped = {(a["dimension_name"], a["field_name"]) for e in samples for a in e["attributes"]
              if a["dimension_name"] in ("enzyme", "substrate")}
    assert mapped == {("enzyme", "sampling strategy"), ("substrate", None)}


@pytest.mark.parametrize("source, quote", [
    ("a weight loss of   $42.6 \\pm 2.9\\%$   of the PET film", "a weight loss of 42.6 ± 2.9% of the PET film"),
    ("was produced at (1.2 g L  $^{-1}$  or 38  $\\mu$  M), followed", "was produced at (1.2 g L⁻¹ or 38 μM), followed"),
    ("could be achieved at   $70^{\\circ}C$   with TfCut2", "could be achieved at 70°C with TfCut2"),
    ("reached the maximum value (5 g L  $^{-1}$  ) at 16.5 h", "reached the maximum value (5 g L−1) at 16.5 h"),
])
def test_quote_in_plain_typography_matches_markdown_math_source(source, quote):
    from fairifier.utils.document_text import normalize_source_evidence_text as norm
    from fairifier.utils.entity_plan import _reported_quote_in_source
    assert _reported_quote_in_source(norm(quote), norm(source))


def test_math_with_names_or_other_numbers_is_not_rendered_plain():
    from fairifier.utils.document_text import normalize_source_evidence_text as norm
    assert norm("$k_{cat}$ of $1.2 \\times 10^{3}$") == "$k_{cat}$ of $1.2 \\times 10^{3}$"
    assert norm("1.2 × 10³ s⁻¹") == "1.2 × 10³ s-1"
    assert norm("$42.6 \\pm 2.9\\%$") != norm("42.6 ± 2.8%")


ROW_TABLE = (
    '<table><tr><td rowspan="2"></td><td rowspan="2">IsPETase variant</td>'
    '<td rowspan="2">Melting point ± SD [°C]</td><td colspan="2">\\(T_{\\text{m}}\\) [°C] increase compared to</td></tr>'
    '<tr><td>IsPETaseWT</td><td>IsPETaseTM</td></tr>'
    '<tr><td>WT</td><td>IsPETaseWT</td><td>45.1 ± 0.1</td><td>-</td><td>-</td></tr>'
    '<tr><td>TM1</td><td>\\(IsPETaseTM^{K95N/F201I}\\)</td><td>61.6 ± 0.1</td><td>16.6</td><td>5.1</td></tr>'
    '<tr><td>TM2</td><td>\\(IsPETaseTM^{N233C/S282C}\\)</td><td>68.2 ± 1.6</td><td>23.1</td><td>11.6</td></tr></table>'
)


@pytest.mark.parametrize("quote, subject, value, expected", [
    ("IsPETaseWT<br>45.1 ± 0.1", "IsPETaseWT", "45.1", "45.1"),
    ("IsPETaseTMK95N/F201I<br>61.6 ± 0.1", "IsPETaseTMK95N/F201I", "61.6", "61.6"),
    ("IsPETaseTMN233C/S282C<br>68.2 ± 1.6", "IsPETaseTMN233C/S282C", "1.6", "1.6"),
    # Another variant's mean or error is not this row's cell.
    ("IsPETaseTMK95N/F201I<br>61.6 ± 0.1", "IsPETaseTMK95N/F201I", "68.2", ""),
    ("IsPETaseTMK95N/F201I<br>61.6 ± 0.1", "IsPETaseTMK95N/F201I", "1.6", ""),
])
def test_cells_rejoined_without_their_row_cite_the_source_row(quote, subject, value, expected):
    from fairifier.utils.entity_plan import _cited_table_row, _row_cell_value

    row, lines = _cited_table_row(quote, ROW_TABLE)
    assert row.startswith("<tr>") and row in ROW_TABLE
    assert _row_cell_value(value, subject, lines) == expected


TIME_TABLE = (
    '<table><tr><td rowspan="2"></td><td colspan="3">TPA variation (mM)</td></tr>'
    '<tr><td>0 h</td><td>2 h</td><td>48 h</td></tr>'
    '<tr><td>Tfu_0883</td><td>5.4 ± 0.1</td><td>7.2 ± 0.2</td><td>12.3 ± 0.1</td></tr>'
    '<tr><td>Q132A/T101A</td><td>1.1 ± 0.2</td><td>16.9 ± 0.2</td><td>19.3 ± 0.1</td></tr></table>'
)
ENZYME_COLUMN_TABLE = (
    '<table><tr><td rowspan="2">Substrate</td><td colspan="2">Km (mM)</td></tr>'
    '<tr><td>EnzA</td><td>EnzB</td></tr>'
    '<tr><td>S1</td><td>1.15 ± 0.01</td><td>5.28</td></tr></table>'
)


def test_a_row_naming_the_material_owns_its_time_point_cells():
    """The record is the row; 0 h / 2 h / 48 h are conditions, not other records."""
    from fairifier.utils.entity_plan import _cited_table_row, _row_cell_value

    quote = "<tr><td>Q132A/T101A</td><td>1.1 ± 0.2</td><td>16.9 ± 0.2</td><td>19.3 ± 0.1</td></tr>"
    row, lines = _cited_table_row(quote, TIME_TABLE)
    assert row == quote
    assert _row_cell_value("16.9 ± 0.2 mM", "Q132A/T101A", lines) == "16.9 ± 0.2 mM"
    # Another row's cell is still not this material's.
    assert _row_cell_value("7.2 ± 0.2 mM", "Q132A/T101A", lines) == ""


def test_a_pivoted_enzyme_column_still_belongs_to_that_enzyme_only():
    from fairifier.utils.entity_plan import _cited_table_row, _row_cell_value

    quote = "<tr><td>S1</td><td>1.15 ± 0.01</td><td>5.28</td></tr>"
    _, lines = _cited_table_row(quote, ENZYME_COLUMN_TABLE)
    assert _row_cell_value("5.28", "EnzB", lines) == "5.28"
    assert _row_cell_value("1.15", "EnzB", lines) == ""


def test_a_result_quote_retyped_from_rendered_math_is_snapped_to_the_source_passage():
    from fairifier.utils.entity_plan import _reported_quote_in_source, repair_reported_assay_quotes
    from fairifier.utils.document_text import normalize_source_evidence_text as norm

    source = ("Compared with GF-PET, the post-consumer PET packaging materials revealed two separate "
              "endothermic peaks in the glass transition range, corresponding to a $T_{g1}$ of 75–78°C "
              "and a $T_{g2}$ of 83–85°C for AP-PET and a $T_{g1}$ of 77–80°C for CP-PET. Other text.")
    retyped = ("the post-consumer PET packaging materials revealed two separate endothermic peaks in "
               "the glass transition range, corresponding to a Tg1 of 75–78°C and a Tg2 of 83–85°C for AP-PET")
    record = {"record_id": "ra_tg_appet", "source_quote": retyped}
    [fixed] = repair_reported_assay_quotes([record], source_text=source)
    assert fixed["source_quote_repaired"] is True
    assert "$T_{g1}$" in fixed["source_quote"]
    assert _reported_quote_in_source(norm(fixed["source_quote"]), norm(source))
    assert "75–78°C" in fixed["source_quote"] and "83–85°C" in fixed["source_quote"]


def test_invented_short_and_table_row_quotes_are_not_repaired():
    from fairifier.utils.entity_plan import repair_reported_assay_quotes

    source = ("The enzyme reached a turnover of 12.3 per second at 50 °C on amorphous film, "
              "while the crystalline film was hydrolysed more slowly. <table><tr><td>A</td><td>1.0</td></tr></table>")
    invented = "The enzyme reached a turnover of 99.9 per second at 70 °C on crystalline pellets and fibres"
    short = "turnover of 12.3"
    row = "<tr><td>A</td><td>1.1</td></tr>"
    for quote in (invented, short, row):
        [kept] = repair_reported_assay_quotes([{"record_id": "r", "source_quote": quote}], source_text=source)
        assert kept["source_quote"] == quote and "source_quote_repaired" not in kept


def test_fragments_matching_no_single_row_cite_nothing():
    from fairifier.utils.entity_plan import _cited_table_row

    assert _cited_table_row("IsPETaseWT<br>61.6 ± 0.1", ROW_TABLE) == ("", [])


@pytest.mark.anyio
@pytest.mark.parametrize("approved", [True, False])
async def test_one_reviewed_table_row_result_repeats_over_the_other_rows(monkeypatch, approved):
    plan, materials, _ = _reported_material_fixture()
    row = "<tr><td>alpha</td><td>1.1 ± 0.1</td><td>7.3</td></tr>"
    source = (
        "Material alpha was purified before characterisation.\n\n"
        "<table><tr><td>Enzyme</td><td>Km (mM)</td><td>kcat (s-1)</td></tr>" + row
        + "<tr><td>beta</td><td>2.4 ± 0.2</td><td>n.d.</td></tr>"
        "<tr><td>gamma</td><td>0.9 ± 0.1</td><td>12.5</td></tr></table>"
    )
    template = {
        "record_id": "kin_alpha", "sample_row_id": "material_alpha", "record_kind": "fitted_result",
        "source_subject": "alpha", "source_quote": row, "label": "alpha kinetics",
        "source_group": "kinetics", "repeat_for_table_rows": True,
        "attributes": [{"field_name": "Michaelis constant Km", "value": "1.1 ± 0.1 mM"},
                       {"field_name": "catalytic rate constant kcat", "value": "7.3 s-1"}],
    }
    knowledge = [
        {"term": "Michaelis constant Km", "metadata": {"isa_sheet": "assay", "syntax": "{number}\\s+\\S.*"}},
        {"term": "catalytic rate constant kcat", "metadata": {"isa_sheet": "assay"}},
    ]
    reviewed = []

    async def review(*args, **kwargs):
        prompt = args[1][0].content
        listed = [item for item in [*materials, template] if f'"{item["record_id"]}"' in prompt]
        reviewed.extend(item["record_id"] for item in listed)
        return {"decisions": [
            {"record_id": item["record_id"], "approved": approved or item is not template,
             "evidence_quote": item["source_quote"], "rationale": "Checked."} for item in listed]}

    monkeypatch.setattr(entity_planner_module, "invoke_structured_output", review)
    planner = object.__new__(EntityStructurePlannerAgent)
    planner.llm_helper = object()
    result = await planner._materialize_reviewed_results(
        plan, [template], knowledge, source, materials=materials)

    # Only the template and the declared materials go to the reviewer.
    assert sorted(reviewed) == ["kin_alpha", "material_alpha", "prep_alpha"]
    assays = next(level for level in result["levels"] if level["level"] == "assay")["entities"]
    values = {(row["parent_row_id"], a["field_name"]): a["value"]
              for row in assays for a in row.get("attributes") or []}
    if not approved:
        assert not assays
        return
    assert values[("material_alpha", "catalytic rate constant kcat")].startswith("7.3")
    assert values[("tbl_beta", "Michaelis constant Km")].startswith("2.4 ± 0.2")
    assert ("tbl_beta", "catalytic rate constant kcat") not in values  # "n.d." is not a value
    assert values[("tbl_gamma", "catalytic rate constant kcat")].startswith("12.5")
    samples = {row["row_id"] for level in result["levels"] if level["level"] == "sample"
               for row in level["entities"]}
    assert {"tbl_beta", "tbl_gamma"} <= samples and "tbl_enzyme" not in samples


GROUPED_TABLE = (
    "<table><tr><td>T (°C)</td><td>massKM(g·L-1)</td><td>kcat(s-1)</td></tr>"
    "<tr><td></td><td>Thc_Cut1</td><td></td></tr>"
    "<tr><td>50</td><td>2.3 ± 0.68</td><td>0.072 ± 0.0056</td></tr>"
    "<tr><td>60</td><td>6.9 ± 1.2</td><td>0.22 ± 0.017</td></tr>"
    "<tr><td></td><td>Thc_Cut2</td><td></td></tr>"
    "<tr><td>50</td><td>3.5 ± 0.68</td><td>0.057 ± 0.0036</td></tr></table>"
)


def test_label_rows_name_the_material_of_the_rows_below():
    from fairifier.services.publication_tables import render_table_rows

    assert render_table_rows(GROUPED_TABLE) == [
        "section = Thc_Cut1; T (°C) = 50; massKM(g·L-1) = 2.3 ± 0.68; kcat(s-1) = 0.072 ± 0.0056",
        "section = Thc_Cut1; T (°C) = 60; massKM(g·L-1) = 6.9 ± 1.2; kcat(s-1) = 0.22 ± 0.017",
        "section = Thc_Cut2; T (°C) = 50; massKM(g·L-1) = 3.5 ± 0.68; kcat(s-1) = 0.057 ± 0.0036",
    ]


def test_grouped_table_template_repeats_per_label_and_condition_row():
    from fairifier.utils.entity_plan import (
        expand_table_row_templates, rebind_results_to_named_samples,
    )

    materials = [
        {"record_id": f"ou_{n}", "level": "observationunit", "parent_row_id": "study_001",
         "record_kind": "material_preparation", "source_subject": name, "source_quote": "x",
         "label": name, "source_group": "enzymes"} for n, name in (("pet", "PET"), ("c1", "Thc_Cut1"), ("c2", "Thc_Cut2"))
    ] + [
        {"record_id": f"s_{n}", "level": "sample", "parent_row_id": f"ou_{n}",
         "record_kind": "material_identity", "source_subject": name, "source_quote": "x",
         "label": name, "source_group": "enzymes"} for n, name in (("pet", "PET"), ("c1", "Thc_Cut1"), ("c2", "Thc_Cut2"))
    ]
    template = {
        "record_id": "kin", "sample_row_id": "s_pet", "record_kind": "fitted_result",
        "source_subject": "Thc_Cut1", "repeat_for_table_rows": True, "label": "Thc_Cut1 kinetics",
        "source_group": "kinetics",
        "source_quote": "TABLE 1 Kinetics. <tr><td>50</td><td>2.3 ± 0.68</td><td>0.072 ± 0.0056</td></tr>",
        "attributes": [{"field_name": "Michaelis constant Km", "value": "2.3 ± 0.68 g·L-1"},
                       {"field_name": "catalytic rate constant kcat", "value": "0.072 ± 0.0056 s-1"},
                       {"field_name": "reaction temperature", "value": "50"}],
    }
    # Filed under the PET substrate, the result moves to the one Sample it names.
    records = rebind_results_to_named_samples([template], materials)
    assert records[0]["sample_row_id"] == "s_c1"
    records, new_materials, derived = expand_table_row_templates(records, materials, GROUPED_TABLE)
    got = {(r["sample_row_id"], a["value"]) for r in records for a in r["attributes"]
           if a["field_name"] in ("Michaelis constant Km", "reaction temperature")}
    assert got == {("s_c1", "2.3 ± 0.68 g·L-1"), ("s_c1", "50"), ("s_c1", "6.9 ± 1.2 g·L-1"),
                   ("s_c1", "60"), ("s_c2", "3.5 ± 0.68 g·L-1"), ("s_c2", "50")}
    assert len(new_materials) == len(materials) and set(derived.values()) == {"kin"}


@pytest.mark.parametrize("quote, expected", [
    ("Thc_Cut1 50: KM 2.3 ± 0.68 g·L-1; kcat 0.072 ± 0.0056 s-1", "2.3 ± 0.68"),
    ("Thc_Cut2 at 50 °C: KM 3.5 ± 0.68, kcat 0.057 ± 0.0036", "3.5 ± 0.68"),
    # One pair matches rows of two materials: no single row is cited.
    ("Km was 2.3 ± 0.68", None),
])
def test_row_retyped_as_prose_cites_the_one_row_holding_its_pairs(quote, expected):
    from fairifier.utils.entity_plan import _cited_table_row

    row, lines = _cited_table_row(quote, GROUPED_TABLE)
    if expected is None:
        assert (row, lines) == ("", [])
    else:
        assert f"<td>{expected}</td>" in row and len(lines) == 1 and "section = Thc_Cut" in lines[0]


PIVOT_TABLE = (
    "<table><tr><td>Temperature</td><td>Measure</td><td>alpha</td><td>beta</td><td>gamma</td></tr>"
    '<tr><td rowspan="2">45 °C</td><td>Specific activity (µmol h-1 mg-1)</td>'
    "<td>245.5 ± 12.5</td><td>210.9 ± 13.5</td><td>n.d.</td></tr>"
    "<tr><td>Conversion (%)</td><td>8.7 ± 2.3</td><td>10.4 ± 0.7</td><td>4.9 ± 0.4</td></tr></table>"
)
PIVOT_ROW = ("<tr><td>Conversion (%)</td><td>8.7 ± 2.3</td><td>10.4 ± 0.7</td>"
             "<td>4.9 ± 0.4</td></tr>")


def test_pivoted_table_result_repeats_over_the_other_enzyme_columns():
    from fairifier.utils.entity_plan import _repeat_across_columns

    template = {
        "record_id": "conv_alpha", "sample_row_id": "s_alpha", "record_kind": "aggregate_result",
        "source_subject": "alpha", "source_quote": PIVOT_ROW, "label": "alpha conversion",
        "source_group": "activity", "repeat_for_table_rows": True,
        "attributes": [{"field_name": "conversion", "value": "8.7 ± 2.3 %"}],
    }
    samples = {"alpha": "s_alpha", "beta": "s_beta", "gamma": "s_gamma"}
    derived: dict = {}
    out = _repeat_across_columns(template, PIVOT_ROW, PIVOT_TABLE, samples, [template], derived)
    values = {r["sample_row_id"]: r["attributes"][0]["value"] for r in out}
    assert values == {"s_beta": "10.4 ± 0.7 %", "s_gamma": "4.9 ± 0.4 %"}
    assert set(derived.values()) == {"conv_alpha"}
    # A column the planner already cited for that sample is not repeated.
    cited = {**template, "record_id": "conv_beta", "sample_row_id": "s_beta"}
    again = _repeat_across_columns(template, PIVOT_ROW, PIVOT_TABLE, samples, [template, cited], {})
    assert {r["sample_row_id"] for r in again} == {"s_gamma"}
def _screening_claims(positions, clones, clone_origin="derived", clone_values=None):
    return {
        "investigations": [{"row_id": "inv_a", "label": "Screen", "evidence": "SSM libraries were screened."}],
        "studies": [{"row_id": "study_a", "parent_row_id": "inv_a", "label": "Screen", "evidence": "SSM screen."}],
        "design_groups": [{
            "group_id": "ssm", "label": "SSM screen", "study_row_id": "study_a",
            "evidence": "Two hundred clones were screened for each SSM library.",
            "dimensions": [
                {"name": "engineered_position", "level_count": positions,
                 "explicit_values": [f"P{i}" for i in range(1, positions + 1)], "origin": "explicit",
                 "semantic_role": "material_path", "field_name": "material label",
                 "applies_to": ["observationunit", "sample", "assay"]},
                {"name": "screened_clones_per_position", "level_count": clones,
                 "explicit_values": list(clone_values or []), "origin": clone_origin,
                 "semantic_role": "observation_condition", "field_name": "clone label",
                 "applies_to": ["assay"]},
            ],
        }],
        "unresolved_ambiguities": [],
    }


def test_screening_campaign_is_not_expanded_into_one_assay_per_unreported_clone():
    plan = materialize_entity_claims(_screening_claims(positions=58, clones=200))
    levels = {level["level"]: level for level in plan["levels"]}

    # 58 positions x 200 unnamed clones would be 11,600 assays
    assert len(levels["assay"]["entities"]) == 58
    assert len(levels["sample"]["entities"]) == 58
    assert not plan["materialization_errors"]
    assert any("screened_clones_per_position" in note and "200" in note
               for note in levels["assay"]["unresolved_ambiguities"])
    assert not any(a["dimension_name"] == "screened_clones_per_position"
                   for row in levels["assay"]["entities"] for a in row["attributes"])


def test_plan_under_the_row_cap_is_expanded_as_before():
    plan = materialize_entity_claims(_screening_claims(positions=10, clones=5))
    levels = {level["level"]: level for level in plan["levels"]}
    assert len(levels["assay"]["entities"]) == 50
    assert not plan["materialization_errors"]


def test_named_levels_are_never_collapsed_and_an_oversized_product_is_refused():
    names = [f"clone {i}" for i in range(1, 201)]
    plan = materialize_entity_claims(
        _screening_claims(positions=58, clones=200, clone_origin="explicit", clone_values=names))
    levels = {level["level"]: level for level in plan["levels"]}
    assert not levels["assay"]["entities"]
    assert any("11600 rows" in error for error in plan["materialization_errors"])


def _template_materials(*subjects):
    materials = []
    for index, subject in enumerate(subjects):
        materials += [
            {"record_id": f"ou_{index}", "level": "observationunit", "parent_row_id": "study_001",
             "record_kind": "material_preparation", "source_subject": subject, "source_quote": "x",
             "label": subject, "source_group": "g"},
            {"record_id": f"s_{index}", "level": "sample", "parent_row_id": f"ou_{index}",
             "record_kind": "material_identity", "source_subject": subject, "source_quote": "x",
             "label": subject, "source_group": "g"},
        ]
    return materials


ANNEAL_TABLE = (
    "<table><tr><td>Annealing condition</td><td>\\( V_{max} \\)[μM s-1]</td></tr>"
    "<tr><td>5 min at 85°C</td><td>\\( 0.22 ± 0.01^{\\text{a}} \\)</td></tr>"
    "<tr><td>3 min at 115°C</td><td>\\( 0.16 ± 0.01^{\\text{ab}} \\)</td></tr>"
    "<tr><td>4 min at 115°C</td><td>\\( 0.13 ± 0.010^{\\text{b}} \\)</td></tr></table>"
)


def test_template_repeats_over_rows_whose_cells_carry_math_markup_and_digit_led_labels():
    from fairifier.utils.entity_plan import expand_table_row_templates

    template = {
        "record_id": "vmax", "sample_row_id": "s_0", "record_kind": "fitted_result",
        "source_subject": "5 min at 85°C", "repeat_for_table_rows": True, "label": "Vmax",
        "source_group": "kinetics", "source_quote": "<tr><td>5 min at 85°C</td><td>\\( 0.22 ± 0.01^{\\text{a}} \\)</td></tr>",
        "attributes": [{"field_name": "reported measurement", "value": "0.22 ± 0.01 μM s-1"}],
    }
    records, materials, derived = expand_table_row_templates(
        [template], _template_materials("5 min at 85°C"), ANNEAL_TABLE)

    clones = {r["source_subject"]: r["attributes"][0]["value"] for r in records if r["record_id"] != "vmax"}
    assert clones == {"3 min at 115°C": "0.16 ± 0.01 μM s-1", "4 min at 115°C": "0.13 ± 0.010 μM s-1"}
    assert {m["source_subject"] for m in materials if m["level"] == "sample"} >= set(clones)


def test_template_whose_subject_is_the_label_row_plus_its_condition_repeats_per_row():
    from fairifier.utils.entity_plan import expand_table_row_templates

    template = {
        "record_id": "kin", "sample_row_id": "s_0", "record_kind": "fitted_result",
        "source_subject": "Thc_Cut1 50°C", "repeat_for_table_rows": True, "label": "kinetics",
        "source_group": "kinetics",
        "source_quote": "<tr><td>50</td><td>2.3 ± 0.68</td><td>0.072 ± 0.0056</td></tr>",
        "attributes": [{"field_name": "Michaelis constant Km", "value": "2.3 ± 0.68 g·L-1"},
                       {"field_name": "reaction temperature", "value": "50"}],
    }
    records, _, _ = expand_table_row_templates(
        [template], _template_materials("Thc_Cut1", "Thc_Cut2"), GROUPED_TABLE)

    got = {(r["sample_row_id"], r["attributes"][0]["value"], r["attributes"][1]["value"])
           for r in records if r["record_id"] != "kin"}
    assert got == {("s_0", "6.9 ± 1.2 g·L-1", "60"), ("s_1", "3.5 ± 0.68 g·L-1", "50")}
