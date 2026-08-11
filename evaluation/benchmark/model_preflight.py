"""Token-free inventory and preflight manifest for hosted and local models.

This module reads model configuration metadata only. It never calls an endpoint,
loads a model, or sends a prompt. Endpoint health and structured-output checks
are an explicit later gate before the model panel is frozen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


SAFE_KEYS = {
    "LLM_PROVIDER",
    "FAIRIFIER_LLM_MODEL",
    "FAIRIFIER_LLM_BASE_URL",
    "LLM_TEMPERATURE",
    "LLM_TOP_P",
    "LLM_TOP_K",
    "LLM_REPEAT_PENALTY",
    "LLM_PRESENCE_PENALTY",
    "LLM_MAX_TOKENS",
    "LLM_ENABLE_THINKING",
}


def _default_model_card_registry_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "model_card_registry.json"


def _load_model_card_registry(path: Path | None = None) -> Dict[str, Any]:
    """Load static official-card metadata without contacting a model service."""

    registry_path = path or _default_model_card_registry_path()
    try:
        value = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def read_safe_env(path: Path) -> Dict[str, str]:
    """Read only non-secret model settings from an env file."""

    values: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in SAFE_KEYS:
            values[key] = value.strip().strip('"').strip("'")
    return values


def _infer_slot(provider: str, model_name: str, model_id: str) -> str:
    if provider == "ollama":
        lowered = model_name.lower()
        size_match = re.search(r"(?<!\d)(\d+)b(?!\d)", lowered)
        if size_match:
            size_b = int(size_match.group(1))
            if size_b <= 20:
                return "local_compact"
            if size_b <= 40:
                return "local_medium"
        return "local_large"
    if any(name in model_name.lower() for name in ("flash", "haiku", "mini")):
        return "hosted_efficient"
    if provider in {"deepseek", "qwen", "zhipu"}:
        return "hosted_independent_family"
    if provider in {"openai", "anthropic"}:
        return "hosted_capability"
    return "unclassified"


def inventory_model_configs(
    model_dir: Path,
    *,
    model_card_registry_path: Path | None = None,
) -> Dict[str, Any]:
    """Build a candidate inventory without reading secrets or contacting APIs."""

    candidates: List[Dict[str, Any]] = []
    identity_groups: Dict[str, List[str]] = {}
    card_registry = _load_model_card_registry(model_card_registry_path).get("models", {})
    if not isinstance(card_registry, Mapping):
        card_registry = {}
    for path in sorted(model_dir.glob("*.env")):
        settings = read_safe_env(path)
        provider = settings.get("LLM_PROVIDER", "unknown")
        model_name = settings.get("FAIRIFIER_LLM_MODEL", "unknown")
        identity_payload = "|".join(
            settings.get(key, "")
            for key in (
                "LLM_PROVIDER",
                "FAIRIFIER_LLM_MODEL",
                "FAIRIFIER_LLM_BASE_URL",
                "LLM_TEMPERATURE",
                "LLM_TOP_P",
                "LLM_TOP_K",
                "LLM_REPEAT_PENALTY",
                "LLM_PRESENCE_PENALTY",
                "LLM_MAX_TOKENS",
                "LLM_ENABLE_THINKING",
            )
        )
        identity = hashlib.sha256(identity_payload.encode("utf-8")).hexdigest()[:16]
        candidate = {
                "model_id": path.stem,
                "config_path": str(path),
                "provider": provider,
                "model_name": model_name,
                "endpoint_class": "local" if provider == "ollama" else "hosted",
                "endpoint": settings.get("FAIRIFIER_LLM_BASE_URL"),
                "temperature": settings.get("LLM_TEMPERATURE"),
                "top_p": settings.get("LLM_TOP_P"),
                "top_k": settings.get("LLM_TOP_K"),
                "repeat_penalty": settings.get("LLM_REPEAT_PENALTY"),
                "presence_penalty": settings.get("LLM_PRESENCE_PENALTY"),
                "max_tokens": settings.get("LLM_MAX_TOKENS"),
                "thinking_enabled": settings.get("LLM_ENABLE_THINKING"),
                "selection_slot": _infer_slot(provider, model_name, path.stem),
                "canonical_model_identity": identity,
                "configuration_hash": identity,
                "model_card": dict(card_registry.get(path.stem, {}))
                if isinstance(card_registry.get(path.stem), Mapping)
                else {},
                "preflight_status": "not_run",
            }
        candidates.append(candidate)
        identity_groups.setdefault(identity, []).append(path.stem)
    for candidate in candidates:
        candidate["configuration_aliases"] = identity_groups[candidate["canonical_model_identity"]]
    return {
        "schema_version": "fairiagent.model_candidate_inventory.v2",
        "endpoint_checks_performed": False,
        "token_calls_performed": False,
        "candidate_count": len(candidates),
        "unique_model_identity_count": len(identity_groups),
        "identity_groups": identity_groups,
        "candidates": candidates,
    }


def restrict_model_inventory(
    inventory: Mapping[str, Any],
    model_ids: Sequence[str],
) -> Dict[str, Any]:
    """Return a token-free inventory containing exactly the requested IDs."""

    requested = [str(model_id) for model_id in model_ids if str(model_id).strip()]
    if not requested:
        raise ValueError("at least one model_id is required")
    requested_set = set(requested)
    candidates = [
        dict(candidate)
        for candidate in inventory.get("candidates", [])
        if isinstance(candidate, Mapping) and str(candidate.get("model_id")) in requested_set
    ]
    present = {str(candidate.get("model_id")) for candidate in candidates}
    missing = [model_id for model_id in requested if model_id not in present]
    if missing:
        raise ValueError("requested model_id not found in inventory: " + ", ".join(missing))
    identity_groups: Dict[str, List[str]] = {}
    for candidate in candidates:
        identity = str(candidate.get("canonical_model_identity") or candidate.get("model_id"))
        identity_groups.setdefault(identity, []).append(str(candidate.get("model_id")))
    for candidate in candidates:
        candidate["configuration_aliases"] = identity_groups[
            str(candidate.get("canonical_model_identity") or candidate.get("model_id"))
        ]
    result = dict(inventory)
    result["candidates"] = candidates
    result["candidate_count"] = len(candidates)
    result["unique_model_identity_count"] = len(identity_groups)
    result["identity_groups"] = identity_groups
    result["requested_model_ids"] = requested
    return result


def select_model_panel(
    inventory: Mapping[str, Any],
    preflight_records: Sequence[Mapping[str, Any]] = (),
    *,
    slots: Sequence[str] = (
        "hosted_efficient",
        "hosted_capability",
        "hosted_independent_family",
        "local_compact",
        "local_medium",
        "local_large",
    ),
    success_tolerance: float = 0.05,
    required_model_ids: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """Select at most one candidate per slot after explicit preflight data.

    With no passed preflight record this function returns ``not_ready`` for the
    slot; it never treats a config file as proof that an endpoint works.
    """

    records = _collapse_preflight_records(preflight_records)
    if required_model_ids is not None:
        candidates_by_id = {
            str(candidate.get("model_id")): candidate
            for candidate in inventory.get("candidates", [])
            if isinstance(candidate, Mapping) and candidate.get("model_id")
        }
        selected_model_ids = [str(model_id) for model_id in required_model_ids]
        missing = [model_id for model_id in selected_model_ids if model_id not in candidates_by_id]
        not_passed = [
            model_id
            for model_id in selected_model_ids
            if model_id in candidates_by_id
            and str((records.get(model_id) or {}).get("status")) != "passed"
        ]
        selected = [
            {
                "model_id": model_id,
                "status": "selected",
                "selection_slot": candidates_by_id[model_id].get("selection_slot", "unclassified"),
                "standard_success_rate": records[model_id].get("standard_success_rate"),
            }
            for model_id in selected_model_ids
            if model_id in candidates_by_id and model_id not in not_passed
        ]
        return {
            "status": "ready" if not missing and not not_passed and selected else "not_ready",
            "success_tolerance": success_tolerance,
            "required_model_ids": selected_model_ids,
            "selected_model_ids": [item["model_id"] for item in selected],
            "missing_model_ids": missing,
            "not_passed_model_ids": not_passed,
            "slots": {item["model_id"]: item for item in selected},
        }
    panel: Dict[str, Any] = {}
    for slot in slots:
        candidates = [
            candidate
            for candidate in inventory.get("candidates", [])
            if candidate.get("selection_slot") == slot
        ]
        explicitly_excluded = [
            candidate
            for candidate in candidates
            if str((records.get(candidate.get("model_id")) or {}).get("status")) == "excluded"
        ]
        if candidates and len(explicitly_excluded) == len(candidates):
            panel[slot] = {
                "status": "excluded",
                "selected_model_id": None,
                "candidate_model_ids": [candidate.get("model_id") for candidate in candidates],
                "exclusion_reasons": sorted(
                    {
                        str((records[candidate["model_id"]].get("exclusion_reason")))
                        for candidate in explicitly_excluded
                    }
                ),
            }
            continue
        passed = [
            candidate
            for candidate in candidates
            if str((records.get(candidate.get("model_id")) or {}).get("status")) == "passed"
        ]
        if not passed:
            panel[slot] = {
                "status": "not_ready",
                "selected_model_id": None,
                "candidate_model_ids": [candidate.get("model_id") for candidate in candidates],
            }
            continue
        scored = [
            (candidate, records[candidate["model_id"]])
            for candidate in passed
            if isinstance(records[candidate["model_id"]].get("standard_success_rate"), (int, float))
        ]
        if not scored:
            panel[slot] = {
                "status": "not_ready",
                "selected_model_id": None,
                "candidate_model_ids": [candidate.get("model_id") for candidate in candidates],
            }
            continue
        best_success = max(float(record["standard_success_rate"]) for _, record in scored)
        near_best = [
            (candidate, record)
            for candidate, record in scored
            if float(record["standard_success_rate"]) >= best_success - success_tolerance
        ]
        def _cost_for_selection(record: Mapping[str, Any]) -> float:
            """Treat an unknown cost as least preferable, never as a crash."""

            value = record.get("estimated_cost_usd")
            if isinstance(value, (int, float)):
                return float(value)
            return float("inf")

        selected, selected_record = min(
            near_best,
            key=lambda item: (
                _cost_for_selection(item[1]),
                -float(item[1]["standard_success_rate"]),
                str(item[0]["model_id"]),
            ),
        )
        panel[slot] = {
            "status": "selected",
            "selected_model_id": selected["model_id"],
            "standard_success_rate": selected_record["standard_success_rate"],
            "selection_rule": "lowest_cost_within_success_tolerance",
            "candidate_model_ids": [candidate.get("model_id") for candidate in candidates],
        }
    return {
        "status": "ready"
        if all(item["status"] in {"selected", "excluded"} for item in panel.values())
        else "not_ready",
        "success_tolerance": success_tolerance,
        "slots": panel,
    }


def _collapse_preflight_records(
    preflight_records: Sequence[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Aggregate repeated/document-level probes into one model-level record.

    A preflight plan may exercise a model on more than one development
    instance. Panel selection needs one comparable record per model, while the
    raw preflight file should retain every probe. Success is conservative:
    every probe must pass and the reported success rate is the arithmetic mean
    across probes. Costs are summed because the same probe schedule is used for
    every candidate.
    """

    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for record in preflight_records:
        model_id = record.get("model_id")
        if isinstance(model_id, str) and model_id:
            grouped.setdefault(model_id, []).append(record)
    collapsed: Dict[str, Dict[str, Any]] = {}
    required_checks = ("endpoint_health", "context_length", "structured_output", "tool_contract")
    for model_id, records in grouped.items():
        statuses = [record.get("status") for record in records]
        passed = all(status == "passed" for status in statuses)
        excluded = all(status == "excluded" for status in statuses)
        check_values = {
            check: "passed"
            if passed and all(record.get(check) == "passed" for record in records)
            else "failed"
            for check in required_checks
        }
        rates = [
            float(record["standard_success_rate"])
            for record in records
            if isinstance(record.get("standard_success_rate"), (int, float))
            and not isinstance(record.get("standard_success_rate"), bool)
        ]
        costs = [
            float(record["estimated_cost_usd"])
            for record in records
            if isinstance(record.get("estimated_cost_usd"), (int, float))
            and not isinstance(record.get("estimated_cost_usd"), bool)
        ]
        collapsed[model_id] = {
            "model_id": model_id,
            "status": "excluded" if excluded else ("passed" if passed else "failed"),
            **check_values,
            "standard_success_rate": sum(rates) / len(rates) if rates else None,
            "estimated_cost_usd": sum(costs) if costs else None,
            "preflight_probe_count": len(records),
            "exclusion_reason": "; ".join(
                sorted(
                    {
                        str(record.get("exclusion_reason"))
                        for record in records
                        if record.get("exclusion_reason")
                    }
                )
            ),
        }
    return collapsed


def build_preflight_plan(
    inventory: Mapping[str, Any],
    development_instance_ids: Sequence[str],
    *,
    repetitions: int = 1,
    estimated_input_tokens_per_probe: int = 2_000,
    estimated_output_tokens_per_probe: int = 800,
) -> Dict[str, Any]:
    """Create a token-free probe plan for explicit researcher approval.

    Configuration aliases sharing one canonical identity are probed once. The
    plan contains no endpoint operation; it only states the calls that a later
    executor would be allowed to make.
    """

    if not development_instance_ids:
        raise ValueError("at least one development instance is required")
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    if estimated_input_tokens_per_probe < 0 or estimated_output_tokens_per_probe < 0:
        raise ValueError("token estimates must be non-negative")

    candidates_by_identity: Dict[str, Dict[str, Any]] = {}
    for candidate in inventory.get("candidates", []):
        if not isinstance(candidate, Mapping):
            continue
        identity = str(candidate.get("canonical_model_identity") or candidate.get("model_id") or "")
        model_id = str(candidate.get("model_id") or "")
        if not identity or not model_id:
            continue
        prior = candidates_by_identity.get(identity)
        if prior is None or model_id < str(prior["model_id"]):
            candidates_by_identity[identity] = dict(candidate)

    jobs: List[Dict[str, Any]] = []
    for candidate in sorted(candidates_by_identity.values(), key=lambda item: str(item["model_id"])):
        for instance_id in development_instance_ids:
            for repetition in range(1, repetitions + 1):
                jobs.append(
                    {
                        "model_id": candidate["model_id"],
                        "canonical_model_identity": candidate.get("canonical_model_identity"),
                        "selection_slot": candidate.get("selection_slot", "unclassified"),
                        "instance_id": str(instance_id),
                        "repetition": repetition,
                        "checks": [
                            "endpoint_health",
                            "context_length",
                            "structured_output",
                            "tool_contract",
                        ],
                        "estimated_llm_calls": 1,
                        "estimated_input_tokens": estimated_input_tokens_per_probe,
                        "estimated_output_tokens": estimated_output_tokens_per_probe,
                    }
                )
    calls = sum(job["estimated_llm_calls"] for job in jobs)
    return {
        "schema_version": "fairiagent.model_preflight_plan.v2",
        "endpoint_checks_performed": False,
        "token_calls_performed": False,
        "model_or_api_calls_performed": False,
        "candidate_identity_count": len(candidates_by_identity),
        "development_instance_ids": [str(value) for value in development_instance_ids],
        "repetitions": repetitions,
        "estimated_llm_calls": calls,
        "estimated_input_tokens": calls * estimated_input_tokens_per_probe,
        "estimated_output_tokens": calls * estimated_output_tokens_per_probe,
        "stop_conditions": [
            "stop after any endpoint health failure without retrying indefinitely",
            "stop a model after one structured-output or tool-contract failure",
            "do not freeze a model panel until every selected slot has a passed record",
            "do not launch the development pilot from this plan automatically",
        ],
        "jobs": jobs,
    }


def validate_preflight_records(
    inventory: Mapping[str, Any],
    preflight_records: Sequence[Mapping[str, Any]],
    *,
    require_interface_checks: bool = True,
) -> List[str]:
    """Validate the evidence required before a model panel can be frozen."""

    known_ids = {
        str(candidate.get("model_id"))
        for candidate in inventory.get("candidates", [])
        if isinstance(candidate, Mapping) and candidate.get("model_id")
    }
    errors: List[str] = []
    seen: set[tuple[str, str | None, int | None]] = set()
    required_checks = ("endpoint_health", "context_length", "structured_output", "tool_contract")
    for index, record in enumerate(preflight_records):
        if not isinstance(record, Mapping):
            errors.append("records[%d] must be an object" % index)
            continue
        model_id = record.get("model_id")
        if not isinstance(model_id, str) or not model_id:
            errors.append("records[%d].model_id is missing" % index)
            continue
        if model_id not in known_ids:
            errors.append("records[%d] references unknown model_id: %s" % (index, model_id))
        key = (model_id, record.get("instance_id"), record.get("repetition"))
        if key in seen:
            errors.append("duplicate preflight record: %s" % (key,))
        seen.add(key)
        if record.get("status") not in {"passed", "failed", "excluded"}:
            errors.append("records[%d].status is invalid" % index)
        if record.get("status") == "passed":
            if require_interface_checks:
                for check in required_checks:
                    if record.get(check) != "passed":
                        errors.append("%s:%s" % (model_id, check))
            if not isinstance(record.get("standard_success_rate"), (int, float)):
                errors.append("%s:standard_success_rate_missing" % model_id)
        elif record.get("status") == "excluded":
            reason = record.get("exclusion_reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append("%s:exclusion_reason_missing" % model_id)
    return errors


def validate_preflight_plan_coverage(
    plan: Mapping[str, Any],
    preflight_records: Sequence[Mapping[str, Any]],
) -> List[str]:
    """Require one raw record for every planned model/instance probe.

    Panel selection may aggregate records across instances, but it must never
    silently accept a partial preflight file. Failed and excluded probes still
    count as covered jobs and remain visible to the caller.
    """

    jobs = plan.get("jobs") if isinstance(plan, Mapping) else None
    if not isinstance(jobs, list) or not jobs:
        return ["preflight_plan_jobs_missing"]
    expected: set[tuple[str, str, int]] = set()
    errors: List[str] = []
    for index, job in enumerate(jobs):
        if not isinstance(job, Mapping):
            errors.append("preflight_plan.jobs[%d] must be an object" % index)
            continue
        model_id = job.get("model_id")
        instance_id = job.get("instance_id")
        repetition = job.get("repetition")
        if (
            not isinstance(model_id, str)
            or not model_id
            or not isinstance(instance_id, str)
            or not instance_id
            or not isinstance(repetition, int)
            or isinstance(repetition, bool)
            or repetition < 1
        ):
            errors.append("preflight_plan.jobs[%d] has an invalid identity" % index)
            continue
        key = (model_id, instance_id, repetition)
        if key in expected:
            errors.append("duplicate preflight plan job: %s" % (key,))
        expected.add(key)

    observed: set[tuple[str, str, int]] = set()
    for index, record in enumerate(preflight_records):
        if not isinstance(record, Mapping):
            errors.append("preflight_records[%d] must be an object" % index)
            continue
        model_id = record.get("model_id")
        instance_id = record.get("instance_id")
        repetition = record.get("repetition")
        if (
            not isinstance(model_id, str)
            or not model_id
            or not isinstance(instance_id, str)
            or not instance_id
            or not isinstance(repetition, int)
            or isinstance(repetition, bool)
            or repetition < 1
        ):
            errors.append("preflight_records[%d] has an invalid identity" % index)
            continue
        key = (model_id, instance_id, repetition)
        if key in observed:
            errors.append("duplicate preflight record identity: %s" % (key,))
        observed.add(key)

    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    if missing:
        errors.append("missing preflight records: " + ", ".join(map(str, missing)))
    if unexpected:
        errors.append("unexpected preflight records: " + ", ".join(map(str, unexpected)))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory model configs without endpoint calls")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--development-instance", action="append", default=[])
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--probe-repetitions", type=int, default=1)
    parser.add_argument(
        "--model-id",
        action="append",
        default=[],
        help="restrict inventory/plan to an explicit model_id; repeat for a panel",
    )
    parser.add_argument("--model-card-registry", type=Path)
    args = parser.parse_args()
    inventory = inventory_model_configs(
        args.model_dir,
        model_card_registry_path=args.model_card_registry,
    )
    if args.model_id:
        inventory = restrict_model_inventory(inventory, args.model_id)
    rendered = json.dumps(inventory, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    if args.development_instance:
        plan = build_preflight_plan(
            inventory,
            args.development_instance,
            repetitions=args.probe_repetitions,
        )
        plan_rendered = json.dumps(plan, indent=2, ensure_ascii=False)
        if args.plan_output:
            args.plan_output.write_text(plan_rendered, encoding="utf-8")
        print(plan_rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
