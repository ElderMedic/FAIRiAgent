"""Single source of truth for FAIR / ISA metadata_json.json format checks.

Used by the CLI after workflow output and by evaluation.SchemaValidator.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

# Mandatory field names per ISA sheet (lowercase match against field_name)
REQUIRED_FIELDS_BY_SHEET: Dict[str, List[str]] = {
    "investigation": [
        "investigation title",
        "investigation description",
    ],
    "study": [
        "study title",
        "study description",
    ],
    "assay": [
        "assay identifier",
        "assay description",
    ],
    "sample": [
        "sample identifier",
        "sample description",
    ],
    "observationunit": [
        "observation unit identifier",
        "observation unit description",
    ],
}


def _validate_date(value: str) -> bool:
    date_patterns = [
        r"^\d{4}-\d{2}-\d{2}$",
        r"^\d{4}-\d{2}$",
        r"^\d{4}$",
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
    ]
    for pattern in date_patterns:
        if re.match(pattern, str(value)):
            return True
    return False


def _validate_url(value: str) -> bool:
    try:
        result = urlparse(str(value))
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def _validate_email(value: str) -> bool:
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, str(value)))


def _validate_ncbi_taxid(value: str) -> bool:
    return str(value).isdigit()


def _validate_numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except Exception:
        return False


def _validate_latitude(value: str) -> bool:
    try:
        lat = float(value)
        return -90 <= lat <= 90
    except Exception:
        return False


def _validate_longitude(value: str) -> bool:
    try:
        lon = float(value)
        return -180 <= lon <= 180
    except Exception:
        return False


def validate_json_structure(
    data: Dict[str, Any], errors: List[str], warnings: List[str]
) -> bool:
    """Validate basic top-level structure (same rules as legacy SchemaValidator)."""
    required_top_level = ["fairifier_version", "generated_at", "document_source"]
    for field in required_top_level:
        if field not in data:
            errors.append(f"Missing required top-level field: {field}")

    has_metadata = "metadata" in data or "isa_structure" in data
    if not has_metadata:
        errors.append("No metadata found (expected 'metadata' or 'isa_structure')")
        return False

    return len(errors) == 0


def validate_required_fields(
    data: Dict[str, Any],
    errors: List[str],
    warnings: List[str],
    required_fields_by_sheet: Dict[str, List[str]] | None = None,
) -> bool:
    """Validate mandatory field names exist per ISA sheet."""
    mapping = required_fields_by_sheet or REQUIRED_FIELDS_BY_SHEET
    isa_structure = data.get("isa_structure", {})

    for sheet_name, required_fields in mapping.items():
        if sheet_name not in isa_structure:
            warnings.append(f"ISA sheet '{sheet_name}' not found")
            continue

        sheet_data = isa_structure[sheet_name]
        fields = sheet_data.get("fields", [])
        field_names = {f.get("field_name", "").lower() for f in fields}

        for required_field in required_fields:
            if required_field.lower() not in field_names:
                errors.append(f"Required field missing in {sheet_name}: {required_field}")

    return len([e for e in errors if "Required field missing" in e]) == 0


def validate_field_datatypes(
    data: Dict[str, Any], errors: List[str], warnings: List[str]
) -> bool:
    isa_structure = data.get("isa_structure", {})

    for sheet_name, sheet_data in isa_structure.items():
        if sheet_name == "description":
            continue

        fields = sheet_data.get("fields", [])
        for field in fields:
            field_name = field.get("field_name", "")
            value = field.get("value")

            if "field_name" not in field:
                errors.append(f"Field in {sheet_name} missing 'field_name'")

            if value is None:
                warnings.append(f"Field '{field_name}' in {sheet_name} has null value")

            if "confidence" in field:
                conf = field["confidence"]
                if not isinstance(conf, (int, float)) or conf < 0 or conf > 1:
                    warnings.append(f"Invalid confidence value for '{field_name}': {conf}")

    return True


def validate_isa_structure(
    data: Dict[str, Any], errors: List[str], warnings: List[str]
) -> bool:
    isa_structure = data.get("isa_structure", {})

    if not isa_structure:
        warnings.append("No ISA structure found")
        return False

    expected_sheets = ["investigation", "study", "assay", "sample"]
    found_sheets = [s for s in expected_sheets if s in isa_structure]

    if len(found_sheets) < 2:
        warnings.append(
            f"Only {len(found_sheets)} ISA sheets found, expected at least 2"
        )

    for sheet_name in found_sheets:
        sheet_data = isa_structure[sheet_name]

        if "fields" not in sheet_data:
            errors.append(f"ISA sheet '{sheet_name}' missing 'fields' array")

        if "description" not in sheet_data:
            warnings.append(f"ISA sheet '{sheet_name}' missing 'description'")

    return True


def validate_value_formats(
    data: Dict[str, Any], errors: List[str], warnings: List[str]
) -> bool:
    isa_structure = data.get("isa_structure", {})

    for sheet_name, sheet_data in isa_structure.items():
        if sheet_name == "description":
            continue

        fields = sheet_data.get("fields", [])
        for field in fields:
            field_name = field.get("field_name", "").lower()
            value = field.get("value", "")

            if not value or str(value).lower() in [
                "not specified",
                "not applicable",
                "n/a",
            ]:
                continue

            if "date" in field_name:
                if not _validate_date(value):
                    warnings.append(f"Invalid date format for '{field_name}': {value}")

            elif "email" in field_name:
                if not _validate_email(value):
                    warnings.append(f"Invalid email format for '{field_name}': {value}")

            elif "url" in field_name or field_name.endswith("_link"):
                if not _validate_url(value):
                    warnings.append(f"Invalid URL format for '{field_name}': {value}")

            elif "taxid" in field_name or "taxonomy" in field_name:
                if not _validate_ncbi_taxid(value):
                    warnings.append(
                        f"Invalid NCBI taxonomy ID for '{field_name}': {value}"
                    )

            elif field_name == "latitude" or "latitude" in field_name:
                if not _validate_latitude(value):
                    warnings.append(f"Invalid latitude for '{field_name}': {value}")

            elif field_name == "longitude" or "longitude" in field_name:
                if not _validate_longitude(value):
                    warnings.append(f"Invalid longitude for '{field_name}': {value}")

    return True


def check_metadata_json_output(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run all FAIR / ISA format checks on a parsed metadata_json object.

    Returns the same structure as evaluation.evaluators.schema_validator.SchemaValidator.validate().
    """
    errors: List[str] = []
    warnings: List[str] = []
    validations: Dict[str, bool] = {}

    structure_valid = validate_json_structure(data, errors, warnings)
    validations["json_structure"] = structure_valid

    required_valid = validate_required_fields(data, errors, warnings)
    validations["required_fields"] = required_valid

    datatypes_valid = validate_field_datatypes(data, errors, warnings)
    validations["field_datatypes"] = datatypes_valid

    isa_valid = validate_isa_structure(data, errors, warnings)
    validations["isa_structure"] = isa_valid

    format_valid = validate_value_formats(data, errors, warnings)
    validations["value_formats"] = format_valid

    total_checks = len(validations)
    passed_checks = sum(1 for v in validations.values() if v)
    compliance_rate = passed_checks / total_checks if total_checks > 0 else 0.0
    is_valid = len(errors) == 0

    return {
        "is_valid": is_valid,
        "schema_compliance_rate": compliance_rate,
        "validations": validations,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "total_checks": total_checks,
            "passed_checks": passed_checks,
            "critical_errors": len(errors),
            "warnings": len(warnings),
            "status": "PASS" if is_valid else "FAIL",
        },
    }
