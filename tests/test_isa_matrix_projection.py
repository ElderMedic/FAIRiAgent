"""Tests for single-projection ISA matrix sync (slim §12.1 path)."""

import json

from fairifier.utils.isa_matrix_projection import (
    apply_matrix_to_metadata,
    sync_compiled_matrix_to_state,
)


def test_sync_compiled_matrix_aligns_metadata_and_sidecar():
    state = {
        "artifacts": {
            "metadata_json": json.dumps(
                {
                    "isa_structure": {
                        "sample": {
                            "fields": [{"field_name": "sample identifier", "value": "X"}],
                            "columns": ["sample identifier"],
                            "rows": [
                                {"sample identifier": "REP_01"},
                                {"sample identifier": "REP_01"},
                            ],
                        }
                    },
                    "isa_values": {
                        "sample": {
                            "columns": ["sample identifier"],
                            "rows": [
                                {"sample identifier": "REP_01"},
                                {"sample identifier": "REP_01"},
                            ],
                        }
                    },
                }
            ),
            "isa_values_json": json.dumps(
                {
                    "sample": {
                        "columns": ["sample identifier"],
                        "rows": [
                            {"sample identifier": "REP_01"},
                            {"sample identifier": "REP_01"},
                        ],
                    }
                }
            ),
        },
        "context": {},
    }
    matrix = {
        "sample": {
            "columns": ["sample identifier"],
            "rows": [
                {"sample identifier": "REP_01"},
                {"sample identifier": "REP_01"},
            ],
        }
    }
    projected = sync_compiled_matrix_to_state(state, matrix, recompile=True)
    assert projected["matrix_id"]
    meta = json.loads(state["artifacts"]["metadata_json"])
    side = json.loads(state["artifacts"]["isa_values_json"])
    assert meta["isa_matrix_id"] == projected["matrix_id"]
    assert len(meta["isa_values"]["sample"]["rows"]) == 1
    assert len(side["sample"]["rows"]) == 1
    assert meta["isa_values"]["sample"]["rows"] == side["sample"]["rows"]


def test_apply_matrix_to_metadata_preserves_fields_list():
    payload = {
        "isa_structure": {
            "study": {
                "fields": [{"field_name": "study title", "value": "T"}],
                "columns": [],
                "rows": [],
            }
        }
    }
    matrix = {
        "study": {
            "columns": ["study identifier", "study title"],
            "rows": [{"study identifier": "ST1", "study title": "T"}],
        }
    }
    updated = apply_matrix_to_metadata(payload, matrix, matrix_id="abc")
    assert updated["isa_structure"]["study"]["fields"][0]["field_name"] == "study title"
    assert updated["isa_values"]["study"]["rows"][0]["study identifier"] == "ST1"
    assert updated["isa_matrix_id"] == "abc"
