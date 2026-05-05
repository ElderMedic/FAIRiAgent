from fairifier.validation.json_schema import SHEX_SHAPES
from fairifier.validation.metadata_json_format import REQUIRED_FIELDS_BY_SHEET


def test_required_fields_by_sheet_match_shex_required_core_fields():
    expected = {}
    for shape in SHEX_SHAPES.values():
        sheet = shape.get("isa_sheet")
        if sheet not in REQUIRED_FIELDS_BY_SHEET:
            continue
        expected[sheet] = sorted(
            name
            for name, prop in shape["properties"].items()
            if prop.get("required")
        )

    observed = {
        sheet: sorted(fields)
        for sheet, fields in REQUIRED_FIELDS_BY_SHEET.items()
    }

    assert observed == expected
