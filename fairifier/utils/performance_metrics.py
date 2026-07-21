"""Deterministic workflow time, token, and cost telemetry aggregation."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _integer(value: Any) -> int | None:
    parsed = _number(value)
    if parsed is None or parsed < 0:
        return None
    return int(parsed)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_seconds(start: Any, end: Any) -> float | None:
    start_dt = _timestamp(start)
    end_dt = _timestamp(end)
    if start_dt is None or end_dt is None:
        return None
    try:
        return round(max(0.0, (end_dt - start_dt).total_seconds()), 6)
    except TypeError:
        return None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[rank], 6)


def _phase_for_label(label: Any) -> str:
    value = str(label or "").strip().lower().replace(" ", "_")
    if "plan" in value:
        return "planning"
    if any(token in value for token in ("document", "parse", "extract_document")):
        return "document_parsing"
    if any(
        token in value
        for token in (
            "knowledge",
            "package",
            "retrieve",
            "field_selection",
            "select_relevant",
        )
    ):
        return "knowledge_retrieval"
    if any(token in value for token in ("critic", "evaluate", "quality", "judge")):
        return "quality_evaluation"
    if any(
        token in value
        for token in ("metadata", "json", "isa", "auto_repair", "generation")
    ):
        return "metadata_generation"
    return "other"


def _usage_candidates(record: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    usage_metadata = record.get("usage_metadata")
    if isinstance(usage_metadata, Mapping):
        yield usage_metadata

    response_metadata = record.get("response_metadata")
    if not isinstance(response_metadata, Mapping):
        return
    for key in ("token_usage", "usage", "usage_metadata"):
        nested = response_metadata.get(key)
        if isinstance(nested, Mapping):
            yield nested
    yield response_metadata


def extract_token_usage(record: Mapping[str, Any]) -> dict[str, int] | None:
    """Normalize OpenAI, Anthropic, Gemini, and Ollama token metadata."""
    for usage in _usage_candidates(record):
        input_tokens = next(
            (
                value
                for value in (
                    _integer(usage.get("input_tokens")),
                    _integer(usage.get("prompt_tokens")),
                    _integer(usage.get("prompt_token_count")),
                )
                if value is not None
            ),
            None,
        )
        output_tokens = next(
            (
                value
                for value in (
                    _integer(usage.get("output_tokens")),
                    _integer(usage.get("completion_tokens")),
                    _integer(usage.get("completion_token_count")),
                    _integer(usage.get("candidates_token_count")),
                )
                if value is not None
            ),
            None,
        )
        total_tokens = next(
            (
                value
                for value in (
                    _integer(usage.get("total_tokens")),
                    _integer(usage.get("total_token_count")),
                )
                if value is not None
            ),
            None,
        )
        if input_tokens is None and output_tokens is None and total_tokens is None:
            continue
        input_tokens = input_tokens or 0
        output_tokens = output_tokens or 0
        total_tokens = total_tokens if total_tokens is not None else input_tokens + output_tokens
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }
    return None


def _gate_check(
    *,
    name: str,
    value: float | int | None,
    limit: float | int,
    unit: str,
    complete: bool = True,
) -> dict[str, Any]:
    if limit <= 0:
        status = "not_configured"
    elif value is None or not complete:
        status = "insufficient_data"
    else:
        status = "pass" if value <= limit else "fail"
    return {
        "name": name,
        "status": status,
        "value": value,
        "limit": limit,
        "unit": unit,
    }


def build_performance_metrics(
    state: Mapping[str, Any],
    llm_responses: Sequence[Mapping[str, Any]] | None,
    settings: Any,
) -> dict[str, Any]:
    """Build report-only telemetry and gates without changing workflow status."""
    responses = list(llm_responses or [])
    execution_history = list(state.get("execution_history") or [])
    workflow_seconds = _duration_seconds(
        state.get("processing_start"),
        state.get("processing_end"),
    )

    phase_durations: dict[str, list[float]] = defaultdict(list)
    for record in execution_history:
        if not isinstance(record, Mapping):
            continue
        duration = _duration_seconds(record.get("start_time"), record.get("end_time"))
        if duration is not None:
            phase_durations[_phase_for_label(record.get("agent_name"))].append(duration)

    phase_usage: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "llm_calls": 0,
            "calls_with_token_usage": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "llm_latencies": [],
        }
    )
    calls_with_usage = 0
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    all_llm_latencies: list[float] = []

    for response in responses:
        if not isinstance(response, Mapping):
            continue
        phase = _phase_for_label(response.get("operation"))
        phase_record = phase_usage[phase]
        phase_record["llm_calls"] += 1
        usage = extract_token_usage(response)
        if usage is not None:
            calls_with_usage += 1
            phase_record["calls_with_token_usage"] += 1
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                phase_record[key] += usage[key]
            input_tokens += usage["input_tokens"]
            output_tokens += usage["output_tokens"]
            total_tokens += usage["total_tokens"]
        latency = _number(response.get("latency_seconds"))
        if latency is not None and latency >= 0:
            phase_record["llm_latencies"].append(latency)
            all_llm_latencies.append(latency)

    input_rate = float(settings.telemetry_llm_input_cost_per_million_usd)
    output_rate = float(settings.telemetry_llm_output_cost_per_million_usd)
    compute_rate = float(settings.telemetry_compute_cost_per_hour_usd)
    token_pricing_configured = input_rate >= 0 and output_rate >= 0
    usage_complete = len(responses) == calls_with_usage
    estimated_llm_cost = None
    if token_pricing_configured and usage_complete:
        estimated_llm_cost = round(
            (input_tokens / 1_000_000 * input_rate)
            + (output_tokens / 1_000_000 * output_rate),
            6,
        )
    estimated_compute_cost = None
    if compute_rate >= 0 and workflow_seconds is not None:
        estimated_compute_cost = round(workflow_seconds / 3600 * compute_rate, 6)
    known_cost_components = [
        value
        for value in (estimated_llm_cost, estimated_compute_cost)
        if value is not None
    ]
    estimated_total_cost = (
        round(sum(known_cost_components), 6) if known_cost_components else None
    )

    phases: dict[str, Any] = {}
    phase_names = sorted(set(phase_durations) | set(phase_usage))
    for phase in phase_names:
        durations = phase_durations.get(phase, [])
        usage = phase_usage.get(phase) or {
            "llm_calls": 0,
            "calls_with_token_usage": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "llm_latencies": [],
        }
        usage = dict(usage)
        latencies = usage.pop("llm_latencies")
        phase_usage_complete = usage["llm_calls"] == usage["calls_with_token_usage"]
        phase_cost = None
        if token_pricing_configured and phase_usage_complete:
            phase_cost = round(
                (usage["input_tokens"] / 1_000_000 * input_rate)
                + (usage["output_tokens"] / 1_000_000 * output_rate),
                6,
            )
        phases[phase] = {
            "attempt_count": len(durations),
            "agent_duration_seconds": round(sum(durations), 6),
            "agent_duration_max_seconds": round(max(durations), 6) if durations else None,
            **usage,
            "llm_latency_seconds": round(sum(latencies), 6),
            "llm_latency_mean_seconds": (
                round(sum(latencies) / len(latencies), 6) if latencies else None
            ),
            "llm_latency_p95_seconds": _percentile(latencies, 0.95),
            "estimated_llm_cost": phase_cost,
            "cost_estimate_status": (
                "complete"
                if token_pricing_configured and phase_usage_complete
                else "insufficient_data"
            ),
        }

    max_phase_seconds = max(
        (item["agent_duration_seconds"] for item in phases.values()),
        default=None,
    )
    max_phase_tokens = max(
        (item["total_tokens"] for item in phases.values()),
        default=0,
    )
    phase_usage_complete = all(
        item["llm_calls"] == item["calls_with_token_usage"]
        for item in phases.values()
    )
    phase_costs = [
        item["estimated_llm_cost"]
        for item in phases.values()
        if item["estimated_llm_cost"] is not None
    ]
    max_phase_cost = max(phase_costs, default=None)
    per_phase_checks: dict[str, list[dict[str, Any]]] = {}
    for phase, item in phases.items():
        per_phase_checks[phase] = [
            _gate_check(
                name="latency",
                value=item["agent_duration_seconds"],
                limit=float(settings.performance_gate_max_phase_seconds),
                unit="seconds",
            ),
            _gate_check(
                name="tokens",
                value=item["total_tokens"],
                limit=int(settings.performance_gate_max_phase_tokens),
                unit="tokens",
                complete=(
                    item["llm_calls"] == item["calls_with_token_usage"]
                ),
            ),
            _gate_check(
                name="estimated_cost",
                value=item["estimated_llm_cost"],
                limit=float(settings.performance_gate_max_phase_cost_usd),
                unit="USD",
                complete=(
                    token_pricing_configured
                    and item["llm_calls"] == item["calls_with_token_usage"]
                ),
            ),
        ]
    checks = [
        _gate_check(
            name="workflow_latency",
            value=workflow_seconds,
            limit=float(settings.performance_gate_max_total_seconds),
            unit="seconds",
        ),
        _gate_check(
            name="phase_latency",
            value=max_phase_seconds,
            limit=float(settings.performance_gate_max_phase_seconds),
            unit="seconds",
        ),
        _gate_check(
            name="total_tokens",
            value=total_tokens if responses else 0,
            limit=int(settings.performance_gate_max_total_tokens),
            unit="tokens",
            complete=usage_complete,
        ),
        _gate_check(
            name="phase_tokens",
            value=max_phase_tokens,
            limit=int(settings.performance_gate_max_phase_tokens),
            unit="tokens",
            complete=phase_usage_complete,
        ),
        _gate_check(
            name="estimated_cost",
            value=estimated_total_cost,
            limit=float(settings.performance_gate_max_estimated_cost_usd),
            unit="USD",
            complete=token_pricing_configured and usage_complete,
        ),
        _gate_check(
            name="phase_estimated_cost",
            value=max_phase_cost,
            limit=float(settings.performance_gate_max_phase_cost_usd),
            unit="USD",
            complete=token_pricing_configured and phase_usage_complete,
        ),
    ]
    statuses = {check["status"] for check in checks}
    statuses.update(
        check["status"]
        for phase_checks in per_phase_checks.values()
        for check in phase_checks
    )
    if "fail" in statuses:
        overall_status = "fail"
    elif "insufficient_data" in statuses:
        overall_status = "insufficient_data"
    elif statuses == {"not_configured"}:
        overall_status = "not_configured"
    else:
        overall_status = "pass"

    return {
        "workflow": {
            "wall_time_seconds": workflow_seconds,
            "recorded_agent_time_seconds": round(
                sum(sum(values) for values in phase_durations.values()),
                6,
            ),
            "execution_records": len(execution_history),
        },
        "phases": phases,
        "llm_usage": {
            "calls": len(responses),
            "calls_with_token_usage": calls_with_usage,
            "usage_coverage_ratio": (
                round(calls_with_usage / len(responses), 4) if responses else 1.0
            ),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "latency_seconds": round(sum(all_llm_latencies), 6),
            "latency_mean_seconds": (
                round(sum(all_llm_latencies) / len(all_llm_latencies), 6)
                if all_llm_latencies
                else None
            ),
            "latency_p95_seconds": _percentile(all_llm_latencies, 0.95),
        },
        "cost": {
            "currency": "USD",
            "input_cost_per_million_tokens": input_rate if input_rate >= 0 else None,
            "output_cost_per_million_tokens": output_rate if output_rate >= 0 else None,
            "compute_cost_per_hour": compute_rate if compute_rate >= 0 else None,
            "estimated_llm_cost": estimated_llm_cost,
            "estimated_compute_cost": estimated_compute_cost,
            "estimated_total_cost": estimated_total_cost,
            "estimate_status": (
                "complete"
                if token_pricing_configured and usage_complete
                else "insufficient_data"
            ),
        },
        "gates": {
            "overall_status": overall_status,
            "report_only": True,
            "checks": checks,
            "per_phase": per_phase_checks,
            "violations": [
                check["name"] for check in checks if check["status"] == "fail"
            ],
            "phase_violations": [
                f"{phase}.{check['name']}"
                for phase, phase_checks in per_phase_checks.items()
                for check in phase_checks
                if check["status"] == "fail"
            ],
        },
        "notes": [
            "Agent durations may overlap and are not added to workflow wall time.",
            "Token/cost coverage includes direct and deep-agent calls captured by LLMHelper; provider calls without usage metadata remain visible as incomplete coverage.",
            "Performance gates are report-only and do not stop the workflow.",
        ],
    }
