"""
Layer 2 — Value accuracy evaluator (semantic + rule-based graded scoring).

Compares extracted field *values* against per-document values-level ground
truth (``evaluation/datasets/annotated/values/ground_truth_{doc}_values.json``).

Headline metric: ``value_mean_score`` = mean continuous match score, where each
field score fuses type-aware rules with sentence-transformer semantic judgment
(see ``evaluation/evaluators/_value_matching.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    _SCIPY = True
except ImportError:  # pragma: no cover
    _SCIPY = False

from fairifier.output_paths import resolve_metadata_output_read_path

from ._value_matching import (
    classify_match_type,
    classify_status,
    normalise_field_name,
    score_value_pair,
    semantic_similarity_available,
)


class ValueAccuracyEvaluator:
    """Layer 2 value-vs-GT accuracy with explicit semantic scoring."""

    def __init__(self, match_type_overrides: Optional[Dict[str, str]] = None):
        self.global_overrides = {
            normalise_field_name(k): v for k, v in (match_type_overrides or {}).items()
        }

    @staticmethod
    def load_gt_sheets(
        gt_values_doc: Dict[str, Any],
    ) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, Dict[str, str]]]:
        sheets: Dict[str, List[Dict[str, str]]] = {}
        overrides: Dict[str, Dict[str, str]] = {}
        for sheet_name, sheet_data in gt_values_doc.get("isa_sheets", {}).items():
            rows = sheet_data.get("expected_rows", [])
            cleaned: List[Dict[str, str]] = []
            for row in rows:
                clean = {
                    k: str(v).strip()
                    for k, v in row.items()
                    if k != "_evidence" and str(v).strip()
                }
                if clean:
                    cleaned.append(clean)
            if cleaned:
                sheets[sheet_name] = cleaned
            sheet_overrides = sheet_data.get("match_type_overrides", {})
            if sheet_overrides:
                overrides[sheet_name] = {
                    normalise_field_name(k): v for k, v in sheet_overrides.items()
                }
        return sheets, overrides

    @staticmethod
    def load_pred_sheets_from_run(run_dir: Path) -> Dict[str, List[Dict[str, str]]]:
        from evaluation.scripts.compare_values_against_gt import load_run_sheets

        return load_run_sheets(run_dir)

    @staticmethod
    def load_pred_sheets_from_metadata(meta: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
        from evaluation.scripts.compare_values_against_gt import load_run_sheets

        # load_run_sheets expects a directory; reuse matrix parsing via temp path pattern
        # by inlining minimal path: write is overkill — import private helper instead
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "metadata.json"
            p.write_text(json.dumps(meta), encoding="utf-8")
            isa_path = Path(tmp) / "isa_values_json.json"
            if meta.get("isa_values"):
                isa_path.write_text(json.dumps(meta["isa_values"]), encoding="utf-8")
            return load_run_sheets(Path(tmp))

    def _match_type_for(self, field: str, sheet_overrides: Optional[Dict[str, str]]) -> str:
        key = normalise_field_name(field)
        if sheet_overrides and key in sheet_overrides:
            return sheet_overrides[key]
        if key in self.global_overrides:
            return self.global_overrides[key]
        return classify_match_type(field)

    def _row_similarity(
        self,
        gt_row: Dict[str, str],
        pred_row: Dict[str, str],
        sheet_overrides: Optional[Dict[str, str]],
    ) -> float:
        if not gt_row:
            return 0.0
        total = 0.0
        for field, gt_val in gt_row.items():
            pred_val = pred_row.get(field) or pred_row.get(normalise_field_name(field), "")
            mt = self._match_type_for(field, sheet_overrides)
            total += score_value_pair(pred_val, gt_val, match_type=mt, field_name=field).score
        return total / len(gt_row)

    def align_rows(
        self,
        gt_rows: List[Dict[str, str]],
        pred_rows: List[Dict[str, str]],
        sheet_overrides: Optional[Dict[str, str]] = None,
    ) -> List[Tuple[Dict[str, str], Optional[Dict[str, str]]]]:
        if not pred_rows:
            return [(r, None) for r in gt_rows]
        n, m = len(gt_rows), len(pred_rows)

        if _SCIPY:
            cost = np.zeros((n, m))
            for i, gr in enumerate(gt_rows):
                for j, pr in enumerate(pred_rows):
                    cost[i, j] = -self._row_similarity(gr, pr, sheet_overrides)
            row_ind, col_ind = linear_sum_assignment(cost)
            matched = dict(zip(row_ind.tolist(), col_ind.tolist()))
        else:
            matched = {}
            used: set = set()
            for i, gr in enumerate(gt_rows):
                best_j, best_s = -1, -1.0
                for j, pr in enumerate(pred_rows):
                    if j in used:
                        continue
                    s = self._row_similarity(gr, pr, sheet_overrides)
                    if s > best_s:
                        best_j, best_s = j, s
                if best_j >= 0:
                    matched[i] = best_j
                    used.add(best_j)

        return [
            (gt_rows[i], pred_rows[matched[i]] if i in matched else None)
            for i in range(n)
        ]

    def evaluate_sheet(
        self,
        sheet_name: str,
        gt_rows: List[Dict[str, str]],
        pred_rows: List[Dict[str, str]],
        sheet_overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        pairs = self.align_rows(gt_rows, pred_rows, sheet_overrides)

        total_fields = match_count = partial_count = wrong_count = missing_count = 0
        score_sum = semantic_sum = 0.0
        row_details: List[Dict[str, Any]] = []

        for gt_row, pred_row in pairs:
            fields: List[Dict[str, Any]] = []
            for field, gt_val in gt_row.items():
                if not gt_val:
                    continue
                pred_val = ""
                if pred_row:
                    pred_val = pred_row.get(field) or pred_row.get(normalise_field_name(field), "") or ""

                mt = self._match_type_for(field, sheet_overrides)
                total_fields += 1

                if not pred_val:
                    status = "missing"
                    missing_count += 1
                    detail = score_value_pair("", gt_val, match_type=mt, field_name=field)
                else:
                    detail = score_value_pair(pred_val, gt_val, match_type=mt, field_name=field)
                    status = classify_status(detail.score, mt)
                    if status == "match":
                        match_count += 1
                    elif status == "partial":
                        partial_count += 1
                    else:
                        wrong_count += 1

                score_sum += detail.score
                semantic_sum += detail.semantic_judgment_score

                fields.append({
                    "field": field,
                    "match_type": mt,
                    "status": status,
                    "score": round(detail.score, 3),
                    "semantic_score": detail.semantic_score,
                    "token_f1_score": detail.token_f1_score,
                    "semantic_judgment_score": detail.semantic_judgment_score,
                    "rule_score": detail.rule_score,
                    "gt_snippet": gt_val[:60],
                    "pred_snippet": pred_val[:60] if pred_val else "(not found)",
                })
            row_details.append({"fields": fields})

        n = total_fields
        mean_score = score_sum / n if n else 0.0
        mean_semantic = semantic_sum / n if n else 0.0

        return {
            "sheet": sheet_name,
            "gt_rows": len(gt_rows),
            "pred_rows": len(pred_rows),
            "total_fields": total_fields,
            "match_count": match_count,
            "partial_count": partial_count,
            "wrong_count": wrong_count,
            "missing_count": missing_count,
            "mean_score": round(mean_score, 4),
            "mean_semantic_judgment_score": round(mean_semantic, 4),
            "semantic_similarity_available": semantic_similarity_available(),
            "row_details": row_details,
        }

    def evaluate(
        self,
        fairifier_output: Dict[str, Any],
        ground_truth_values_doc: Dict[str, Any],
        *,
        run_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        gt_sheets, overrides_by_sheet = self.load_gt_sheets(ground_truth_values_doc)
        if run_dir is not None:
            pred_sheets = self.load_pred_sheets_from_run(run_dir)
        else:
            pred_sheets = self.load_pred_sheets_from_metadata(fairifier_output)

        per_sheet: Dict[str, Any] = {}
        for sheet_name, gt_rows in gt_sheets.items():
            pred_rows = pred_sheets.get(sheet_name, [])
            per_sheet[sheet_name] = self.evaluate_sheet(
                sheet_name, gt_rows, pred_rows, overrides_by_sheet.get(sheet_name)
            )

        total_fields = sum(s["total_fields"] for s in per_sheet.values())
        total_match = sum(s["match_count"] for s in per_sheet.values())
        total_partial = sum(s["partial_count"] for s in per_sheet.values())
        total_wrong = sum(s["wrong_count"] for s in per_sheet.values())
        total_missing = sum(s["missing_count"] for s in per_sheet.values())

        mean_score = (
            sum(s["mean_score"] * s["total_fields"] for s in per_sheet.values()) / total_fields
            if total_fields else 0.0
        )
        mean_semantic = (
            sum(s["mean_semantic_judgment_score"] * s["total_fields"] for s in per_sheet.values())
            / total_fields
            if total_fields else 0.0
        )

        return {
            "per_sheet": per_sheet,
            "summary_metrics": {
                "n_gt_populated_fields": total_fields,
                "match_count": total_match,
                "partial_count": total_partial,
                "wrong_count": total_wrong,
                "missing_count": total_missing,
                "value_mean_score": round(mean_score, 4),
                "value_partial_credit_score": round(mean_score, 4),
                "value_match_rate": round(total_match / total_fields, 4) if total_fields else 0.0,
                "mean_semantic_judgment_score": round(mean_semantic, 4),
                "semantic_similarity_available": semantic_similarity_available(),
            },
        }

    def evaluate_run_dir(self, gt_values_path: Path, run_dir: Path) -> Dict[str, Any]:
        import json

        with open(gt_values_path, encoding="utf-8") as f:
            gt_doc = json.load(f)
        meta_path = resolve_metadata_output_read_path(run_dir)
        if meta_path is None:
            raise FileNotFoundError(f"metadata not found in {run_dir}")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        return self.evaluate(meta, gt_doc, run_dir=run_dir)
