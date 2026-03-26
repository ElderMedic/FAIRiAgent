"""Evidence packet builders for downstream context engineering."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


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
