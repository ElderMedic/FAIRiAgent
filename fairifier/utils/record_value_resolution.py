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
  parent) and a verbatim passage from the document, not generated context;
* within a planned source group, one cited record attribute cannot justify
  different values for the same column. Unknown groups retain the global
  consistency check.

Nothing here depends on field names, domains, or input-specific patterns.
"""

from __future__ import annotations

import json
import re
from itertools import zip_longest
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from ..services.publication_tables import DERIVED_TABLE_ROWS_HEADER, render_table_rows, unit_key
from .document_text import normalize_source_evidence_text
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
_MAX_SOURCE_PASSAGE_CHARS = 1400
_MAX_GROUP_NEEDLES = 12


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _norm(value: Any) -> str:
    return " ".join(_text(value).strip().lower().split())


def _source_norm(value: Any) -> str:
    """Normalize typography and whitespace without discarding scientific symbols."""
    return normalize_source_evidence_text(value)


def _source_contains(source: str, fragment: str) -> bool:
    if not fragment:
        return False
    pattern = r"(?<!\w)" + re.escape(fragment) + r"(?!\w)"
    for match in re.finditer(pattern, source):
        start, end = match.span()
        # A quote may omit sentence punctuation, but cannot start inside a
        # signed/decimal number or omit the fractional part of its last number.
        if start and fragment[0].isdigit() and source[start - 1] in "+-.,":
            continue
        if fragment[-1].isdigit() and re.match(r"[.,]\d", source[end:]):
            continue
        return True
    return False


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


def _aligned_entities(
    entity_plan: Mapping[str, Any], level: str, rows: List[Mapping[str, Any]],
) -> Optional[List[Mapping[str, Any]]]:
    """Join rows to plan entities through unique internal or external identifiers."""
    entities = _level_entities(entity_plan, level)
    if len(rows) != len(entities):
        return None
    canonical: Dict[str, int] = {}
    aliases: Dict[str, set[int]] = {}
    for index, entity in enumerate(entities):
        row_id = _text(entity.get("row_id")).strip()
        if not row_id or row_id in canonical:
            return None
        canonical[row_id] = index
        external_id = _text(entity.get("external_identifier")).strip()
        if external_id:
            aliases.setdefault(external_id, set()).add(index)
    aligned: List[Mapping[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        identifier = _text(row.get(_ID_FIELDS[level])).strip()
        index = canonical.get(identifier)
        if index is None:
            matches = aliases.get(identifier, set())
            if len(matches) != 1:
                return None
            index = next(iter(matches))
        if index in seen:
            return None
        seen.add(index)
        aligned.append(entities[index])
    return aligned


def _attribute_pairs(entity: Optional[Mapping[str, Any]]) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for attribute in (entity or {}).get("attributes") or []:
        if not isinstance(attribute, Mapping):
            continue
        value = _text(attribute.get("value")).strip()
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
    *,
    additional_columns: Optional[Mapping[str, Iterable[str]]] = None,
) -> Dict[str, List[str]]:
    """Return incomplete columns plus explicitly requested source reviews.

    Plan-owned attribute columns, identity/narrative/linkage columns, and
    columns declared level-wide by the restore step are excluded: those
    already have an authoritative owner.
    """
    partial: Dict[str, List[str]] = {}
    for level in MULTI_ROW_ISA_LEVELS:
        block = matrix.get(level) or {}
        rows = [row for row in block.get("rows") or [] if isinstance(row, Mapping)]
        entities = _aligned_entities(entity_plan, level, rows)
        if not entities:
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
            if 0 < filled < len(rows) or column in (additional_columns or {}).get(level, ()):
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
        value = _text(row.get(column)).strip()
        if not _is_blank(value):
            values.setdefault(_norm(value), value)
    for field in fields:
        if str(field.get("field_name") or "").strip().lower() != column:
            continue
        value = _text(field.get("value")).strip()
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


def derived_table_rows_matching(
    text: str, needles: Iterable[str], max_chars: int = 6000,
) -> List[str]:
    """Whole header-labelled table rows that name any of ``needles``.

    A pivoted table names a record's attributes in its row label and column
    headers; a character window around a match would cut either off.
    """
    from ..services.publication_tables import DERIVED_TABLE_ROWS_HEADER

    _, marker, derived = (text or "").partition(DERIVED_TABLE_ROWS_HEADER)
    if not marker:
        return []
    patterns = [p for p in (_needle_pattern(n) for n in dict.fromkeys(needles)) if p]
    rows, used = [], 0
    for line in derived.splitlines():
        if "=" not in line or not any(p.search(line) for p in patterns):
            continue
        if used + len(line) > max_chars:
            break
        rows.append(line)
        used += len(line)
    return rows


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
    """Reserve the context budget for source passages across requested fields."""
    fields = list(fields)
    parts: List[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        key = _norm(text)
        if key and key not in seen:
            seen.add(key)
            parts.append(text)

    # Generated hints must not consume the budget before any original text.
    # Interleave field-specific matches so a frequent early-document value
    # cannot displace evidence for a different field near the end of the paper.
    windows_by_field = []
    for column in columns:
        needles = list(candidates.get(column) or [])
        needles.extend(
            str(field.get("evidence") or "").strip()
            for field in fields
            if str(field.get("field_name") or "").strip().lower() == column
            and field.get("evidence")
        )
        windows_by_field.append(_source_windows(document_text, needles))
    group_values = list(group_values)
    for line in derived_table_rows_matching(
        document_text, group_values, max_chars=_MAX_CONTEXT_CHARS // 3,
    ):
        add(f"[source table row] {line}")
    windows_by_field.append(_source_windows(document_text, group_values))
    for round_windows in zip_longest(*windows_by_field):
        for window in round_windows:
            if window:
                add(f"[source passage] {window[:_MAX_SOURCE_PASSAGE_CHARS]}")

    for field in fields:
        name = str(field.get("field_name") or "").strip().lower()
        evidence = str(field.get("evidence") or "").strip()
        if name in columns and evidence:
            add(f"[unverified {name} extraction hint] {evidence[:_MAX_FIELD_EVIDENCE_CHARS]}")

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
            f"[unverified design group {group.get('group_id')}: {group.get('label')}] {evidence}"
            + (f" Dimensions: {'; '.join(dimensions)}" if dimensions else "")
        )

    context = "\n".join(parts)
    return context[:_MAX_CONTEXT_CHARS]


def build_record_payloads(
    level: str,
    entity_plan: Mapping[str, Any],
    rows: List[Mapping[str, Any]],
    columns: List[str],
) -> List[Dict[str, Any]]:
    """Describe each record by its own plan attributes and current cells."""
    entities = _aligned_entities(entity_plan, level, rows)
    if entities is None:
        return []
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
                "current": {column: _text(row.get(column)) for column in columns},
            }
        )
    return payloads


RESOLUTION_SYSTEM_PROMPT = (
    "You assign per-record metadata values. For each record and each requested "
    "column, decide the value for THAT record only, using that record's own "
    "attributes and the supplied source context.\n"
    "Only document passages are evidence. Extraction hints and design descriptions "
    "are unverified proposals; do not quote them as source passages.\n"
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
    parts = [
        f"ISA level: {level}",
        "Columns and candidate values:\n"
        + json.dumps({column: candidates.get(column) or [] for column in columns}, ensure_ascii=False, indent=1),
    ]
    if source_context:
        parts.append("Source context:\n" + source_context)
    parts.append("Records:\n" + json.dumps(records, ensure_ascii=False, indent=1))
    return "\n\n".join(parts)


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


def _cited_keys(citable: Mapping[str, str], attribute: str) -> List[str]:
    """Consistency keys of the record attribute(s) a decision cites.

    A citation may combine several of the record's own entries
    ("enzyme=X, substrate=Y"); every part must then be citable. Empty when
    any part is not an entry of this record.
    """
    def one(part: str) -> Optional[str]:
        key = citable.get(part)
        if key is None and "=" in part:
            key = citable.get(_norm(part.partition("=")[2]))
        return key

    key = one(attribute)
    if key is not None:
        return [key]
    parts = [part for part in re.split(r"\s*[;,]\s*|\s+and\s+", attribute) if part]
    keys = [one(part) for part in parts] if len(parts) > 1 else [None]
    return [] if None in keys else keys  # type: ignore[return-value]


_TABLE_QUANTITY_RE = re.compile(
    r"\s*((?:[+-]?(?:\d+(?:\.\d+)?|\.\d+))(?:\s*±\s*(?:\d+(?:\.\d+)?|\.\d+))?)"
    r"(?:\s+(\S.*?))?\s*"
)
_NUMERIC_START_RE = re.compile(r"[<>≤≥~]?\s*[+-]?\.?\d")


def _is_numeric_cell(cell: str) -> bool:
    """A value cell, not a row label: "9.7 ± 0.5" or "55 °C", but not "3 min at 115°C"."""
    return bool(_NUMERIC_START_RE.match(cell)) and not re.search(r"[A-Za-z]{3,}", cell)


def _entries(record: Mapping[str, Any]) -> List[Tuple[str, str]]:
    pairs = []
    for key in ("attributes", "parent_attributes"):
        for entry in record.get(key) or []:
            name, _, value = str(entry).partition("=")
            if value.strip():
                pairs.append((_norm(name), _norm(value)))
    return list(dict.fromkeys(pairs))


def _rivals(entries: List[List[Tuple[str, str]]]) -> List[Dict[str, set]]:
    """Per record: other records' values of the attributes it also carries."""
    rivals: List[Dict[str, set]] = []
    for own in entries:
        own_values = dict(own)
        rival: Dict[str, set] = {}
        for other in entries:
            for name, value in other:
                if name in own_values and value != own_values[name]:
                    rival.setdefault(name, set()).add(value)
        rivals.append(rival)
    return rivals


def align_cells_with_source_tables(
    level: str,
    entity_plan: Mapping[str, Any],
    rows: List[Dict[str, Any]],
    document_text: str,
) -> List[str]:
    """Check mapped quantities against the record coordinates of source tables.

    A cell whose value sits in a derived table row under another record's
    coordinates (row label or pivoted sub-column), and under none of this
    record's own, was copied from the wrong row and is cleared. A value with
    its unit that is this record's own ``mean ± error`` cell without the
    error gets the error back. The unit (the value's own, else one of the
    row's unit columns) must match the cell's column header, so a bare number
    is never compared across quantities. Values the tables do not bind to any
    record are left to the other checks.
    """
    _, sep, derived = document_text.partition(DERIVED_TABLE_ROWS_HEADER)
    lines = [_source_norm(line) for line in derived.splitlines() if "=" in line] if sep else []
    records = build_record_payloads(level, entity_plan, rows, []) if lines else []
    if not records:
        return []
    entries = [_entries(record) for record in records]
    rivals = _rivals(entries)

    def bound(index: int, quantity: str, line: str) -> Optional[str]:
        """None: not in this line; "": a cell of another record; else the value."""
        binding = _table_cell_binding(quantity, line, entries[index], rivals[index])
        return None if binding is None else (binding[1] if binding[0] else "")

    issues: List[str] = []
    for index, row in enumerate(rows):
        name = records[index]["identifier"] or records[index]["record_id"]
        foreign: List[Tuple[str, str]] = []
        row_units = [
            _text(cell).strip() for column, cell in row.items()
            if str(column).strip().lower().endswith("unit") and _text(cell).strip()
        ]
        for column, raw in list(row.items()):
            value = _text(raw).strip()
            match = _TABLE_QUANTITY_RE.fullmatch(value) if value else None
            if not match:
                continue
            quantities = [value] if match.group(2) else [f"{value} {unit}" for unit in row_units]
            verdicts = [
                (quantity, line, bound(index, quantity, line))
                for quantity in quantities for line in lines
            ]
            own = next((verdict for _, _, verdict in verdicts if verdict), None)
            if own:
                if match.group(2) and own != value:
                    row[column] = own
                    issues.append(f"Source table reports {level}.{column} for {name} as {own!r}.")
                continue
            if any(
                bound(other, quantity, line)
                for quantity, line, verdict in verdicts if verdict == ""
                for other in range(len(records)) if other != index
            ):
                foreign.append((column, value))
        # The row's own "mean ± error" cell makes a bare error term its own
        # (LCC Km 25.82 ± 2.31 vs another record's Km of 2.31); judged after
        # the ± restoration above so column order does not matter.
        for column, value in foreign:
            own_error = re.compile(r"±\s*" + re.escape(value) + r"(?![\d.])")
            if any(own_error.search(_text(cell)) for other, cell in row.items() if other != column):
                continue
            row[column] = ""
            issues.append(
                f"Source table assigns {level}.{column}={value!r} to another record, "
                f"not {name}; cleared."
            )
    return issues


def _table_cell_binding(
    value: str,
    quote: str,
    entries: List[Tuple[str, str]],
    rivals: Mapping[str, set],
) -> Optional[Tuple[List[str], Optional[str]]]:
    """Bind a quantity to a record through a derived table row in ``quote``.

    Derived rows read ``<label> = <x>; <column> | <sub-column> = <cell>``.
    When ``value`` is a cell of the quoted row, the table decides which record
    it belongs to, not the attribute the judge cited: the cell's column header
    and the row's label cells must name this record's own attribute values and
    no other record's value of the same attribute; under a pivoted column
    (several sub-columns) the cell's sub-column must name this record. The
    magnitude must be the whole cell or its mean before ``±``; a unit must be
    in the column header.

    Returns None when no cell of the quote holds the value, ``([], None)``
    when one does but not for this record, else (consistency keys, value);
    a mean with a unit taken from a ``mean ± error`` cell comes back with
    its error.
    """
    match = _TABLE_QUANTITY_RE.fullmatch(value)
    if not match:
        return None
    magnitude = re.sub(r"\s+", "", match.group(1))
    unit = unit_key(match.group(2) or "")
    cells = [
        (header.strip(), cell.strip())
        for header, sep, cell in (part.partition("=") for part in quote.split(";"))
        if sep
    ]
    labels = " ; ".join(
        f"{header} = {cell}" for header, cell in cells
        if "|" not in header and not _is_numeric_cell(cell)
    )
    sub_columns: Dict[str, set] = {}
    for header, _ in cells:
        top, _, sub = header.partition("|")
        sub_columns.setdefault(top.strip(), set()).add(sub.strip().lower())
    found = False
    for header, cell in cells:
        compact = re.sub(r"\s+", "", cell)
        if magnitude not in (compact, compact.partition("±")[0]):
            continue
        found = True
        if unit and ((len(unit) < 2 and unit != "%") or unit not in unit_key(header)):
            continue
        top, _, sub = header.partition("|")
        if len(sub_columns[top.strip()]) > 1 and not any(
            _source_contains(sub.lower(), own) for _, own in entries
        ):
            continue  # a pivoted cell must sit in this record's own sub-column
        coordinates = f"{header} ; {labels}".lower()
        keys = []
        for name, own in entries:
            if any(
                rival not in own and _source_contains(coordinates, rival)
                for rival in rivals.get(name, ())
            ):
                break
            if _source_contains(coordinates, own):
                keys.append(f"{name}={own}")
        else:
            if keys:
                if match.group(2) and "±" in compact and "±" not in value:
                    # The source reports mean ± error; a quantity with its unit
                    # keeps both. A bare number stays bare (its error has a
                    # column of its own).
                    return keys, f"{cell.strip()} {match.group(2)}"
                return keys, value.strip()
    return ([], None) if found else None


def _quote_table_binding(
    value: str,
    quote: str,
    entries: List[Tuple[str, str]],
    rivals: Mapping[str, set],
) -> Optional[Tuple[List[str], Optional[str]]]:
    """``_table_cell_binding`` for a quote that is a derived row or a raw table.

    A judge may cite the raw HTML table instead of its derived rows. The rows
    are a deterministic rendering of the same grid, so each is checked as if
    it had been cited.
    """
    binding = _table_cell_binding(value, quote, entries, rivals)
    if binding is not None or "<table" not in quote.lower():
        return binding
    for line in render_table_rows(quote):
        row = _table_cell_binding(value, _source_norm(line), entries, rivals)
        if row is not None and (row[0] or binding is None):
            binding = row
            if row[0]:
                break
    return binding


def _accepted_value(
    value: str,
    candidates: List[str],
    source_text: str,
    *,
    source_quote: str = "",
    record_attribute_values: Iterable[str] = (),
) -> Optional[str]:
    normalized = _norm(value)
    if not normalized or normalized in _PLACEHOLDERS:
        return None
    for candidate in candidates:
        if _norm(candidate) == normalized:
            return candidate
    literal = _source_norm(value)
    number = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"
    quantity = rf"(?:[<>≤≥]=?\s*)?{number}(?:\s*±\s*{number})?"
    if re.fullmatch(quantity, literal):
        # New numerical values must occur as a complete quantity in this
        # record's cited passage, not merely somewhere in the document.
        # Iterating whole quantities prevents taking a mean or uncertainty
        # fragment out of a reported mean ± uncertainty expression.
        if not all(
            _source_contains(source_quote.lower(), attribute.lower())
            for attribute in record_attribute_values
        ):
            return None
        quantities = re.finditer(
            rf"(?<![\w.+\-<>=≤≥±]){quantity}(?!\w|[.,]\d)", source_quote
        )
        if any(_source_norm(match.group()) == literal for match in quantities):
            return value.strip()
        return None
    if (
        len(normalized) >= 3
        and any(character.isalpha() for character in normalized)
        and _source_contains(source_text, literal)
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
    *,
    verified_cells: Optional[Dict[Tuple[int, str], str]] = None,
    reviewed_rows: Optional[Iterable[int]] = None,
) -> Tuple[List[str], Dict[str, int]]:
    """Validate judged values and write the accepted ones into ``rows``.

    ``rows`` and ``records`` are index-aligned. Returns review-worthy issues
    (replaced or cleared cells) and counts for logging. ``reviewed_rows``
    limits the reset of earlier verifications to the rows actually reviewed
    (a targeted repair reviews a subset).
    """
    # Generated retrieval hints may guide the judge, but cannot authenticate a
    # quote or introduce a value absent from both candidates and the document.
    source_text = _source_norm(document_text)
    if verified_cells is not None:
        for index in (range(len(rows)) if reviewed_rows is None else reviewed_rows):
            for column in columns:
                verified_cells.pop((index, column), None)
    by_id = {record["record_id"]: index for index, record in enumerate(records)}
    entries = [_entries(record) for record in records]
    rivals = _rivals(entries)
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
                if status != "supported":
                    if status in {"unsupported", "contradicted"}:
                        rejected += 1
                    continue
                quote = _source_norm(decision.get("source_quote"))
                binding = _quote_table_binding(
                    _text(decision.get("value")), quote, entries[index], rivals[index]
                )
                if binding is not None:
                    keys, accepted = binding
                else:
                    keys = _cited_keys(citable, _norm(decision.get("record_attribute")))
                    accepted = _accepted_value(
                        _text(decision.get("value")),
                        list(candidates.get(column) or []),
                        source_text,
                        source_quote=quote,
                        record_attribute_values=[key.partition("=")[2] for key in keys],
                    )
                consistency_key = " & ".join(sorted(set(keys))) if keys else None
                if (
                    consistency_key is None
                    or accepted is None
                    or len(quote.split()) < 3
                    or not _source_contains(source_text, quote)
                ):
                    rejected += 1
                    continue
                supported.append((index, column, consistency_key, accepted))

    # A donor or material can participate in separate experiments with
    # different procedures. Use the locked record's source group, never a
    # response-supplied group, to scope those comparisons. If a citation has
    # an unknown group, retain the conservative global check for that key.
    group_ids = [
        "" if _is_blank(record.get("source_group"))
        else _text(record["source_group"]).strip()
        for record in records
    ]
    unscoped_keys = {
        (column, key) for index, column, key, _ in supported if not group_ids[index]
    }

    def scoped_key(index: int, column: str, key: str) -> Tuple[str, str, str]:
        group = "" if (column, key) in unscoped_keys else group_ids[index]
        return column, key, group

    # Within that scope, reject every use of a non-discriminating attribute,
    # and clear a current value that rested on it.
    values_by_key: Dict[Tuple[str, str, str], set[str]] = {}
    values_by_cell: Dict[Tuple[int, str], set[str]] = {}
    for index, column, key, accepted in supported:
        values_by_key.setdefault(scoped_key(index, column, key), set()).add(_norm(accepted))
        values_by_cell.setdefault((index, column), set()).add(_norm(accepted))
    conflicting_cells = {cell for cell, values in values_by_cell.items() if len(values) > 1}
    writes: Dict[Tuple[int, str], str] = {}
    for index, column, key, accepted in supported:
        if (index, column) in conflicting_cells:
            rejected += 1
            continue
        if len(values_by_key[scoped_key(index, column, key)]) > 1:
            rejected += 1
            if _norm(rows[index].get(column)) == _norm(accepted):
                unsupported.append((index, column))
            continue
        writes[(index, column)] = accepted

    issues: List[str] = []
    filled = changed = cleared = 0

    def label(index: int) -> str:
        return records[index]["identifier"] or records[index]["record_id"]

    for index, column in sorted(conflicting_cells):
        current = _text(rows[index].get(column))
        issues.append(
            f"Conflicting record-level decisions for {level}.{column} on {label(index)}; "
            f"current value {current!r} left unchanged for review."
        )

    for (index, column), accepted in writes.items():
        row = rows[index]
        current = _text(row.get(column))
        if _is_blank(current):
            filled += 1
        elif _norm(current) != _norm(accepted):
            changed += 1
            issues.append(
                f"Record-level evidence replaced {level}.{column} for {label(index)}: "
                f"{current!r} -> {accepted!r}."
            )
        row[column] = accepted
        if verified_cells is not None:
            verified_cells[(index, column)] = accepted
    for index, column in dict.fromkeys(unsupported):
        if (index, column) in writes or (index, column) in conflicting_cells:
            continue
        current = _text(rows[index].get(column))
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
    "align_cells_with_source_tables",
    "collect_candidates",
    "find_partial_columns",
    "record_group_values",
]


# ── Compact review protocol: cite numbered source units instead of quotes ──

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])")


def segment_source_units(text: str, max_chars: int = 700) -> List[str]:
    """Split a source into citable units: lines, then sentences of long lines.

    Units are verbatim substrings of the source, so a cited unit is a source
    quote by construction. Header-labelled table rows stay one unit each.
    """
    units: List[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [line] if len(line) <= max_chars else _SENTENCE_SPLIT.split(line)
        for part in parts:
            part = part.strip()
            if part:
                units.append(part)
    return units


def render_numbered_units(units: List[str]) -> str:
    return "\n".join(f"[S{index}] {unit}" for index, unit in enumerate(units, start=1))


COMPACT_RESOLUTION_SYSTEM_PROMPT = (
    "You judge per-record metadata values against a numbered source. The source "
    "lines are labelled [S1], [S2], ... Decide each requested column for THAT "
    "record only.\n"
    "Rules:\n"
    "1. Give a value only when a numbered source unit links one of this record's "
    "own attribute values (identifier, label, source_group, attributes or "
    "parent_attributes) to that value. Cite the unit id(s) and the record "
    "attribute.\n"
    "2. Belonging to the same group as another record is not evidence when the "
    "source says that group used several values. No elimination or majority.\n"
    "3. Prefer a candidate value; otherwise copy the exact source wording.\n"
    "4. If a non-empty 'current' value has no support for this record, return it "
    "with value \"\" to clear it.\n"
    "5. Omit every cell you cannot decide. Report only decided cells.\n"
    "Return JSON only:\n"
    '{"records": [{"record_id": "...", "values": {"<column>": {"value": "...", '
    '"units": ["S12"], "attribute": "<one entry copied from this record, e.g. name=value>"}}}]}'
)


def expand_compact_response(parsed: Any, units: List[str]) -> Dict[str, Any]:
    """Convert a compact (unit-citing) answer to the standard decision format.

    Cited units become the verbatim ``source_quote``; an empty value means
    "unsupported". The standard ``apply_resolutions`` checks then apply
    unchanged (the value and record attribute must occur in the cited text).
    """
    records = []
    for item in (parsed or {}).get("records") or [] if isinstance(parsed, Mapping) else []:
        if not isinstance(item, Mapping) or not isinstance(item.get("values"), Mapping):
            continue
        values = {}
        for column, decision in item["values"].items():
            if not isinstance(decision, Mapping):
                continue
            if "source_quote" in decision or "status" in decision:
                values[column] = dict(decision)  # already in the standard format
                continue
            ids = decision.get("units") or decision.get("unit") or []
            ids = [ids] if isinstance(ids, str) else list(ids)
            quote_parts = []
            for unit_id in ids:
                match = re.fullmatch(r"\s*S?(\d+)\s*", str(unit_id))
                if match and 1 <= int(match.group(1)) <= len(units):
                    quote_parts.append(units[int(match.group(1)) - 1])
            value = str(decision.get("value") or "").strip()
            values[column] = {
                "value": value,
                "status": "supported" if value else "unsupported",
                "record_attribute": str(decision.get("attribute") or ""),
                "source_quote": " ".join(quote_parts),
            }
        records.append({"record_id": item.get("record_id"), "values": values})
    return {"records": records}
