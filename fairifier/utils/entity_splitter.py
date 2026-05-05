"""Shared utility for splitting merged LLM outputs into multiple entity rows."""
import logging
import re
from typing import Any, Dict, List, Tuple
from fairifier.utils.isa_order import MULTI_ROW_ISA_LEVELS

logger = logging.getLogger(__name__)

ENTITY_SEPARATOR_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("numbered_group", re.compile(r"(?=(?:Experiment|Group|Treatment)\s+\d+)", re.IGNORECASE)),
]

def calc_entity_count_from_semicolons(text: str) -> Tuple[int, List[str]]:
    if ";" not in text:
        return 1, []
    parts = [p.strip() for p in text.split(";") if p.strip()]
    meaningful = [p for p in parts if len(p) > 10]
    if len(meaningful) < 2:
        return 1, []
    avg_len = sum(len(p) for p in meaningful) / len(meaningful)
    similar = all(avg_len * 0.3 < len(p) < avg_len * 3.0 for p in meaningful)
    if not similar:
        return 1, []
    return len(meaningful), meaningful

def calc_entity_count_from_patterns(text: str) -> Tuple[int, List[str]]:
    text_stripped = text.strip()
    for _name, pattern in ENTITY_SEPARATOR_PATTERNS:
        parts = pattern.split(text_stripped)
        parts = [p.strip() for p in parts if len(p.strip()) > 10]
        if len(parts) >= 2:
            return len(parts), parts
    return 1, []

def detect_entity_count(row: Dict[str, Any]) -> Tuple[int, str, List[str]]:
    best_count = 1
    best_field = ""
    best_parts: List[str] = []

    for key, value in row.items():
        if not value:
            continue
        val_lower = str(value).lower()
        if "not specified" in val_lower:
            continue

        text = str(value)
        count, parts = calc_entity_count_from_semicolons(text)
        if count > best_count:
            best_count = count
            best_field = key
            best_parts = parts

        count2, parts2 = calc_entity_count_from_patterns(text)
        if count2 > best_count:
            best_count = count2
            best_field = key
            best_parts = parts2

    return best_count, best_field, best_parts

def build_split_row(
    original_row: Dict[str, Any],
    entity_index: int,
    total_entities: int,
    best_field: str,
    best_parts: List[str],
) -> Dict[str, Any]:
    entity_row: Dict[str, Any] = {}
    for key, value in original_row.items():
        text = str(value) if value else ""
        if ";" in text:
            parts = [p.strip() for p in text.split(";") if p.strip()]
            if parts:
                entity_row[key] = parts[entity_index] if entity_index < len(parts) else parts[-1]
            else:
                entity_row[key] = value
            continue

        if key == best_field:
            if best_parts:
                entity_row[key] = best_parts[entity_index] if entity_index < len(best_parts) else best_parts[-1]
            else:
                entity_row[key] = value
            continue

        entity_row[key] = value
    return entity_row

def split_entities_in_isa_structure(isa_structure: Dict[str, Any]) -> Dict[str, Any]:
    for sheet_name in MULTI_ROW_ISA_LEVELS:
        sheet = isa_structure.get(sheet_name)
        if not isinstance(sheet, dict):
            continue
        rows = sheet.get("rows", [])
        if len(rows) != 1:
            continue

        row = rows[0]
        count, best_field, best_parts = detect_entity_count(row)
        if count < 2:
            continue

        new_rows = [
            build_split_row(row, i, count, best_field, best_parts)
            for i in range(count)
        ]
        sheet["rows"] = new_rows
        logger.debug(
            "Entity split: '%s' 1 -> %d rows (driving field='%s')",
            sheet_name, count, best_field,
        )

    for sheet_name in MULTI_ROW_ISA_LEVELS:
        sheet = isa_structure.get(sheet_name)
        if not isinstance(sheet, dict):
            continue
        rows = sheet.get("rows", [])
        columns = sheet.get("columns", [])
        if rows and columns:
            sheet["fields"] = [
                {"field_name": col, "value": rows[0].get(col.strip().lower())}
                for col in columns
            ]
    return isa_structure
