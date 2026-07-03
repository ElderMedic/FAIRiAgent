"""Deterministic merge of fragmented ISA entity rows.

When JSONGenerator assigns a distinct ``entity_id`` per field (or per batch),
ISAValueMapper can inherit many sparse rows (1–3 populated cells each) that
describe the same real-world entity.  This module merges compatible rows
*before* matrix normalization so downstream Excel export and evaluation see
denser entity rows.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Set, Tuple

from fairifier.utils.isa_order import MULTI_ROW_ISA_LEVELS

logger = logging.getLogger(__name__)

_IDENTIFIER_FIELDS: Dict[str, str] = {
    "observationunit": "observation unit identifier",
    "sample": "sample identifier",
    "assay": "assay identifier",
}

_EMPTY_VALUES = {"", "not specified", "n/a", "na", "none", "unknown"}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_empty(value: Any) -> bool:
    return _norm(value) in _EMPTY_VALUES


def _populated_count(row: Dict[str, Any]) -> int:
    return sum(1 for v in row.values() if not _is_empty(v))


def _values_conflict(left: Any, right: Any) -> bool:
    a, b = _norm(left), _norm(right)
    if not a or not b or a == b:
        return False
    if a in _EMPTY_VALUES or b in _EMPTY_VALUES:
        return False
    if a in b or b in a:
        return False
    # Numeric-ish tolerance: "25 °C" vs "25°C"
    compact_a = re.sub(r"[\s_\-°]+", "", a)
    compact_b = re.sub(r"[\s_\-°]+", "", b)
    if compact_a == compact_b:
        return False
    return True


def _rows_conflict(row_a: Dict[str, Any], row_b: Dict[str, Any]) -> bool:
    keys = set(row_a.keys()) | set(row_b.keys())
    for key in keys:
        va, vb = row_a.get(key), row_b.get(key)
        if _is_empty(va) or _is_empty(vb):
            continue
        if _values_conflict(va, vb):
            return True
    return False


def _shared_non_empty_fields(row_a: Dict[str, Any], row_b: Dict[str, Any]) -> int:
    count = 0
    for key in set(row_a.keys()) & set(row_b.keys()):
        if not _is_empty(row_a.get(key)) and not _is_empty(row_b.get(key)):
            count += 1
    return count


def _identifier_match(sheet: str, row_a: Dict[str, Any], row_b: Dict[str, Any]) -> bool:
    id_field = _IDENTIFIER_FIELDS.get(sheet)
    if not id_field:
        return False
    a, b = _norm(row_a.get(id_field)), _norm(row_b.get(id_field))
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _merge_score(sheet: str, row_a: Dict[str, Any], row_b: Dict[str, Any]) -> float:
    if _rows_conflict(row_a, row_b):
        return -1.0
    score = 0.0
    shared = _shared_non_empty_fields(row_a, row_b)
    if shared:
        score += 0.2 * shared
    if _identifier_match(sheet, row_a, row_b):
        score += 0.5
    # Prefer merging sparse rows with denser anchors.
    sparse_bonus = 0.0
    for row in (row_a, row_b):
        populated = _populated_count(row)
        if populated <= 2:
            sparse_bonus += 0.25
        elif populated <= 4:
            sparse_bonus += 0.1
    score += sparse_bonus
    # Disjoint field sets (classic fragmentation) get a strong signal.
    overlap_keys = {
        k
        for k in set(row_a.keys()) & set(row_b.keys())
        if not _is_empty(row_a.get(k)) and not _is_empty(row_b.get(k))
    }
    if not overlap_keys:
        score += 0.35
    return score


def _merge_row_dicts(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(primary)
    for key, value in secondary.items():
        if _is_empty(value):
            continue
        existing = merged.get(key)
        if _is_empty(existing):
            merged[key] = value
            continue
        if not _values_conflict(existing, value):
            if len(str(value)) > len(str(existing)):
                merged[key] = value
    return merged


def _mergeable_pair(sheet: str, row_a: Dict[str, Any], row_b: Dict[str, Any], *, min_score: float) -> bool:
    return _merge_score(sheet, row_a, row_b) >= min_score


def merge_sparse_entity_rows(
    matrix: Dict[str, Dict[str, Any]],
    *,
    min_merge_score: float = 0.35,
    sparse_field_threshold: int = 3,
) -> Dict[str, Dict[str, Any]]:
    """Merge compatible sparse rows within each multi-row ISA sheet."""
    for sheet in MULTI_ROW_ISA_LEVELS:
        sheet_data = matrix.get(sheet)
        if not isinstance(sheet_data, dict):
            continue
        rows = sheet_data.get("rows") or []
        if len(rows) < 2:
            continue

        original_count = len(rows)
        merged_any = True
        while merged_any and len(rows) >= 2:
            merged_any = False
            best: Tuple[float, int, int] | None = None
            for i in range(len(rows)):
                for j in range(i + 1, len(rows)):
                    if not isinstance(rows[i], dict) or not isinstance(rows[j], dict):
                        continue
                    score = _merge_score(sheet, rows[i], rows[j])
                    if score < min_merge_score:
                        continue
                    # Require at least one side to look sparse unless identifiers match.
                    sparse_side = (
                        _populated_count(rows[i]) <= sparse_field_threshold
                        or _populated_count(rows[j]) <= sparse_field_threshold
                    )
                    if not sparse_side and not _identifier_match(sheet, rows[i], rows[j]):
                        continue
                    if best is None or score > best[0]:
                        best = (score, i, j)

            if best is None:
                break
            _, idx_a, idx_b = best
            anchor, donor = rows[idx_a], rows[idx_b]
            if _populated_count(donor) > _populated_count(anchor):
                anchor, donor = donor, anchor
            new_row = _merge_row_dicts(anchor, donor)
            keep_idx, drop_idx = (idx_a, idx_b) if rows[idx_a] is anchor else (idx_b, idx_a)
            rows[keep_idx] = new_row
            rows.pop(drop_idx)
            merged_any = True

        if len(rows) != original_count:
            logger.info(
                "Entity merge: %s rows %d → %d",
                sheet,
                original_count,
                len(rows),
            )
        sheet_data["rows"] = rows
    return matrix
