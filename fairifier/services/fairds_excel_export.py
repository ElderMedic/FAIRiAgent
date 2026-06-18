"""Backward-compatibility wrapper for Excel exporting logic now in fairifier.graph.excel."""

from fairifier.graph.excel import (
    _excel_safe_value,
    _resolve_rows,
    _build_header_column_map,
    _build_column_requirement_map,
    _REQ_FILLS,
    _REQ_FONTS,
    _requirement_label,
    _requirement_fill,
    _requirement_font,
    _generate_xlsx_local,
    _fill_missing_data_rows,
    try_export_fairds_metadata_excel,
    split_entities_in_isa_structure,
)

__all__ = [
    "try_export_fairds_metadata_excel",
    "split_entities_in_isa_structure",
    "_generate_xlsx_local",
    "_fill_missing_data_rows",
    "_resolve_rows",
]
