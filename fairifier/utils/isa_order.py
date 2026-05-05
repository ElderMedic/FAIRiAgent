"""Canonical ISA level ordering helpers.

The repository should unfold ISA metadata in semantic hierarchy order:
investigation -> study -> observationunit -> sample -> assay.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence


ISA_LEVEL_ORDER: tuple[str, ...] = (
    "investigation",
    "study",
    "observationunit",
    "sample",
    "assay",
)

MULTI_ROW_ISA_LEVELS: tuple[str, ...] = (
    "observationunit",
    "sample",
    "assay",
)

SINGLE_ROW_ISA_LEVELS: tuple[str, ...] = (
    "investigation",
    "study",
)

ISA_LEVEL_INDEX: dict[str, int] = {
    level: index for index, level in enumerate(ISA_LEVEL_ORDER)
}


def ordered_isa_levels(
    levels: Iterable[str],
    *,
    include_unknown_tail: bool = True,
) -> List[str]:
    """Return ISA levels sorted by canonical order.

    Unknown levels are appended in lexical order by default so callers preserve
    deterministic output even when upstream data introduces new sheet labels.
    """
    seen = {
        str(level).strip().lower()
        for level in levels
        if str(level).strip()
    }
    ordered = [level for level in ISA_LEVEL_ORDER if level in seen]
    if include_unknown_tail:
        ordered.extend(sorted(level for level in seen if level not in ISA_LEVEL_INDEX))
    return ordered


def ordered_isa_mapping(
    mapping: Sequence[str] | dict[str, object],
    *,
    include_unknown_tail: bool = True,
) -> List[str]:
    """Convenience wrapper for already-materialized level containers."""
    if isinstance(mapping, dict):
        return ordered_isa_levels(mapping.keys(), include_unknown_tail=include_unknown_tail)
    return ordered_isa_levels(mapping, include_unknown_tail=include_unknown_tail)
