"""Deterministic IsaMatrixCompiler graph node tests."""

import json

import pytest

from fairifier.graph.app import FAIRifierLangGraphApp
from fairifier.graph.nodes import IsaMatrixCompilerNode


@pytest.mark.anyio
async def test_isa_matrix_compiler_node_collapses_duplicate_ids_and_syncs():
    node = IsaMatrixCompilerNode()
    state = {
        "artifacts": {
            "metadata_json": json.dumps(
                {
                    "isa_structure": {
                        "sample": {
                            "fields": [
                                {"field_name": "sample identifier", "value": "REP_01"}
                            ],
                            "columns": ["sample identifier", "sample name"],
                            "rows": [
                                {"sample identifier": "REP_01", "sample name": "A"},
                                {"sample identifier": "REP_01", "sample name": ""},
                            ],
                        }
                    },
                    "isa_values": {
                        "sample": {
                            "columns": ["sample identifier", "sample name"],
                            "rows": [
                                {"sample identifier": "REP_01", "sample name": "A"},
                                {"sample identifier": "REP_01", "sample name": ""},
                            ],
                        }
                    },
                }
            ),
            "isa_values_json": json.dumps(
                {
                    "sample": {
                        "columns": ["sample identifier", "sample name"],
                        "rows": [
                            {"sample identifier": "REP_01", "sample name": "A"},
                            {"sample identifier": "REP_01", "sample name": ""},
                        ],
                    }
                }
            ),
        },
        "context": {},
        "errors": [],
    }

    result = await node(state)
    meta = json.loads(result["artifacts"]["metadata_json"])
    side = json.loads(result["artifacts"]["isa_values_json"])

    assert result["context"]["isa_matrix_compiler"] == "isa_matrix_compiler"
    assert meta["isa_matrix_id"] == result["artifacts"]["isa_matrix_id"]
    assert len(meta["isa_values"]["sample"]["rows"]) == 1
    assert len(side["sample"]["rows"]) == 1
    assert meta["isa_values"]["sample"]["rows"] == side["sample"]["rows"]
    # Flat field list must keep values (compiler must not wipe them).
    assert meta["isa_structure"]["sample"]["fields"][0]["value"] == "REP_01"


def test_main_workflow_routes_through_isa_matrix_compiler():
    app = FAIRifierLangGraphApp.__new__(FAIRifierLangGraphApp)
    graph = app._build_graph_structure()

    assert "isa_matrix_compiler" in graph.nodes
    assert ("orchestrate", "isa_matrix_compiler") in graph.edges
    assert ("isa_matrix_compiler", "auto_repair") in graph.edges
    assert ("auto_repair", "finalize") in graph.edges
    assert ("orchestrate", "auto_repair") not in graph.edges
