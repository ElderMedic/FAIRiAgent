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

import re
from collections import Counter
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
    numeric_tolerance_match,
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
_ENTITY_ID_FIELDS = {
    "investigation": "investigation identifier",
    "study": "study identifier",
    "observationunit": "observation unit identifier",
    "sample": "sample identifier",
    "assay": "assay identifier",
}
_EXTERNAL_ID_FIELDS = re.compile(r"accession|doi|url|uri|orcid|taxonomy|ontology|reference")
_CONTACT_ID_FIELDS = ("firstname", "lastname", "email address", "orcid")
_CONTACT_FIELDS = {*_CONTACT_ID_FIELDS, "organization", "department"}


class _EntityAlignment:
    """Document-local row mappings; external identifiers keep normal scoring."""

    def __init__(self, gt_sheets, pred_sheets):
        self.gt_row_ids = self._counts(gt_sheets, collapse_contacts=False)
        self.pred_row_ids = self._counts(pred_sheets, collapse_contacts=False)
        self.gt_ids = self._counts(gt_sheets)
        self.pred_ids = self._counts(pred_sheets)
        self.id_map = {sheet: {} for sheet in _ENTITY_ID_FIELDS}
        self.pairs = {}
        self.row_sheets = {id(row): sheet for sheet, rows in gt_sheets.items() for row in rows}
        self.content_scores = {}
        self.overrides = {}

    @staticmethod
    def _counts(sheets, *, collapse_contacts=True):
        counts = {
            sheet: Counter(
                row.get(field, "") for row in sheets.get(sheet, []) if row.get(field)
            )
            for sheet, field in _ENTITY_ID_FIELDS.items()
        }
        if not collapse_contacts:
            return counts
        primary = _ENTITY_ID_FIELDS["investigation"]
        for identifier, count in list(counts["investigation"].items()):
            if count < 2:
                continue
            rows = [row for row in sheets.get("investigation", [])
                    if row.get(primary) == identifier]
            contacts = [tuple(str(row.get(field, "")).strip().casefold()
                              for field in _CONTACT_ID_FIELDS) for row in rows]
            shared = {}
            for row in rows:
                for field, value in row.items():
                    if value and field != primary and field not in _CONTACT_FIELDS:
                        shared.setdefault(field, set()).add(" ".join(str(value).split()))
            # FAIR-DS repeats one Investigation across distinct contacts. Only
            # consistent non-contact metadata establishes a single parent.
            if (shared and all(len(values) == 1 for values in shared.values())
                    and all(any(contact) for contact in contacts)
                    and len(set(contacts)) == len(contacts)):
                counts["investigation"][identifier] = 1
        return counts

    def target(self, field, gt_value):
        field = normalise_field_name(field)
        if _EXTERNAL_ID_FIELDS.search(field) or re.match(
            r"(?:https?://|(?:doi:\s*)?10\.\d{4,9}/)", gt_value, re.I
        ):
            return None
        for sheet, primary_field in _ENTITY_ID_FIELDS.items():
            if field == primary_field:
                return sheet if gt_value in self.gt_ids[sheet] else None
        if not (field.endswith(" identifier") or field.endswith(" id")):
            return None
        targets = [sheet for sheet, counts in self.gt_ids.items() if gt_value in counts]
        return targets[0] if len(targets) == 1 else None

    def score(self, field, gt_value, pred_value):
        target = self.target(field, gt_value)
        if target is None:
            return None
        return float(
            self.gt_ids[target][gt_value] == 1
            and self.pred_ids[target][pred_value] == 1
            and self.id_map[target].get(pred_value) == gt_value
        )

    def links_valid(self, gt_row, pred_row):
        return all(
            self.score(field, value, pred_row.get(normalise_field_name(field), "")) != 0.0
            for field, value in gt_row.items()
        )

    def reference_similarity(self, gt_row, pred_row):
        primary = _ENTITY_ID_FIELDS.get(self.row_sheets[id(gt_row)])
        scores = [
            self.score(field, value, pred_row.get(normalise_field_name(field), ""))
            for field, value in gt_row.items() if field != primary
        ]
        scores = [score for score in scores if score is not None]
        return sum(scores) / len(scores) if scores else 0.0

    def _preserves_grouped_parent(self, gt_row, current_row, candidate_row):
        for field, value in gt_row.items():
            target = self.target(field, value)
            if target != "investigation":
                continue
            if not (self.gt_row_ids[target][value] > 1 or any(
                self.pred_row_ids[target][identifier] > 1
                for identifier, mapped in self.id_map[target].items() if mapped == value
            )):
                continue
            if self.score(field, value, candidate_row.get(field, "")) < self.score(
                field, value, current_row.get(field, "")
            ):
                return False
        return True

    def resolve_reference_ties(self, evaluator, gt_sheets, pred_sheets, overrides):
        """Resolve content ties using incoming and outgoing links, with a bounded search.

        Candidate pairs must preserve the established content score. The search
        cannot rescue wrong values, missing rows, duplicate IDs or broken links.
        """
        if all(self.links_valid(g, p) for pairs in self.pairs.values() for g, p in pairs if p):
            return
        candidates, gt_nodes, pred_nodes = {}, {}, {}
        for sheet, pairs in self.pairs.items():
            primary = _ENTITY_ID_FIELDS.get(sheet)
            if primary is None:
                continue
            for pred_row in pred_sheets.get(sheet, []):
                pred_id = pred_row.get(primary, "")
                if self.pred_row_ids[sheet][pred_id] == 1:
                    pred_nodes[sheet, pred_id] = pred_row
            for gt_row, pred_row in pairs:
                gt_id = gt_row.get(primary, "")
                if not gt_id:
                    continue
                if pred_row is None or self.gt_ids[sheet][gt_id] != 1:
                    continue
                # One graph node cannot replace several independently scored
                # contact rows. Their already-aligned parent remains fixed.
                if (self.gt_row_ids[sheet][gt_id] != 1 or
                        self.pred_row_ids[sheet][pred_row.get(primary, "")] != 1):
                    continue
                key = (sheet, gt_id)
                score = evaluator._row_similarity(gt_row, pred_row, overrides.get(sheet), self, True)
                if score < 0.3:
                    continue
                gt_nodes[key] = gt_row
                candidates[key] = [
                    pred_key for pred_key, row in pred_nodes.items()
                    if pred_key[0] == sheet and abs(
                        evaluator._row_similarity(gt_row, row, overrides.get(sheet), self, True) - score
                    ) < 1e-12 and self._preserves_grouped_parent(gt_row, pred_row, row)
                ]
        if not any(len(options) > 1 for options in candidates.values()):
            return
        outgoing = {key: {} for key in gt_nodes}
        incoming = {key: [] for key in gt_nodes}
        for key, row in gt_nodes.items():
            for field, value in row.items():
                target = self.target(field, value)
                if target is None or field == _ENTITY_ID_FIELDS[key[0]]:
                    continue
                target_key = (target, value)
                if target_key not in candidates:
                    continue
                outgoing[key][field] = target_key
                incoming[target_key].append((key, field))
        # Shared candidates and references define independent matching problems.
        # Errors elsewhere must not disable alignment of an otherwise usable component.
        adjacent = {key: set(outgoing[key].values()) | {s for s, _ in incoming[key]}
                    for key in candidates}
        owners = {}
        for key, options in candidates.items():
            for option in options:
                if option in owners:
                    adjacent[key].add(owners[option])
                    adjacent[owners[option]].add(key)
                else:
                    owners[option] = key
        unseen, resolved = set(candidates), {}
        while unseen:
            component, frontier = set(), [next(iter(unseen))]
            while frontier:
                key = frontier.pop()
                if key not in component:
                    component.add(key)
                    frontier.extend(adjacent[key] - component)
            unseen -= component
            assignment = {key: candidates[key][0] for key in component if len(candidates[key]) == 1}
            used = set(assignment.values())
            if len(used) != len(assignment):
                continue
            pending = sorted(
                (key for key in candidates if key in component and key not in assignment),
                key=lambda key: (len(candidates[key]), -len(incoming[key])),
            )
            if not pending or len(pending) > 200:
                continue
            best, best_score, remaining = {}, (-1, -1), 5000

            def bounds():
                correct, possible, complete, possible_complete = 0, 0, 0, 0
                for source in component:
                    successes, unknown = 0, 0
                    for field, target in outgoing[source].items():
                        if source not in assignment or target not in assignment:
                            unknown += 1
                        elif pred_nodes[assignment[source]].get(field, "") == assignment[target][1]:
                            successes += 1
                    total = len(outgoing[source])
                    correct += successes
                    possible += successes + unknown
                    complete += successes == total
                    possible_complete += successes + unknown == total
                return (correct, complete), (possible, possible_complete)

            def search(index):
                nonlocal remaining, best, best_score
                score, upper = bounds()
                if upper <= best_score or remaining <= 0:
                    return
                if index == len(pending):
                    best, best_score = dict(assignment), score
                    return
                key = pending[index]
                for pred_key in candidates[key]:
                    if pred_key in used:
                        continue
                    remaining -= 1
                    assignment[key] = pred_key
                    used.add(pred_key)
                    search(index + 1)
                    used.remove(pred_key)
                    del assignment[key]

            search(0)
            # Keep the established assignment if the bound prevented a full search.
            if remaining > 0:
                resolved.update(best)
        for sheet, mappings in self.id_map.items():
            self.id_map[sheet] = {
                pred_id: gt_id for pred_id, gt_id in mappings.items()
                if (sheet, gt_id) not in resolved
            }
        for (sheet, gt_id), (_, pred_id) in resolved.items():
            self.id_map[sheet][pred_id] = gt_id
        for sheet, pairs in self.pairs.items():
            primary = _ENTITY_ID_FIELDS.get(sheet)
            self.pairs[sheet] = [
                (row, pred_nodes[resolved[sheet, row[primary]]])
                if primary in row and (sheet, row[primary]) in resolved else (row, pred_row)
                for row, pred_row in pairs
            ]


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
                    normalise_field_name(k): str(v).strip()
                    for k, v in row.items()
                    if k != "_evidence" and v is not None and str(v).strip()
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
                            raw_value = field.get("value")
                            value = str(raw_value).strip() if raw_value is not None else ""
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
                    raw_value = field.get("value")
                    value = str(raw_value).strip() if raw_value is not None else ""
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
        entity_alignment: Optional[_EntityAlignment] = None,
        content_only: bool = False,
    ) -> float:
        if not gt_row:
            return 0.0
        cache_key = (id(gt_row), id(pred_row))
        if content_only and entity_alignment and cache_key in entity_alignment.content_scores:
            return entity_alignment.content_scores[cache_key]
        total = 0.0
        count = 0
        for field, gt_val in gt_row.items():
            if content_only and entity_alignment and entity_alignment.target(field, gt_val):
                continue
            pred_val = pred_row.get(field) or pred_row.get(normalise_field_name(field), "")
            total += self._field_score(
                field, gt_val, pred_val, sheet_overrides, entity_alignment, gt_row, pred_row
            )
            count += 1
        score = total / count if count else 0.0
        if content_only and entity_alignment:
            entity_alignment.content_scores[cache_key] = score
        return score

    def _field_score(
        self, field, gt_val, pred_val, sheet_overrides=None, entity_alignment=None,
        gt_row=None, pred_row=None,
    ):
        if not pred_val:
            return 0.0
        if sheet_overrides is None and entity_alignment and gt_row is not None:
            sheet = entity_alignment.row_sheets.get(id(gt_row))
            sheet_overrides = entity_alignment.overrides.get(sheet)
        key = normalise_field_name(field)
        if key in (sheet_overrides or {}) or key in self.global_overrides:
            return match_value(
                pred_val, gt_val, match_type=self._match_type_for(key, sheet_overrides)
            )
        if entity_alignment:
            local_score = entity_alignment.score(field, gt_val, pred_val)
            if local_score is not None:
                return local_score
        if (
            gt_row and pred_row and field in {"measurement value", "measurement unit"}
            and "measurement value" in gt_row and "measurement unit" in gt_row
            and field not in (sheet_overrides or {}) and field not in self.global_overrides
        ):
            if not pred_row.get("measurement value") or not pred_row.get("measurement unit"):
                return 0.0
            return numeric_tolerance_match(
                pred_row["measurement value"] + " " + pred_row["measurement unit"],
                gt_row["measurement value"] + " " + gt_row["measurement unit"],
            )
        return match_value(
            pred_val, gt_val, match_type=self._match_type_for(field, sheet_overrides)
        )

    def align_document(self, gt_sheets, pred_sheets, overrides_by_sheet):
        """Align scientific content before resolving arbitrary local IDs.

        ID-only rows cannot justify a mapping. Conflicting duplicate IDs remain
        unresolved; consistent Investigation contact rows share one parent.
        """
        context = _EntityAlignment(gt_sheets, pred_sheets)
        context.overrides = overrides_by_sheet
        # Resolve parent references to break content ties. Local ID text never
        # enters the content score, and a row's own ID cannot break its own tie.
        for _ in range(len(_ENTITY_ID_FIELDS) + 1):
            previous = {sheet: dict(mapping) for sheet, mapping in context.id_map.items()}
            for sheet, gt_rows in gt_sheets.items():
                overrides = overrides_by_sheet.get(sheet)
                pairs = self.align_rows(
                    gt_rows, pred_sheets.get(sheet, []), overrides, context, content_only=True
                )
                context.pairs[sheet] = pairs
                primary = _ENTITY_ID_FIELDS.get(sheet)
                if primary is None:
                    continue
                context.id_map[sheet] = {}
                candidate_ids = []
                for gt_row, pred_row in pairs:
                    if pred_row is None:
                        continue
                    gt_id, pred_id = gt_row.get(primary, ""), pred_row.get(primary, "")
                    content_score = self._row_similarity(
                        gt_row, pred_row, overrides, context, content_only=True
                    )
                    if (
                        context.gt_ids[sheet][gt_id] == context.pred_ids[sheet][pred_id] == 1
                        and content_score >= 0.3
                    ):
                        candidate_ids.append((gt_id, pred_id))
                gt_targets, pred_targets = {}, {}
                for gt_id, pred_id in candidate_ids:
                    gt_targets.setdefault(gt_id, set()).add(pred_id)
                    pred_targets.setdefault(pred_id, set()).add(gt_id)
                for gt_id, pred_id in candidate_ids:
                    if len(gt_targets[gt_id]) == len(pred_targets[pred_id]) == 1:
                        context.id_map[sheet][pred_id] = gt_id
            if previous == context.id_map:
                break
        context.resolve_reference_ties(self, gt_sheets, pred_sheets, overrides_by_sheet)
        return context

    def align_rows(
        self,
        gt_rows: List[Dict[str, str]],
        pred_rows: List[Dict[str, str]],
        sheet_overrides: Optional[Dict[str, str]] = None,
        entity_alignment: Optional[_EntityAlignment] = None,
        content_only: bool = False,
    ) -> List[Tuple[Dict[str, str], Optional[Dict[str, str]]]]:
        """Hungarian-algorithm (or greedy fallback) alignment of GT rows to prediction rows."""
        if not pred_rows:
            return [(r, None) for r in gt_rows]
        n, m = len(gt_rows), len(pred_rows)

        def similarity(gr, pr):
            score = self._row_similarity(gr, pr, sheet_overrides, entity_alignment, content_only)
            if content_only and entity_alignment:
                score += 1e-6 * entity_alignment.reference_similarity(gr, pr)
            return score

        if _SCIPY:
            cost = np.zeros((n, m))
            for i, gr in enumerate(gt_rows):
                for j, pr in enumerate(pred_rows):
                    cost[i, j] = -similarity(gr, pr)
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
                    s = similarity(gr, pr)
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
        entity_alignment: Optional[_EntityAlignment] = None,
    ) -> Dict[str, Any]:
        if entity_alignment is None:
            entity_alignment = self.align_document(
                {sheet_name: gt_rows}, {sheet_name: pred_rows}, {sheet_name: sheet_overrides}
            )
        pairs = entity_alignment.pairs[sheet_name]

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
                    score = self._field_score(
                        field, gt_val, pred_val, sheet_overrides, entity_alignment, gt_row, pred_row
                    )
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
        entity_alignment = self.align_document(gt_sheets, pred_sheets, overrides_by_sheet)

        per_sheet: Dict[str, Any] = {}
        for sheet_name, gt_rows in gt_sheets.items():
            pred_rows = pred_sheets.get(sheet_name, [])
            per_sheet[sheet_name] = self.evaluate_sheet(
                sheet_name, gt_rows, pred_rows, overrides_by_sheet.get(sheet_name), entity_alignment
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
