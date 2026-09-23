"""Machine-readable release gate for a FAIRiAgent benchmark batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .assets import collect_asset_checksums
from .contracts import load_manifest
from .dataset_inventory import validate_split_leakage
from .model_preflight import (
    select_model_panel,
    validate_preflight_plan_coverage,
    validate_preflight_records,
)
from .run_index import validate_run_index


_BASELINE_CONTEXT_REQUIREMENTS = {
    "standards_guided_extraction": ("standards_context_path",),
    "retrieval_assisted_extraction": (
        "standards_context_path",
        "retrieved_context_path",
    ),
}


def validate_condition_contexts(manifest: Mapping[str, Any]) -> list[str]:
    """Fail closed when a selected publication baseline lacks context assets.

    Agentic conditions materialize their package/retrieval state inside their
    own execution adapter. The three publication baselines instead receive
    explicit immutable context files, so their requirements are checked here
    before a release can be approved.
    """

    condition_ids = {
        str(condition.get("condition_id"))
        for condition in manifest.get("conditions", [])
        if isinstance(condition, Mapping) and condition.get("condition_id")
    }
    errors: list[str] = []
    for condition_id, required_keys in _BASELINE_CONTEXT_REQUIREMENTS.items():
        if condition_id not in condition_ids:
            continue
        for instance in manifest.get("instances", []):
            if not isinstance(instance, Mapping):
                continue
            instance_id = str(instance.get("instance_id") or "unknown")
            for key in required_keys:
                value = instance.get(key)
                if not isinstance(value, str) or not value.strip():
                    errors.append(
                        "%s requires %s for instance %s"
                        % (condition_id, key, instance_id)
                    )
    return errors


def audit_release(
    manifest_path: Path,
    *,
    project_root: Path,
    model_inventory_path: Optional[Path] = None,
    preflight_path: Optional[Path] = None,
    preflight_plan_path: Optional[Path] = None,
    run_index_path: Optional[Path] = None,
    required_model_ids: list[str] | None = None,
) -> Dict[str, Any]:
    """Audit release prerequisites without contacting any endpoint."""

    gates: Dict[str, Dict[str, Any]] = {}
    try:
        manifest = load_manifest(manifest_path)
        gates["manifest"] = {"status": "passed", "errors": []}
    except Exception as exc:  # noqa: BLE001 - gate must report all blockers
        return {
            "status": "blocked",
            "gates": {"manifest": {"status": "failed", "errors": [str(exc)]}},
        }

    try:
        assets = collect_asset_checksums(
            manifest,
            manifest_path,
            project_root=project_root,
            require_ground_truth=True,
        )
        leakage = validate_split_leakage(manifest["instances"], assets)
        gates["assets_and_split"] = {
            "status": "passed" if not leakage else "failed",
            "errors": leakage,
            "instance_count": len(manifest["instances"]),
        }
    except Exception as exc:  # noqa: BLE001
        gates["assets_and_split"] = {"status": "failed", "errors": [str(exc)]}

    context_errors = validate_condition_contexts(manifest)
    gates["condition_contexts"] = {
        "status": "passed" if not context_errors else "blocked",
        "errors": context_errors,
    }

    inventory: Mapping[str, Any] = {"candidates": []}
    inventory_errors: list[str] = []
    if model_inventory_path and model_inventory_path.is_file():
        try:
            loaded_inventory = json.loads(model_inventory_path.read_text(encoding="utf-8"))
            if not isinstance(loaded_inventory, Mapping):
                inventory_errors = ["model_inventory_must_be_an_object"]
            else:
                inventory = loaded_inventory
        except (OSError, json.JSONDecodeError) as exc:
            inventory_errors = ["model_inventory_error:%s" % exc]
    elif model_inventory_path:
        inventory_errors = ["model_inventory_not_found"]
    preflight_records = []
    preflight_errors = ["preflight_not_supplied"]
    preflight_plan: Optional[Mapping[str, Any]] = None
    preflight_envelope: Mapping[str, Any] = {}
    if preflight_path and preflight_path.is_file():
        try:
            value = json.loads(preflight_path.read_text(encoding="utf-8"))
            if isinstance(value, Mapping):
                preflight_envelope = value
                candidate_plan = value.get("plan")
                if isinstance(candidate_plan, Mapping):
                    preflight_plan = candidate_plan
                preflight_records = value.get("records", value)
            else:
                preflight_records = value
            if isinstance(preflight_records, list):
                preflight_errors = validate_preflight_records(inventory, preflight_records)
                if preflight_plan is not None:
                    preflight_errors.extend(
                        validate_preflight_plan_coverage(preflight_plan, preflight_records)
                    )
            else:
                preflight_errors = ["preflight_records_must_be_a_list"]
        except (OSError, json.JSONDecodeError) as exc:
            preflight_errors = ["preflight_error:%s" % exc]
    elif preflight_path:
        preflight_errors = ["preflight_not_found"]
    if preflight_plan is None and preflight_plan_path:
        if preflight_plan_path.is_file():
            try:
                candidate_plan = json.loads(preflight_plan_path.read_text(encoding="utf-8"))
                if isinstance(candidate_plan, Mapping):
                    preflight_plan = candidate_plan
                else:
                    preflight_errors.append("preflight_plan_must_be_an_object")
            except (OSError, json.JSONDecodeError) as exc:
                preflight_errors.append("preflight_plan_error:%s" % exc)
        else:
            preflight_errors.append("preflight_plan_not_found")
    preflight_errors = inventory_errors + preflight_errors
    panel = select_model_panel(
        inventory,
        preflight_records or [],
        required_model_ids=required_model_ids,
    )
    interface_ready = (
        (bool(inventory.get("endpoint_checks_performed")) or bool(preflight_envelope.get("endpoint_checks_performed")))
        and (bool(inventory.get("token_calls_performed")) or bool(preflight_envelope.get("token_calls_performed")))
        and not preflight_errors
    )
    gates["model_panel"] = {
        "status": "passed" if panel["status"] == "ready" and interface_ready else "blocked",
        "selection": panel,
        "endpoint_checks_performed": bool(inventory.get("endpoint_checks_performed")) or bool(preflight_envelope.get("endpoint_checks_performed")),
        "token_calls_performed": bool(inventory.get("token_calls_performed")) or bool(preflight_envelope.get("token_calls_performed")),
        "preflight_errors": preflight_errors,
    }

    if run_index_path and run_index_path.is_file():
        try:
            run_index = json.loads(run_index_path.read_text(encoding="utf-8"))
            run_index_errors = validate_run_index(run_index)
            scheduled_count = len(manifest["scheduled_runs"])
            observed_count = len(run_index.get("results") or [])
            attached = run_index.get("evaluated_with") == "evaluation.benchmark.attach_evaluator"
            gates["run_index"] = {
                "status": "passed"
                if attached and observed_count == scheduled_count and not run_index_errors
                else "blocked",
                "scheduled_count": scheduled_count,
                "observed_count": observed_count,
                "evaluator_attached": attached,
                "errors": run_index_errors,
            }
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            gates["run_index"] = {"status": "failed", "errors": [str(exc)]}
    else:
        gates["run_index"] = {"status": "blocked", "reason": "run_index_not_supplied"}

    blockers = [name for name, gate in gates.items() if gate.get("status") != "passed"]
    return {
        "schema_version": "fairiagent.release_gate.v2",
        "status": "passed" if not blockers else "blocked",
        "blockers": blockers,
        "gates": gates,
        "model_or_api_calls_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit FAIRiAgent benchmark release prerequisites")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--model-inventory", type=Path)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--preflight-plan", type=Path)
    parser.add_argument("--run-index", type=Path)
    parser.add_argument("--model-id", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_release(
        args.manifest,
        project_root=args.project_root,
        model_inventory_path=args.model_inventory,
        preflight_path=args.preflight,
        preflight_plan_path=args.preflight_plan,
        run_index_path=args.run_index,
        required_model_ids=args.model_id or None,
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
