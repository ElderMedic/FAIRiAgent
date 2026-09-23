"""Approval-gated interface preflight runner.

The planner in :mod:`model_preflight` is deliberately token-free.  This module
is the separate execution boundary: it only performs model calls when
``--execute --approval-id`` is supplied.  Each probe asks the selected model to
call one JSON-schema tool, so the same response exercises tool serialization
and structured arguments without running the FAIRiAgent workflow.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

TOOL_NAME = "benchmark_preflight_echo"
TOOL_ARGUMENTS = {"value": "ok"}
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "Return the supplied probe value unchanged.",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    },
}


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_env(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values


def _endpoint_model_present(
    base_url: str,
    model_name: str,
) -> tuple[bool, str, Dict[str, Any] | None]:
    """Check an Ollama tag list without generating tokens."""

    url = base_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - configured local URL
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return False, "ollama_unreachable:%s" % type(exc).__name__, None
    models = payload.get("models", []) if isinstance(payload, Mapping) else []
    for item in models:
        if isinstance(item, Mapping) and str(item.get("name")) == model_name:
            # Preserve only the endpoint's model metadata; no prompt or
            # generation request is made by this check.
            return True, "ollama_tags_passed", dict(item)
    return False, "model_not_present:%s" % model_name, None


def _context_check(candidate: Mapping[str, Any]) -> tuple[bool, str]:
    card = candidate.get("model_card")
    context = card.get("context_length") if isinstance(card, Mapping) else None
    if not isinstance(context, int) or context < 8192:
        return False, "context_length_missing_or_too_small"
    return True, "context_length=%d" % context


def _extract_tool_args(result: Any) -> tuple[bool, Dict[str, Any] | None, str]:
    calls = getattr(result, "tool_calls", None)
    if not isinstance(calls, list):
        additional = getattr(result, "additional_kwargs", None)
        calls = additional.get("tool_calls") if isinstance(additional, Mapping) else None
    if not isinstance(calls, list) or not calls:
        return False, None, "tool_call_missing"
    for call in calls:
        if not isinstance(call, Mapping):
            continue
        name = call.get("name")
        if not name and isinstance(call.get("function"), Mapping):
            name = call["function"].get("name")
        if name != TOOL_NAME:
            continue
        args = call.get("args")
        if args is None and isinstance(call.get("function"), Mapping):
            args = call["function"].get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return False, None, "tool_arguments_not_json"
        if not isinstance(args, Mapping):
            return False, None, "tool_arguments_not_object"
        normalized = dict(args)
        if normalized == TOOL_ARGUMENTS:
            return True, normalized, "tool_and_structured_arguments_passed"
        return False, normalized, "tool_arguments_schema_mismatch"
    return False, None, "expected_tool_not_called"


async def _invoke_probe(candidate: Mapping[str, Any], prompt: str) -> Dict[str, Any]:
    """Invoke one model after the parent has explicitly authorized execution."""

    # Import only after the execution boundary is crossed; importing this
    # module alone never initializes an LLM.
    from langchain_core.messages import HumanMessage
    from fairifier.config import config
    from fairifier.utils.llm_helper import LLMHelper

    helper = LLMHelper()
    llm = helper.get_llm()
    provider = str(candidate.get("provider") or config.llm_provider)
    # LangChain exposes `any` for Ollama and `required` for OpenAI-compatible
    # providers.  Force the dummy call so a plain natural-language response
    # cannot be mistaken for a passed tool contract.
    tool_choice = "any" if provider == "ollama" else "required"
    llm_with_tools = llm.bind_tools([TOOL_SCHEMA], tool_choice=tool_choice)
    if provider == "ollama":
        llm_with_tools = llm_with_tools.bind(think=False)
    elif provider == "deepseek":
        llm_with_tools = llm_with_tools.bind(extra_body={"thinking": {"type": "disabled"}})
    elif provider == "qwen":
        llm_with_tools = llm_with_tools.bind(extra_body={"enable_thinking": False})
    result = await llm_with_tools.ainvoke([HumanMessage(content=prompt)])
    tool_ok, args, detail = _extract_tool_args(result)
    return {
        "tool_ok": tool_ok,
        "structured_output_ok": tool_ok,
        "tool_arguments": args,
        "detail": detail,
    }


def _run_single_job(job_path: Path, record_path: Path) -> int:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    candidate = job["candidate"]
    context_ok, context_detail = _context_check(candidate)
    endpoint_ok = True
    endpoint_detail = "hosted_call_pending"
    endpoint_model_metadata: Dict[str, Any] | None = None
    provider = str(candidate.get("provider"))
    if provider == "ollama":
        base_url = str(candidate.get("endpoint") or os.getenv("FAIRIFIER_LLM_BASE_URL") or "")
        endpoint_ok, endpoint_detail, endpoint_model_metadata = _endpoint_model_present(
            base_url,
            str(candidate.get("model_name")),
        )
    record: Dict[str, Any] = {
        "model_id": job["model_id"],
        "instance_id": job["instance_id"],
        "repetition": job["repetition"],
        "status": "failed",
        "endpoint_health": "passed" if endpoint_ok else "failed",
        "context_length": "passed" if context_ok else "failed",
        "structured_output": "failed",
        "tool_contract": "failed",
        "structured_output_mode": "tool_arguments_json_schema",
        "endpoint_detail": endpoint_detail,
        "endpoint_model_metadata": endpoint_model_metadata,
        "context_detail": context_detail,
        "model_or_api_calls_performed": False,
    }
    if not endpoint_ok or not context_ok:
        record["exclusion_reason"] = endpoint_detail if not endpoint_ok else context_detail
        record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return 0
    prompt = (
        "This is an interface preflight. Do not explain. Call the tool "
        f"{TOOL_NAME} exactly once with the JSON arguments "
        '{"value":"ok"}. Do not invent additional arguments.'
    )
    try:
        result = asyncio.run(_invoke_probe(candidate, prompt))
        record["structured_output"] = "passed" if result["structured_output_ok"] else "failed"
        record["tool_contract"] = "passed" if result["tool_ok"] else "failed"
        record["tool_arguments"] = result.get("tool_arguments")
        record["probe_detail"] = result.get("detail")
        record["model_or_api_calls_performed"] = True
        record["endpoint_health"] = "passed"
        if all(record[key] == "passed" for key in ("endpoint_health", "context_length", "structured_output", "tool_contract")):
            record["status"] = "passed"
            record["standard_success_rate"] = 1.0
        else:
            record["standard_success_rate"] = 0.0
            record["exclusion_reason"] = result.get("detail") or "interface_contract_failed"
    except Exception as exc:  # noqa: BLE001 - preserve one failed job, continue batch
        record["model_or_api_calls_performed"] = True
        record["endpoint_health"] = "failed"
        record["exclusion_reason"] = "probe_exception:%s" % type(exc).__name__
        record["error_type"] = type(exc).__name__
    record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


def execute_preflight(
    inventory: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    model_config_dir: Path,
    approval_id: str,
    timeout_seconds: int = 180,
) -> Dict[str, Any]:
    """Execute the explicit plan in isolated child processes."""

    if not approval_id.strip():
        raise ValueError("approval_id is required")
    candidates = {
        str(candidate.get("model_id")): candidate
        for candidate in inventory.get("candidates", [])
        if isinstance(candidate, Mapping) and candidate.get("model_id")
    }
    records: list[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="fairiagent_preflight_") as temp_dir:
        temp_path = Path(temp_dir)
        for index, job in enumerate(plan.get("jobs", [])):
            model_id = str(job.get("model_id"))
            candidate = candidates.get(model_id)
            if candidate is None:
                records.append({
                    "model_id": model_id,
                    "instance_id": job.get("instance_id"),
                    "repetition": job.get("repetition"),
                    "status": "failed",
                    "exclusion_reason": "model_missing_from_inventory",
                })
                continue
            config_path = Path(str(candidate.get("config_path")))
            if not config_path.is_absolute() and not config_path.is_file():
                config_path = model_config_dir / config_path.name
            if not config_path.is_file():
                records.append({
                    "model_id": model_id,
                    "instance_id": job.get("instance_id"),
                    "repetition": job.get("repetition"),
                    "status": "failed",
                    "exclusion_reason": "model_config_missing",
                })
                continue
            job_payload = dict(job)
            job_payload["candidate"] = dict(candidate)
            job_path = temp_path / ("job_%04d.json" % index)
            record_path = temp_path / ("record_%04d.json" % index)
            job_path.write_text(json.dumps(job_payload, ensure_ascii=False), encoding="utf-8")
            child_env = os.environ.copy()
            child_env.update(_read_env(config_path))
            child_env["FAIRIFIER_PREFLIGHT_APPROVAL_ID"] = approval_id
            command = [
                sys.executable,
                "-m",
                "evaluation.benchmark.model_preflight_runner",
                "--single-job",
                str(job_path),
                "--single-record",
                str(record_path),
            ]
            try:
                subprocess.run(
                    command,
                    env=child_env,
                    check=False,
                    timeout=timeout_seconds,
                    capture_output=True,
                    text=True,
                )
                if record_path.is_file():
                    records.append(json.loads(record_path.read_text(encoding="utf-8")))
                else:
                    records.append({
                        "model_id": model_id,
                        "instance_id": job.get("instance_id"),
                        "repetition": job.get("repetition"),
                        "status": "failed",
                        "exclusion_reason": "probe_child_no_record",
                    })
            except subprocess.TimeoutExpired:
                records.append({
                    "model_id": model_id,
                    "instance_id": job.get("instance_id"),
                    "repetition": job.get("repetition"),
                    "status": "failed",
                    "exclusion_reason": "probe_timeout",
                })
    return {
        "schema_version": "fairiagent.model_preflight_records.v1",
        "approval_id": approval_id,
        "plan_digest": _digest(plan),
        "inventory_digest": _digest(inventory),
        "endpoint_checks_performed": True,
        "token_calls_performed": True,
        "model_or_api_calls_performed": True,
        "records": records,
    }


def _job_key(value: Mapping[str, Any]) -> tuple[str, str, int]:
    """Return the stable identity used to merge a preflight retry."""

    return (
        str(value.get("model_id")),
        str(value.get("instance_id")),
        int(value.get("repetition", 0)),
    )


def retry_failed_preflight(
    inventory: Mapping[str, Any],
    plan: Mapping[str, Any],
    previous_records: Sequence[Mapping[str, Any]],
    *,
    model_config_dir: Path,
    approval_id: str,
    timeout_seconds: int = 180,
) -> Dict[str, Any]:
    """Retry only failed jobs and merge them without hiding original evidence.

    The original record set remains the denominator.  A retry is an explicit
    interface-stability diagnostic, not a best-of-repetition selection rule.
    """

    failed_keys = {
        _job_key(record)
        for record in previous_records
        if str(record.get("status")) != "passed"
    }
    retry_jobs = [
        dict(job)
        for job in plan.get("jobs", [])
        if _job_key(job) in failed_keys
    ]
    retry_plan = dict(plan)
    retry_plan["jobs"] = retry_jobs
    retry_result = execute_preflight(
        inventory,
        retry_plan,
        model_config_dir=model_config_dir,
        approval_id=approval_id,
        timeout_seconds=timeout_seconds,
    )
    retry_by_key = {
        _job_key(record): dict(record)
        for record in retry_result.get("records", [])
    }
    merged: list[Dict[str, Any]] = []
    for record in previous_records:
        merged.append(retry_by_key.get(_job_key(record), dict(record)))
    result = dict(retry_result)
    result["plan_digest"] = _digest(plan)
    result["retry_plan_digest"] = _digest(retry_plan)
    result["previous_records_digest"] = _digest(list(previous_records))
    result["retry_job_count"] = len(retry_jobs)
    result["records"] = merged
    result["retry_mode"] = "failed_jobs_only_preserve_original_denominator"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run approval-gated model interface preflight")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--preflight-plan", type=Path)
    parser.add_argument("--model-config-dir", type=Path, default=Path("evaluation/config/model_configs"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approval-id")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--single-job", type=Path)
    parser.add_argument("--single-record", type=Path)
    parser.add_argument(
        "--retry-failed-records",
        type=Path,
        help="Retry only non-passed jobs from a prior record artifact and merge the records",
    )
    args = parser.parse_args()

    if args.single_job and args.single_record:
        return _run_single_job(args.single_job, args.single_record)
    if not args.inventory or not args.preflight_plan:
        parser.error("--inventory and --preflight-plan are required unless --single-job is used")
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    plan = json.loads(args.preflight_plan.read_text(encoding="utf-8"))
    if not args.execute:
        result = {
            "schema_version": "fairiagent.model_preflight_execution_plan.v1",
            "status": "dry_run",
            "model_or_api_calls_performed": False,
            "planned_jobs": len(plan.get("jobs", [])),
            "approval_required": True,
            "required_flag": "--execute --approval-id <researcher-decision-id>",
        }
    else:
        if not args.approval_id:
            parser.error("--approval-id is required with --execute")
        if args.retry_failed_records:
            previous = json.loads(args.retry_failed_records.read_text(encoding="utf-8"))
            previous_records = previous.get("records") if isinstance(previous, Mapping) else None
            if not isinstance(previous_records, list):
                parser.error("--retry-failed-records must contain a records list")
            result = retry_failed_preflight(
                inventory,
                plan,
                previous_records,
                model_config_dir=args.model_config_dir,
                approval_id=args.approval_id,
                timeout_seconds=args.timeout_seconds,
            )
        else:
            result = execute_preflight(
                inventory,
                plan,
                model_config_dir=args.model_config_dir,
                approval_id=args.approval_id,
                timeout_seconds=args.timeout_seconds,
            )
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
