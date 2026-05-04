"""Unit tests for evaluation/scripts/compare_values_against_gt.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from evaluation.scripts.compare_values_against_gt import (
    _normalize,
    token_f1,
    align_rows,
    evaluate_sheet,
    load_gt_sheets,
    load_run_sheets,
)


# ── token_f1 ──────────────────────────────────────────────────────────────────

class TestTokenF1:
    def test_exact_match(self):
        _, _, f1 = token_f1("Eisenia fetida", "Eisenia fetida")
        assert f1 == 1.0

    def test_case_insensitive(self):
        _, _, f1 = token_f1("eisenia fetida", "Eisenia fetida")
        assert f1 == 1.0

    def test_punctuation_ignored(self):
        _, _, f1 = token_f1("Poly(A) enrichment", "poly(a) enrichment")
        assert f1 == 1.0

    def test_partial_overlap(self):
        _, _, f1 = token_f1("RNA-Seq library preparation", "RNA-Seq")
        assert 0 < f1 < 1

    def test_no_overlap(self):
        _, _, f1 = token_f1("ZnO nanomaterial", "PCR amplification")
        assert f1 == 0.0

    def test_empty_pred(self):
        _, _, f1 = token_f1("", "Eisenia fetida")
        assert f1 == 0.0

    def test_empty_gt(self):
        # Empty GT → trivially matched (nothing to compare)
        _, _, f1 = token_f1("something", "")
        assert f1 == 0.0

    def test_stopwords_filtered(self):
        # "The Netherlands" → filtered to "netherlands" only
        _, _, f1 = token_f1("The Netherlands", "Netherlands")
        assert f1 == 1.0

    def test_ncbi_taxid_exact(self):
        _, _, f1 = token_f1("1510822", "1510822")
        assert f1 == 1.0

    def test_ncbi_taxid_wrong(self):
        _, _, f1 = token_f1("6791", "1510822")
        assert f1 == 0.0


# ── align_rows ────────────────────────────────────────────────────────────────

class TestAlignRows:
    def test_single_gt_single_pred(self):
        gt = [{"name": "Alice"}]
        pred = [{"name": "Alice"}]
        pairs = align_rows(gt, pred)
        assert len(pairs) == 1
        assert pairs[0][1] == {"name": "Alice"}

    def test_multiple_gt_no_pred(self):
        gt = [{"name": "A"}, {"name": "B"}]
        pairs = align_rows(gt, [])
        assert all(p[1] is None for p in pairs)

    def test_best_match_alignment(self):
        # GT row 0 should match pred row 1 (better overlap)
        gt = [{"species": "Eisenia fetida"}, {"species": "Arabidopsis thaliana"}]
        pred = [{"species": "Arabidopsis thaliana"}, {"species": "Eisenia fetida"}]
        pairs = align_rows(gt, pred)
        # After alignment, each GT row should be paired with its best match
        matched = {i: pairs[i][1]["species"] for i in range(2) if pairs[i][1]}
        assert matched[0] == "Eisenia fetida"
        assert matched[1] == "Arabidopsis thaliana"

    def test_fewer_pred_than_gt(self):
        gt = [{"a": "1"}, {"a": "2"}, {"a": "3"}]
        pred = [{"a": "2"}]
        pairs = align_rows(gt, pred)
        assert len(pairs) == 3
        # At most one pair should have a non-None pred
        non_none = [p for p in pairs if p[1] is not None]
        assert len(non_none) <= 1


# ── evaluate_sheet ────────────────────────────────────────────────────────────

class TestEvaluateSheet:
    def test_perfect_match(self):
        gt   = [{"species": "Eisenia fetida", "country": "Netherlands"}]
        pred = [{"species": "Eisenia fetida", "country": "Netherlands"}]
        r = evaluate_sheet("sample", gt, pred)
        assert r["match_count"] == 2
        assert r["miss_count"] == 0
        assert r["mean_score"] == 1.0

    def test_missing_field(self):
        gt   = [{"species": "Eisenia fetida", "email": "user@example.com"}]
        pred = [{"species": "Eisenia fetida"}]
        r = evaluate_sheet("investigation", gt, pred)
        assert r["match_count"] == 1
        assert r["missing_name_count"] == 1

    def test_empty_pred_sheet(self):
        gt   = [{"species": "Eisenia fetida"}]
        r = evaluate_sheet("sample", gt, [])
        assert r["miss_count"] == 1
        assert r["mean_score"] == 0.0

    def test_field_coverage(self):
        # All field names present → coverage = 100%
        gt   = [{"name": "A", "desc": "B"}]
        pred = [{"name": "X", "desc": "Y"}]  # names present but values wrong
        r = evaluate_sheet("study", gt, pred)
        assert r["field_coverage"] == 1.0

    def test_partial_match_counted(self):
        gt   = [{"desc": "RNA-seq of earthworm tissue from experiment 1 control"}]
        pred = [{"desc": "RNA-seq of earthworm tissue"}]
        r = evaluate_sheet("assay", gt, pred)
        # Should be a partial match (some overlap but not >= 0.5)
        assert r["match_count"] + r["partial_count"] >= 1


# ── load_run_sheets ───────────────────────────────────────────────────────────

class TestLoadRunSheets:
    def test_columns_rows_format(self, tmp_path):
        meta = {
            "isa_values": {
                "investigation": {
                    "columns": ["investigation title", "firstname"],
                    "rows": [["My Study", "Alice"]],
                }
            }
        }
        (tmp_path / "metadata.json").write_text(
            __import__("json").dumps(meta), encoding="utf-8"
        )
        sheets = load_run_sheets(tmp_path)
        assert "investigation" in sheets
        row = sheets["investigation"][0]
        assert row.get("investigation title") == "My Study"
        assert row.get("firstname") == "Alice"

    def test_metadata_fields_fallback(self, tmp_path):
        meta = {
            "metadata_fields": [
                {"field_name": "species", "value": "Earthworm", "isa_sheet": "sample"},
            ]
        }
        (tmp_path / "metadata.json").write_text(
            __import__("json").dumps(meta), encoding="utf-8"
        )
        sheets = load_run_sheets(tmp_path)
        assert "sample" in sheets
        assert sheets["sample"][0].get("species") == "Earthworm"

    def test_missing_metadata_raises(self, tmp_path):
        import pytest
        with pytest.raises(FileNotFoundError):
            load_run_sheets(tmp_path)
