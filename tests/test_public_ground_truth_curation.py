from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from evaluation.benchmark.ground_truth_curation import (
    EXCLUDED_DATASETS,
    PROJECT_ROOT,
    curate_document,
    validate_document,
)


def _fixture_document(document_id: str = "example") -> dict:
    return {
        "document_id": document_id,
        "document_source": "source.pdf",
        "isa_sheets": {
            "investigation": {
                "multi_row": False,
                "expected_rows": [{"investigation identifier": "inv", "investigation title": "Source title"}],
            },
            "study": {
                "multi_row": False,
                "expected_rows": [{"study identifier": "study", "investigation identifier": "inv"}],
            },
            "observationunit": {
                "multi_row": True,
                "expected_rows": [{"observation unit identifier": "", "observation unit name": "treated maize"}],
            },
            "sample": {
                "multi_row": True,
                "expected_rows": [{"sample identifier": "", "sample name": "treated maize", "collection date": "Not specified in paper"}],
            },
            "assay": {
                "multi_row": True,
                "expected_rows": [{"assay identifier": "", "assay description": "treated maize assay", "_evidence": "line 2"}],
            },
        },
    }


def test_curator_removes_placeholders_and_builds_resolvable_links(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("evaluation.benchmark.ground_truth_curation._source_assets", lambda _: [{"path": "source.pdf", "role": "primary_source", "sha256": "a" * 64}])
    curated = curate_document(_fixture_document())

    assert curated["schema_profile"]["field_policy"] == "source_reported_fields_only"
    assert "collection date" not in curated["isa_sheets"]["sample"]["expected_rows"][0]
    assert "_evidence" not in curated["isa_sheets"]["assay"]["expected_rows"][0]
    assert curated["isa_sheets"]["sample"]["expected_rows"][0]["observation unit identifier"]
    assert curated["isa_sheets"]["assay"]["expected_rows"][0]["sample identifier"]
    assert validate_document(curated) == []


@pytest.mark.parametrize("document_id", sorted(EXCLUDED_DATASETS))
def test_curator_refuses_excluded_datasets(document_id: str) -> None:
    with pytest.raises(ValueError, match="Excluded dataset"):
        curate_document(_fixture_document(document_id))


def test_current_public_collection_has_27_non_secret_documents() -> None:
    collection_path = PROJECT_ROOT / "evaluation/datasets/annotated/ground_truth_public_curated.json"
    if not collection_path.exists():
        pytest.skip("local ignored evaluation dataset is not installed")
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    ids = {document["document_id"] for document in collection["documents"]}
    assert collection["document_count"] == len(ids) == 27
    assert not ids.intersection(EXCLUDED_DATASETS)
    assert sum(document_id.startswith("petase_") for document_id in ids) == 19


def test_current_public_values_validate_and_have_no_placeholders() -> None:
    collection_path = PROJECT_ROOT / "evaluation/datasets/annotated/ground_truth_public_curated.json"
    if not collection_path.exists():
        pytest.skip("local ignored evaluation dataset is not installed")
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    schema = json.loads((PROJECT_ROOT / "evaluation/schemas/ground_truth_values.schema.json").read_text(encoding="utf-8"))
    schema_validator = Draft202012Validator(schema)
    issues = []
    for entry in collection["documents"]:
        values_path = PROJECT_ROOT / entry["ground_truth_values_path"]
        document = json.loads(values_path.read_text(encoding="utf-8"))
        issues.extend(validate_document(document))
        issues.extend(error.message for error in schema_validator.iter_errors(document))
    assert issues == []


def test_earthworm_publication_is_verified_and_biosensor_doi_is_not_invented() -> None:
    values_dir = PROJECT_ROOT / "evaluation/datasets/annotated/values"
    if not values_dir.exists():
        pytest.skip("local ignored evaluation dataset is not installed")
    earthworm = json.loads((values_dir / "ground_truth_earthworm_values.json").read_text(encoding="utf-8"))
    biosensor = json.loads((values_dir / "ground_truth_biosensor_values.json").read_text(encoding="utf-8"))
    assert earthworm["publication"]["doi"] == "10.1101/2025.06.16.660036"
    assert {row["ncbi taxonomy id"] for row in earthworm["isa_sheets"]["sample"]["expected_rows"]} == {"6396"}
    assert all("observation unit identifier" not in row for row in earthworm["isa_sheets"]["assay"]["expected_rows"])
    assert biosensor["publication"]["doi_status"] == "not_present_in_source"
    assert "doi" not in biosensor["publication"]
    unsupported = {"biosafety level", "geographic location (country and/or sea)", "broad-scale environmental context", "local environmental context", "environmental medium"}
    assert all(not unsupported.intersection(row) for row in biosensor["isa_sheets"]["sample"]["expected_rows"])
