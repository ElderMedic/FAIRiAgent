"""Evidence packet builders for downstream context engineering."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Sequence


def _normalize_items(value: Any) -> List[str]:
    """Flatten scalar/list values into a list of concise strings."""
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        items: List[str] = []
        for item in value:
            items.extend(_normalize_items(item))
        return items
    if isinstance(value, dict):
        compact = "; ".join(
            f"{k}: {v}"
            for k, v in value.items()
            if v not in (None, "", [], {})
        )
        return [compact] if compact else []
    text = str(value).strip()
    return [text] if text else []


def _find_section_heading(text: str, match_pos: int) -> Optional[str]:
    """Find the nearest Markdown or uppercase heading above a match position."""
    prefix = text[:match_pos]
    heading = None
    for raw_line in prefix.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
        elif len(line) < 120 and line.isupper():
            heading = line
    return heading


def _evidence_excerpt(text: str, snippet: str, field_name: str) -> tuple[str, Optional[str]]:
    """Extract a short excerpt around a value or field hint."""
    if not text:
        return "", None

    candidates = [snippet.strip(), field_name.replace("_", " ").strip()]
    for candidate in candidates:
        if not candidate:
            continue
        match = re.search(re.escape(candidate[:120]), text, re.IGNORECASE)
        if match:
            start = max(0, match.start() - 140)
            end = min(len(text), match.end() + 180)
            excerpt = " ".join(text[start:end].split())
            return excerpt[:360], _find_section_heading(text, match.start())

    excerpt = " ".join(text[:320].split())
    return excerpt, None


def build_evidence_packets(
    doc_info: Dict[str, Any],
    source_text: str,
    *,
    source_type: str,
    max_packets: int = 24,
) -> List[Dict[str, Any]]:
    """Create compact evidence packets from document parser output."""
    packets: List[Dict[str, Any]] = []

    confidence = float(doc_info.get("confidence", 0.75) or 0.75)
    for field_name, raw_value in doc_info.items():
        if field_name in {"confidence", "raw_text"}:
            continue
        values = _normalize_items(raw_value)
        for item in values[:4]:
            evidence_text, section = _evidence_excerpt(source_text, item, field_name)
            packets.append(
                {
                    "packet_id": f"ep-{len(packets) + 1:03d}",
                    "field_candidate": field_name,
                    "value": item[:500],
                    "evidence_text": evidence_text,
                    "section": section,
                    "source_type": source_type,
                    "confidence": confidence,
                    "provenance": {
                        "agent": "DocumentParser",
                        "strategy": "document_parser_structured_extraction",
                    },
                }
            )
            if len(packets) >= max_packets:
                return packets

    return packets


def evidence_packet_dedupe_key(packet: Dict[str, Any]) -> str:
    """Stable content key for evidence-packet merge/deduplication.

    Prefer source span + field/value when present; otherwise hash the payload
    fields that identify the candidate. ``packet_id`` is intentionally ignored
    so producers can assign their own IDs without defeating dedupe.
    """
    source_id = str(packet.get("source_id") or "").strip()
    char_start = packet.get("char_start")
    char_end = packet.get("char_end")
    field = str(
        packet.get("field_candidate") or packet.get("field_name") or ""
    ).strip().lower()
    value = str(packet.get("value") or "").strip().lower()
    producer = str(
        packet.get("produced_by")
        or (packet.get("provenance") or {}).get("agent")
        or ""
    ).strip().lower()
    if source_id and char_start is not None and char_end is not None and field:
        return f"{producer}|{source_id}|{char_start}|{char_end}|{field}|{value}"
    digest = hashlib.sha1(
        "|".join(
            [
                producer,
                field,
                value,
                str(packet.get("evidence_text") or "").strip().lower()[:240],
                str(packet.get("section") or "").strip().lower(),
                str(packet.get("source_type") or "").strip().lower(),
            ]
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"{producer}|{digest}"


def merge_evidence_packets(
    existing: Sequence[Dict[str, Any]] | None,
    new_packets: Sequence[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    """Merge evidence packets without dropping prior producers.

    Used so DocumentParser can append its structured-extraction packets while
    preserving SectionMapReduce / BioMetadata packets already in state.
    """
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for packet in list(existing or []) + list(new_packets or []):
        if not isinstance(packet, dict):
            continue
        key = evidence_packet_dedupe_key(packet)
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(packet))
    return merged


def build_evidence_context(
    evidence_packets: List[Dict[str, Any]],
    *,
    max_packets: int = 16,
    max_chars: int = 2500,
) -> str:
    """Render evidence packets into a compact context block for downstream agents."""
    if not evidence_packets:
        return ""

    lines = ["Evidence packets:"]
    total_chars = len(lines[0])
    for packet in evidence_packets[:max_packets]:
        line = (
            f"- {packet.get('field_candidate')}: {packet.get('value')} "
            f"(section: {packet.get('section') or 'n/a'}; evidence: {packet.get('evidence_text') or 'n/a'})"
        )
        if total_chars + len(line) > max_chars:
            break
        lines.append(line)
        total_chars += len(line)

    return "\n".join(lines)
