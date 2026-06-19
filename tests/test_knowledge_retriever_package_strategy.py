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
