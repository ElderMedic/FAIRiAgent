"""Tests for ISA entity row merging under §12.1 identity rules."""

from fairifier.utils.entity_merge import (
    collapse_rows_sharing_identifier,
    merge_sparse_entity_rows,
    postprocess_entity_matrix,
)


def test_merge_does_not_combine_conflicting_rows():
    matrix = {
        "sample": {
            "columns": ["sample identifier", "reaction temperature"],
            "rows": [
                {"sample identifier": "ENZ_A", "reaction temperature": "30 °C"},
                {"sample identifier": "ENZ_B", "reaction temperature": "50 °C"},
            ],
        }
    }
    merged = merge_sparse_entity_rows(matrix)
    assert len(merged["sample"]["rows"]) == 2


def test_merge_by_exact_matching_identifier():
    matrix = {
        "sample": {
            "columns": ["sample identifier", "assembly software"],
            "rows": [
                {"sample identifier": "ZYMO_EVEN", "assembly software": ""},
                {"sample identifier": "ZYMO_EVEN", "assembly software": "Flye; Medaka"},
            ],
        }
    }
    merged = merge_sparse_entity_rows(matrix)
    assert len(merged["sample"]["rows"]) == 1
    assert merged["sample"]["rows"][0]["sample identifier"] == "ZYMO_EVEN"
    assert merged["sample"]["rows"][0]["assembly software"] == "Flye; Medaka"


def test_merge_folds_fragmented_study_rows_with_same_identifier():
    """Reproduces an observed regression: JSONGenerator assigns distinct
    entity_ids per field batch for the study sheet, leaving many near-empty
    duplicate rows that all carry the *same* study identifier."""
    matrix = {
        "study": {
            "columns": ["study identifier", "study title", "study design"],
            "rows": [
                {
                    "study identifier": "pea_cold_mirna_mrna",
                    "study title": "Cold response time series in Pisum sativum",
                    "study design": "",
                },
                {"study identifier": "pea_cold_mirna_mrna", "study design": ""},
                {"study identifier": "pea_cold_mirna_mrna", "study design": ""},
                {
                    "study identifier": "pea_cold_mirna_mrna",
                    "study design": "time series design",
                },
            ],
        }
    }
    merged = merge_sparse_entity_rows(matrix)
    assert len(merged["study"]["rows"]) == 1
    row = merged["study"]["rows"][0]
    assert row["study identifier"] == "pea_cold_mirna_mrna"
    assert row["study title"] == "Cold response time series in Pisum sativum"
    assert row["study design"] == "time series design"


def test_merge_does_not_collapse_genuinely_distinct_studies():
    matrix = {
        "study": {
            "columns": ["study identifier", "study title"],
            "rows": [
                {"study identifier": "ZYMO_PRJEB29504", "study title": "UNmOCK_ZYMO"},
                {"study identifier": "BMOCK12_PRJNA496047", "study title": "UNmOCK_BMOCK12"},
            ],
        }
    }
    merged = merge_sparse_entity_rows(matrix)
    assert len(merged["study"]["rows"]) == 2


def test_collapse_rows_sharing_identifier_merges_duplicate_sample_ids():
    """Biosensor-style duplication: dense row + identifier-only row for the
    same sample identifier from different entity_id batches."""
    matrix = {
        "sample": {
            "columns": ["sample identifier", "sample name", "collection date"],
            "rows": [
                {
                    "sample identifier": "REP_01",
                    "sample name": "Replicate 1",
                    "collection date": "2024-01-01",
                },
                {"sample identifier": "REP_01"},
                {
                    "sample identifier": "REP_02",
                    "sample name": "Replicate 2",
                },
                {"sample identifier": "REP_02"},
            ],
        }
    }
    collapsed = collapse_rows_sharing_identifier(matrix)
    assert len(collapsed["sample"]["rows"]) == 2
    by_id = {r["sample identifier"]: r for r in collapsed["sample"]["rows"]}
    assert by_id["REP_01"]["collection date"] == "2024-01-01"
    assert by_id["REP_02"]["sample name"] == "Replicate 2"


def test_postprocess_entity_matrix_collapses_exact_ids_keeps_unkeyed():
    matrix = {
        "observationunit": {
            "columns": ["observation unit identifier", "organism"],
            "rows": [
                {"observation unit identifier": "OU_A", "organism": ""},
                {"observation unit identifier": "OU_A", "organism": "E. coli"},
                {"observation unit identifier": "", "organism": "B. subtilis"},
            ],
        }
    }
    result = postprocess_entity_matrix(matrix)
    assert len(result["observationunit"]["rows"]) == 2
    ou_a = next(
        r for r in result["observationunit"]["rows"] if r.get("observation unit identifier") == "OU_A"
    )
    assert ou_a["organism"] == "E. coli"
