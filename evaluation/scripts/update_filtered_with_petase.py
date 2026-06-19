#!/usr/bin/env python3
"""Register or refresh PETase papers in ground_truth_filtered.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parents[2]
FILTERED_PATH = PROJECT_ROOT / "evaluation/datasets/annotated/ground_truth_filtered.json"
VALUES_DIR = PROJECT_ROOT / "evaluation/datasets/annotated/values"


def build_document_entry(gt: dict[str, Any]) -> dict[str, Any]:
    doc_id = gt["document_id"]
    doi = gt.get("paper_doi", "")
    slug = doc_id.replace("petase_", "", 1)

    fields: list[dict[str, Any]] = []
    sheet_stats: dict[str, dict[str, int]] = {}

    for sheet_name, sheet_data in gt.get("isa_sheets", {}).items():
        rows = sheet_data.get("expected_rows", [])
        if not rows:
            sheet_stats[sheet_name] = {"total": 0, "required": 0, "recommended": 0}
            continue

        field_names = {
            key
            for row in rows
            for key in row.keys()
            if not key.startswith("_")
        }

        required = 0
        recommended = 0
        for fname in sorted(field_names):
            is_default_field = fname in {
                "investigation identifier",
                "investigation title",
                "investigation description",
                "investigation contentUrl",
                "firstname",
                "lastname",
                "email address",
                "orcid",
                "organization",
                "department",
                "study identifier",
                "study title",
                "study description",
            }
            if sheet_name == "investigation":
                req = (
                    "required"
                    if fname
                    in {
                        "investigation title",
                        "investigation description",
                        "investigation contentUrl",
                        "investigation identifier",
                        "firstname",
                        "lastname",
                        "organization",
                    }
                    else "recommended"
                )
            elif sheet_name == "study":
                req = (
                    "required"
                    if fname
                    in {"study title", "study description", "study identifier"}
                    else "recommended"
                )
            else:
                req = "recommended"

            if req == "required":
                required += 1
            else:
                recommended += 1

            fields.append(
                {
                    "field_name": fname,
                    "isa_sheet": sheet_name,
                    "package_source": "default" if is_default_field else "petase_enzyme_engineering",
                    "is_required": req == "required",
                    "is_recommended": req == "recommended",
                    "evidence_location": f"Paper DOI: {doi}",
                    "notes": "PETase domain-specific GT converted to FAIR-DS (assay-level v2)",
                }
            )

        sheet_stats[sheet_name] = {
            "total": len(field_names),
            "required": required,
            "recommended": recommended,
        }

    total_required = sum(item["required"] for item in sheet_stats.values())
    total_recommended = sum(item["recommended"] for item in sheet_stats.values())

    paper_dir = f"evaluation/datasets/raw/petase_enzyme_engineering/papers/{slug}"
    return {
        "document_id": doc_id,
        "document_path": paper_dir,
        "metadata": {
            "domain": "Enzyme engineering / biocatalysis for plastic degradation",
            "experiment_type": "PET hydrolase characterization and engineering",
            "annotation_date": gt.get("generated_at", "2026-06-08"),
            "annotator": gt.get("generated_by", "manual_curation_by_domain_expert__converted_to_fairds"),
            "notes": f"DOI: {doi}",
        },
        "ground_truth_fields": fields,
        "ground_truth_stats": {
            "total_required_fields": total_required,
            "total_recommended_fields": total_recommended,
            "by_isa_sheet": sheet_stats,
        },
    }


def main() -> None:
    master = json.loads(FILTERED_PATH.read_text(encoding="utf-8"))
    documents = master.get("documents", [])
    non_petase = [doc for doc in documents if not doc.get("document_id", "").startswith("petase_")]

    petase_files = sorted(VALUES_DIR.glob("ground_truth_petase_*_values.json"))
    print(f"Non-PETase documents kept: {len(non_petase)}")
    print(f"PETase values files found: {len(petase_files)}")

    petase_docs: list[dict[str, Any]] = []
    for values_path in petase_files:
        gt = json.loads(values_path.read_text(encoding="utf-8"))
        entry = build_document_entry(gt)
        petase_docs.append(entry)
        stats = entry["ground_truth_stats"]
        print(
            f"  ✓ {entry['document_id']} "
            f"({len(entry['ground_truth_fields'])} fields, "
            f"{stats['total_required_fields']}R/{stats['total_recommended_fields']}O)"
        )

    master["documents"] = non_petase + petase_docs
    FILTERED_PATH.write_text(json.dumps(master, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone. Total documents: {len(master['documents'])} (PETase: {len(petase_docs)})")


if __name__ == "__main__":
    main()
