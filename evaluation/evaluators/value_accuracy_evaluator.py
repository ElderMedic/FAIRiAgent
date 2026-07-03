"""
Layer 2 - Value Accuracy Evaluator for FAIRiAgent outputs.

Promotes the value-comparison logic that used to live only in the
disconnected ``evaluation/scripts/compare_values_against_gt.py`` CLI script
into a first-class, batch-pipeline evaluator.

Unlike ``CorrectnessEvaluator`` (Layer 1), which only checks whether a field
*name* was extracted, this evaluator checks whether the extracted *value* is
actually correct against ground truth, using type-aware matching
(``exact`` / ``numeric_tolerance`` / ``categorical`` / ``semantic`` -- see
``_value_matching.classify_match_type``).

Ground truth format
--------------------
Expects the per-document *value* ground truth
(``evaluation/datasets/annotated/values/ground_truth_{doc}_values.json``),
not the field-*presence* ground truth used by Layer 1
(``ground_truth_filtered.json``). Example shape::

    {
      "document_id": "earthworm",
      "isa_sheets": {
        "sample": {
          "multi_row": true,
          "expected_rows": [
            {"sample name": "...", "scientific name": "Eisenia fetida", "_evidence": "..."},
            ...
          ],
          "match_type_overrides": {"ncbi taxonomy id": "exact"}   # optional
        }
      }
    }

Row handling
------------
For multi-row sheets, GT rows are aligned to predicted rows via the
Hungarian algorithm (best global 1:1 assignment by mean per-field match
score) purely so that value accuracy isn't penalised by row-order
differences. This evaluator does *not* report alignment quality itself --
that's ``StructuralEvaluator`` (Layer 3), which reuses the same alignment
but reports it as a first-class ``row_alignment_f1`` metric and recomputes
value accuracy specifically within matched pairs
(``value_accuracy_given_correct_structure``).

Baseline-schema adapter
------------------------
Baseline single-prompt outputs (``evaluation/scripts/baseline_single_prompt.py``)
are flat, non-ISA JSON (e.g. ``{"investigation": {...}, "samples": [...]}``)
rather than ``isa_structure``. ``adapter="auto"`` (the default) detects this
and uses ``FLAT_SHEET_ALIASES`` to map baseline keys onto ISA sheet names so
both agentic and baseline outputs can be scored with the same metric.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    _SCIPY = True
except ImportError:  # pragma: no cover - scipy optional
    _SCIPY = False

from ._value_matching import (
    match_value,
    classify_match_type,
    classify_status,
    normalise_field_name,
)

# Maps baseline_single_prompt.py's flat top-level keys onto ISA sheet names.
FLAT_SHEET_ALIASES: Dict[str, str] = {
    "investigation": "investigation",
    "study": "study",
    "studies": "study",
    "sample": "sample",
    "samples": "sample",
    "observationunit": "observationunit",
    "observationunits": "observationunit",
    "assay": "assay",
    "assays": "assay",
    "sequencing_data": "assay",
    "sequencing": "assay",
}

ISA_SHEET_NAMES = {"investigation", "study", "sample", "observationunit", "assay"}


class ValueAccuracyEvaluator:
    """Layer 2: true value-vs-ground-truth accuracy (type-aware)."""

    def __init__(self, match_type_overrides: Optional[Dict[str, str]] = None):
        """
        Args:
            match_type_overrides: global field_name -> match_type overrides
                (lower-cased, normalized field names), applied when the GT
                document itself doesn't specify a per-sheet override.
        """
        self.global_overrides = {
            normalise_field_name(k): v for k, v in (match_type_overrides or {}).items()
        }

    # ------------------------------------------------------------------
    # GT / prediction loaders
    # ------------------------------------------------------------------

    @staticmethod
    def load_gt_sheets(
        gt_values_doc: Dict[str, Any]
    ) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, Dict[str, str]]]:
        """Returns (sheet -> [row_dict, ...], sheet -> {field: match_type override})."""
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
    def detect_adapter(fairifier_output: Dict[str, Any]) -> str:
        if any(k in fairifier_output for k in ("isa_values", "isa_structure", "metadata_fields")):
            return "isa"
        if any(k in fairifier_output for k in FLAT_SHEET_ALIASES):
            return "flat_baseline"
        return "isa"

    @staticmethod
    def load_pred_sheets_isa(fairifier_output: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
        """ISA-structured agentic output: isa_values matrix / isa_structure.fields / metadata_fields."""
        out: Dict[str, List[Dict[str, str]]] = {}

        isa_values = fairifier_output.get("isa_values") or fairifier_output.get("isa_structure", {})
        if isinstance(isa_values, dict):
            for sheet_name, sheet_data in isa_values.items():
                if sheet_name in ("description", "statistics"):
                    continue
                if isinstance(sheet_data, dict) and "columns" in sheet_data and "rows" in sheet_data:
                    cols, rows = sheet_data["columns"], sheet_data["rows"]
                    if isinstance(cols, list) and isinstance(rows, list):
                        built: List[Dict[str, str]] = []
                        for row in rows:
                            if isinstance(row, list):
                                row_dict = {
                                    normalise_field_name(cols[i]): str(row[i]).strip()
                                    for i in range(min(len(cols), len(row)))
                                    if row[i] is not None and str(row[i]).strip()
                                }
                            elif isinstance(row, dict):
                                row_dict = {
                                    normalise_field_name(k): str(v).strip()
                                    for k, v in row.items()
                                    if v is not None and str(v).strip()
                                }
                            else:
                                continue
                            if row_dict:
                                built.append(row_dict)
                        if built:
                            out[sheet_name] = built
                        continue
                if isinstance(sheet_data, dict) and "fields" in sheet_data:
                    row_dict: Dict[str, str] = {}
                    for field in sheet_data["fields"]:
                        if isinstance(field, dict):
                            name = normalise_field_name(field.get("field_name", ""))
                            value = str(field.get("value", "")).strip()
                            if name and value:
                                row_dict[name] = value
                    if row_dict:
                        out[sheet_name] = [row_dict]

        if not out:
            fields = fairifier_output.get("metadata_fields", [])
            if fields:
                by_sheet: Dict[str, Dict[str, str]] = {}
                for field in fields:
                    sheet = field.get("isa_sheet", "unknown")
                    name = normalise_field_name(field.get("field_name", ""))
                    value = str(field.get("value", "")).strip()
                    if name and value:
                        by_sheet.setdefault(sheet, {})[name] = value
                for sheet, row_dict in by_sheet.items():
                    out[sheet] = [row_dict]

        return out

    @staticmethod
    def load_pred_sheets_flat_baseline(data: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
        """Flat non-ISA baseline output -> {sheet: [row_dict, ...]} via FLAT_SHEET_ALIASES."""
        out: Dict[str, List[Dict[str, str]]] = {}
        # Baseline output may itself be wrapped under a top-level "metadata" key.
        root = data.get("metadata", data) if isinstance(data, dict) else {}

        def _flatten_row(obj: Any) -> Dict[str, str]:
            flat: Dict[str, str] = {}
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, (dict, list)):
                        continue  # nested structures handled at sheet level
                    if v is not None and str(v).strip() and str(v).strip().lower() not in ("not specified", "n/a"):
                        flat[normalise_field_name(k)] = str(v).strip()
            return flat

        for key, value in (root or {}).items():
            sheet_name = FLAT_SHEET_ALIASES.get(normalise_field_name(key).replace(" ", "_"))
            if sheet_name is None:
                sheet_name = FLAT_SHEET_ALIASES.get(key.lower())
            if sheet_name is None:
                continue
            if isinstance(value, list):
                rows = [_flatten_row(item) for item in value if isinstance(item, dict)]
                rows = [r for r in rows if r]
                if rows:
                    out.setdefault(sheet_name, []).extend(rows)
            elif isinstance(value, dict):
                row = _flatten_row(value)
                if row:
                    out.setdefault(sheet_name, []).append(row)
        return out

    def load_pred_sheets(
        self, fairifier_output: Dict[str, Any], adapter: str = "auto"
    ) -> Dict[str, List[Dict[str, str]]]:
        if adapter == "auto":
            adapter = self.detect_adapter(fairifier_output)
        if adapter == "flat_baseline":
            return self.load_pred_sheets_flat_baseline(fairifier_output)
        return self.load_pred_sheets_isa(fairifier_output)

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

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
            total += match_value(pred_val, gt_val, match_type=mt)
        return total / len(gt_row)

    def align_rows(
        self,
        gt_rows: List[Dict[str, str]],
        pred_rows: List[Dict[str, str]],
        sheet_overrides: Optional[Dict[str, str]] = None,
    ) -> List[Tuple[Dict[str, str], Optional[Dict[str, str]]]]:
        """Hungarian-algorithm (or greedy fallback) alignment of GT rows to prediction rows."""
        if not pred_rows:
            return [(r, None) for r in gt_rows]
        n, m = len(gt_rows), len(pred_rows)

        if _SCIPY:
            cost = np.zeros((n, m))
            for i, gr in enumerate(gt_rows):
                for j, pr in enumerate(pred_rows):
                    cost[i, j] = -self._row_similarity(gr, pr, sheet_overrides)
            row_ind, col_ind = linear_sum_assignment(cost)
            matched: Dict[int, int] = dict(zip(row_ind.tolist(), col_ind.tolist()))
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

    # ------------------------------------------------------------------
    # Per-sheet / per-document evaluation
    # ------------------------------------------------------------------

    def evaluate_sheet(
        self,
        sheet_name: str,
        gt_rows: List[Dict[str, str]],
        pred_rows: List[Dict[str, str]],
        sheet_overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        pairs = self.align_rows(gt_rows, pred_rows, sheet_overrides)

        total_fields = 0
        match_count = 0
        partial_count = 0
        wrong_count = 0
        missing_count = 0
        score_sum = 0.0
        row_details: List[Dict[str, Any]] = []

        for gt_row, pred_row in pairs:
            fields: List[Dict[str, Any]] = []
            for field, gt_val in gt_row.items():
                if not gt_val:
                    continue
                mt = self._match_type_for(field, sheet_overrides)
                pred_val = ""
                if pred_row:
                    pred_val = pred_row.get(field) or pred_row.get(normalise_field_name(field), "") or ""

                total_fields += 1
                if not pred_val:
                    status = "missing"
                    score = 0.0
                    missing_count += 1
                else:
                    score = match_value(pred_val, gt_val, match_type=mt)
                    status = classify_status(score, mt)
                    if status == "match":
                        match_count += 1
                    elif status == "partial":
                        partial_count += 1
                    else:
                        wrong_count += 1
                score_sum += score

                fields.append({
                    "field": field,
                    "match_type": mt,
                    "status": status,
                    "score": round(score, 3),
                    "gt_snippet": gt_val[:60],
                    "pred_snippet": pred_val[:60] if pred_val else "(not found)",
                })
            row_details.append({"fields": fields})

        n_gt_populated = total_fields
        mean_score = score_sum / total_fields if total_fields else 0.0
        value_match_rate = match_count / n_gt_populated if n_gt_populated else 0.0
        # Continuous partial credit: mean per-field score (not binned 0/0.5/1).
        value_partial_credit_score = mean_score

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
            "value_match_rate": round(value_match_rate, 4),
            "value_partial_credit_score": round(value_partial_credit_score, 4),
            "row_details": row_details,
        }

    def evaluate(
        self,
        fairifier_output: Dict[str, Any],
        ground_truth_values_doc: Dict[str, Any],
        adapter: str = "auto",
    ) -> Dict[str, Any]:
        """
        Evaluate one document's output against its value-level ground truth.

        Returns per-sheet detail plus continuous aggregate:
        ``value_partial_credit_score`` = ``value_mean_score`` = mean per-field
        match score in [0, 1] (graded partial credit, not binned match/wrong).
        ``match_count`` / ``partial_count`` / ``wrong_count`` are diagnostic bins.
        """
        gt_sheets, overrides_by_sheet = self.load_gt_sheets(ground_truth_values_doc)
        pred_sheets = self.load_pred_sheets(fairifier_output, adapter=adapter)

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
        value_match_rate = total_match / total_fields if total_fields else 0.0
        value_partial_credit_score = mean_score

        return {
            "per_sheet": per_sheet,
            "summary_metrics": {
                "n_gt_populated_fields": total_fields,
                "match_count": total_match,
                "partial_count": total_partial,
                "wrong_count": total_wrong,
                "missing_count": total_missing,
                "value_mean_score": round(mean_score, 4),
                "value_match_rate": round(value_match_rate, 4),
                "value_partial_credit_score": round(value_partial_credit_score, 4),
            },
        }

    def evaluate_batch(
        self,
        fairifier_outputs: Dict[str, Dict[str, Any]],
        ground_truth_values_docs: Dict[str, Dict[str, Any]],
        adapter: str = "auto",
    ) -> Dict[str, Any]:
        """Evaluate multiple documents. Only documents with a values-GT entry are scored."""
        per_document: Dict[str, Any] = {}
        for doc_id, gt_values_doc in ground_truth_values_docs.items():
            if doc_id not in fairifier_outputs:
                continue
            per_document[doc_id] = self.evaluate(
                fairifier_outputs[doc_id], gt_values_doc, adapter=adapter
            )

        aggregated = self._aggregate(per_document)
        return {"per_document": per_document, "aggregated": aggregated}

    @staticmethod
    def _aggregate(per_document: Dict[str, Any]) -> Dict[str, Any]:
        if not per_document:
            return {}
        mean_scores = [r["summary_metrics"]["value_mean_score"] for r in per_document.values()]
        match_rates = [r["summary_metrics"]["value_match_rate"] for r in per_document.values()]
        partial_credit = [
            r["summary_metrics"]["value_partial_credit_score"] for r in per_document.values()
        ]
        return {
            "mean_value_mean_score": sum(mean_scores) / len(mean_scores),
            "mean_value_match_rate": sum(match_rates) / len(match_rates),
            "mean_value_partial_credit_score": sum(partial_credit) / len(partial_credit),
            "n_documents": len(per_document),
        }
