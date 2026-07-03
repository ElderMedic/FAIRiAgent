"""Deterministic field-candidate extraction from section map-reduce workers."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_SECTION_TYPE_FIELD_HINTS: Dict[str, List[str]] = {
    "introduction": ["investigation description", "study description", "project name"],
    "methods": [
        "sequencing method",
        "library construction method",
        "nucleic acid extraction",
        "sample preparation",
    ],
    "results": ["assay name", "experimental factor"],
    "discussion": ["investigation description"],
    "metadata": ["project name", "investigation identifier"],
}

_KV_LINE = re.compile(
    r"^\s*(?:[-*•]\s*)?"
    r"(?P<label>[A-Za-z][A-Za-z0-9 /\-_()]{2,72})\s*"
    r"[:=]\s*"
    r"(?P<value>.+?)\s*$"
)
_NUMERIC_HINT = re.compile(
    r"\b("
    r"latitude|longitude|elevation|depth|temperature|pH|"
    r"concentration|doi|accession|sra|ena|geo"
    r")\b",
    re.IGNORECASE,
)


def _normalize_field_name(label: str) -> str:
    return re.sub(r"\s+", " ", str(label or "").strip().lower())


def _normalize_value(value: str) -> str:
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) > 500:
        cleaned = cleaned[:497].rstrip() + "..."
    return cleaned


def _line_char_offset(section_text: str, line_start: int, section_char_start: int) -> tuple[int, int]:
    line_end = section_text.find("\n", line_start)
    if line_end < 0:
        line_end = len(section_text)
    return section_char_start + line_start, section_char_start + line_end


def extract_field_candidates_from_section(
    section: Dict[str, Any],
    *,
    source_meta: Optional[Dict[str, Dict[str, Any]]] = None,
    produced_by: str = "section_map_reduce",
    max_candidates: int = 12,
) -> List[Dict[str, Any]]:
    """Extract label/value and keyword-backed candidates from one section."""
    text = str(section.get("text") or "")
    if not text.strip():
        return []

    source_meta = source_meta or {}
    source_id = str(section.get("source_id") or "")
    meta = source_meta.get(source_id, {})
    source_role = str(meta.get("source_role") or "unknown")
    relevance = float(meta.get("relevance_score") or 0.5)
    section_id = str(section.get("section_id") or "section")
    section_title = str(section.get("title") or section_id)
    section_type = str(section.get("section_type") or "unknown")
    char_start = int(section.get("char_start") or 0)
    char_end = int(section.get("char_end") or char_start + len(text))

    records: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _append(field_name: str, value: str, evidence_text: str, abs_start: int, abs_end: int) -> None:
        key = (_normalize_field_name(field_name), _normalize_value(value).lower())
        if not key[0] or not key[1] or key in seen:
            return
        seen.add(key)
        idx = len(records)
        records.append(
            {
                "evidence_id": f"{section_id}_fc_{idx:03d}",
                "packet_id": f"{section_id}_fc_{idx:03d}",
                "kind": "field_candidate",
                "field_name": _normalize_field_name(field_name),
                "field_candidate": _normalize_field_name(field_name),
                "value": _normalize_value(value),
                "evidence_text": evidence_text[:1200],
                "section": section_title,
                "source_id": source_id,
                "source_role": source_role,
                "relevance_score": relevance,
                "char_start": abs_start,
                "char_end": abs_end,
                "confidence": 0.55,
                "retrieval_method": "section_map_reduce",
                "provenance": {
                    "agent": produced_by,
                    "strategy": "section_field_extraction",
                    "section_type": section_type,
                },
                "produced_by": produced_by,
            }
        )

    for match in _KV_LINE.finditer(text):
        label = match.group("label")
        value = match.group("value")
        if len(value) < 2 or label.lower() in {"figure", "table", "section", "page"}:
            continue
        abs_start, abs_end = _line_char_offset(text, match.start(), char_start)
        excerpt = text[max(0, match.start() - 80) : min(len(text), match.end() + 120)]
        _append(label, value, excerpt, abs_start, abs_end)
        if len(records) >= max_candidates:
            return records

    for hint_field in _SECTION_TYPE_FIELD_HINTS.get(section_type, []):
        pattern = re.compile(re.escape(hint_field.replace("_", " ")), re.IGNORECASE)
        found = pattern.search(text)
        if not found:
            continue
        snippet_start = max(0, found.start() - 40)
        snippet_end = min(len(text), found.end() + 160)
        snippet = text[snippet_start:snippet_end]
        value = " ".join(snippet.split())[:240]
        abs_start = char_start + snippet_start
        abs_end = min(char_end, char_start + snippet_end)
        _append(hint_field, value, snippet, abs_start, abs_end)
        if len(records) >= max_candidates:
            return records

    for match in _NUMERIC_HINT.finditer(text):
        hint = match.group(1).lower()
        snippet_start = max(0, match.start() - 60)
        snippet_end = min(len(text), match.end() + 120)
        snippet = text[snippet_start:snippet_end]
        tail = text[match.end() : match.end() + 80]
        value_match = re.search(r"[:=]\s*([^\n;]{2,80})", tail)
        value = value_match.group(1).strip() if value_match else " ".join(snippet.split())[:120]
        abs_start = char_start + snippet_start
        abs_end = min(char_end, char_start + snippet_end)
        _append(hint, value, snippet, abs_start, abs_end)
        if len(records) >= max_candidates:
            break

    return records


def field_candidate_record_to_dict(record: Dict[str, Any]) -> Dict[str, Any]:
    """Stable serialization for LangGraph state."""
    return {
        "field_name": record.get("field_name") or record.get("field_candidate"),
        "value": record.get("value"),
        "source_id": record.get("source_id"),
        "source_role": record.get("source_role", "unknown"),
        "relevance_score": float(record.get("relevance_score") or 0.5),
        "evidence": (
            f"{record.get('source_id')}:{record.get('char_start')}-{record.get('char_end')} "
            f"[role={record.get('source_role', 'unknown')}] "
            f"({record.get('section')}): {record.get('evidence_text') or record.get('value')}"
        ),
        "confidence": float(record.get("confidence") or 0.55),
        "char_start": record.get("char_start"),
        "char_end": record.get("char_end"),
        "retrieval_method": record.get("retrieval_method") or "section_map_reduce",
        "section_id": record.get("section"),
        "provenance": record.get("provenance") or {},
    }
