#!/usr/bin/env python3
"""Curate all public GT values and build the canonical public benchmark index."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evaluation.benchmark.ground_truth_curation import (
    ANNOTATED_DIR,
    PROJECT_ROOT,
    curate_document,
    load_publication_cache,
    public_value_paths,
    validate_document,
)


COLLECTION_PATH = ANNOTATED_DIR / "ground_truth_public_curated.json"
PROFILE_PATH = ANNOTATED_DIR / "public_schema_profile.json"


def _profile(documents: list[dict[str, Any]]) -> dict[str, Any]:
    fields: dict[str, Counter[str]] = defaultdict(Counter)
    extensions: Counter[str] = Counter()
    extension_fields: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for document in documents:
        for extension in document["schema_profile"]["extensions"]:
            extensions[extension] += 1
        for sheet_name, sheet in document["isa_sheets"].items():
            observed = {key for row in sheet.get("expected_rows", []) for key in row if not key.startswith("_")}
            fields[sheet_name].update(observed)
            for extension in document["schema_profile"]["extensions"]:
                extension_fields[extension][sheet_name].update(observed)
    count = len(documents)
    profile = {
        "schema_version": "fairiagent.public_schema_profile.v1",
        "description": "Observed, source-backed project metadata architecture; frequencies are descriptive and do not create required fields.",
        "document_count": count,
        "core_policy": {
            "structural_required": ["document_id", "source_assets", "isa_sheets", "unique row identifiers", "resolvable declared references"],
            "domain_field_policy": "optional unless explicitly reported in the source GT",
            "missing_value_policy": "omit; never use placeholder strings",
        },
        "extensions": dict(sorted(extensions.items())),
        "observed_fields": {
            sheet: [
                {"field_name": name, "document_frequency": frequency, "coverage": round(frequency / count, 3)}
                for name, frequency in sorted(counter.items())
            ]
            for sheet, counter in sorted(fields.items())
        },
        "extension_profiles": {
            extension: {
                "document_count": extensions[extension],
                "observed_fields": {
                    sheet: [
                        {
                            "field_name": name,
                            "document_frequency": frequency,
                            "coverage_within_extension": round(frequency / extensions[extension], 3),
                        }
                        for name, frequency in sorted(counter.items())
                    ]
                    for sheet, counter in sorted(sheet_fields.items())
                },
            }
            for extension, sheet_fields in sorted(extension_fields.items())
        },
    }
    package_path = PROJECT_ROOT / "evaluation/config/packages/petase_enzyme_engineering_package.json"
    if package_path.exists():
        package = json.loads(package_path.read_text(encoding="utf-8"))
        petase_documents = [document for document in documents if document["document_id"].startswith("petase_")]
        observed_counts: Counter[str] = Counter()
        observed_sheets: dict[str, set[str]] = defaultdict(set)
        for document in petase_documents:
            per_document = set()
            for sheet_name, sheet in document["isa_sheets"].items():
                for row in sheet.get("expected_rows", []):
                    for field_name in row:
                        if not field_name.startswith("_"):
                            per_document.add(field_name.casefold())
                            observed_sheets[field_name.casefold()].add(sheet_name)
            observed_counts.update(per_document)
        package_labels = {item["label"].casefold() for item in package.get("metadata", [])}
        profile["petase_package_alignment"] = {
            "package_name": package.get("packageName"),
            "package_field_count": len(package.get("metadata", [])),
            "policy": "Package fields define a vocabulary, not a requirement. A field is scored only when present in a document's source-backed GT.",
            "package_fields": [
                {
                    "field_name": item["label"],
                    "declared_sheet": item.get("sheetName"),
                    "package_requirement": item.get("requirement"),
                    "reported_document_count": observed_counts[item["label"].casefold()],
                    "observed_status": "reported_in_gt" if observed_counts[item["label"].casefold()] else "not_reported_in_current_gt",
                }
                for item in package.get("metadata", [])
            ],
            "gt_fields_outside_package": [
                {
                    "field_name": field_name,
                    "observed_sheets": sorted(observed_sheets[field_name]),
                    "reported_document_count": observed_counts[field_name],
                    "classification": "linked_isa_core_or_source_specific_extension",
                }
                for field_name in sorted(observed_counts)
                if field_name not in package_labels
            ],
        }
    return profile


def _document_entry(document: dict[str, Any], values_path: Path) -> dict[str, Any]:
    field_count = sum(
        len({key for row in sheet.get("expected_rows", []) for key in row if not key.startswith("_")})
        for sheet in document["isa_sheets"].values()
    )
    primary = next((asset["path"] for asset in document["source_assets"] if asset["role"] == "primary_source"), document["document_source"])
    return {
        "document_id": document["document_id"],
        "document_path": primary,
        "ground_truth_values_path": str(values_path.relative_to(PROJECT_ROOT)),
        "metadata": {
            "publication": document.get("publication", {}),
            "schema_extensions": document["schema_profile"]["extensions"],
            "annotation_policy": "source_reported_fields_only",
        },
        "ground_truth_stats": {"observed_field_count": field_count},
    }


def main() -> None:
    cache = load_publication_cache()
    documents = []
    entries = []
    issues = []
    for path in public_value_paths():
        original = json.loads(path.read_text(encoding="utf-8"))
        curated = curate_document(original, cache)
        path.write_text(json.dumps(curated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        documents.append(curated)
        entries.append(_document_entry(curated, path))
        issues.extend(validate_document(curated))
        print(f"curated {curated['document_id']}")

    if issues:
        raise SystemExit("GT validation failed:\n- " + "\n- ".join(issues))
    collection = {
        "schema_version": "fairiagent.ground_truth_collection.v3",
        "dataset_id": "public_curated",
        "description": "Public source-grounded GT; excludes biorem, pomato, and compbiobench.",
        "exclusions": ["biorem", "pomato", "compbiobench"],
        "document_count": len(entries),
        "documents": entries,
    }
    COLLECTION_PATH.write_text(json.dumps(collection, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    PROFILE_PATH.write_text(json.dumps(_profile(documents), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {COLLECTION_PATH.relative_to(PROJECT_ROOT)} ({len(entries)} documents)")
    print(f"wrote {PROFILE_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
