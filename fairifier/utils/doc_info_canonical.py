"""Canonicalize DocumentParser output to a fixed schema.

Different LLM providers and prompts return varying field names for the same
concept (`investigation_title` vs `title`, `summary` vs `abstract`, etc.).
This module maps those aliases to canonical field names ONCE at the
DocumentParser boundary, so downstream agents (KnowledgeRetriever,
JSONGenerator, ISAValueMapper) can rely on a stable contract instead of
maintaining defensive fallback chains.

See ARCHITECTURE_REFACTOR_PLAN.md §1 (P0 — document_info fixed schema).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# Aliases mapped to a canonical field. Order in each list does NOT matter:
# the canonical field (when present) always wins over aliases.
_ALIAS_MAP: Dict[str, List[str]] = {
    "title": [
        "investigation_title",
        "project_title",
        "study_title",
        "document_title",
        "article_title",
    ],
    "abstract": [
        "summary",
        "description",
        "investigation_description",
        "project_abstract",
        "study_abstract",
    ],
    "authors": [
        "investigators",
        "personnel",
        "consortium",
    ],
    "keywords": [
        "tags",
        "topics",
    ],
    "research_domain": [
        "domain",
        "field_of_study",
        "research_area",
        # 'scientific_domain' handled specially because it can be a dict
    ],
}

# Canonical fields that are passed through unchanged when present.
# Anything not in this set or _ALIAS_MAP is dropped.
_CANONICAL_FIELDS = frozenset(
    {
        "document_type",
        "title",
        "abstract",
        "authors",
        "keywords",
        "research_domain",
        "methodology",
        "location",
        "coordinates",
        "doi",
        "journal",
        "publication_date",
        "datasets_mentioned",
        "instruments",
        "variables",
        "key_findings",
        "confidence",
    }
)

# Maximum length when extracting title from free-form text fragments.
_TITLE_MAX_LEN = 250
_TITLE_MIN_LEN = 10


def canonicalize_doc_info(doc_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Map LLM-returned field aliases to canonical names.

    Behavior:
    - Returns ``{}`` for ``None`` or empty input.
    - Unwraps ``{"metadata": {...}}`` wrapper if the LLM nested its output.
    - Pulls fields from ``metadata_for_fair_principles`` nested dict if needed.
    - Maps known aliases (e.g. ``summary`` → ``abstract``) to canonical fields.
    - Collapses dict-valued ``scientific_domain`` to a single string.
    - Normalizes ``authors`` and ``keywords`` to lists, filtering empties.
    - Drops any field that is neither canonical nor a known alias.

    Args:
        doc_info: Raw extraction dict from the parser LLM, possibly with aliases.

    Returns:
        A dict using only canonical field names. Empty if input is empty/None.
    """
    if not doc_info:
        return {}

    if not isinstance(doc_info, dict):
        return {}

    # Unwrap common LLM wrapper: {"metadata": {actual_fields}}.
    if "metadata" in doc_info and isinstance(doc_info["metadata"], dict):
        # Merge: outer fields take precedence over inner
        merged = dict(doc_info["metadata"])
        for key, value in doc_info.items():
            if key != "metadata":
                merged[key] = value
        doc_info = merged

    # Pull nested metadata_for_fair_principles fields up to top level (if missing there).
    fair_meta = doc_info.get("metadata_for_fair_principles")
    if isinstance(fair_meta, dict):
        for key, value in fair_meta.items():
            doc_info.setdefault(key, value)

    result: Dict[str, Any] = {}

    # 1. Apply alias map (canonical wins over alias).
    for canonical, aliases in _ALIAS_MAP.items():
        if canonical in doc_info and _is_meaningful(doc_info[canonical]):
            result[canonical] = doc_info[canonical]
        else:
            for alias in aliases:
                if alias in doc_info and _is_meaningful(doc_info[alias]):
                    result[canonical] = doc_info[alias]
                    break

    # 2. Special handling for scientific_domain (dict or string).
    if "research_domain" not in result:
        sd = doc_info.get("scientific_domain")
        if isinstance(sd, str) and sd.strip():
            result["research_domain"] = sd.strip()
        elif isinstance(sd, dict):
            collapsed = _collapse_domain_dict(sd)
            if collapsed:
                result["research_domain"] = collapsed

    # 3. Pass through canonical fields not handled above.
    for key, value in doc_info.items():
        if key in _CANONICAL_FIELDS and key not in result and _is_meaningful(value):
            result[key] = value

    # 4. Normalize list-shaped fields.
    if "authors" in result:
        result["authors"] = _normalize_to_str_list(result["authors"])
        if not result["authors"]:
            del result["authors"]
    if "keywords" in result:
        result["keywords"] = _normalize_to_str_list(result["keywords"])
        if not result["keywords"]:
            del result["keywords"]
    if "datasets_mentioned" in result:
        result["datasets_mentioned"] = _normalize_to_str_list(
            result["datasets_mentioned"]
        )
    if "instruments" in result:
        result["instruments"] = _normalize_to_str_list(result["instruments"])
    if "variables" in result:
        result["variables"] = _normalize_to_str_list(result["variables"])
    if "key_findings" in result:
        result["key_findings"] = _normalize_to_str_list(result["key_findings"])

    return result


def _is_meaningful(value: Any) -> bool:
    """A value is meaningful if it is non-empty after stripping whitespace."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def _normalize_to_str_list(value: Any) -> List[Any]:
    """Coerce a value to a list, filtering empties.

    For author/keyword-style fields, dicts are kept as-is (downstream code
    that needs structured author info — name, affiliation — relies on this).
    Other non-string scalars are stringified.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    out: List[Any] = []
    for item in value:
        if item is None or item == "":
            continue
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str):
            stripped = item.strip()
            if stripped:
                out.append(stripped)
        else:
            out.append(str(item))
    return out


def _collapse_domain_dict(sd: Dict[str, Any]) -> Optional[str]:
    """Collapse a structured ``scientific_domain`` dict into a single string."""
    primary = sd.get("primary_field") or sd.get("domain") or sd.get("field")
    subfields = sd.get("subfields") or sd.get("subdomains") or []
    if not primary:
        return None
    if subfields:
        sub_strs = [str(s) for s in subfields[:5] if s]
        if sub_strs:
            return f"{primary} ({', '.join(sub_strs)})"
    return str(primary)
