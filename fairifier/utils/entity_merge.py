"""Deterministic merge of fragmented ISA entity rows.

When JSONGenerator assigns a distinct ``entity_id`` per field (or per batch),
ISAValueMapper can inherit many sparse rows (1–3 populated cells each) that
describe the same real-world entity.  This module folds rows that share an
*exact* normalized sheet identifier (§12.1). Identifier-less sparse fragments
are not merged without a strong source anchor.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Set, Tuple

from fairifier.utils.isa_order import MULTI_ROW_ISA_LEVELS

logger = logging.getLogger(__name__)

_IDENTIFIER_FIELDS: Dict[str, str] = {
    "investigation": "investigation identifier",
    "study": "study identifier",
    "observationunit": "observation unit identifier",
    "sample": "sample identifier",
    "assay": "assay identifier",
}

# ``investigation``/``study`` are nominally single-row, but real documents
# occasionally describe more than one underlying study (e.g. a comparative
# analysis referencing two distinct external bioprojects with different
# study identifiers). Rather than force-collapsing them — which would
# silently discard a genuinely distinct second study — we run them through
# the same conflict-aware sparse-row merge used for multi-row sheets: rows
# sharing the same (or empty) identifier and no conflicting values get
# folded together; rows with distinct, non-empty, non-overlapping
# identifiers are left alone. This fixes upstream entity_id fragmentation
# (many near-empty duplicate rows repeating the *same* identifier) without
# assuming every document has exactly one investigation/study.
_MERGEABLE_LEVELS: Tuple[str, ...] = ("investigation", "study") + MULTI_ROW_ISA_LEVELS

_EMPTY_VALUES = {"", "not specified", "n/a", "na", "none", "unknown"}


def normalize_identifier(value: Any) -> str:
    """Conservative identifier normalization (§12.1).

    Unicode NFKC → trim → collapse internal whitespace → ``casefold()``.
    Punctuation, hyphens, underscores, and numeric boundaries are retained so
    ``REP-01`` / ``REP_01`` / ``REP.01`` remain distinct.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = " ".join(text.split())
    return text.casefold()


def _norm(value: Any) -> str:
    """Generic cell normalization for conflict/empty checks (not identity)."""
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
    """Exact normalized identifier equality only — no substring matching."""
    id_field = _IDENTIFIER_FIELDS.get(sheet)
    if not id_field:
        return False
    a, b = normalize_identifier(row_a.get(id_field)), normalize_identifier(row_b.get(id_field))
    if not a or not b:
        return False
    return a == b


def _merge_score(sheet: str, row_a: Dict[str, Any], row_b: Dict[str, Any]) -> float:
    """Score only exact-identifier pairs (§12.1: no sparse-only merges)."""
    if _rows_conflict(row_a, row_b):
        return -1.0
    if not _identifier_match(sheet, row_a, row_b):
        return -1.0
    score = 0.75
    shared = _shared_non_empty_fields(row_a, row_b)
    if shared:
        score += 0.1 * shared
    return score


def _merge_row_dicts(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(primary)
    for key, value in secondary.items():
        if _is_empty(value):
            continue
        key_lower = str(key).strip().lower()
        existing_key = None
        for k in merged.keys():
            if str(k).strip().lower() == key_lower:
                existing_key = k
                break

        if existing_key is None:
            merged[key] = value
            continue

        existing = merged.get(existing_key)
        if _is_empty(existing):
            merged[existing_key] = value
            continue
        if not _values_conflict(existing, value):
            if len(str(value)) > len(str(existing)):
                merged[existing_key] = value
    return merged


def _mergeable_pair(sheet: str, row_a: Dict[str, Any], row_b: Dict[str, Any], *, min_score: float) -> bool:
    return _merge_score(sheet, row_a, row_b) >= min_score


def collapse_rows_sharing_identifier(
    matrix: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Fold rows that share the same non-empty sheet identifier.

    Cross-batch LLM extraction often assigns a fresh ``entity_id`` per batch
    while repeating the same ``sample identifier`` / ``observation unit
    identifier``.  Sparse-row merge can miss dense+sparse pairs; this pass
    unconditionally merges identifier-equal rows when values do not conflict.
    """
    for sheet in _MERGEABLE_LEVELS:
        id_field = _IDENTIFIER_FIELDS.get(sheet)
        if not id_field:
            continue
        sheet_data = matrix.get(sheet)
        if not isinstance(sheet_data, dict):
            continue
        rows = sheet_data.get("rows") or []
        if len(rows) < 2:
            continue

        original_count = len(rows)
        canonical: Dict[str, Dict[str, Any]] = {}
        unkeyed: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = normalize_identifier(row.get(id_field))
            if not key:
                unkeyed.append(row)
                continue
            existing = canonical.get(key)
            if existing is None:
                canonical[key] = dict(row)
                continue
            if _rows_conflict(existing, row):
                # Same explicit ID with conflicting cells → keep separate
                # (collision group; compiler must not silently drop).
                unkeyed.append(row)
                continue
            anchor, donor = existing, row
            if _populated_count(donor) > _populated_count(anchor):
                anchor, donor = donor, anchor
            canonical[key] = _merge_row_dicts(anchor, donor)

        new_rows = list(canonical.values()) + unkeyed
        if len(new_rows) != original_count:
            logger.info(
                "Identifier collapse: %s rows %d → %d",
                sheet,
                original_count,
                len(new_rows),
            )
        sheet_data["rows"] = new_rows
    return matrix


def postprocess_entity_matrix(
    matrix: Dict[str, Dict[str, Any]],
    *,
    min_merge_score: float = 0.35,
    sparse_field_threshold: int = 3,
) -> Dict[str, Dict[str, Any]]:
    """Canonical structural post-process for ISA entity matrices.

    Order: identifier collapse (same real-world entity, different entity_id
    buckets) then sparse-row merge (disjoint field fragments).
    """
    matrix = collapse_rows_sharing_identifier(matrix)
    return merge_sparse_entity_rows(
        matrix,
        min_merge_score=min_merge_score,
        sparse_field_threshold=sparse_field_threshold,
    )


def merge_sparse_entity_rows(
    matrix: Dict[str, Dict[str, Any]],
    *,
    min_merge_score: float = 0.35,
    sparse_field_threshold: int = 3,
) -> Dict[str, Dict[str, Any]]:
    """Merge rows that share an exact normalized sheet identifier.

    Identifier-less fragments are left unresolved (§12.1). ``sparse_field_threshold``
    is retained for API compatibility but no longer authorizes merges.
    """
    del sparse_field_threshold  # unused under strict identity rules
    for sheet in _MERGEABLE_LEVELS:
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
