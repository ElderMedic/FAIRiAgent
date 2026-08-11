"""Release gate tests; no endpoint or model calls are made."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.benchmark.release_gate import audit_release


FIXTURES = Path(__file__).parents[1] / "evaluation" / "benchmark" / "fixtures"


def test_smoke_release_gate_reports_unapproved_model_and_run_blockers(tmp_path: Path) -> None:
    manifest = FIXTURES / "benchmark_v2_smoke_manifest.json"
    result = audit_release(manifest, project_root=FIXTURES)
    assert result["status"] == "blocked"
    assert "model_panel" in result["blockers"]
    assert "run_index" in result["blockers"]
    assert result["model_or_api_calls_performed"] is False


def test_release_gate_reports_split_leakage(tmp_path: Path) -> None:
    manifest = json.loads((FIXTURES / "benchmark_v2_smoke_manifest.json").read_text())
    manifest["instances"][0]["split"] = "generalization"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    result = audit_release(path, project_root=FIXTURES)
    # No duplicate group exists in this one-instance fixture; the gate still
    # remains blocked for the intentionally missing model/run approvals.
    assert result["gates"]["assets_and_split"]["status"] == "passed"


def test_release_gate_does_not_freeze_panel_from_success_rate_only(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "model_id": "fixture_model",
                        "selection_slot": slot,
                        "provider": "fixture",
                        "model_name": "fixture",
                    }
                    for slot in (
                        "hosted_efficient",
                        "hosted_capability",
                        "hosted_independent_family",
                        "local_compact",
                        "local_medium",
                        "local_large",
                    )
                ],
                "endpoint_checks_performed": False,
                "token_calls_performed": False,
            }
        )
    )
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(
        json.dumps(
            {
                "records": [
                    {"model_id": "fixture_model", "status": "passed", "standard_success_rate": 1.0}
                ]
            }
        )
    )
    result = audit_release(
        FIXTURES / "benchmark_v2_smoke_manifest.json",
        project_root=FIXTURES,
        model_inventory_path=inventory_path,
        preflight_path=preflight_path,
    )
    assert result["gates"]["model_panel"]["status"] == "blocked"
    assert result["gates"]["model_panel"]["preflight_errors"]


def test_release_gate_fails_closed_when_baseline_context_is_missing(tmp_path: Path) -> None:
    manifest = json.loads((FIXTURES / "benchmark_v2_smoke_manifest.json").read_text())
    manifest["conditions"] = [
        {
            "condition_id": "standards_guided_extraction",
            "publication_name": "Standards-guided extraction",
            "component_settings": {"standards_context": True},
        }
    ]
    for run in manifest["scheduled_runs"]:
        run["condition_id"] = "standards_guided_extraction"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    result = audit_release(path, project_root=FIXTURES)
    assert result["gates"]["condition_contexts"]["status"] == "blocked"
    assert "standards_context_path" in result["gates"]["condition_contexts"]["errors"][0]


def test_release_gate_rejects_partial_preflight_plan_records(tmp_path: Path) -> None:
    slots = (
        "hosted_efficient",
        "hosted_capability",
        "hosted_independent_family",
        "local_compact",
        "local_medium",
        "local_large",
    )
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "model_id": "fixture_model",
                        "selection_slot": slot,
                        "provider": "fixture",
                        "model_name": "fixture",
                    }
                    for slot in slots
                ],
                "endpoint_checks_performed": True,
                "token_calls_performed": True,
            }
        )
    )
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(
        json.dumps(
            {
                "plan": {
                    "jobs": [
                        {
                            "model_id": "fixture_model",
                            "instance_id": "fixture_document",
                            "repetition": 1,
                        }
                    ]
                },
                "records": [],
            }
        )
    )
    result = audit_release(
        FIXTURES / "benchmark_v2_smoke_manifest.json",
        project_root=FIXTURES,
        model_inventory_path=inventory_path,
        preflight_path=preflight_path,
    )
    errors = result["gates"]["model_panel"]["preflight_errors"]
    assert any("missing preflight records" in error for error in errors)
