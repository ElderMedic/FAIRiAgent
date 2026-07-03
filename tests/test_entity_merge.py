"""Tests for sparse ISA entity row merging."""

from fairifier.utils.entity_merge import merge_sparse_entity_rows


def test_merge_disjoint_sparse_rows_into_one():
    matrix = {
        "sample": {
            "columns": ["sample identifier", "reaction temperature", "reaction ph"],
            "rows": [
                {"sample identifier": "ENZ_A", "reaction temperature": "", "reaction ph": ""},
                {"sample identifier": "", "reaction temperature": "30 °C", "reaction ph": ""},
                {"sample identifier": "", "reaction temperature": "", "reaction ph": "8.0"},
            ],
        }
    }
    merged = merge_sparse_entity_rows(matrix)
    assert len(merged["sample"]["rows"]) == 1
    row = merged["sample"]["rows"][0]
    assert row["sample identifier"] == "ENZ_A"
    assert "30" in row["reaction temperature"]
    assert row["reaction ph"] == "8.0"


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


def test_merge_by_matching_identifier():
    matrix = {
        "sample": {
            "columns": ["sample identifier", "assembly software"],
            "rows": [
                {"sample identifier": "ZYMO_EVEN", "assembly software": ""},
                {"sample identifier": "", "assembly software": "Flye; Medaka"},
            ],
        }
    }
    merged = merge_sparse_entity_rows(matrix)
    assert len(merged["sample"]["rows"]) == 1
    assert merged["sample"]["rows"][0]["sample identifier"] == "ZYMO_EVEN"
    assert merged["sample"]["rows"][0]["assembly software"] == "Flye; Medaka"
