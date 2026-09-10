"""Validation helpers for FAIR-DS field value contracts.

FAIR-DS field labels describe the workbook columns, while their term records
may additionally constrain cell values with ``regex``/``syntax``.  These
helpers keep that second part of the contract available to generation,
mapping, validation, and deliverable auditing without embedding
domain- or input-specific aliases.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from fairifier.services.fairds_api_parser import FAIRDSAPIParser


ContractIndex = Dict[Tuple[str, str], Dict[str, Any]]


def normalize_field_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _usable_pattern(metadata: Mapping[str, Any]) -> str:
    """Return a compilable FAIR-DS hard value pattern, if one is declared.

    ``syntax`` is retained for prompts and documentation but is not itself a
    validation guarantee; FAIR-DS uses templates such as ``{number}`` there.
    Only the explicit ``regex`` field defines the machine-enforced boundary.
    """
    raw = str(metadata.get("regex") or "").strip()
    if not raw:
        return ""
    try:
        re.compile(raw)
    except re.error:
        return ""
    return raw


def usable_regex_pattern(value: Any) -> str:
    """Return a compilable regex string, or empty for invalid service data."""
    return _usable_pattern({"regex": value})


def build_contract_index(items: Iterable[Mapping[str, Any]]) -> ContractIndex:
    """Index retrieved FAIR-DS definitions by canonical ISA level and term."""
    index: ContractIndex = {}
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        nested = item.get("metadata")
        metadata = nested if isinstance(nested, Mapping) else item
        field_name = normalize_field_name(
            item.get("term")
            or item.get("field_name")
            or item.get("name")
            or item.get("label")
            or metadata.get("term")
            or metadata.get("field_name")
            or metadata.get("name")
            or metadata.get("label")
        )
        level = FAIRDSAPIParser.normalize_isa_sheet(
            metadata.get("isa_sheet") or metadata.get("sheet")
        )
        pattern = _usable_pattern(metadata)
        if not field_name or not level or not pattern:
            continue
        index[(level, field_name)] = {
            "pattern": pattern,
            "regex": str(metadata.get("regex") or "").strip(),
            "syntax": str(metadata.get("syntax") or "").strip(),
            "example": metadata.get("example"),
            "definition": metadata.get("definition") or item.get("definition"),
        }
    return index


def literal_enum_choices(pattern: str) -> Tuple[str, ...]:
    """Extract choices only from a simple literal ``(A|B|C)`` pattern.

    This deliberately refuses nested or expressive regular expressions.  It is
    used only to restore canonical casing for an already equivalent value, not
    to guess scientific semantics.
    """
    text = str(pattern or "").strip()
    if text.startswith("^"):
        text = text[1:]
    if text.endswith("$"):
        text = text[:-1]
    if len(text) < 3 or not (text.startswith("(") and text.endswith(")")):
        return ()
    inner = text[1:-1]
    if any(char in inner for char in "()[]{}\\?*^"):
        return ()
    choices = tuple(part for part in inner.split("|") if part)
    if len(choices) < 2:
        return ()
    if any(not re.fullmatch(r"[A-Za-z0-9_.+ /-]+", choice) for choice in choices):
        return ()
    return choices


def canonicalize_value(value: Any, contract: Mapping[str, Any]) -> Optional[str]:
    """Return a contract-valid value, or ``None`` when it cannot be justified.

    Exact matches are preserved.  Case-only differences against a literal
    enumeration are canonicalized.  Semantic aliases are intentionally left to
    the LLM with the full field contract and source evidence.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    pattern = str(contract.get("pattern") or "").strip()
    if not pattern:
        return text
    try:
        if re.fullmatch(pattern, text):
            return text
    except re.error:
        return text
    folded = " ".join(text.casefold().split())
    for choice in literal_enum_choices(pattern):
        if " ".join(choice.casefold().split()) == folded:
            return choice
    return None


def is_field_selector_contract(
    contract: Mapping[str, Any], field_names: Iterable[Any]
) -> bool:
    """Return whether an enum selects other fields rather than storing values.

    FAIR-DS includes schema fields whose allowed values are the names of other
    fields (for example, a design-factor selector).  Such a column may store
    the selected variable name, but entity dimension values belong in the
    selected value field.  Detect this from the live contract graph rather than
    from a package, organism, input, or hard-coded field-name pattern.
    """
    choices = literal_enum_choices(str(contract.get("pattern") or ""))
    if not choices:
        return False
    available = {normalize_field_name(name) for name in field_names if name}
    matches = {
        normalize_field_name(choice)
        for choice in choices
        if normalize_field_name(choice) in available
    }
    return len(matches) >= 2


def contract_for(
    index: Mapping[Tuple[str, str], Mapping[str, Any]],
    level: str,
    field_name: str,
) -> Optional[Mapping[str, Any]]:
    return index.get((str(level or "").strip().lower(), normalize_field_name(field_name)))
