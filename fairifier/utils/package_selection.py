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

GENERIC_CONTROLLED_VALUES = {
    "any",
    "none",
    "not applicable",
    "not available",
    "other",
    "unknown",
    "unspecified",
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
        "mandatory_fields": [],
    }


def attach_package_field_catalog(
    packages: List[Dict[str, Any]],
    fields: Iterable[Dict[str, Any]],
    *,
    label_limit: int = 24,
    match_text: str = "",
) -> List[Dict[str, Any]]:
    """Attach representative field labels to package summary records.

    FAIR-DS package summaries are useful for discovery, but descriptions alone
    are too coarse for deciding whether a package's schema applies to a source.
    The selector needs to see the actual field contract (for example, library
    strategy/source/selection) without receiving every term definition.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        package_name = str(field.get("packageName") or "").strip()
        if package_name:
            grouped.setdefault(package_name.lower(), []).append(field)

    enriched: List[Dict[str, Any]] = []
    document_tokens = _tokenize_for_matching(match_text)
    for package in packages:
        record = dict(package)
        package_fields = grouped.get(str(record.get("name") or "").lower(), [])

        def field_priority(field: Dict[str, Any]) -> tuple[int, int, int, str]:
            term = field.get("term") if isinstance(field.get("term"), dict) else {}
            field_text = " ".join(
                str(value or "")
                for value in (
                    field.get("label"),
                    field.get("definition"),
                    term.get("definition"),
                    term.get("syntax"),
                    term.get("regex"),
                    term.get("example"),
                )
            )
            overlap = len(document_tokens & _tokenize_for_matching(field_text))
            controlled_value_matches = _matching_controlled_values(field, match_text)
            requirement = str(field.get("requirement") or "").upper()
            mandatory_rank = 0 if requirement in {"MANDATORY", "REQUIRED"} else 1
            return (
                -len(controlled_value_matches),
                -overlap,
                mandatory_rank,
                str(field.get("label") or "").lower(),
            )

        package_fields = sorted(package_fields, key=field_priority)
        labels: List[str] = []
        mandatory_labels: List[str] = []
        field_contract: List[Dict[str, Any]] = []
        for field in package_fields:
            label = str(field.get("label") or "").strip()
            if not label:
                continue
            if label not in labels and len(labels) < label_limit:
                labels.append(label)
            requirement = str(field.get("requirement") or "").upper()
            if (
                requirement in {"MANDATORY", "REQUIRED"}
                and label not in mandatory_labels
                and len(mandatory_labels) < label_limit
            ):
                mandatory_labels.append(label)
            if len(field_contract) < label_limit:
                term = field.get("term") if isinstance(field.get("term"), dict) else {}
                allowed_values = _extract_controlled_values(field)[:24]
                matched_values = _matching_controlled_values(field, match_text)
                field_contract.append(
                    {
                        "label": label,
                        "level": str(field.get("level") or "").strip(),
                        "requirement": requirement,
                        "definition": str(
                            field.get("definition") or term.get("definition") or ""
                        ).strip()[:240],
                        "allowed_values": allowed_values,
                        "source_matched_values": matched_values[:8],
                    }
                )
        record["sample_fields"] = labels
        record["mandatory_fields"] = mandatory_labels
        record["field_contract"] = field_contract
        # Legacy FAIR-DS installations expose package names but return empty
        # summary statistics. The fetched field contract is authoritative in
        # that case; derive sheet/count metadata so downstream burden and
        # coverage arbitration does not silently treat a 98-field checklist as
        # a zero-field package.
        if package_fields:
            derived_sheets = list(
                dict.fromkeys(
                    str(field.get("level") or "").strip()
                    for field in package_fields
                    if str(field.get("level") or "").strip()
                )
            )
            record["sheets"] = derived_sheets or list(record.get("sheets") or [])
            record["field_count"] = len(package_fields)
            record["mandatory_count"] = sum(
                str(field.get("requirement") or "").upper()
                in {"MANDATORY", "REQUIRED"}
                for field in package_fields
            )
            record["optional_count"] = sum(
                str(field.get("requirement") or "").upper() == "OPTIONAL"
                for field in package_fields
            )
            record["recommended_count"] = sum(
                str(field.get("requirement") or "").upper() == "RECOMMENDED"
                for field in package_fields
            )
        enriched.append(record)
    return enriched


def _normalize_schema_value(value: str) -> str:
    """Normalize source/schema values for punctuation-insensitive comparison."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _extract_controlled_values(field: Dict[str, Any]) -> List[str]:
    """Extract bounded enum-like values from a FAIR-DS field contract."""
    term = field.get("term") if isinstance(field.get("term"), dict) else {}
    candidates: List[str] = []
    for raw in (term.get("syntax"), term.get("regex")):
        text = str(raw or "").strip()
        if not text or "|" not in text:
            continue
        text = text.strip("()")
        for value in text.split("|"):
            cleaned = value.strip().strip("()[]{}^$")
            if not cleaned or len(cleaned) > 80 or "\\" in cleaned:
                continue
            if cleaned not in candidates:
                candidates.append(cleaned)
    example = str(term.get("example") or "").strip()
    if example and len(example) <= 80 and example not in candidates:
        candidates.append(example)
    return candidates


def _matching_controlled_values(field: Dict[str, Any], match_text: str) -> List[str]:
    """Return controlled values explicitly compatible with the source text."""
    normalized_source = _normalize_schema_value(match_text)
    if not normalized_source:
        return []
    matches: List[str] = []
    for value in _extract_controlled_values(field):
        if str(value).strip().lower() in GENERIC_CONTROLLED_VALUES:
            continue
        normalized_value = _normalize_schema_value(value)
        if len(normalized_value) < 4:
            continue
        if normalized_value in normalized_source or normalized_source in normalized_value:
            matches.append(value)
    return matches


def mandatory_source_support(
    package: Dict[str, Any],
    source_text: str,
) -> Dict[str, Any]:
    """Measure whether a package's mandatory burden is supported by the source.

    This is deliberately lexical and conservative. It does not decide that a
    package applies; it identifies packages whose mandatory contract would add
    mostly source-absent columns. A mandatory label is counted as supported only
    when at least two informative label tokens occur in the source, or a real
    (non-generic) controlled value is explicitly matched.
    """
    mandatory_labels = [
        str(label).strip()
        for label in package.get("mandatory_fields") or []
        if str(label).strip()
    ]
    declared_count = int(package.get("mandatory_count") or 0)
    mandatory_count = max(declared_count, len(mandatory_labels))
    source_tokens = _tokenize_for_matching(source_text)
    supported: List[str] = []
    contract_by_label = {
        _normalize_schema_value(field.get("label", "")): field
        for field in package.get("field_contract") or []
        if isinstance(field, dict)
    }
    for label in mandatory_labels:
        field = contract_by_label.get(_normalize_schema_value(label), {})
        overlap = source_tokens & _tokenize_for_matching(label)
        matched_values = _matching_controlled_values(field, source_text)
        if len(overlap) >= 2 or matched_values:
            supported.append(label)
    unsupported_count = max(0, mandatory_count - len(supported))
    return {
        "mandatory_count": mandatory_count,
        "supported_mandatory_count": len(supported),
        "unsupported_mandatory_count": unsupported_count,
        "supported_mandatory_fields": supported,
        "support_ratio": (
            len(supported) / mandatory_count if mandatory_count else 1.0
        ),
    }


def prefer_lower_burden_package_set(
    selected_names: Iterable[str],
    packages: List[Dict[str, Any]],
    source_text: str,
) -> tuple[List[str], List[Dict[str, Any]]]:
    """Replace a high-burden extension with a leaner relevant peer.

    The rule is schema-generic: a selected extension must have at least four
    mandatory fields, most of them unsupported, and a same-level alternative
    must reduce the mandatory burden by at least three fields while retaining
    meaningful source relevance. Technology peers with comparable mandatory
    contracts are therefore not swapped arbitrarily.
    """
    records = {
        str(package.get("name") or "").strip().lower(): package
        for package in packages
        if str(package.get("name") or "").strip()
    }
    chosen = list(dict.fromkeys(str(name).strip() for name in selected_names if str(name).strip()))
    chosen_lower = {name.lower() for name in chosen}
    decisions: List[Dict[str, Any]] = []

    for index, name in enumerate(list(chosen)):
        if name.lower() == "default":
            continue
        current = records.get(name.lower())
        if not current:
            continue
        burden = mandatory_source_support(current, source_text)
        if (
            burden["mandatory_count"] < 4
            or burden["support_ratio"] >= 0.5
        ):
            continue
        current_levels = {
            str(level).strip().lower()
            for level in current.get("sheets") or []
            if str(level).strip()
        }
        current_relevance = score_package_relevance(source_text, current)
        alternatives: List[tuple[int, int, int, str, Dict[str, Any], Dict[str, Any]]] = []
        for candidate in packages:
            candidate_name = str(candidate.get("name") or "").strip()
            if not candidate_name or candidate_name.lower() == name.lower():
                continue
            candidate_levels = {
                str(level).strip().lower()
                for level in candidate.get("sheets") or []
                if str(level).strip()
            }
            if not current_levels or not (current_levels & candidate_levels):
                continue
            candidate_burden = mandatory_source_support(candidate, source_text)
            if (
                candidate_burden["mandatory_count"]
                > burden["mandatory_count"] - 3
            ):
                continue
            relevance = score_package_relevance(source_text, candidate)
            if relevance < 2 or relevance * 2 < max(1, current_relevance):
                continue
            alternatives.append(
                (
                    candidate_burden["unsupported_mandatory_count"],
                    candidate_burden["mandatory_count"],
                    -relevance,
                    candidate_name.lower(),
                    candidate,
                    candidate_burden,
                )
            )
        if not alternatives:
            decisions.append(
                {"package": name, "action": "retain", "burden": burden}
            )
            continue
        # Relevance is a gate above, not the primary optimizer here. Once a
        # peer is demonstrably applicable, prefer the contract that requires
        # the fewest source-absent mandatory values. Ranking relevance first
        # systematically favours broad checklists because they contain more
        # matchable prose and fields -- precisely the schema-width bias this
        # arbitration is meant to remove.
        alternatives.sort(key=lambda item: item[:4])
        _, _, _, _, replacement, replacement_burden = alternatives[0]
        replacement_name = str(replacement.get("name") or "")
        chosen[index] = replacement_name
        chosen_lower.discard(name.lower())
        chosen_lower.add(replacement_name.lower())
        decisions.append(
            {
                "package": name,
                "action": "replace",
                "replacement": replacement_name,
                "burden": burden,
                "replacement_burden": replacement_burden,
            }
        )
    return list(dict.fromkeys(chosen)), decisions


def complete_source_schema_coverage(
    selected_names: Iterable[str],
    packages: List[Dict[str, Any]],
    source_text: str,
    *,
    levels: Iterable[str] = ("sample", "assay"),
) -> tuple[List[str], List[Dict[str, Any]]]:
    """Complete source-backed ISA-level coverage from real package contracts.

    This is a bounded safety boundary after LLM selection. It does not infer
    packages from domain keywords. Eligible candidates must have strong
    current-source/field-contract matches. Near-best candidates are then
    compared by unsupported mandatory burden so broad checklists do not win by
    schema width. Stable name ordering only breaks otherwise equal contracts.
    """
    records = {
        str(package.get("name") or "").strip().lower(): package
        for package in packages
        if str(package.get("name") or "").strip()
    }
    chosen = list(
        dict.fromkeys(str(name).strip() for name in selected_names if str(name).strip())
    )
    chosen_lower = {name.lower() for name in chosen}
    desired_levels = {
        str(level).strip().lower()
        for level in levels
        if str(level).strip().lower() in {"sample", "assay"}
    }
    matches = source_schema_matches(packages, source_text)
    decisions: List[Dict[str, Any]] = []

    def selected_levels() -> set[str]:
        return {
            str(level).strip().lower()
            for name in chosen
            if name.lower() != "default"
            for level in (records.get(name.lower(), {}).get("sheets") or [])
            if str(level).strip().lower() in desired_levels
        }

    for level in sorted(desired_levels - selected_levels()):
        eligible = [
            match
            for match in matches
            if level in {str(item).strip().lower() for item in match.get("levels") or []}
            and str(match.get("package") or "").strip().lower() not in chosen_lower
        ]
        if not eligible:
            continue
        best_score = max(int(match.get("score") or 0) for match in eligible)
        score_floor = max(4, int(best_score * 0.75))
        ranked: List[tuple[int, int, int, int, str, Dict[str, Any]]] = []
        for match in eligible:
            score = int(match.get("score") or 0)
            if score < score_floor:
                continue
            package_name = str(match.get("package") or "").strip()
            package = records.get(package_name.lower())
            if not package:
                continue
            relevance = score_package_relevance(source_text, package)
            if relevance < 2:
                continue
            burden = mandatory_source_support(package, source_text)
            ranked.append(
                (
                    burden["unsupported_mandatory_count"],
                    burden["mandatory_count"],
                    -score,
                    -relevance,
                    package_name.lower(),
                    match,
                )
            )
        if not ranked:
            continue
        ranked.sort(key=lambda item: item[:5])
        winner_match = ranked[0][5]
        winner = str(winner_match.get("package") or "").strip()
        chosen.append(winner)
        chosen_lower.add(winner.lower())
        decisions.append(
            {
                "action": "add",
                "package": winner,
                "level": level,
                "schema_match": winner_match,
                "burden": mandatory_source_support(records[winner.lower()], source_text),
            }
        )
    return list(dict.fromkeys(chosen)), decisions


def source_schema_matches(
    packages: List[Dict[str, Any]],
    match_text: str,
    *,
    min_score: int = 4,
) -> List[Dict[str, Any]]:
    """Summarize strong source-to-schema matches for coverage auditing.

    This is package-agnostic: evidence comes from the current document and the
    real FAIR-DS field contract, including controlled values. It deliberately
    does not infer a package from a hard-coded assay or organism pattern.
    """
    document_tokens = _tokenize_for_matching(match_text)
    matches: List[Dict[str, Any]] = []
    for package in packages:
        if str(package.get("name") or "").strip().lower() == "default":
            continue
        field_hits: List[tuple[int, List[str], str]] = []
        for field in package.get("field_contract") or []:
            if not isinstance(field, dict):
                continue
            label = str(field.get("label") or "").strip()
            matched_values = [
                str(value).strip()
                for value in field.get("source_matched_values") or []
                if str(value).strip()
            ]
            field_score = 0
            field_evidence: List[str] = []
            if matched_values:
                field_score += 4 + min(2, len(matched_values) - 1)
                field_evidence.append(f"{label}={matched_values[0]}")
            field_text = " ".join(
                str(field.get(key) or "") for key in ("label", "definition")
            )
            overlap = document_tokens & _tokenize_for_matching(field_text)
            if overlap:
                field_score += min(2, len(overlap))
                field_evidence.append(
                    f"{label}: {', '.join(sorted(overlap)[:3])}"
                )
            if field_score:
                field_hits.append(
                    (
                        field_score,
                        field_evidence,
                        str(field.get("level") or "").strip().lower(),
                    )
                )
        # Prevent large checklists from winning merely because they contain
        # many generic fields. Applicability is based on the strongest few
        # source/contract correspondences, not raw schema width.
        strongest_hits = sorted(field_hits, key=lambda hit: -hit[0])[:3]
        score = sum(hit[0] for hit in strongest_hits)
        if score >= min_score:
            evidence = [
                item
                for _, hit_evidence, _ in strongest_hits
                for item in hit_evidence
            ]
            levels = list(
                dict.fromkeys(
                    level for _, _, level in strongest_hits if level
                )
            )
            matches.append(
                {
                    "package": str(package.get("name") or ""),
                    "score": score,
                    "evidence": list(dict.fromkeys(evidence))[:6],
                    "levels": levels,
                }
            )
    matches.sort(key=lambda item: (-int(item["score"]), item["package"].lower()))
    return matches


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

    for field in package.get("field_contract") or []:
        if not isinstance(field, dict):
            continue
        field_tokens = _tokenize_for_matching(
            " ".join(
                str(field.get(key) or "") for key in ("label", "definition")
            )
        )
        score += min(2, len(doc_tokens & field_tokens))
        if field.get("source_matched_values"):
            score += 4

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
