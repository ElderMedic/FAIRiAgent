from __future__ import annotations

from fairifier.agents.knowledge_retriever import KnowledgeRetrieverAgent
from fairifier.utils.package_selection import (
    build_document_match_text,
    rank_packages_by_document,
    score_package_relevance,
    summary_to_package_record,
)


def test_summary_to_package_record_maps_fairds_fields():
    record = summary_to_package_record(
        {
            "name": "soil",
            "description": "MIxS soil environmental standard for terrestrial soil sampling.",
            "levels": ["Sample"],
            "fieldCount": 42,
            "requirements": {"MANDATORY": 5, "OPTIONAL": 30, "RECOMMENDED": 7},
        }
    )

    assert record["name"] == "soil"
    assert "MIxS soil" in record["description"]
    assert record["field_count"] == 42
    assert record["mandatory_count"] == 5
    assert record["optional_count"] == 30
    assert record["recommended_count"] == 7
    assert record["sheets"] == ["Sample"]


def test_score_package_relevance_uses_description_not_only_name():
    package = {
        "name": "miscellaneous natural or artificial environment",
        "description": "Generic environmental metadata for mixed natural or artificial habitats.",
        "sheets": ["Sample"],
    }
    earthworm_text = build_document_match_text(
        {
            "title": "Earthworm gut microbiome in agricultural soil",
            "research_domain": "ecology",
            "keywords": ["earthworm", "soil", "microbiome"],
        }
    )
    soil_package = {
        "name": "soil",
        "description": "MIxS soil environmental standard for terrestrial soil sampling and characterisation.",
        "sheets": ["Sample"],
    }

    assert score_package_relevance(earthworm_text, soil_package) > score_package_relevance(
        earthworm_text, package
    )


def test_rank_packages_by_document_puts_relevant_packages_first():
    packages = [
        {
            "name": "human oral",
            "description": "Human oral microbiome reporting standard.",
            "sheets": ["Sample"],
        },
        {
            "name": "soil",
            "description": "MIxS soil environmental standard for terrestrial soil sampling.",
            "sheets": ["Sample"],
        },
        {
            "name": "Illumina",
            "description": "Illumina sequencing assay metadata.",
            "sheets": ["Assay"],
        },
    ]
    match_text = build_document_match_text(
        {
            "title": "RNA-seq of earthworms in contaminated soil",
            "keywords": ["rna-seq", "soil", "earthworm"],
            "methodology": "Illumina sequencing",
        }
    )

    ranked = rank_packages_by_document(packages, match_text)

    assert ranked[0]["name"] in {"soil", "Illumina"}
    assert ranked[-1]["name"] == "human oral"


def test_build_candidate_package_names_uses_description_catalog():
    kr = object.__new__(KnowledgeRetrieverAgent)
    catalog = [
        {
            "name": "soil",
            "description": "MIxS soil environmental standard for terrestrial soil sampling.",
            "sheets": ["Sample"],
        },
        {
            "name": "human oral",
            "description": "Human oral microbiome reporting standard.",
            "sheets": ["Sample"],
        },
        {
            "name": "Illumina",
            "description": "Illumina sequencing assay metadata.",
            "sheets": ["Assay"],
        },
    ]

    candidates = kr._build_candidate_package_names(
        doc_info={
            "title": "Earthworm populations in agricultural soil using Illumina",
            "keywords": ["earthworm", "soil", "illumina"],
        },
        planner_instruction=None,
        available_package_names=[pkg["name"] for pkg in catalog],
        evidence_packets=[{"value": "Lumbricus terrestris sampled from rhizosphere soil"}],
        priority_package_hints=["default"],
        excluded_package_names=set(),
        package_catalog=catalog,
    )

    assert "soil" in candidates
    assert "Illumina" in candidates
    assert "human oral" not in candidates


def test_build_candidate_package_names_caps_total_at_twelve_with_catalog():
    kr = object.__new__(KnowledgeRetrieverAgent)
    catalog = [
        {
            "name": "soil",
            "description": "MIxS soil environmental standard for terrestrial soil sampling.",
            "sheets": ["Sample"],
        },
        {
            "name": "Illumina",
            "description": "Illumina short-read sequencing assay metadata.",
            "sheets": ["Assay"],
        },
        {
            "name": "Genome",
            "description": "Whole-genome sequencing metadata.",
            "sheets": ["Assay"],
        },
        {
            "name": "sediment",
            "description": "MIxS sediment environmental standard for aquatic sediment sampling.",
            "sheets": ["Sample"],
        },
        {
            "name": "water",
            "description": "MIxS water environmental standard for aquatic sampling.",
            "sheets": ["Sample"],
        },
        {
            "name": "miscellaneous natural or artificial environment",
            "description": "Generic environmental metadata for mixed habitats.",
            "sheets": ["Sample"],
        },
    ] + [
        {
            "name": f"ranked_package_{idx}",
            "description": "Earthworm soil illumina sequencing metadata extension.",
            "sheets": ["Sample"],
        }
        for idx in range(12)
    ]
    available = [pkg["name"] for pkg in catalog]

    candidates = kr._build_candidate_package_names(
        doc_info={
            "title": "Earthworm populations in agricultural soil using Illumina",
            "keywords": ["earthworm", "soil", "illumina", "sequencing"],
            "methodology": "Illumina sequencing of soil samples",
        },
        planner_instruction=None,
        available_package_names=available,
        evidence_packets=[{"value": "Lumbricus terrestris sampled from rhizosphere soil"}],
        priority_package_hints=[],
        excluded_package_names=set(),
        package_catalog=catalog,
    )

    assert len(candidates) <= 12


def test_build_candidate_package_names_padding_includes_local_packages():
    kr = object.__new__(KnowledgeRetrieverAgent)
    catalog = [
        {
            "name": "soil",
            "description": "MIxS soil environmental standard for terrestrial soil sampling.",
            "sheets": ["Sample"],
        }
    ]

    candidates = kr._build_candidate_package_names(
        doc_info={
            "title": "Engineered PETase depolymerises polyethylene terephthalate",
            "research_domain": "biocatalysis enzyme engineering",
            "keywords": ["PETase", "PET depolymerization"],
        },
        planner_instruction="Use PETase enzyme engineering metadata fields.",
        available_package_names=["default", "soil", "petase_enzyme_engineering"],
        evidence_packets=[{"value": "LCC ICCG enzyme, Gf-PET substrate"}],
        priority_package_hints=["default"],
        excluded_package_names=set(),
        package_catalog=catalog,
        document_match_text=build_document_match_text(
            {
                "title": "Engineered PETase depolymerises polyethylene terephthalate",
                "research_domain": "biocatalysis enzyme engineering",
                "keywords": ["PETase", "PET depolymerization"],
            },
            planner_instruction="Use PETase enzyme engineering metadata fields.",
            evidence_packets=[{"value": "LCC ICCG enzyme, Gf-PET substrate"}],
        ),
    )

    assert "petase_enzyme_engineering" in candidates
