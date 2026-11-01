"""Resolve partially populated per-record ISA columns record by record.

The matrix mapper often returns one representative row per experimental group.
Plan projection then copies a row-varying value (for example a library
preparation protocol) only onto the planned entity whose identifier matches
that representative row, so every sibling record stays blank. Broadcasting the
representative value to siblings would be unsafe: siblings that share a parent
condition can still differ in the varying value.

This module builds a bounded, record-level re-evaluation task instead. Each
record is judged on its own plan attributes together with source passages, and
an accepted value must satisfy deterministic checks:

* the value is an existing candidate for the column or occurs literally in the
  source text;
* the judge cites an attribute value that belongs to *this* record (or its
  parent) and a verbatim passage from the supplied source context;
* one cited record attribute never justifies different values for the same
  column (a non-discriminating attribute is rejected for every record).

Nothing here depends on field names, domains, or input-specific patterns.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .entity_plan import (
    _CONTACT_FIELDS,
    _DESCRIPTION_FIELDS,
    _ID_FIELDS,
    _NAME_FIELDS,
    _PARENT_FIELDS,
)
from .isa_order import ISA_LEVEL_ORDER, MULTI_ROW_ISA_LEVELS

RESERVED_COLUMNS = frozenset(
    {
        *_ID_FIELDS.values(),
        *_NAME_FIELDS.values(),
        *_DESCRIPTION_FIELDS.values(),
        *_PARENT_FIELDS.values(),
        *_CONTACT_FIELDS,
    }
)

_PLACEHOLDERS = frozenset(
    {"", "not specified", "n/a", "na", "none", "unknown", "null", "-", "tbd"}
)
_WINDOW_CHARS = 350
_WINDOWS_PER_CANDIDATE = 6
_MAX_FIELD_EVIDENCE_CHARS = 400
_MAX_GROUP_EVIDENCE_CHARS = 900
_MAX_CONTEXT_CHARS = 14000
_MAX_GROUP_NEEDLES = 12


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _loose(value: Any) -> str:
    """Normalize for quote matching: case, punctuation, and spacing agnostic."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", str(value or "").lower()).split())


def _is_blank(value: Any) -> bool:
    return _norm(value) in _PLACEHOLDERS


def _level_entities(entity_plan: Mapping[str, Any], level: str) -> List[Mapping[str, Any]]:
    for item in entity_plan.get("levels") or []:
        if isinstance(item, Mapping) and str(item.get("level") or "") == level:
            return [
                entity
                for entity in item.get("entities") or []
                if isinstance(entity, Mapping)
            ]
    return []


def _attribute_pairs(entity: Optional[Mapping[str, Any]]) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for attribute in (entity or {}).get("attributes") or []:
        if not isinstance(attribute, Mapping):
            continue
        value = str(attribute.get("value") or "").strip()
        if not value:
            continue
        name = str(
            attribute.get("dimension_name") or attribute.get("field_name") or "attribute"
        ).strip()
        pairs.append((name, value))
    return pairs


def find_partial_columns(
    matrix: Mapping[str, Any],
    entity_plan: Mapping[str, Any],
    fields_by_level: Mapping[str, List[Mapping[str, Any]]],
) -> Dict[str, List[str]]:
    """Return selected columns filled on some planned records but not others.

    Plan-owned attribute columns, identity/narrative/linkage columns, and
    columns declared level-wide by the restore step are excluded: those
    already have an authoritative owner.
    """
    partial: Dict[str, List[str]] = {}
    for level in MULTI_ROW_ISA_LEVELS:
        block = matrix.get(level) or {}
        rows = [row for row in block.get("rows") or [] if isinstance(row, Mapping)]
        entities = _level_entities(entity_plan, level)
        if len(entities) < 2 or len(rows) != len(entities):
            continue
        plan_owned = {
            str(attribute.get("field_name") or "").strip().lower()
            for entity in entities
            for attribute in entity.get("attributes") or []
            if isinstance(attribute, Mapping) and attribute.get("field_name")
        }
        shared = {
            str(column or "").strip().lower()
            for column in block.get("_shared_columns") or []
        }
        selected = [
            str(field.get("field_name") or "").strip().lower()
            for field in fields_by_level.get(level) or []
            if isinstance(field, Mapping) and str(field.get("field_name") or "").strip()
        ]
        columns: List[str] = []
        for column in dict.fromkeys(selected):
            if column in RESERVED_COLUMNS or column in plan_owned or column in shared:
                continue
            filled = sum(not _is_blank(row.get(column)) for row in rows)
            if 0 < filled < len(rows):
                columns.append(column)
        if columns:
            partial[level] = columns
    return partial


def collect_candidates(
    rows: Iterable[Mapping[str, Any]],
    column: str,
    fields: Iterable[Mapping[str, Any]],
) -> List[str]:
    """Distinct non-blank values already proposed for one column."""
    values: Dict[str, str] = {}
    for row in rows:
        value = str(row.get(column) or "").strip()
        if not _is_blank(value):
            values.setdefault(_norm(value), value)
    for field in fields:
        if str(field.get("field_name") or "").strip().lower() != column:
            continue
        value = str(field.get("value") or "").strip()
        if _is_blank(value):
            continue
        try:
            if float(field.get("confidence") or 0.0) <= 0.0 and "confidence" in field:
                continue
        except (TypeError, ValueError):
            pass
        values.setdefault(_norm(value), value)
    return list(values.values())


def _needle_pattern(needle: str) -> Optional[re.Pattern[str]]:
    words = re.findall(r"[0-9a-z]+", str(needle or "").lower())
    if not words or len("".join(words)) < 3:
        return None
    return re.compile(r"[\W_]+".join(re.escape(word) for word in words), re.IGNORECASE)


def _source_windows(text: str, needles: Iterable[str]) -> List[str]:
    """Passages around needle occurrences, spread across the whole document."""
    if not text:
        return []
    spans: List[Tuple[int, int]] = []
    for needle in dict.fromkeys(needles):
        pattern = _needle_pattern(needle)
        if pattern is None:
            continue
        hits = [match.span() for match in pattern.finditer(text)]
        if len(hits) > _WINDOWS_PER_CANDIDATE:
            step = (len(hits) - 1) / (_WINDOWS_PER_CANDIDATE - 1)
            hits = [hits[round(i * step)] for i in range(_WINDOWS_PER_CANDIDATE)]
        for begin, end in hits:
            spans.append(
                (max(0, begin - _WINDOW_CHARS), min(len(text), end + _WINDOW_CHARS))
            )
    spans.sort()
    merged: List[List[int]] = []
    for begin, end in spans:
        if merged and begin <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([begin, end])
    return [" ".join(text[begin:end].split()) for begin, end in merged]


def record_group_values(records: Iterable[Mapping[str, Any]]) -> List[str]:
    """Attribute values shared by several (not all) records: group-like labels.

    Passages naming such a value (e.g. a series or branch label) can tie a
    whole source-defined subset of records to a value; unique identifiers and
    constants shared by every record cannot.
    """
    records = list(records)
    counts: Dict[str, int] = {}
    originals: Dict[str, str] = {}
    for record in records:
        values = {str(record.get("source_group") or "")}
        for key in ("attributes", "parent_attributes"):
            values.update(str(entry).partition("=")[2] for entry in record.get(key) or [])
        for value in values:
            key = _norm(value)
            if (
                len(key) < 4
                or key in _PLACEHOLDERS
                or not any(character.isalpha() for character in key)
            ):
                continue
            counts[key] = counts.get(key, 0) + 1
            originals.setdefault(key, value)
    shared = [
        originals[key] for key, count in counts.items() if 1 < count < len(records)
    ]
    return shared[:_MAX_GROUP_NEEDLES]


def build_source_context(
    level: str,
    columns: List[str],
    candidates: Mapping[str, List[str]],
    fields: Iterable[Mapping[str, Any]],
    entity_plan: Mapping[str, Any],
    document_text: str,
    group_values: Iterable[str] = (),
) -> str:
    """Assemble bounded source context for one level's partial columns."""
    parts: List[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        key = _norm(text)
        if key and key not in seen:
            seen.add(key)
            parts.append(text)

    for field in fields:
        name = str(field.get("field_name") or "").strip().lower()
        evidence = str(field.get("evidence") or "").strip()
        if name in columns and evidence:
            add(f"[extracted {name} evidence] {evidence[:_MAX_FIELD_EVIDENCE_CHARS]}")

    design_spec = entity_plan.get("design_spec") or {}
    for group in design_spec.get("design_groups") or []:
        if not isinstance(group, Mapping):
            continue
        dimensions = []
        for dimension in group.get("dimensions") or []:
            if not isinstance(dimension, Mapping):
                continue
            levels = [
                str(item.get("value") or "").strip()
                for item in dimension.get("levels") or []
                if isinstance(item, Mapping) and str(item.get("value") or "").strip()
            ]
            if levels:
                dimensions.append(f"{dimension.get('name')}: {' | '.join(levels)}")
        evidence = str(group.get("evidence") or "").strip()[:_MAX_GROUP_EVIDENCE_CHARS]
        add(
            f"[design group {group.get('group_id')}: {group.get('label')}] {evidence}"
            + (f" Dimensions: {'; '.join(dimensions)}" if dimensions else "")
        )

    needles = [value for column in columns for value in candidates.get(column) or []]
    needles.extend(group_values)
    for window in _source_windows(document_text, needles):
        add(f"[source passage] {window}")

    context = "\n".join(parts)
    return context[:_MAX_CONTEXT_CHARS]


def build_record_payloads(
    level: str,
    entity_plan: Mapping[str, Any],
    rows: List[Mapping[str, Any]],
    columns: List[str],
) -> List[Dict[str, Any]]:
    """Describe each record by its own plan attributes and current cells."""
    entities = _level_entities(entity_plan, level)
    parent_level = (
        ISA_LEVEL_ORDER[ISA_LEVEL_ORDER.index(level) - 1] if level in _PARENT_FIELDS else ""
    )
    parents = {
        str(entity.get("row_id") or ""): entity
        for entity in _level_entities(entity_plan, parent_level)
    } if parent_level else {}
    payloads: List[Dict[str, Any]] = []
    for row, entity in zip(rows, entities):
        parent = parents.get(str(entity.get("parent_row_id") or ""))
        payloads.append(
            {
                "record_id": str(entity.get("row_id") or ""),
                "identifier": str(
                    entity.get("external_identifier") or row.get(_ID_FIELDS[level]) or ""
                ),
                "label": str(entity.get("label") or ""),
                "source_group": str(entity.get("source_group") or ""),
                "attributes": [f"{name}={value}" for name, value in _attribute_pairs(entity)],
                "parent_attributes": [
                    f"{name}={value}" for name, value in _attribute_pairs(parent)
                ],
                "current": {column: str(row.get(column) or "") for column in columns},
            }
        )
    return payloads


RESOLUTION_SYSTEM_PROMPT = (
    "You assign per-record metadata values. For each record and each requested "
    "column, decide the value for THAT record only, using that record's own "
    "attributes and the supplied source context.\n"
    "Rules:\n"
    "1. Assign a value only when a source passage links one of this record's own "
    "attribute values (identifier, label, source_group, attributes, or "
    "parent_attributes) to that value. Cite the record attribute and quote the "
    "passage verbatim.\n"
    "2. Belonging to the same parent, timepoint, condition, or group as another "
    "record is NOT evidence when the source says that group used more than one "
    "value for this column. Do not choose by elimination, majority, or position.\n"
    "3. Prefer a value from the candidate list; otherwise copy the exact source "
    "wording. Never invent or paraphrase values.\n"
    "4. A non-empty 'current' value is only a proposal. If the record's own "
    "evidence supports a different value, return that value with status "
    "'supported'. If nothing links this record to the current value (for example "
    "it was copied from a group that used several values), use status "
    "'unsupported' with value ''.\n"
    "5. Otherwise use status 'undetermined' with value ''. Blank is better than a guess.\n"
    "Return JSON only:\n"
    '{"records": [{"record_id": "...", "values": {"<column>": {"value": "...", '
    '"status": "supported|undetermined|unsupported", "record_attribute": '
    '"<one entry copied from this record, e.g. name=value>", "source_quote": '
    '"<verbatim passage, <= 40 words>"}}}]}'
)


def build_resolution_prompt(
    level: str,
    columns: List[str],
    candidates: Mapping[str, List[str]],
    source_context: str,
    records: List[Dict[str, Any]],
) -> str:
    return "\n\n".join(
        [
            f"ISA level: {level}",
            "Columns and candidate values:\n"
            + json.dumps({column: candidates.get(column) or [] for column in columns}, ensure_ascii=False, indent=1),
            "Source context:\n" + (source_context or "(none)"),
            "Records:\n" + json.dumps(records, ensure_ascii=False, indent=1),
        ]
    )


def _record_attribute_values(record: Mapping[str, Any]) -> Dict[str, str]:
    """Map normalized citable entries of one record to a consistency key."""
    citable: Dict[str, str] = {}
    for key in ("identifier", "label", "source_group"):
        value = str(record.get(key) or "").strip()
        if value:
            citable[_norm(value)] = f"{key}={_norm(value)}"
            citable[_norm(f"{key}={value}")] = f"{key}={_norm(value)}"
    for key in ("attributes", "parent_attributes"):
        for entry in record.get(key) or []:
            name, _, value = str(entry).partition("=")
            if not value.strip():
                continue
            consistency_key = f"{_norm(name)}={_norm(value)}"
            citable[_norm(entry)] = consistency_key
            citable[_norm(value)] = consistency_key
    return citable


def _accepted_value(
    value: str,
    candidates: List[str],
    corpus_loose: str,
) -> Optional[str]:
    normalized = _norm(value)
    if not normalized or normalized in _PLACEHOLDERS:
        return None
    for candidate in candidates:
        if _norm(candidate) == normalized:
            return candidate
    loose = _loose(value)
    if (
        len(normalized) >= 3
        and any(character.isalpha() for character in normalized)
        and loose
        and f" {loose} " in f" {corpus_loose} "
    ):
        return value.strip()
    return None


def apply_resolutions(
    level: str,
    rows: List[Dict[str, Any]],
    records: List[Dict[str, Any]],
    columns: List[str],
    candidates: Mapping[str, List[str]],
    responses: Iterable[Mapping[str, Any]],
    source_context: str,
    document_text: str,
) -> Tuple[List[str], Dict[str, int]]:
    """Validate judged values and write the accepted ones into ``rows``.

    ``rows`` and ``records`` are index-aligned. Returns review-worthy issues
    (replaced or cleared cells) and counts for logging.
    """
    corpus_loose = _loose(f"{source_context}\n{document_text}")
    by_id = {record["record_id"]: index for index, record in enumerate(records)}
    supported: List[Tuple[int, str, str, str]] = []
    unsupported: List[Tuple[int, str]] = []
    rejected = 0
    for response in responses:
        for item in (response or {}).get("records") or []:
            if not isinstance(item, Mapping):
                continue
            index = by_id.get(str(item.get("record_id") or ""))
            if index is None:
                continue
            citable = _record_attribute_values(records[index])
            for column, decision in (item.get("values") or {}).items():
                column = str(column or "").strip().lower()
                if column not in columns or not isinstance(decision, Mapping):
                    continue
                status = _norm(decision.get("status"))
                if status in {"unsupported", "contradicted"} and _is_blank(
                    decision.get("value")
                ):
                    unsupported.append((index, column))
                    continue
                if status not in {"supported", "unsupported", "contradicted"}:
                    continue
                attribute = _norm(decision.get("record_attribute"))
                consistency_key = citable.get(attribute)
                if consistency_key is None and "=" in attribute:
                    consistency_key = citable.get(_norm(attribute.partition("=")[2]))
                quote = _loose(decision.get("source_quote"))
                accepted = _accepted_value(
                    str(decision.get("value") or ""),
                    list(candidates.get(column) or []),
                    corpus_loose,
                )
                if (
                    consistency_key is None
                    or accepted is None
                    or len(quote.split()) < 3
                    or f" {quote} " not in f" {corpus_loose} "
                ):
                    rejected += 1
                    continue
                supported.append((index, column, consistency_key, accepted))

    # A cited attribute that justifies different values for one column does
    # not discriminate between records: reject every use of it, and treat a
    # current value that rested on it as unsupported.
    values_by_key: Dict[Tuple[str, str], set[str]] = {}
    for _, column, key, accepted in supported:
        values_by_key.setdefault((column, key), set()).add(_norm(accepted))
    writes: Dict[Tuple[int, str], str] = {}
    for index, column, key, accepted in supported:
        if len(values_by_key[(column, key)]) > 1:
            rejected += 1
            if _norm(rows[index].get(column)) == _norm(accepted):
                unsupported.append((index, column))
            continue
        writes[(index, column)] = accepted

    issues: List[str] = []
    filled = changed = cleared = 0

    def label(index: int) -> str:
        return records[index]["identifier"] or records[index]["record_id"]

    for (index, column), accepted in writes.items():
        row = rows[index]
        current = str(row.get(column) or "")
        if _is_blank(current):
            filled += 1
        elif _norm(current) != _norm(accepted):
            changed += 1
            issues.append(
                f"Record-level evidence replaced {level}.{column} for {label(index)}: "
                f"{current!r} -> {accepted!r}."
            )
        row[column] = accepted
    for index, column in dict.fromkeys(unsupported):
        if (index, column) in writes:
            continue
        current = str(rows[index].get(column) or "")
        if _is_blank(current):
            continue
        cleared += 1
        rows[index][column] = ""
        issues.append(
            f"No record-level evidence for {level}.{column}={current!r} on "
            f"{label(index)}; cleared."
        )
    stats = {
        "filled": filled,
        "replaced": changed,
        "cleared": cleared,
        "rejected": rejected,
    }
    return issues, stats


__all__ = [
    "RESOLUTION_SYSTEM_PROMPT",
    "apply_resolutions",
    "build_record_payloads",
    "build_resolution_prompt",
    "build_source_context",
    "collect_candidates",
    "find_partial_columns",
    "record_group_values",
]
