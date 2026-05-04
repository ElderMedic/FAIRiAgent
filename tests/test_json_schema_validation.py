"""Tests for dynamic JSON Schema generation and validation from FAIRDS ShEx rules."""

import pytest


class TestShExShapeDefinitions:
    """Verify ShEx-derived shape definitions are complete and consistent."""

    def test_all_isa_sheets_have_shapes(self):
        from fairifier.validation.json_schema import SHEX_SHAPES

        expected_sheets = {"investigation", "study", "assay", "sample", "observationunit"}
        found_sheets = set()
        for shape_name, shape_def in SHEX_SHAPES.items():
            sheet = shape_def.get("isa_sheet")
            if sheet in expected_sheets:
                found_sheets.add(sheet)

        assert expected_sheets == found_sheets, \
            f"ShEx shapes missing sheets: {expected_sheets - found_sheets}"

    def test_every_shape_has_required_properties(self):
        from fairifier.validation.json_schema import SHEX_SHAPES

        for shape_name, shape_def in SHEX_SHAPES.items():
            props = shape_def.get("properties", {})
            required = [k for k, v in props.items() if v.get("required")]
            assert len(required) >= 2, \
                f"{shape_name}: expected >=2 required props, got {len(required)}: {required}"

    def test_person_shape_has_email_givenname_familyname(self):
        from fairifier.validation.json_schema import SHEX_SHAPES

        person = SHEX_SHAPES["schema:Person"]["properties"]
        assert person["email"]["required"] is True
        assert person["givenname"]["required"] is True
        assert person["familyname"]["required"] is True
        assert person["orcid"]["required"] is False

    def test_every_property_has_a_type(self):
        from fairifier.validation.json_schema import SHEX_SHAPES

        for shape_name, shape_def in SHEX_SHAPES.items():
            for prop_name, prop_def in shape_def["properties"].items():
                assert "type" in prop_def, \
                    f"{shape_name}.{prop_name} missing 'type'"

    def test_shex_shapes_match_isa_sheet_names(self):
        from fairifier.validation.json_schema import SHEX_SHAPES

        sheet_shapes = {
            "jerm:Investigation":      "investigation",
            "jerm:Study":              "study",
            "jerm:Assay":              "assay",
            "jerm:Sample":             "sample",
            "ppeo:observation_unit":   "observationunit",
        }
        for shape_name, expected_sheet in sheet_shapes.items():
            assert shape_name in SHEX_SHAPES, f"Missing shape: {shape_name}"
            assert SHEX_SHAPES[shape_name]["isa_sheet"] == expected_sheet


class TestBuildIsaSchema:
    """Test per-ISA-sheet schema generation from selected fields."""

    def test_build_investigation_schema_minimal(self):
        from fairifier.validation.json_schema import build_isa_schema

        fields = [
            {"name": "investigation title",       "data_type": "string"},
            {"name": "investigation description", "data_type": "text"},
            {"name": "investigation identifier",  "data_type": "string"},
        ]
        schema = build_isa_schema("investigation", fields)

        assert schema["type"] == "object"
        assert set(schema["required"]) == {
            "investigation title",
            "investigation description",
            "investigation identifier",
        }
        # All 3 should be in properties
        for name in ["investigation title", "investigation description", "investigation identifier"]:
            assert name in schema["properties"]

    def test_build_schema_optional_field_not_in_required(self):
        from fairifier.validation.json_schema import build_isa_schema

        fields = [
            {"name": "investigation title",       "data_type": "string"},
            {"name": "investigation contributor", "data_type": "string"},
        ]
        schema = build_isa_schema("investigation", fields)

        # title is ShEx-required, contributor is optional
        assert "investigation title" in schema["required"]
        assert "investigation contributor" not in schema["required"]

    def test_build_schema_respects_data_types(self):
        from fairifier.validation.json_schema import build_isa_schema

        fields = [
            {"name": "study title",         "data_type": "string"},
            {"name": "study identifier",    "data_type": "string"},
            {"name": "study contentUrl",    "data_type": "uri"},
            {"name": "sample count",        "data_type": "integer"},
        ]
        schema = build_isa_schema("study", fields)

        # URI field gets format hint (field_key lowercases names)
        assert schema["properties"]["study contenturl"].get("format") == "uri"

    def test_build_schema_date_format(self):
        from fairifier.validation.json_schema import build_isa_schema

        fields = [
            {"name": "investigation title",       "data_type": "string"},
            {"name": "investigation description", "data_type": "string"},
            {"name": "investigation identifier",  "data_type": "string"},
            {"name": "assay date",                "data_type": "date"},
        ]
        schema = build_isa_schema("investigation", fields)

        assert schema["properties"]["assay date"].get("format") == "date"

    def test_build_empty_fields_returns_minimal_schema(self):
        from fairifier.validation.json_schema import build_isa_schema

        schema = build_isa_schema("study", [])
        assert schema["type"] == "object"
        assert schema["properties"] == {}
        assert "required" in schema
        assert schema["required"] == []

    def test_additional_properties_default_true(self):
        from fairifier.validation.json_schema import build_isa_schema

        schema = build_isa_schema("investigation", [
            {"name": "investigation title", "data_type": "string"},
        ])
        assert schema["additionalProperties"] is True


class TestBuildMetadataSchema:
    """Test top-level metadata.json schema generation."""

    def test_top_level_structure(self):
        from fairifier.validation.json_schema import build_metadata_schema

        fields_by_sheet = {
            "investigation": [
                {"name": "investigation title",       "data_type": "string"},
                {"name": "investigation description", "data_type": "text"},
                {"name": "investigation identifier",  "data_type": "string"},
            ],
        }
        schema = build_metadata_schema(fields_by_sheet)

        assert schema["type"] == "object"
        assert "fairifier_version" in schema["properties"]
        assert "isa_structure" in schema["properties"]
        assert "document_info" in schema["properties"]
        assert "investigation" in schema["properties"]["isa_structure"]["properties"]

    def test_empty_sheets_are_skipped(self):
        from fairifier.validation.json_schema import build_metadata_schema

        schema = build_metadata_schema({})
        assert schema["properties"]["isa_structure"]["properties"] == {}


class TestValidateIsaStructure:
    """Test ISA structure validation against dynamic schema."""

    def test_valid_investigation_passes(self):
        from fairifier.validation.json_schema import validate_isa_structure

        fields = [
            {"name": "investigation title",       "data_type": "string", "isa_sheet": "investigation"},
            {"name": "investigation description", "data_type": "text",   "isa_sheet": "investigation"},
            {"name": "investigation identifier",  "data_type": "string", "isa_sheet": "investigation"},
        ]
        isa = {
            "investigation": {
                "fields": [
                    {"field_name": "investigation title",       "value": "Test Study"},
                    {"field_name": "investigation description", "value": "A test investigation"},
                    {"field_name": "investigation identifier",  "value": "INV-001"},
                ]
            }
        }
        result = validate_isa_structure(isa, fields)
        assert result["valid"], f"Expected valid, got errors: {result['errors']}"

    def test_missing_required_field_fails(self):
        from fairifier.validation.json_schema import validate_isa_structure

        fields = [
            {"name": "investigation title",       "data_type": "string", "isa_sheet": "investigation"},
            {"name": "investigation description", "data_type": "text",   "isa_sheet": "investigation"},
            {"name": "investigation identifier",  "data_type": "string", "isa_sheet": "investigation"},
        ]
        # Missing "investigation description" and "investigation identifier"
        isa = {
            "investigation": {
                "fields": [
                    {"field_name": "investigation title", "value": "Test Study"},
                ]
            }
        }
        result = validate_isa_structure(isa, fields)
        assert not result["valid"], "Expected validation failure for missing required fields"
        assert len(result["errors"]) > 0

    def test_wrong_type_value_fails(self):
        from fairifier.validation.json_schema import validate_isa_structure

        fields = [
            {"name": "investigation title",       "data_type": "string", "isa_sheet": "investigation"},
            {"name": "investigation description", "data_type": "text",   "isa_sheet": "investigation"},
            {"name": "investigation identifier",  "data_type": "string", "isa_sheet": "investigation"},
            {"name": "sample count",              "data_type": "integer", "isa_sheet": "investigation"},
        ]
        isa = {
            "investigation": {
                "fields": [
                    {"field_name": "investigation title",       "value": "Test"},
                    {"field_name": "investigation description", "value": "Desc"},
                    {"field_name": "investigation identifier",  "value": "ID1"},
                    {"field_name": "sample count",              "value": "not_a_number"},
                ]
            }
        }
        result = validate_isa_structure(isa, fields)
        assert not result["valid"], "Expected failure for int field with string value"

    def test_extra_properties_are_allowed(self):
        from fairifier.validation.json_schema import validate_isa_structure

        fields = [
            {"name": "investigation title",       "data_type": "string", "isa_sheet": "investigation"},
            {"name": "investigation description", "data_type": "text",   "isa_sheet": "investigation"},
            {"name": "investigation identifier",  "data_type": "string", "isa_sheet": "investigation"},
        ]
        isa = {
            "investigation": {
                "fields": [
                    {"field_name": "investigation title",       "value": "Test"},
                    {"field_name": "investigation description", "value": "Desc"},
                    {"field_name": "investigation identifier",  "value": "ID1"},
                    {"field_name": "extra_custom_field",        "value": "bonus data"},
                ]
            }
        }
        result = validate_isa_structure(isa, fields)
        assert result["valid"], f"Extra fields should be allowed, got: {result['errors']}"

    def test_multiple_sheets_validated(self):
        from fairifier.validation.json_schema import validate_isa_structure

        fields = [
            {"name": "investigation title",       "data_type": "string", "isa_sheet": "investigation"},
            {"name": "investigation description", "data_type": "text",   "isa_sheet": "investigation"},
            {"name": "investigation identifier",  "data_type": "string", "isa_sheet": "investigation"},
            {"name": "study title",               "data_type": "string", "isa_sheet": "study"},
            {"name": "study description",         "data_type": "text",   "isa_sheet": "study"},
            {"name": "study identifier",          "data_type": "string", "isa_sheet": "study"},
        ]
        isa = {
            "investigation": {
                "fields": [
                    {"field_name": "investigation title",       "value": "T1"},
                    {"field_name": "investigation description", "value": "D1"},
                    {"field_name": "investigation identifier",  "value": "I1"},
                ]
            },
            "study": {
                "fields": [
                    {"field_name": "study title",       "value": "S1"},
                    {"field_name": "study description", "value": "SD1"},
                    {"field_name": "study identifier",  "value": "SI1"},
                ]
            },
        }
        result = validate_isa_structure(isa, fields)
        assert result["valid"], f"Multi-sheet validation failed: {result['errors']}"

    def test_shapes_warn_when_mandatory_not_selected(self):
        from fairifier.validation.json_schema import validate_isa_structure

        # Only select non-mandatory fields for investigation
        fields = [
            {"name": "investigation contributor", "data_type": "string", "isa_sheet": "investigation"},
        ]
        isa = {"investigation": {"fields": [
            {"field_name": "investigation contributor", "value": "John"},
        ]}}
        result = validate_isa_structure(isa, fields)
        # Schema is valid because we only check what was selected,
        # but we warn about missing ShEx-mandatory fields
        assert len(result["warnings"]) > 0, "Should warn about unselected mandatory fields"

    def test_empty_isa_structure(self):
        from fairifier.validation.json_schema import validate_isa_structure

        result = validate_isa_structure({}, [])
        assert result["valid"], "Empty ISA structure should be valid"


class TestValidateMetadata:
    """Test full metadata.json validation."""

    def test_validate_complete_metadata(self):
        from fairifier.validation.json_schema import validate_metadata

        fields = [
            {"name": "investigation title",       "data_type": "string", "isa_sheet": "investigation"},
            {"name": "investigation description", "data_type": "text",   "isa_sheet": "investigation"},
            {"name": "investigation identifier",  "data_type": "string", "isa_sheet": "investigation"},
        ]
        metadata = {
            "fairifier_version": "1.5.0",
            "generated_at": "2026-05-03T00:00:00",
            "document_source": "/tmp/test.bam",
            "overall_confidence": 0.75,
            "needs_review": False,
            "packages_used": ["default", "Genome"],
            "isa_structure": {
                "investigation": {
                    "fields": [
                        {"field_name": "investigation title",       "value": "Test"},
                        {"field_name": "investigation description", "value": "Desc"},
                        {"field_name": "investigation identifier",  "value": "ID1"},
                    ]
                }
            },
            "document_info": {"title": "test"},
            "evidence_packets_summary": {},
            "confidence_scores": {},
            "errors": [],
            "warnings": [],
        }
        errors = validate_metadata(metadata, fields)
        assert errors == [], f"Expected valid, got: {errors}"


class TestTypeMapping:
    """Test FAIRDS data_type → JSON Schema type mapping."""

    def test_all_type_values_are_mapped(self):
        from fairifier.validation.json_schema import _json_type_for, _TYPE_MAP

        for type_key in _TYPE_MAP:
            result = _json_type_for({"data_type": type_key})
            assert "type" in result, f"No JSON type mapped for FAIRDS type: {type_key}"
            assert result["type"] in ("string", "number", "integer", "boolean"), \
                f"Unexpected JSON type for {type_key}: {result['type']}"

    def test_unknown_type_defaults_to_string(self):
        from fairifier.validation.json_schema import _json_type_for

        result = _json_type_for({"data_type": "exotic_custom_type"})
        assert result["type"] == "string"


class TestFieldKeyNormalization:
    """Test field name → schema property key normalization."""

    def test_field_key_lowercase(self):
        from fairifier.validation.json_schema import _field_key

        assert _field_key({"name": "Investigation Title"}) == "investigation title"
        assert _field_key({"label": "Study ID"}) == "study id"

    def test_field_key_strips_whitespace(self):
        from fairifier.validation.json_schema import _field_key

        assert _field_key({"name": "  assay name  "}) == "assay name"
