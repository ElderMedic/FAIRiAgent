"""Helpers for ranking FAIR-DS packages using structured /api/packages summaries."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

PACKAGE_STOP_TOKENS = {
    "checklist",
    "sample",
    "reporting",
    "standard",
    "pilot",
    "global",
    "enhanced",
    "annotation",
    "associated",
    "default",
    "ena",
    "gsc",
    "metadata",
    "package",
    "field",
    "fields",
    "level",
    "levels",
}


def summary_to_package_record(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Map a FAIR-DS /api/packages summary row to the KR package catalog shape."""
    requirements = summary.get("requirements") or {}
    return {
        "name": summary["name"],
        "description": summary.get("description", ""),
        "field_count": summary.get("fieldCount", 0),
        "mandatory_count": requirements.get("MANDATORY", 0)
        + requirements.get("REQUIRED", 0),
        "optional_count": requirements.get("OPTIONAL", 0),
        "recommended_count": requirements.get("RECOMMENDED", 0),
        "sheets": summary.get("levels", []),
        "sample_fields": [],
    }


def build_document_match_text(
    doc_info: Dict[str, Any],
    *,
    planner_instruction: Optional[str] = None,
    evidence_packets: Optional[List[Dict[str, Any]]] = None,
    critic_feedback: Optional[Dict[str, Any]] = None,
    extra_text: Optional[Iterable[str]] = None,
) -> str:
    """Collect document-side signals used for lexical package matching."""
    packet_values = " ".join(
        str(packet.get("value", ""))
        for packet in (evidence_packets or [])[:16]
        if packet.get("value")
    )
    critic_text = " ".join(
        str(part)
        for part in [
            critic_feedback.get("critique") if critic_feedback else "",
            " ".join(critic_feedback.get("suggestions", []) or [])
            if critic_feedback
            else "",
            " ".join(critic_feedback.get("issues", []) or []) if critic_feedback else "",
        ]
        if part
    )
    parts = [
        doc_info.get("title", ""),
        doc_info.get("document_type", ""),
        doc_info.get("research_domain", ""),
        doc_info.get("methodology", ""),
        doc_info.get("abstract", ""),
        " ".join(doc_info.get("keywords", []) or []),
        packet_values,
        planner_instruction or "",
        critic_text,
    ]
    if extra_text:
        parts.extend(str(item) for item in extra_text if item)
    return " ".join(str(part) for part in parts if part)


def _tokenize_for_matching(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]{4,}", str(text or "").lower())
    return {token for token in tokens if token not in PACKAGE_STOP_TOKENS}


def score_package_relevance(match_text: str, package: Dict[str, Any]) -> int:
    """Score one package against document text using name, description, and ISA levels."""
    doc_tokens = _tokenize_for_matching(match_text)
    if not doc_tokens:
        return 0

    score = 0
    name_tokens = _tokenize_for_matching(package.get("name", ""))
    description_tokens = _tokenize_for_matching(package.get("description", ""))
    sheet_tokens = _tokenize_for_matching(
        " ".join(package.get("sheets") or package.get("levels") or [])
    )

    for token in name_tokens:
        if token in doc_tokens:
            score += 3
    for token in description_tokens:
        if token in doc_tokens:
            score += 2
    for token in sheet_tokens:
        if token in doc_tokens:
            score += 1

    match_lower = match_text.lower()
    description_lower = str(package.get("description", "")).lower()
    if description_lower and len(description_lower) >= 12:
        for token in description_tokens:
            if len(token) >= 6 and token in match_lower:
                score += 1

    return score


def rank_packages_by_document(
    packages: List[Dict[str, Any]],
    match_text: str,
) -> List[Dict[str, Any]]:
    """Return packages sorted by relevance score (highest first)."""
    scored = [(score_package_relevance(match_text, package), package) for package in packages]
    scored.sort(key=lambda item: (-item[0], str(item[1].get("name", "")).lower()))
    return [package for _, package in scored]


def top_relevant_package_names(
    packages: List[Dict[str, Any]],
    match_text: str,
    *,
    limit: int = 12,
    min_score: int = 2,
) -> List[str]:
    """Return the highest-scoring package names above ``min_score``."""
    ranked = rank_packages_by_document(packages, match_text)
    selected: List[str] = []
    for package in ranked:
        name = package.get("name")
        if not name:
            continue
        if score_package_relevance(match_text, package) < min_score:
            break
        if name not in selected:
            selected.append(str(name))
        if len(selected) >= limit:
            break
    return selected
