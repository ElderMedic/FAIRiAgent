"""
Layer 3 - Structural / Hierarchical Evaluator for FAIRiAgent outputs.

Measures neither field-name existence (Layer 1) nor value-text correctness
(Layer 2) in isolation -- it measures whether extracted fields/values are
correctly *placed* within the ISA hierarchy (right sheet, right distinct
entity/row). This is the metric that ``evaluation/datasets/DATASET_README.md``
has long promised as "Hierarchical-F1" but that had no implementation
anywhere in the codebase before this evaluator.

Split into two independently-reported sub-checks so it can never be
silently conflated with Layer 2 (value accuracy) again:

3a. Sheet-placement accuracy (pure structural, field-level, no value
    comparison at all): for every extracted field that also appears in GT,
    does its ``(field_name, isa_sheet)`` pair match GT? E.g. a field named
    "sample temperature" reported under ``observationunit`` instead of
    ``sample`` fails this check even if its value is perfect.

3b. Entity/row alignment accuracy (structural, entity-level; a CEAF-style
    (Luo, 2005) entity-alignment metric, not a value-scoring metric): for
    multi-row sheets (sample, observationunit, assay), find the optimal
    one-to-one mapping between GT rows and predicted rows via the
    Hungarian algorithm (delegated to
    ``ValueAccuracyEvaluator.align_rows``), then report
    ``row_alignment_recall`` / ``row_alignment_precision`` / ``row_alignment_f1``
    from that mapping. CEAF (one-to-one via Kuhn-Munkres) is used instead of
    a B-cubed-style mention-weighted scheme specifically because B-cubed is
    known to give counter-intuitive scores when entities are merged/split --
    exactly the "3 samples collapsed into 1 row" failure mode this
    sub-metric needs to catch cleanly.

Only *after* rows are aligned, ``value_accuracy_given_correct_structure`` is
reported separately (Layer-2-style scoring, but restricted to row pairs that
cleared the alignment-acceptability bar) alongside the existing global
Layer-2 score. A large gap between the two tells readers the model's errors
are mostly about *entity grouping*, not about *writing correct values*.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ._value_matching import match_value, normalise_field_name
from .value_accuracy_evaluator import ValueAccuracyEvaluator

# Sheets that can contain more than one real-world entity (rows).
MULTI_ROW_SHEETS = {"sample", "observationunit", "assay"}

# Mean per-field match score above which a GT<->predicted row pair counts as
# an "acceptable" alignment (i.e. the agent recognized this as the same
# real-world entity), independent of whether every field value is correct.
ROW_ALIGNMENT_THRESHOLD = 0.3


class StructuralEvaluator:
    """Layer 3: sheet-placement (3a) + CEAF-style row alignment (3b)."""

    def __init__(self, value_evaluator: Optional[ValueAccuracyEvaluator] = None):
        self.value_evaluator = value_evaluator or ValueAccuracyEvaluator()

    # ------------------------------------------------------------------
    # 3a. Sheet placement
    # ------------------------------------------------------------------

    @staticmethod
    def _build_gt_field_sheet_map(
        gt_sheets: Dict[str, List[Dict[str, str]]]
    ) -> Dict[str, set]:
        """field_name (normalized) -> set of sheets it legitimately belongs to."""
        mapping: Dict[str, set] = {}
        for sheet_name, rows in gt_sheets.items():
            for row in rows:
                for field_name in row.keys():
                    mapping.setdefault(normalise_field_name(field_name), set()).add(sheet_name)
        return mapping

    def evaluate_sheet_placement(
        self,
        gt_sheets: Dict[str, List[Dict[str, str]]],
        pred_sheets: Dict[str, List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        gt_field_sheet = self._build_gt_field_sheet_map(gt_sheets)

        total_checked = 0
        correctly_placed = 0
        misplacements: List[Dict[str, str]] = []

        for sheet_name, rows in pred_sheets.items():
            for row in rows:
                for field_name in row.keys():
                    key = normalise_field_name(field_name)
                    if key not in gt_field_sheet:
                        continue  # not a GT field; scope check is Layer 4's job
                    total_checked += 1
                    if sheet_name in gt_field_sheet[key]:
                        correctly_placed += 1
                    else:
                        misplacements.append({
                            "field_name": field_name,
                            "predicted_sheet": sheet_name,
                            "expected_sheets": sorted(gt_field_sheet[key]),
                        })

        accuracy = correctly_placed / total_checked if total_checked else 1.0
        return {
            "total_fields_checked": total_checked,
            "correctly_placed": correctly_placed,
            "sheet_placement_accuracy": round(accuracy, 4),
            "misplacements": misplacements,
        }

    # ------------------------------------------------------------------
    # 3b. Row alignment (CEAF-style)
    # ------------------------------------------------------------------

    @staticmethod
    def _avg_populated_fields(rows: List[Dict[str, str]]) -> float:
        if not rows:
            return 0.0
        counts = [
            sum(1 for v in row.values() if v and str(v).strip())
            for row in rows
        ]
        return sum(counts) / len(counts)

    @staticmethod
    def _row_preview(row: Dict[str, str], *, max_fields: int = 6) -> Dict[str, str]:
        populated = {
            k: (str(v)[:80] if v else "")
            for k, v in row.items()
            if v and str(v).strip()
        }
        if len(populated) <= max_fields:
            return populated
        keys = sorted(populated.keys())[:max_fields]
        preview = {k: populated[k] for k in keys}
        preview["_truncated"] = f"+{len(populated) - max_fields} more fields"
        return preview

    def evaluate_row_alignment(
        self,
        sheet_name: str,
        gt_rows: List[Dict[str, str]],
        pred_rows: List[Dict[str, str]],
        sheet_overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if not gt_rows:
            return {
                "sheet": sheet_name,
                "gt_rows": 0,
                "pred_rows": len(pred_rows),
                "row_count_ratio": 0.0 if not pred_rows else float("inf"),
                "row_alignment_recall": 1.0,
                "row_alignment_precision": 1.0 if not pred_rows else 0.0,
                "row_alignment_f1": 1.0 if not pred_rows else 0.0,
                "diagnostics": {
                    "avg_fields_per_gt_row": 0.0,
                    "avg_fields_per_pred_row": self._avg_populated_fields(pred_rows),
                    "unmatched_gt_rows": [],
                    "unmatched_pred_rows": [
                        self._row_preview(row) for row in pred_rows
                    ],
                    "low_confidence_alignments": [],
                    "fragmentation_hint": "no_gt_rows",
                },
                "matched_pairs": [],
            }

        pairs = self.value_evaluator.align_rows(gt_rows, pred_rows, sheet_overrides)

        acceptable_pairs: List[Tuple[Dict[str, str], Dict[str, str]]] = []
        low_confidence_alignments: List[Dict[str, Any]] = []
        for gt_row, pred_row in pairs:
            if pred_row is None:
                continue
            sim = self.value_evaluator._row_similarity(gt_row, pred_row, sheet_overrides)
            if sim >= ROW_ALIGNMENT_THRESHOLD:
                acceptable_pairs.append((gt_row, pred_row))
                if sim < ROW_ALIGNMENT_THRESHOLD + 0.15:
                    low_confidence_alignments.append({
                        "similarity": round(sim, 4),
                        "gt_row_preview": self._row_preview(gt_row),
                        "pred_row_preview": self._row_preview(pred_row),
                    })
            else:
                low_confidence_alignments.append({
                    "similarity": round(sim, 4),
                    "below_threshold": True,
                    "gt_row_preview": self._row_preview(gt_row),
                    "pred_row_preview": self._row_preview(pred_row),
                })

        acceptable_gt_ids = {id(g) for g, _ in acceptable_pairs}
        acceptable_pred_ids = {id(p) for _, p in acceptable_pairs}
        unmatched_gt_rows = [
            self._row_preview(gt_row)
            for gt_row in gt_rows
            if id(gt_row) not in acceptable_gt_ids
        ]
        unmatched_pred_rows = [
            self._row_preview(row)
            for row in pred_rows
            if id(row) not in acceptable_pred_ids
        ]

        recall = len(acceptable_pairs) / len(gt_rows) if gt_rows else 1.0
        precision = len(acceptable_pairs) / len(pred_rows) if pred_rows else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        row_count_ratio = (
            len(pred_rows) / len(gt_rows) if gt_rows else 0.0
        )
        avg_gt = self._avg_populated_fields(gt_rows)
        avg_pred = self._avg_populated_fields(pred_rows)
        fragmentation_hint = "ok"
        if row_count_ratio > 1.5 and precision < 0.7:
            fragmentation_hint = "over_fragmentation"
        elif row_count_ratio < 0.5 and recall < 0.7:
            fragmentation_hint = "over_merging"
        elif f1 < 0.3 and row_count_ratio <= 1.2:
            fragmentation_hint = "structural_granularity_mismatch"

        return {
            "sheet": sheet_name,
            "gt_rows": len(gt_rows),
            "pred_rows": len(pred_rows),
            "row_count_ratio": round(row_count_ratio, 4),
            "acceptable_alignments": len(acceptable_pairs),
            "row_alignment_recall": round(recall, 4),
            "row_alignment_precision": round(precision, 4),
            "row_alignment_f1": round(f1, 4),
            "diagnostics": {
                "avg_fields_per_gt_row": round(avg_gt, 2),
                "avg_fields_per_pred_row": round(avg_pred, 2),
                "unmatched_gt_rows": unmatched_gt_rows[:20],
                "unmatched_pred_rows": unmatched_pred_rows[:20],
                "low_confidence_alignments": low_confidence_alignments[:20],
                "fragmentation_hint": fragmentation_hint,
            },
            "_matched_pairs": acceptable_pairs,  # internal use only, not serialized by caller
        }

    def _value_accuracy_within_pairs(
        self,
        pairs: List[Tuple[Dict[str, str], Dict[str, str]]],
        sheet_overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, float]:
        """Layer-2-style scoring, restricted to already-aligned (acceptable) row pairs."""
        total, match_count, partial_count = 0, 0, 0
        missing_count, wrong_count = 0, 0
        score_sum = 0.0
        for gt_row, pred_row in pairs:
            for field, gt_val in gt_row.items():
                if not gt_val:
                    continue
                mt = self.value_evaluator._match_type_for(field, sheet_overrides)
                pred_val = pred_row.get(field) or pred_row.get(normalise_field_name(field), "")
                total += 1
                if not pred_val:
                    missing_count += 1
                    continue
                score = match_value(pred_val, gt_val, match_type=mt)
                score_sum += score
                from ._value_matching import classify_status
                status = classify_status(score, mt)
                if status == "match":
                    match_count += 1
                elif status == "partial":
                    partial_count += 1
                else:
                    wrong_count += 1
        return {
            "n_fields": total,
            "mean_score": score_sum / total if total else 0.0,
            "value_match_rate": match_count / total if total else 0.0,
            "value_partial_credit_score": (match_count + 0.5 * partial_count) / total if total else 0.0,
            "missing_field_rate": missing_count / total if total else 0.0,
            "wrong_value_rate": wrong_count / total if total else 0.0,
        }

    # ------------------------------------------------------------------
    # Document-level evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        fairifier_output: Dict[str, Any],
        ground_truth_values_doc: Dict[str, Any],
        adapter: str = "auto",
    ) -> Dict[str, Any]:
        gt_sheets, overrides_by_sheet = self.value_evaluator.load_gt_sheets(ground_truth_values_doc)
        pred_sheets = self.value_evaluator.load_pred_sheets(fairifier_output, adapter=adapter)

        sheet_placement = self.evaluate_sheet_placement(gt_sheets, pred_sheets)

        per_sheet_alignment: Dict[str, Any] = {}
        all_acceptable_pairs: List[Tuple[Dict[str, str], Dict[str, str]]] = []
        for sheet_name in MULTI_ROW_SHEETS:
            gt_rows = gt_sheets.get(sheet_name, [])
            if not gt_rows:
                continue
            pred_rows = pred_sheets.get(sheet_name, [])
            result = self.evaluate_row_alignment(
                sheet_name, gt_rows, pred_rows, overrides_by_sheet.get(sheet_name)
            )
            all_acceptable_pairs.extend(result.pop("_matched_pairs"))
            per_sheet_alignment[sheet_name] = result

        # Single-row sheets: alignment is trivial (0 or 1 GT row).
        for sheet_name in ("investigation", "study"):
            gt_rows = gt_sheets.get(sheet_name, [])
            if not gt_rows:
                continue
            pred_rows = pred_sheets.get(sheet_name, [])
            if pred_rows:
                sim = self.value_evaluator._row_similarity(
                    gt_rows[0], pred_rows[0], overrides_by_sheet.get(sheet_name)
                )
                if sim >= ROW_ALIGNMENT_THRESHOLD:
                    all_acceptable_pairs.append((gt_rows[0], pred_rows[0]))

        if per_sheet_alignment:
            total_gt = sum(r["gt_rows"] for r in per_sheet_alignment.values())
            total_pred = sum(r["pred_rows"] for r in per_sheet_alignment.values())
            total_acceptable = sum(r["acceptable_alignments"] for r in per_sheet_alignment.values())
            row_alignment_recall = total_acceptable / total_gt if total_gt else 1.0
            row_alignment_precision = total_acceptable / total_pred if total_pred else 0.0
            row_alignment_f1 = (
                2 * row_alignment_precision * row_alignment_recall
                / (row_alignment_precision + row_alignment_recall)
                if (row_alignment_precision + row_alignment_recall) > 0
                else 0.0
            )
            row_count_ratio = total_pred / total_gt if total_gt else 0.0
        else:
            row_alignment_recall = row_alignment_precision = row_alignment_f1 = 1.0
            row_count_ratio = 0.0

        value_accuracy_given_correct_structure = self._value_accuracy_within_pairs(
            all_acceptable_pairs
        )

        return {
            "sheet_placement": sheet_placement,
            "row_alignment_by_sheet": per_sheet_alignment,
            "summary_metrics": {
                "sheet_placement_accuracy": sheet_placement["sheet_placement_accuracy"],
                "row_alignment_recall": round(row_alignment_recall, 4),
                "row_alignment_precision": round(row_alignment_precision, 4),
                "row_alignment_f1": round(row_alignment_f1, 4),
                "row_count_ratio": round(row_count_ratio, 4),
                "value_accuracy_given_correct_structure": round(
                    value_accuracy_given_correct_structure["mean_score"], 4
                ),
                "value_match_rate_given_correct_structure": round(
                    value_accuracy_given_correct_structure["value_match_rate"], 4
                ),
                "missing_field_rate_given_correct_structure": round(
                    value_accuracy_given_correct_structure["missing_field_rate"], 4
                ),
                "wrong_value_rate_given_correct_structure": round(
                    value_accuracy_given_correct_structure["wrong_value_rate"], 4
                ),
            },
            "value_accuracy_given_correct_structure_detail": value_accuracy_given_correct_structure,
        }

    def evaluate_batch(
        self,
        fairifier_outputs: Dict[str, Dict[str, Any]],
        ground_truth_values_docs: Dict[str, Dict[str, Any]],
        adapter: str = "auto",
    ) -> Dict[str, Any]:
        per_document: Dict[str, Any] = {}
        for doc_id, gt_values_doc in ground_truth_values_docs.items():
            if doc_id not in fairifier_outputs:
                continue
            per_document[doc_id] = self.evaluate(fairifier_outputs[doc_id], gt_values_doc, adapter=adapter)

        aggregated = self._aggregate(per_document)
        return {"per_document": per_document, "aggregated": aggregated}

    @staticmethod
    def _aggregate(per_document: Dict[str, Any]) -> Dict[str, Any]:
        if not per_document:
            return {}
        keys = [
            "sheet_placement_accuracy",
            "row_alignment_recall",
            "row_alignment_precision",
            "row_alignment_f1",
            "row_count_ratio",
            "value_accuracy_given_correct_structure",
            "missing_field_rate_given_correct_structure",
            "wrong_value_rate_given_correct_structure",
        ]
        agg = {}
        for key in keys:
            values = [r["summary_metrics"][key] for r in per_document.values()]
            agg[f"mean_{key}"] = sum(values) / len(values)
        agg["n_documents"] = len(per_document)
        return agg
