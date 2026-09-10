"""Dynamic JSON Schema generation from FAIRDS ShEx + API field definitions.

Generates per-run schemas that validate only the fields actually selected
by KnowledgeRetriever — not the entire FAIRDS universe.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from fairifier.utils.isa_order import ISA_LEVEL_ORDER


# -- Structural rules derived from FAIRDS.shex (ISA-level shape definitions) --
# Cardinality: no suffix = required(1), ? = optional(0..1), * = optional(0..n)

SHEX_SHAPES: Dict[str, Dict[str, Any]] = {
    "jerm:Investigation": {
        "isa_sheet": "investigation",
        "properties": {
            "investigation title":        {"required": True,  "type": "string"},
            "investigation description":  {"required": True,  "type": "string"},
            "investigation identifier":   {"required": True,  "type": "string"},
            "investigation contributor":  {"required": False, "type": "person"},
            "investigation contenturl":   {"required": False, "type": "uri"},
        },
    },
    "jerm:Study": {
        "isa_sheet": "study",
        "properties": {
            "study title":               {"required": True,  "type": "string"},
            "study description":         {"required": True,  "type": "string"},
            "study identifier":          {"required": True,  "type": "string"},
            "study contributor":         {"required": False, "type": "person"},
            "study contenturl":          {"required": False, "type": "uri"},
        },
    },
    "jerm:Assay": {
        "isa_sheet": "assay",
        "properties": {
            # FAIR-DS default currently marks assay name OPTIONAL, and curated
            # FAIR-DS workbooks use identifier + description as assay core.
            "assay name":                {"required": False, "type": "string"},
            "assay description":         {"required": True,  "type": "string"},
            "assay identifier":          {"required": True,  "type": "string"},
            "assay contributor":         {"required": False, "type": "person"},
            "assay contenturl":          {"required": False, "type": "uri"},
            "assay additionaltype":      {"required": False, "type": "uri"},
        },
    },
    "jerm:Sample": {
        "isa_sheet": "sample",
        "properties": {
            "sample name":               {"required": True,  "type": "string"},
            "sample description":        {"required": True,  "type": "string"},
            "sample identifier":         {"required": True,  "type": "string"},
            "sample contributor":        {"required": False, "type": "person"},
            "sample contenturl":         {"required": False, "type": "uri"},
        },
    },
    "ppeo:observation_unit": {
        "isa_sheet": "observationunit",
        "properties": {
            "observation unit name":        {"required": True,  "type": "string"},
            "observation unit description": {"required": True,  "type": "string"},
            "observation unit identifier":  {"required": True,  "type": "string"},
            "observation unit contributor": {"required": False, "type": "person"},
            "observation unit contenturl":  {"required": False, "type": "uri"},
        },
    },
    "schema:Person": {
        "isa_sheet": "person",
        "properties": {
            "email":         {"required": True,  "type": "email"},
            "givenname":     {"required": True,  "type": "string"},
            "familyname":    {"required": True,  "type": "string"},
            "orcid":         {"required": False, "type": "uri"},
            "jobtitle":      {"required": False, "type": "string"},
            "department":    {"required": False, "type": "string"},
            "organization":  {"required": False, "type": "string"},
        },
    },
    "jerm:Data_sample": {
        "isa_sheet": "data",
        "properties": {
            "name":           {"required": True,  "type": "string"},
            "identifier":     {"required": True,  "type": "string"},
            "sha256":         {"required": False, "type": "string"},
            "contenturl":     {"required": False, "type": "uri"},
            "contentsize":    {"required": False, "type": "integer"},
        },
    },
}

# Maps FAIRDS API data_type hints to JSON Schema types
_TYPE_MAP = {
    "string":   "string",
    "number":   "number",
    "integer":  "integer",
    "boolean":  "boolean",
    "date":     "string",  # + format: date
    "datetime": "string",  # + format: date-time
    "uri":      "string",  # + format: uri
    "email":    "string",  # + format: email
    "text":     "string",
    "file":     "string",  # file paths
    "ontology_term": "string",  # + format: uri
}

_MISSING_VALUE_SENTINELS = [
    "",
    "not applicable",
    "not available",
    "not provided",
    "not specified",
    "unknown",
]


def _field_key(field: Dict[str, Any]) -> str:
    """Normalize a field dict into a schema property key."""
    # FAIR-DS field definitions use ``term`` in current runtime artifacts,
    # while older fixtures and API payloads use ``name`` or ``label``.  Value
    # records use ``field_name``.  Treat all four as the same contract key.
    name = (
        field.get("name")
        or field.get("term")
        or field.get("label")
        or field.get("field_name")
        or ""
    ).strip().lower()
    return name


def _json_type_for(field: Dict[str, Any]) -> Dict[str, Any]:
    """Map a FAIRDS API field to a JSON Schema type descriptor."""
    data_type = (field.get("data_type") or "string").lower()
    syntax = (field.get("syntax") or "").lower()
    json_type = _TYPE_MAP.get(data_type, "string")
    prop: Dict[str, Any] = {"type": json_type}

    if json_type == "string":
        if "date" in data_type or "date" in syntax:
            prop["format"] = "date"
        elif "uri" in data_type or "url" in data_type or "iri" in data_type:
            prop["format"] = "uri"
        elif "email" in data_type:
            prop["format"] = "email"

    if field.get("regex"):
        # FAIR-DS regexes describe the complete cell syntax. JSON Schema's
        # ``pattern`` uses substring search, so anchor the upstream expression
        # to preserve FAIR-DS full-cell semantics.  Some upstream FAIR-DS
        # records contain malformed expressions (for example a quantifier
        # applied to another quantifier).  Such a service-data defect must not
        # crash validation or prevent Excel export; omit only that unusable
        # constraint, matching the contract-index boundary used by Mapper.
        raw_pattern = str(field["regex"])
        try:
            re.compile(raw_pattern)
        except re.error:
            raw_pattern = ""
        if raw_pattern:
            pattern = raw_pattern
            if not (pattern.startswith("^") and pattern.endswith("$")):
                pattern = f"^(?:{pattern})$"
            try:
                re.compile(pattern)
            except re.error:
                pattern = ""
            if pattern:
                prop["pattern"] = pattern

    return prop


def _coerce_value_for_schema(value: Any, field: Dict[str, Any]) -> Any:
    """Coerce lexical numbers solely for validation, without mutating output."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    data_type = (field.get("data_type") or "string").lower()
    json_type = _TYPE_MAP.get(data_type, "string")
    try:
        if json_type == "integer" and re.fullmatch(r"[+-]?\d+", stripped):
            return int(stripped)
        if json_type == "number" and re.fullmatch(
            r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", stripped
        ):
            return float(stripped)
    except (TypeError, ValueError, OverflowError):
        return value
    return value


def build_isa_schema(
    isa_sheet: str,
    selected_fields: List[Dict[str, Any]],
    *,
    additional_properties: bool = True,
) -> Dict[str, Any]:
    """Build a JSON Schema for one ISA sheet from its selected fields.

    Required fields come from the ShEx shape for this sheet. All selected
    fields are included in the schema; ShEx-mandatory fields that were NOT
    selected are flagged as warnings (we don't fail for missing selection,
    we fail only for selected-but-empty required fields).
    """
    properties: Dict[str, Any] = {}
    required: List[str] = []

    # Find ShEx shape that maps to this ISA sheet
    shex_props: Dict[str, Any] = {}
    for shape_name, shape_def in SHEX_SHAPES.items():
        if shape_def["isa_sheet"] == isa_sheet:
            shex_props = shape_def["properties"]
            break

    # Build properties from selected fields
    for field in selected_fields:
        key = _field_key(field)
        if not key:
            # An unnamed API record cannot define a JSON property.  Silently
            # excluding it is safer than creating the empty required key "".
            continue
        prop = _json_type_for(field)

        # ShEx structural requirement overrides API 'required' flag
        shex_match = shex_props.get(key) or shex_props.get(field.get("name", ""))
        if shex_match is not None and shex_match.get("required"):
            required.append(key)
        elif field.get("required") or field.get("requirement", "").upper() == "MANDATORY":
            required.append(key)

        prop.setdefault("description", field.get("definition", ""))
        properties[key] = prop

    schema: Dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": additional_properties,
    }
    return schema


def build_metadata_schema(
    fields_by_sheet: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Build a top-level JSON Schema for the full metadata.json output.

    Args:
        fields_by_sheet: {sheet_name: [field_dict, ...]} as produced by
                         KnowledgeRetriever/FAIRDSAPIParser.
    """
    sheet_schemas: Dict[str, Any] = {}
    for sheet_name, fields in fields_by_sheet.items():
        if not fields:
            continue
        sheet_schemas[sheet_name] = build_isa_schema(sheet_name, fields)

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "fairifier_version": {"type": "string"},
            "generated_at":      {"type": "string", "format": "date-time"},
            "document_source":   {"type": "string"},
            "overall_confidence": {"type": "number"},
            "needs_review":      {"type": "boolean"},
            "packages_used":     {"type": "array", "items": {"type": "string"}},
            "isa_structure": {
                "type": "object",
                "properties": sheet_schemas,
            },
            "document_info":     {"type": "object"},
            "evidence_packets_summary": {"type": "object"},
            "confidence_scores":  {"type": "object"},
            "errors":             {"type": "array"},
            "warnings":           {"type": "array"},
        },
    }


def validate_metadata(
    metadata: Dict[str, Any],
    selected_fields: List[Dict[str, Any]],
) -> List[str]:
    """Validate a metadata.json dict against dynamically generated schema.

    Args:
        metadata: The metadata JSON dict to validate.
        selected_fields: Flat list of all field dicts selected by
                         KnowledgeRetriever for this run.

    Returns:
        List of validation error messages (empty = valid).
    """
    # Delegate to validate_isa_structure which handles the field_name/value format
    result = validate_isa_structure(metadata.get("isa_structure", {}), selected_fields)
    return result["errors"]


def validate_isa_structure(
    isa_metadata: Dict[str, Any],
    selected_fields: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Validate isa_structure portion against per-sheet schemas.

    Returns:
        {"valid": bool, "errors": [...], "warnings": [...]}
    """
    try:
        import jsonschema
    except ImportError:
        return {"valid": False, "errors": ["jsonschema library not installed"], "warnings": []}

    fields_by_sheet: Dict[str, List[Dict[str, Any]]] = {}
    for field in selected_fields:
        sheet = (field.get("isa_sheet") or field.get("sheet") or "").strip().lower()
        if not sheet:
            continue
        fields_by_sheet.setdefault(sheet, []).append(field)

    all_errors: List[str] = []
    all_warnings: List[str] = []

    for sheet_name in ISA_LEVEL_ORDER:
        sheet_data = isa_metadata.get(sheet_name, {})
        sheet_fields = fields_by_sheet.get(sheet_name, [])

        if not sheet_fields:
            continue

        # Normalize sheet_data to a flat dict of {field_name: value}
        if isinstance(sheet_data, dict) and not isinstance(sheet_data, list):
            # May be {"fields": [...]} or already a flat dict
            fields_list = sheet_data.get("fields", [])
            if not fields_list and sheet_data and "rows" not in sheet_data:
                # Already flattened: use as-is
                flat_dict = {
                    k.strip().lower(): v for k, v in sheet_data.items()
                    if k != "fields"
                }
            else:
                flat_dict = {}
        else:
            fields_list = sheet_data
            flat_dict = {}
        matrix_rows: List[Dict[str, Any]] = []
        if isinstance(sheet_data, dict):
            rows = sheet_data.get("rows", [])
            if isinstance(rows, list):
                matrix_rows = [
                    {str(k).strip().lower(): v for k, v in row.items()}
                    for row in rows
                    if isinstance(row, dict)
                ]

        if isinstance(fields_list, list):
            for item in fields_list:
                if isinstance(item, dict):
                    name = (item.get("field_name") or item.get("name") or "").strip().lower()
                    if name:
                        val = item.get("value", item.get("field_value"))
                        flat_dict[name] = val

        schema = build_isa_schema(sheet_name, sheet_fields, additional_properties=True)
        fields_by_key = {_field_key(field): field for field in sheet_fields if _field_key(field)}
        validator = jsonschema.Draft202012Validator(schema)
        # ``fields`` carries provenance/confidence, while ``rows`` is the
        # authoritative compiled matrix. Validate every row; checking only row
        # zero lets later invalid controlled values escape unnoticed.
        validation_rows = matrix_rows or [flat_dict]
        for row_index, matrix_row in enumerate(validation_rows, start=1):
            payload = dict(flat_dict)
            payload.update(matrix_row)
            payload = {
                name: _coerce_value_for_schema(value, fields_by_key.get(name, {}))
                for name, value in payload.items()
            }
            errors_list = [
                error
                for error in validator.iter_errors(payload)
                if not (
                    isinstance(error.instance, str)
                    and error.instance.strip().lower() in _MISSING_VALUE_SENTINELS
                )
            ]
            for error in errors_list:
                suffix = f" row {row_index}" if matrix_rows else ""
                all_errors.append(f"{sheet_name}{suffix}: {error.message}")

        # Check ShEx-mandatory fields are present
        for shape_name, shape_def in SHEX_SHAPES.items():
            if shape_def["isa_sheet"] != sheet_name:
                continue
            for prop_name, prop_def in shape_def["properties"].items():
                if prop_def.get("required"):
                    found = any(
                        _field_key(f) == prop_name
                        for f in sheet_fields
                    )
                    if not found:
                        all_warnings.append(
                            f"{sheet_name}: ShEx-mandatory field '{prop_name}' not in selected fields"
                        )

    return {
        "valid": len(all_errors) == 0,
        "errors": all_errors,
        "warnings": all_warnings,
    }
