"""Dynamic JSON Schema generation from FAIRDS ShEx + API field definitions.

Generates per-run schemas that validate only the fields actually selected
by KnowledgeRetriever — not the entire FAIRDS universe.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


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
            "investigation contentUrl":   {"required": False, "type": "uri"},
        },
    },
    "jerm:Study": {
        "isa_sheet": "study",
        "properties": {
            "study title":               {"required": True,  "type": "string"},
            "study description":         {"required": True,  "type": "string"},
            "study identifier":          {"required": True,  "type": "string"},
            "study contributor":         {"required": False, "type": "person"},
            "study contentUrl":          {"required": False, "type": "uri"},
        },
    },
    "jerm:Assay": {
        "isa_sheet": "assay",
        "properties": {
            "assay name":                {"required": True,  "type": "string"},
            "assay description":         {"required": True,  "type": "string"},
            "assay identifier":          {"required": True,  "type": "string"},
            "assay contributor":         {"required": False, "type": "person"},
            "assay contentUrl":          {"required": False, "type": "uri"},
            "assay additionalType":      {"required": False, "type": "uri"},
        },
    },
    "jerm:Sample": {
        "isa_sheet": "sample",
        "properties": {
            "sample name":               {"required": True,  "type": "string"},
            "sample description":        {"required": True,  "type": "string"},
            "sample identifier":         {"required": True,  "type": "string"},
            "sample contributor":        {"required": False, "type": "person"},
            "sample contentUrl":         {"required": False, "type": "uri"},
        },
    },
    "ppeo:observation_unit": {
        "isa_sheet": "observationunit",
        "properties": {
            "observation unit name":        {"required": True,  "type": "string"},
            "observation unit description": {"required": True,  "type": "string"},
            "observation unit identifier":  {"required": True,  "type": "string"},
            "observation unit contributor": {"required": False, "type": "person"},
            "observation unit contentUrl":  {"required": False, "type": "uri"},
        },
    },
    "schema:Person": {
        "isa_sheet": "person",
        "properties": {
            "email":         {"required": True,  "type": "email"},
            "givenName":     {"required": True,  "type": "string"},
            "familyName":    {"required": True,  "type": "string"},
            "orcid":         {"required": False, "type": "uri"},
            "jobTitle":      {"required": False, "type": "string"},
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
            "contentUrl":     {"required": False, "type": "uri"},
            "contentSize":    {"required": False, "type": "integer"},
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


def _field_key(field: Dict[str, Any]) -> str:
    """Normalize a field dict into a schema property key."""
    name = (field.get("name") or field.get("label") or "").strip().lower()
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
        prop["pattern"] = field["regex"]

    return prop


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
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = required

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
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema library not installed — cannot validate"]

    # Group selected fields by ISA sheet
    fields_by_sheet: Dict[str, List[Dict[str, Any]]] = {}
    for field in selected_fields:
        sheet = (field.get("isa_sheet") or field.get("sheet") or "").strip().lower()
        if not sheet:
            continue
        fields_by_sheet.setdefault(sheet, []).append(field)

    schema = build_metadata_schema(fields_by_sheet)
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(metadata))
    return [e.message for e in errors]


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

    for sheet_name in ["investigation", "study", "assay", "sample", "observationunit"]:
        sheet_data = isa_metadata.get(sheet_name, {})
        sheet_fields = fields_by_sheet.get(sheet_name, [])

        if not sheet_fields:
            continue

        schema = build_isa_schema(sheet_name, sheet_fields, additional_properties=True)
        validator = jsonschema.Draft202012Validator(schema)

        # Validate only the fields array within each sheet
        fields_list = sheet_data if isinstance(sheet_data, list) else sheet_data.get("fields", [])
        if isinstance(fields_list, list):
            for idx, field_obj in enumerate(fields_list):
                field_errors = list(validator.iter_errors(field_obj))
                for e in field_errors:
                    all_errors.append(f"{sheet_name}[{idx}]: {e.message}")

        # Check ShEx-mandatory fields are present
        for shape_name, shape_def in SHEX_SHAPES.items():
            if shape_def["isa_sheet"] != sheet_name:
                continue
            for prop_name, prop_def in shape_def["properties"].items():
                if prop_def.get("required"):
                    found = any(
                        _field_key(f) == prop_name or f.get("name") == prop_name
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
