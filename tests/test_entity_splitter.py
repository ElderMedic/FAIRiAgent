from fairifier.utils.entity_splitter import split_entities_in_isa_structure


def test_split_entities_in_isa_structure_splits_semicolon_rows():
    isa_structure = {
        "sample": {
            "columns": ["sample name", "sample description", "scientific name"],
            "rows": [
                {
                    "sample name": "Sample A; Sample B",
                    "sample description": "Description for sample A; Description for sample B",
                    "scientific name": "Eisenia fetida",
                }
            ],
            "fields": [],
        }
    }

    result = split_entities_in_isa_structure(isa_structure)
    rows = result["sample"]["rows"]

    assert len(rows) == 2
    assert rows[0]["sample name"] == "Sample A"
    assert rows[1]["sample name"] == "Sample B"
    assert rows[0]["scientific name"] == "Eisenia fetida"
    assert rows[1]["scientific name"] == "Eisenia fetida"


def test_split_entities_in_isa_structure_updates_legacy_fields_from_first_row():
    isa_structure = {
        "sample": {
            "columns": ["sample name", "sample description"],
            "rows": [
                {
                    "sample name": "Sample A; Sample B",
                    "sample description": "Description for sample A; Description for sample B",
                }
            ],
            "fields": [],
        }
    }

    result = split_entities_in_isa_structure(isa_structure)

    assert result["sample"]["fields"] == [
        {"field_name": "sample name", "value": "Sample A"},
        {"field_name": "sample description", "value": "Description for sample A"},
    ]


def test_split_entities_in_isa_structure_keeps_single_entity_method_text():
    isa_structure = {
        "assay": {
            "columns": ["assay description"],
            "rows": [
                {
                    "assay description": "Heating; then cooling",
                }
            ],
            "fields": [],
        }
    }

    result = split_entities_in_isa_structure(isa_structure)

    assert len(result["assay"]["rows"]) == 1
    assert result["assay"]["rows"][0]["assay description"] == "Heating; then cooling"
