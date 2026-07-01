from __future__ import annotations

from fairifier.agents.knowledge_retriever import KnowledgeRetrieverAgent


def _make_kr_without_init() -> KnowledgeRetrieverAgent:
    return object.__new__(KnowledgeRetrieverAgent)


def test_merge_available_package_names_includes_local_extensions():
    kr = _make_kr_without_init()

    merged = kr._merge_available_package_names(
        ["default", "MIFE"],
        ["petase_enzyme_engineering", "default"],
    )

    assert merged == ["default", "MIFE", "petase_enzyme_engineering"]


def test_infer_local_domain_package_hints_for_petase_context():
    kr = _make_kr_without_init()

    hints = kr._infer_local_domain_package_hints(
        doc_info={
            "title": (
                "An engineered PET depolymerase to break down plastic bottles"
            ),
            "research_domain": "biocatalysis",
            "keywords": ["PETase", "UHPLC", "MHET"],
        },
        planner_instruction=(
            "Prioritize PET depolymerization assay metadata fields."
        ),
        evidence_packets=[
            {"value": "LCC ICCG variant, substrate crystallinity 7.7%"}
        ],
        local_package_names=["petase_enzyme_engineering"],
    )

    assert "petase_enzyme_engineering" in hints


def test_petase_local_package_hint_limits_generic_environment_candidates():
    kr = _make_kr_without_init()

    candidates = kr._build_candidate_package_names(
        doc_info={
            "title": "Engineered PETase depolymerises polyethylene terephthalate",
            "research_domain": "biocatalysis enzyme engineering",
            "keywords": ["PETase", "PET depolymerization", "substrate"],
            "methodology": "UHPLC product quantification",
        },
        planner_instruction="Use PETase enzyme engineering metadata fields.",
        available_package_names=[
            "default",
            "miscellaneous natural or artificial environment",
            "soil",
            "petase_enzyme_engineering",
        ],
        evidence_packets=[
            {"value": "LCC ICCG enzyme, Gf-PET substrate, pH 8.0, 65 °C"}
        ],
        priority_package_hints=["default", "petase_enzyme_engineering"],
        excluded_package_names=set(),
    )

    assert candidates == ["default", "petase_enzyme_engineering"]


def test_petase_local_package_prunes_biological_default_sample_fields():
    kr = _make_kr_without_init()

    fields = [
        {
            "label": "investigation identifier",
            "sheetName": "Investigation",
            "packageName": "default",
        },
        {
            "label": "ncbi taxonomy id",
            "sheetName": "Sample",
            "packageName": "default",
        },
        {
            "label": "sample name",
            "sheetName": "Sample",
            "packageName": "default",
        },
        {
            "label": "enzyme type",
            "sheetName": "Sample",
            "packageName": "petase_enzyme_engineering",
        },
    ]

    pruned = kr._prune_default_fields_for_local_domain_package(
        fields,
        selected_package_names=["default", "petase_enzyme_engineering"],
        local_package_registry={"petase_enzyme_engineering": {"metadata": []}},
    )

    assert [field["label"] for field in pruned] == [
        "investigation identifier",
        "enzyme type",
    ]


def test_petase_local_package_clamps_final_selected_packages():
    kr = _make_kr_without_init()

    selected = kr._clamp_selected_packages_for_local_domain(
        selected_package_names=[
            "petase_enzyme_engineering",
            "default",
            "miappe",
            "miscellaneous natural or artificial environment",
            "soil",
        ],
        local_domain_package_hints=["petase_enzyme_engineering"],
        available_package_names=[
            "default",
            "miappe",
            "miscellaneous natural or artificial environment",
            "soil",
            "petase_enzyme_engineering",
        ],
    )

    assert selected == ["default", "petase_enzyme_engineering"]


def test_search_local_package_fields_matches_labels_and_definitions():
    kr = _make_kr_without_init()
    kr._local_package_registry = {
        "petase_enzyme_engineering": {
            "packageName": "petase_enzyme_engineering",
            "metadata": [
                {
                    "label": "PET crystallinity",
                    "sheetName": "Sample",
                    "packageName": "petase_enzyme_engineering",
                    "requirement": "RECOMMENDED",
                    "term": {"definition": "Crystalline fraction of the PET substrate"},
                },
                {
                    "label": "reaction temperature",
                    "sheetName": "Assay",
                    "packageName": "petase_enzyme_engineering",
                    "requirement": "MANDATORY",
                    "term": {"definition": "Temperature of enzyme incubation"},
                },
            ],
        }
    }

    label_hits = kr._search_local_package_fields(
        "crystallinity", ["petase_enzyme_engineering"]
    )
    definition_hits = kr._search_local_package_fields(
        "enzyme incubation", ["petase_enzyme_engineering"]
    )
    excluded_hits = kr._search_local_package_fields("crystallinity", ["default"])

    assert [field["label"] for field in label_hits] == ["PET crystallinity"]
    assert [field["label"] for field in definition_hits] == ["reaction temperature"]
    assert excluded_hits == []


def test_deduplicate_local_fields_preserves_same_label_on_different_sheets():
    fields = [
        {
            "label": "study identifier",
            "sheetName": "Study",
            "packageName": "default",
        },
        {
            "label": "study identifier",
            "sheetName": "Assay",
            "packageName": "petase_enzyme_engineering",
        },
    ]

    assert len(KnowledgeRetrieverAgent._deduplicate_package_fields(fields)) == 2
