#!/usr/bin/env python3
"""Create a machine-readable quality and usability audit for public GT."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date

from evaluation.benchmark.ground_truth_curation import PROJECT_ROOT, validate_document


COLLECTION = PROJECT_ROOT / "evaluation/datasets/annotated/ground_truth_public_curated.json"
PROFILE = PROJECT_ROOT / "evaluation/datasets/annotated/public_schema_profile.json"
REPORT = PROJECT_ROOT / "evaluation/reports/public_ground_truth_quality_report.json"


def main() -> None:
    collection = json.loads(COLLECTION.read_text(encoding="utf-8"))
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    documents = []
    all_issues = []
    totals: Counter[str] = Counter()
    for entry in collection["documents"]:
        values_path = PROJECT_ROOT / entry["ground_truth_values_path"]
        document = json.loads(values_path.read_text(encoding="utf-8"))
        issues = validate_document(document)
        all_issues.extend(issues)
        rows = {name: len(sheet.get("expected_rows", [])) for name, sheet in document["isa_sheets"].items()}
        fields = {
            name: len({key for row in sheet.get("expected_rows", []) for key in row if not key.startswith("_")})
            for name, sheet in document["isa_sheets"].items()
        }
        totals.update({f"rows_{key}": value for key, value in rows.items()})
        documents.append(
            {
                "document_id": document["document_id"],
                "publication_status": "doi_verified" if document.get("publication", {}).get("doi") else document.get("publication", {}).get("doi_status", "source_without_doi"),
                "source_asset_count": len(document["source_assets"]),
                "row_counts": rows,
                "observed_field_counts": fields,
                "schema_extensions": document["schema_profile"]["extensions"],
                "structural_issues": issues,
            }
        )

    alignment = profile["petase_package_alignment"]
    report = {
        "report_date": date.today().isoformat(),
        "collection": str(COLLECTION.relative_to(PROJECT_ROOT)),
        "document_count": len(documents),
        "excluded_and_untouched": collection["exclusions"],
        "quality_summary": {
            "schema_conformant_documents": len(documents) if not all_issues else len(documents) - len({issue.split('/')[0] for issue in all_issues}),
            "structural_issue_count": len(all_issues),
            "placeholder_policy": "omit; no placeholder labels",
            "relationship_policy": "declared links must resolve; uncertain links omitted",
            "publication_doi_verified": sum(item["publication_status"] == "doi_verified" for item in documents),
            "publication_without_source_doi": sum(item["publication_status"] != "doi_verified" for item in documents),
            "total_rows_by_sheet": dict(sorted(totals.items())),
        },
        "petase_package_alignment": {
            "package_field_count": alignment["package_field_count"],
            "reported_package_fields": sum(item["reported_document_count"] > 0 for item in alignment["package_fields"]),
            "currently_unreported_package_fields": sum(item["reported_document_count"] == 0 for item in alignment["package_fields"]),
            "gt_fields_outside_package": len(alignment["gt_fields_outside_package"]),
            "interpretation": alignment["policy"],
        },
        "usability": {
            "value_level_evaluation": "ready",
            "schema_extraction": "ready; use public_schema_profile.json as descriptive vocabulary, not a global required-field list",
            "release_benchmark": "conditional: split assignment and independent second-curator sampling remain human checkpoints",
            "known_limitations": [
                "Biosensor is a manuscript with no DOI present in the source.",
                "Annotation review status records a structural/source-grounding pass, not independent inter-annotator agreement.",
                "Fields absent from a paper cannot be interpreted as biologically not applicable without a second domain review.",
            ],
        },
        "documents": documents,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report["quality_summary"], indent=2, ensure_ascii=False))
    print(f"wrote {REPORT.relative_to(PROJECT_ROOT)}")
    if all_issues:
        raise SystemExit("quality audit failed with structural issues")


if __name__ == "__main__":
    main()
