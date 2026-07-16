"""§12.1 entity identity: exact normalized IDs only; no sparse-only merges."""

from fairifier.utils.entity_merge import (
    collapse_rows_sharing_identifier,
    merge_sparse_entity_rows,
    normalize_identifier,
    postprocess_entity_matrix,
)
from fairifier.utils.isa_matrix_compiler import compile_isa_matrix, matrix_id_for


def test_normalize_identifier_is_conservative_nfkc_casefold():
    assert normalize_identifier("  REP_01  ") == normalize_identifier("rep_01")
    # Punctuation / hyphens / underscores are retained (collision-safe).
    assert normalize_identifier("REP-01") != normalize_identifier("REP_01")
    assert normalize_identifier("REP.01") != normalize_identifier("REP01")


def test_collapse_requires_exact_normalized_identifier_not_substring():
    matrix = {
        "sample": {
            "columns": ["sample identifier", "sample name"],
            "rows": [
                {"sample identifier": "REP_01", "sample name": "A"},
                {"sample identifier": "REP_01_batch", "sample name": "B"},
                {"sample identifier": "REP_01", "sample name": ""},
            ],
        }
    }
    collapsed = collapse_rows_sharing_identifier(matrix)
    assert len(collapsed["sample"]["rows"]) == 2
    ids = {r["sample identifier"] for r in collapsed["sample"]["rows"]}
    assert "REP_01" in ids
    assert "REP_01_batch" in ids


def test_identifier_less_fragments_do_not_merge_on_sparseness_alone():
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
    assert len(merged["sample"]["rows"]) == 3


def test_compile_isa_matrix_is_deterministic_and_stable():
    matrix = {
        "sample": {
            "columns": ["sample identifier", "sample name"],
            "rows": [
                {"sample identifier": "REP_01", "sample name": "A"},
                {"sample identifier": "REP_01", "sample name": ""},
                {"sample identifier": "REP_02", "sample name": "B"},
            ],
        }
    }
    compiled_a = compile_isa_matrix(matrix)
    compiled_b = compile_isa_matrix(matrix)
    assert compiled_a["matrix_id"] == compiled_b["matrix_id"]
    assert compiled_a["matrix_id"] == matrix_id_for(compiled_a["matrix"])
    assert len(compiled_a["matrix"]["sample"]["rows"]) == 2
    # Idempotent: compiling twice does not change matrix_id.
    again = compile_isa_matrix(compiled_a["matrix"])
    assert again["matrix_id"] == compiled_a["matrix_id"]


def test_postprocess_matches_compiler_matrix():
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
    post = postprocess_entity_matrix(matrix)
    compiled = compile_isa_matrix(matrix)["matrix"]
    assert post == compiled
    assert len(compiled["observationunit"]["rows"]) == 2
