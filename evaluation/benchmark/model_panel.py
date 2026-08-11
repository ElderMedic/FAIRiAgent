"""Materialize an auditable frozen model-panel artifact without model calls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from .model_preflight import (
    select_model_panel,
    validate_preflight_plan_coverage,
    validate_preflight_records,
)


class ModelPanelError(ValueError):
    """Raised when panel evidence is incomplete or ambiguous."""


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def freeze_model_panel(
    inventory: Mapping[str, Any],
    preflight_plan: Mapping[str, Any],
    preflight_records: Sequence[Mapping[str, Any]],
    *,
    freeze_confirmation: str,
    hardware_records: Mapping[str, Mapping[str, Any]] | None = None,
    slots: Sequence[str] | None = None,
    required_model_ids: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """Create a frozen panel artifact from complete preflight evidence.

    This function only serializes already-produced evidence. It never probes an
    endpoint or loads a model. A non-empty researcher confirmation and local
    hardware/quantization records are required before a panel can be frozen.
    """

    if not isinstance(freeze_confirmation, str) or not freeze_confirmation.strip():
        raise ModelPanelError("freeze_confirmation is required")
    record_errors = validate_preflight_records(inventory, preflight_records)
    record_errors.extend(validate_preflight_plan_coverage(preflight_plan, preflight_records))
    if record_errors:
        raise ModelPanelError("preflight evidence is incomplete:\n- " + "\n- ".join(record_errors))

    selection = select_model_panel(
        inventory,
        preflight_records,
        slots=slots or (
            "hosted_efficient",
            "hosted_capability",
            "hosted_independent_family",
            "local_compact",
            "local_medium",
            "local_large",
        ),
        required_model_ids=required_model_ids,
    )
    if selection.get("status") != "ready":
        raise ModelPanelError("model panel is not ready: %s" % json.dumps(selection, sort_keys=True))

    candidates = {
        str(candidate.get("model_id")): candidate
        for candidate in inventory.get("candidates", [])
        if isinstance(candidate, Mapping) and candidate.get("model_id")
    }
    collapsed_records: Dict[str, Dict[str, Any]] = {}
    for record in preflight_records:
        model_id = record.get("model_id")
        if not isinstance(model_id, str) or not model_id:
            continue
        bucket = collapsed_records.setdefault(model_id, {"model_id": model_id, "records": []})
        bucket["records"].append(dict(record))

    hardware = dict(hardware_records or {})
    models: list[Dict[str, Any]] = []
    excluded_slots: list[Dict[str, Any]] = []
    for slot, item in selection["slots"].items():
        if item["status"] == "excluded":
            excluded_slots.append(
                {
                    "slot": slot,
                    "candidate_model_ids": item["candidate_model_ids"],
                    "exclusion_reasons": item.get("exclusion_reasons", []),
                }
            )
            continue
        model_id = str(item.get("selected_model_id") or item.get("model_id"))
        candidate = candidates.get(model_id)
        if candidate is None:
            raise ModelPanelError("selected model is absent from inventory: %s" % model_id)
        model = dict(candidate)
        model["selection_slot"] = candidate.get("selection_slot", slot)
        model["standard_success_rate"] = item.get("standard_success_rate")
        model_records = collapsed_records.get(model_id, {}).get("records", [])
        model["preflight_record_count"] = len(model_records)
        # The inventory is intentionally token-free and therefore starts with
        # ``preflight_status=not_run``.  Once complete records are validated,
        # the frozen panel must carry the observed contract status rather than
        # the planning placeholder.
        model["preflight_status"] = "passed"
        model["preflight_endpoint_health"] = "passed"
        model["preflight_context_length"] = "passed"
        model["preflight_structured_output"] = "passed"
        model["preflight_tool_contract"] = "passed"
        if model.get("endpoint_class") == "local":
            local_record = hardware.get(model_id)
            if not isinstance(local_record, Mapping):
                raise ModelPanelError("local hardware record is missing: %s" % model_id)
            required_hardware = ("serving_version", "quantization", "hardware_model", "memory_gb")
            missing = [key for key in required_hardware if not local_record.get(key)]
            if missing:
                raise ModelPanelError(
                    "%s local hardware record is missing: %s" % (model_id, ", ".join(missing))
                )
            model["local_hardware"] = dict(local_record)
            if local_record.get("endpoint_digest"):
                model["endpoint_digest"] = local_record["endpoint_digest"]
            if local_record.get("endpoint_model"):
                model["resolved_endpoint_model"] = local_record["endpoint_model"]
        models.append(model)

    return {
        "schema_version": "fairiagent.model_panel.v1",
        "status": "frozen",
        "freeze_confirmation": freeze_confirmation.strip(),
        "selection_rule": (
            "explicit_researcher_requested_panel"
            if required_model_ids is not None
            else "lowest_cost_within_success_tolerance"
        ),
        "requested_model_ids": list(required_model_ids) if required_model_ids is not None else None,
        "success_tolerance": selection.get("success_tolerance"),
        "models": models,
        "excluded_slots": excluded_slots,
        "preflight": {
            "plan_schema_version": preflight_plan.get("schema_version"),
            "plan_digest": _canonical_digest(preflight_plan),
            "records_digest": _canonical_digest(list(preflight_records)),
            "record_count": len(preflight_records),
            "coverage_validated": True,
        },
        "inventory_digest": _canonical_digest(inventory),
        "model_or_api_calls_performed": False,
        "materialized_without_new_model_calls": True,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Materialize a frozen model panel from preflight evidence")
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--preflight-plan", type=Path, required=True)
    parser.add_argument("--preflight-records", type=Path, required=True)
    parser.add_argument("--hardware-records", type=Path)
    parser.add_argument("--freeze-confirmation", required=True)
    parser.add_argument("--slot", action="append", default=[])
    parser.add_argument("--model-id", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    plan = json.loads(args.preflight_plan.read_text(encoding="utf-8"))
    raw_records = json.loads(args.preflight_records.read_text(encoding="utf-8"))
    # The preflight runner writes an auditable envelope, while the library
    # function accepts the underlying record sequence.  Accept both forms so
    # the persisted execution artifact can be passed directly to this CLI.
    if isinstance(raw_records, Mapping):
        records = raw_records.get("records")
    else:
        records = raw_records
    if not isinstance(records, list):
        parser.error("--preflight-records must contain a list or an envelope with a records list")
    hardware = (
        json.loads(args.hardware_records.read_text(encoding="utf-8"))
        if args.hardware_records
        else None
    )
    panel = freeze_model_panel(
        inventory,
        plan,
        records,
        freeze_confirmation=args.freeze_confirmation,
        hardware_records=hardware,
        slots=args.slot or None,
        required_model_ids=args.model_id or None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(panel, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(panel, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
