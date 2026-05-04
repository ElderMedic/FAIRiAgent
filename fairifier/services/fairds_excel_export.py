"""Standalone FAIR-DS metadata Excel generator with multi-row support.

Generates ``metadata_fairds.xlsx`` from the ``isa_structure`` in
``metadata.json``.

Features
--------
* **Local generation** — no API dependency; can produce a fully formatted
  workbook from the ISA structure alone.
* **Multi-row support** — each ISA sheet gets one Excel row per entity
  (the ``columns`` + ``rows`` format).
* **Entity splitting** — semicolon-separated values, "Experiment N" patterns,
  and other heuristics expand single merged rows into per-entity rows.
* **Backward compatibility** — the flat ``fields`` list is still accepted.
* **FAIR-DS API integration** — when an API URL is provided and reachable,
  ``POST /api/isa`` supplies the column headers (and any data rows the
  server writes); the local filling logic adds the remaining rows.
* **Graceful degradation** — if ``openpyxl`` is not installed, the function
  falls back to the API path; if neither works it returns ``None``.
"""

from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Entity splitting: constants & helpers ────────────────────────

_MULTI_ROW_LEVELS = frozenset({"assay", "sample", "observationunit"})
"""ISA sheets where multiple rows per entity are expected."""

_ENTITY_SEPARATOR_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # "Experiment N" / "Group N" / "Treatment N" (lower- or upper-case)
    (
        "numbered_group",
        re.compile(r"(?=(?:Experiment|Group|Treatment)\s+\d+)", re.IGNORECASE),
    ),
]
"""Named regex patterns for entity-boundary detection."""


def _calc_entity_count_from_semicolons(text: str) -> Tuple[int, List[str]]:
    """Detect entity count from semicolon-separated parts.

    Returns ``(count, meaningful_parts)`` where each part is a trimmed
    non-empty segment of *text*.  Returns ``(1, [])`` when no plausible
    multi-entity signal is found.
    """
    if ";" not in text:
        return 1, []

    parts = [p.strip() for p in text.split(";") if p.strip()]
    # Filter to "meaningful" parts (arbitrarily > 10 chars to skip
    # short list items that are likely a single field's comma list).
    meaningful = [p for p in parts if len(p) > 10]
    if len(meaningful) < 2:
        return 1, []

    # Roughly equal-length parts suggests genuine entity split.
    avg_len = sum(len(p) for p in meaningful) / len(meaningful)
    similar = all(avg_len * 0.3 < len(p) < avg_len * 3.0 for p in meaningful)
    if not similar:
        return 1, []

    return len(meaningful), meaningful


def _calc_entity_count_from_patterns(text: str) -> Tuple[int, List[str]]:
    """Detect entity count from named patterns (e.g. "Experiment 1 …")."""
    text_stripped = text.strip()
    for _name, pattern in _ENTITY_SEPARATOR_PATTERNS:
        parts = pattern.split(text_stripped)
        parts = [p.strip() for p in parts if len(p.strip()) > 10]
        if len(parts) >= 2:
            return len(parts), parts
    return 1, []


def _detect_entity_count(row: Dict[str, Any]) -> Tuple[int, str, List[str]]:
    """Scan *row* for the best entity-split candidate.

    Returns ``(count, best_field_name, best_parts)``.  When *count* < 2
    the row should not be split.
    """
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

        # 1. Semicolons
        count, parts = _calc_entity_count_from_semicolons(text)
        if count > best_count:
            best_count = count
            best_field = key
            best_parts = parts

        # 2. Named patterns
        count2, parts2 = _calc_entity_count_from_patterns(text)
        if count2 > best_count:
            best_count = count2
            best_field = key
            best_parts = parts2

    return best_count, best_field, best_parts


def _build_split_row(
    original_row: Dict[str, Any],
    entity_index: int,
    total_entities: int,
    best_field: str,
    best_parts: List[str],
) -> Dict[str, Any]:
    """Build one entity row from the merged original row."""
    entity_row: Dict[str, Any] = {}
    for key, value in original_row.items():
        text = str(value) if value else ""

        # Try semicolons: map part i to entity i; reuse last part when i runs out
        # (do not assign the full concatenated string to every entity).
        if ";" in text:
            parts = [p.strip() for p in text.split(";") if p.strip()]
            if parts:
                entity_row[key] = (
                    parts[entity_index]
                    if entity_index < len(parts)
                    else parts[-1]
                )
            else:
                entity_row[key] = value
            continue

        if key == best_field:
            if best_parts:
                entity_row[key] = (
                    best_parts[entity_index]
                    if entity_index < len(best_parts)
                    else best_parts[-1]
                )
            else:
                entity_row[key] = value
            continue

        entity_row[key] = value

    return entity_row


def split_entities_in_isa_structure(
    isa_structure: Dict[str, Any],
) -> Dict[str, Any]:
    """Split single-row sheets into multi-row when values contain entity separators.

    Operates on the ``isa_structure`` dict **in place** (also returned for
    convenience).  Heuristics target ``sample``, ``assay``, and
    ``observationunit`` sheets that have exactly one row whose values show
    signs of merged entities (semicolons, "Experiment N" repeats, …).

    Shared/constant fields are copied to every entity row; the driving
    field (the one with the highest detected entity count) controls the
    split pattern.

    Returns
    -------
    Dict[str, Any]
        The same dict (mutated in place).
    """
    for sheet_name in _MULTI_ROW_LEVELS:
        sheet = isa_structure.get(sheet_name)
        if not isinstance(sheet, dict):
            continue
        rows = sheet.get("rows", [])
        if len(rows) != 1:
            continue  # already multi-row, empty, or no rows

        row = rows[0]
        count, best_field, best_parts = _detect_entity_count(row)
        if count < 2:
            continue

        # Build per-entity rows
        new_rows = [
            _build_split_row(row, i, count, best_field, best_parts)
            for i in range(count)
        ]

        sheet["rows"] = new_rows
        logger.debug(
            "Entity split: '%s' 1 -> %d rows (driving field='%s')",
            sheet_name,
            count,
            best_field,
        )

    # Also update the backward-compat "fields" list to reflect the first
    # split row so that any code reading ``fields`` still gets data.
    for sheet_name in _MULTI_ROW_LEVELS:
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


# ── Row resolution ──────────────────────────────────────────────


def _resolve_rows(level_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Resolve data rows from an ISA sheet's *level_data*.

    Prefers ``rows`` (``columns`` + ``rows`` multi-row format); falls back
    to the flat ``fields`` list (backward-compatible single-row).

    Returns
    -------
    List[Dict[str, Any]]
        Each dict maps a **lowercase field name** to its string value.
        Empty list if no data is present.
    """
    rows: List[Dict[str, Any]] = level_data.get("rows", [])
    if rows:
        return rows

    fields: List[Dict[str, Any]] = level_data.get("fields", [])
    if fields:
        row: Dict[str, Any] = {}
        for f in fields:
            name = (f.get("field_name") or "").strip().lower()
            val = f.get("value")
            if name and val is not None:
                row[name] = str(val)
        if row:
            return [row]

    return []


# ── Header-column map builder ────────────────────────────────────


def _build_header_column_map(ws: "openpyxl.worksheet.worksheet.Worksheet") -> Dict[str, int]:
    """Build ``{lowercase_header: column_1_indexed}`` from Excel row 1."""
    header_col: Dict[str, int] = {}
    for col_idx in range(1, ws.max_column + 1):
        h = ws.cell(row=1, column=col_idx).value
        if h:
            header_col[str(h).strip().lower()] = col_idx
    return header_col


# ── Local Excel generation (no API needed) ───────────────────────


def _generate_xlsx_local(
    isa_structure: Dict[str, Any],
) -> Optional[bytes]:
    """Generate a complete ``metadata_fairds.xlsx`` from *isa_structure*.

    Uses **openpyxl** only.  Returns raw ``.xlsx`` bytes or ``None`` if
    the library is unavailable or an error occurs.
    """
    try:
        import openpyxl
        from openpyxl.styles import (
            Alignment,
            Border,
            Font,
            PatternFill,
            Side,
        )
        from openpyxl.utils import get_column_letter
    except ImportError:
        logger.warning("openpyxl not installed; cannot generate Excel locally")
        return None

    # ── Style definitions ───────────────────────────────────────
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell_align = Alignment(vertical="top", wrap_text=False)
    thin_side = Side(style="thin")
    thin_border = Border(
        left=thin_side, right=thin_side, top=thin_side, bottom=thin_side
    )
    # ── end style definitions ───────────────────────────────────

    wb = openpyxl.Workbook()
    # Remove the auto-created empty sheet
    default_sheet = wb.active
    wb.remove(default_sheet)

    isa_level_order = [
        "investigation",
        "study",
        "assay",
        "sample",
        "observationunit",
    ]
    isa_descriptions = {
        "investigation": "Investigation-level metadata (project info)",
        "study": "Study-level metadata (experimental design)",
        "assay": "Assay-level metadata (measurement details)",
        "sample": "Sample-level metadata (biological material)",
        "observationunit": "ObservationUnit-level metadata (individual observations)",
        "help": "Help — workbook overview",
    }

    # ── ISA data sheets ─────────────────────────────────────────
    for level_name in isa_level_order:
        level_data = isa_structure.get(level_name, {})
        if not isinstance(level_data, dict):
            continue

        columns: List[str] = level_data.get("columns", [])
        if not columns:
            logger.debug("Skipping '%s' sheet: no columns defined", level_name)
            continue

        rows = _resolve_rows(level_data)
        ws = wb.create_sheet(title=level_name.capitalize())

        # Row 1: column headers
        for col_idx, col_name in enumerate(columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = thin_border

        # Row 2+: data rows
        for row_idx, row_data in enumerate(rows, start=2):
            for col_idx, col_name in enumerate(columns, start=1):
                key = col_name.strip().lower()
                value = row_data.get(key)
                if value is not None:
                    cell = ws.cell(row=row_idx, column=col_idx, value=str(value))
                    cell.alignment = cell_align
                    cell.border = thin_border

        # Column widths (auto-fit, clamped 10–60)
        for col_idx, col_name in enumerate(columns, start=1):
            col_letter = get_column_letter(col_idx)
            lengths = [len(str(col_name))]
            for row_data in rows:
                val_str = str(row_data.get(col_name.strip().lower(), ""))
                lengths.append(len(val_str))
            width = min(max(max(lengths) + 2, 10), 60)
            ws.column_dimensions[col_letter].width = width

        # Freeze header row
        ws.freeze_panes = "A2"

        logger.debug(
            "Generated '%s' sheet: %d columns x %d rows",
            level_name,
            len(columns),
            len(rows),
        )

    # ── Help sheet ──────────────────────────────────────────────
    ws_help = wb.create_sheet(title="Help", index=len(wb.sheetnames))
    help_lines = [
        ["FAIR-DS Metadata Excel Export"],
        [""],
        [
            "This workbook contains metadata organised by ISA-TAB levels: "
            "Investigation, Study, Assay, Sample, ObservationUnit."
        ],
        [""],
        ["Sheets:"],
        ["  Investigation"] + ["Project-level metadata (title, authors, contacts)"],
        ["  Study"] + ["Study-level metadata (experimental design, description)"],
        ["  Assay"] + ["Assay-level metadata (measurements, protocols, files)"],
        ["  Sample"] + ["Sample-level metadata (biological material, environment)"],
        ["  ObservationUnit"] + ["Individual observation metadata"],
        [""],
        [
            "Each sheet has one header row followed by one data row per entity. "
            "Fields present in the column header but absent in a particular row "
            "are considered 'not specified'."
        ],
        [""],
        ["Generated by FAIRiAgent"],
    ]
    for row_idx, row_data in enumerate(help_lines, start=1):
        for col_idx, value in enumerate(row_data, start=1):
            ws_help.cell(row=row_idx, column=col_idx, value=value)
    ws_help.column_dimensions["A"].width = 100

    try:
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    except Exception as exc:
        logger.warning("Failed to save Excel workbook: %s", exc)
        return None


# ── Post-process: fill rows into API-generated workbook ─────────


def _fill_missing_data_rows(
    xlsx_bytes: bytes,
    isa_structure: Dict[str, Any],
) -> bytes:
    """Post-process Excel: fill data rows for ISA sheets the API left empty.

    The FAIR-DS ``POST /api/isa`` endpoint writes data rows only for
    ``investigation`` and ``study``.  This function fills the remaining
    sheets from the ``columns`` + ``rows`` (or legacy ``fields``) data in
    ``isa_structure`` — **one Excel row per entity**.

    Returns
    -------
    bytes
        The (possibly modified) ``.xlsx`` bytes.
    """
    try:
        import openpyxl
    except ImportError:
        return xlsx_bytes

    try:
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    except Exception:
        return xlsx_bytes

    isa_level_names = {
        "investigation",
        "study",
        "assay",
        "sample",
        "observationunit",
    }

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        if sheet_name.lower() not in isa_level_names:
            continue
        # Only fill if the sheet has headers but no data rows yet.
        if ws.max_row > 1:
            continue

        level_data = isa_structure.get(sheet_name.lower())
        if not isinstance(level_data, dict):
            continue

        rows = _resolve_rows(level_data)
        if not rows:
            continue

        header_col = _build_header_column_map(ws)
        if not header_col:
            continue

        total_filled = 0
        for row_idx, row_data in enumerate(rows, start=2):
            filled_in_row = 0
            for key, value in row_data.items():
                col = header_col.get(key.lower())
                if col is not None and value is not None:
                    ws.cell(row=row_idx, column=col, value=str(value))
                    filled_in_row += 1
            total_filled += filled_in_row

        if total_filled:
            logger.debug(
                "Filled %d values across %d row(s) in '%s' sheet",
                total_filled,
                len(rows),
                sheet_name,
            )

    try:
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    except Exception:
        return xlsx_bytes


# ── Public API ──────────────────────────────────────────────────


def try_export_fairds_metadata_excel(
    output_dir: Path,
    *,
    fair_ds_api_url: Optional[str] = None,
) -> Optional[Path]:
    """Write ``metadata_fairds.xlsx`` when ``metadata.json`` has fillable ISA data.

    Workflow
    --------
    1. Read ``metadata.json``, extract ``isa_structure``.
    2. Apply entity-splitting heuristics to expand single merged rows.
    3. If a FAIR-DS API URL is available **and** the server is reachable,
       call ``POST /api/isa`` to obtain a workbook with column headers.
       Then fill data rows from the (split) ISA structure.
    4. If the API is unavailable or not configured, generate the workbook
       entirely locally with ``openpyxl``.
    5. Return the path to the written ``.xlsx`` file, or ``None`` on
       failure / missing data.

    Parameters
    ----------
    output_dir : Path
        Directory containing ``metadata.json`` (and where the ``.xlsx``
        will be written).
    fair_ds_api_url : str, optional
        Override the configured FAIR-DS API URL.  ``None`` (default) uses
        ``config.fair_ds_api_url``.

    Returns
    -------
    Path or None
        Absolute path to the written ``metadata_fairds.xlsx`` file.
    """
    from ..config import config
    from ..output_paths import (
        FAIRDS_METADATA_EXCEL_FILENAME,
        resolve_metadata_output_read_path,
    )
    from .fair_data_station import FAIRDataStationClient

    url = config.fair_ds_api_url if fair_ds_api_url is None else fair_ds_api_url

    meta_path = resolve_metadata_output_read_path(Path(output_dir))
    if not meta_path:
        logger.debug(
            "FAIR-DS Excel export skipped: no metadata.json in %s",
            output_dir,
        )
        return None

    try:
        with open(meta_path, encoding="utf-8") as fh:
            data: Dict[str, Any] = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "FAIR-DS Excel export skipped: cannot read %s: %s",
            meta_path,
            exc,
        )
        return None

    isa_structure = data.get("isa_structure")
    if not isinstance(isa_structure, dict) or not isa_structure:
        logger.debug(
            "FAIR-DS Excel export skipped: missing or empty isa_structure"
        )
        return None

    # Prefer dedicated matrix; fall back to isa_structure.
    isa_values = data.get("isa_values")
    if isinstance(isa_values, dict):
        fill_structure = split_entities_in_isa_structure(isa_values)
    else:
        fill_structure = split_entities_in_isa_structure(isa_structure)

    # Check for fillable content.
    has_content = False
    for _level, block in fill_structure.items():
        if isinstance(block, dict) and (
            block.get("fields") or block.get("rows")
        ):
            has_content = True
            break
    if not has_content:
        logger.debug(
            "FAIR-DS Excel export skipped: no fields/rows under isa_structure"
        )
        return None

    # ── Step 1: Entity splitting ───────────────────────────────
    # Defensive: even if the JSON generator already split entities,
    # re-apply to catch any remaining semicolons in merged rows.
    isa_structure = split_entities_in_isa_structure(isa_structure)

    # ── Step 2: Generate Excel ─────────────────────────────────
    xlsx_bytes: Optional[bytes] = None
    api_used = False

    if url and str(url).strip():
        base = str(url).strip().rstrip("/")
        client = FAIRDataStationClient(base)
        if client.is_available():
            try:
                xlsx_bytes = client.generate_excel_from_isa_structure(
                    isa_structure
                )
                api_used = True
            except Exception as exc:
                logger.warning(
                    "FAIR-DS API Excel generation failed: %s", exc
                )
        else:
            logger.debug(
                "FAIR-DS API not reachable at %s; falling back to local generation",
                base,
            )
    else:
        logger.debug(
            "FAIR-DS API URL not set; using local Excel generation"
        )

    if xlsx_bytes is not None and api_used:
        # The API returned headers (and perhaps a few data rows);
        # fill the remaining data locally.
        xlsx_bytes = _fill_missing_data_rows(xlsx_bytes, fill_structure)
    elif xlsx_bytes is None:
        # API was not used or failed — generate entirely locally.
        xlsx_bytes = _generate_xlsx_local(fill_structure)

    if xlsx_bytes is None:
        logger.warning(
            "FAIR-DS Excel export failed: no xlsx bytes generated"
        )
        return None

    out = Path(output_dir) / FAIRDS_METADATA_EXCEL_FILENAME
    try:
        out.write_bytes(xlsx_bytes)
    except OSError as exc:
        logger.warning(
            "FAIR-DS Excel export could not write %s: %s",
            out,
            exc,
        )
        return None

    logger.info(
        "FAIR-DS metadata Excel written: %s (%s bytes)",
        out.name,
        len(xlsx_bytes),
    )
    return out


__all__ = [
    "try_export_fairds_metadata_excel",
    "split_entities_in_isa_structure",
    "_generate_xlsx_local",
    "_fill_missing_data_rows",
    "_resolve_rows",
]
