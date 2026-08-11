"""Token-free campaign planner for FAIRiAgent conditions.

The publication baseline runner covers the three non-agentic controls.  This
module describes the remaining agentic and retrieval-ablation cells using the
same v2 manifest, without importing the workflow or contacting a model.  An
execution adapter can consume the plan only after a reviewed budget and an
explicit approval identifier are supplied.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from .assets import collect_asset_checksums, resolve_manifest_path
from .contracts import load_manifest
from .run_index import create_run_index, record_result
from fairifier.output_paths import resolve_metadata_output_read_path


logger = logging.getLogger(__name__)

NON_AGENTIC_CONDITIONS = {
    "single_pass_structured_extraction",
    "standards_guided_extraction",
    "retrieval_assisted_extraction",
}

# Local Ollama panel ids share a host by default; use --allow-local-parallel
# with --local-endpoint-pool for true multi-GPU pinning.
_LOCAL_MODEL_ID_PREFIXES = ("ollama_",)


def _parse_assignments(values: Sequence[str], *, label: str) -> Dict[str, Path]:
    parsed: Dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("%s must use identifier=path: %s" % (label, value))
        identifier, raw_path = value.split("=", 1)
        if not identifier or not raw_path:
            raise ValueError("%s must use identifier=path: %s" % (label, value))
        if identifier in parsed:
            raise ValueError("duplicate %s identifier: %s" % (label, identifier))
        parsed[identifier] = Path(raw_path)
    return parsed


def _resolve(value: str, manifest_path: Path, project_root: Path) -> Path:
    return resolve_manifest_path(value, manifest_path, project_root)


def _scope_manifest(
    manifest: Mapping[str, Any],
    selected_conditions: Sequence[str],
    selected_runs: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    selected = set(selected_conditions)
    scoped = dict(manifest)
    scoped["conditions"] = [
        dict(condition)
        for condition in manifest.get("conditions", [])
        if condition.get("condition_id") in selected
    ]
    scoped["scheduled_runs"] = [dict(run) for run in selected_runs]
    provenance = dict(manifest.get("provenance") or {})
    provenance["condition_scope"] = list(selected_conditions)
    scoped["provenance"] = provenance
    return scoped


def _absolutize_scope_paths(
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path,
    project_root: Path,
) -> Dict[str, Any]:
    """Make a campaign scope portable when it is written beside the run index."""

    scoped = dict(manifest)
    instances = []
    path_keys = (
        "source_path",
        "ground_truth_path",
        "ground_truth_values_path",
        "package_path",
        "standards_context_path",
        "retrieved_context_path",
    )
    for original in manifest.get("instances", []):
        instance = dict(original)
        for key in path_keys:
            value = instance.get(key)
            if isinstance(value, str) and value:
                instance[key] = str(_resolve(value, manifest_path, project_root))
        supplementary = instance.get("supplementary_paths")
        if isinstance(supplementary, list):
            instance["supplementary_paths"] = [
                str(_resolve(str(value), manifest_path, project_root)) for value in supplementary
            ]
        instances.append(instance)
    scoped["instances"] = instances
    return scoped


def build_agentic_campaign_plan(
    manifest: Mapping[str, Any],
    manifest_path: Path,
    *,
    project_root: Path,
    output_dir: Path,
    model_configs: Mapping[str, Path],
    base_env: Path | None = None,
    condition_envs: Mapping[str, Path] | None = None,
    selected_conditions: Sequence[str] | None = None,
    timeout_seconds: int = 3600,
) -> Dict[str, Any]:
    """Build an explicit agentic campaign plan without execution."""

    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    condition_map = {
        str(condition.get("condition_id")): condition
        for condition in manifest.get("conditions", [])
        if isinstance(condition, Mapping) and condition.get("condition_id")
    }
    requested = list(selected_conditions) if selected_conditions else [
        condition_id
        for condition_id in condition_map
        if condition_id not in NON_AGENTIC_CONDITIONS
    ]
    unknown = sorted(set(requested) - set(condition_map))
    if unknown:
        raise ValueError("unknown campaign condition(s): " + ", ".join(unknown))
    selected_runs = [
        run
        for run in manifest.get("scheduled_runs", [])
        if run.get("condition_id") in set(requested)
    ]
    instances = {item["instance_id"]: item for item in manifest.get("instances", [])}
    errors: list[str] = []
    jobs: list[Dict[str, Any]] = []
    resolved_condition_envs = dict(condition_envs or {})
    for condition_id, env_path in resolved_condition_envs.items():
        if condition_id not in requested:
            errors.append("condition environment supplied for unselected condition: %s" % condition_id)
        elif not env_path.is_file():
            errors.append("condition environment does not exist: %s" % env_path)
    if base_env is not None and not base_env.is_file():
        errors.append("base environment does not exist: %s" % base_env)

    for run in selected_runs:
        instance = instances.get(run.get("instance_id"))
        if not isinstance(instance, Mapping):
            errors.append("scheduled run references unknown instance: %s" % run.get("run_id"))
            continue
        model_id = str(run["model_id"])
        config_path = model_configs.get(model_id)
        if config_path is None:
            errors.append("missing model config assignment for: %s" % model_id)
            continue
        if not config_path.is_file():
            errors.append("model config does not exist: %s" % config_path)
            continue
        condition_id = str(run["condition_id"])
        declared_condition_env = resolved_condition_envs.get(condition_id)
        condition_env = declared_condition_env or base_env
        if condition_env is None:
            errors.append("no base or condition environment for: %s" % condition_id)
            continue
        if not condition_env.is_file():
            # Already reported above for condition-specific paths; keep this
            # branch for a missing base fallback.
            errors.append("environment does not exist: %s" % condition_env)
            continue
        source_path = _resolve(str(instance["source_path"]), manifest_path, project_root)
        supplementary_paths = [
            _resolve(str(value), manifest_path, project_root)
            for value in (instance.get("supplementary_paths") or [])
        ]
        for path in [source_path, *supplementary_paths]:
            if not path.is_file():
                errors.append("source asset does not exist for %s: %s" % (run["run_id"], path))
        run_dir = output_dir / condition_id / model_id / str(run["instance_id"]) / (
            "run_%02d" % int(run["repetition"])
        )
        jobs.append(
            {
                **{key: run[key] for key in ("run_id", "instance_id", "condition_id", "model_id", "repetition")},
                "source_path": str(source_path),
                "supplementary_paths": [str(path) for path in supplementary_paths],
                "model_config_path": str(config_path),
                "base_environment_path": str(base_env) if base_env else None,
                "condition_environment_path": (
                    str(declared_condition_env) if declared_condition_env else None
                ),
                "expected_output_dir": str(run_dir),
                "timeout_seconds": timeout_seconds,
                "execution_adapter": "fairifier.cli.process_with_merged_environment",
                "approval_required": True,
            }
        )

    scoped_manifest = _absolutize_scope_paths(
        _scope_manifest(manifest, requested, selected_runs),
        manifest_path=manifest_path,
        project_root=project_root,
    )
    return {
        "schema_version": "fairiagent.agentic_campaign_plan.v1",
        "status": "ready" if not errors else "blocked",
        "errors": errors,
        "benchmark_release": manifest.get("benchmark_release"),
        "condition_scope": requested,
        "scheduled_count": len(selected_runs),
        "planned_job_count": len(jobs),
        "model_or_api_calls_performed": False,
        "approval_required_before_execution": True,
        "execution_contract": {
            "entrypoint": "fairifier.cli process",
            "environment_sources": "base/condition environment plus model config",
            "canonical_output": "metadata.json plus result envelope v2 after deterministic attachment",
            "missing_or_failed_runs_remain_in_denominator": True,
        },
        "scoped_manifest": scoped_manifest,
        "jobs": jobs,
    }


def _read_env_file(path: Path) -> Dict[str, str]:
    """Read simple KEY=VALUE settings without logging secret values."""

    values: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip()
    return values


def _write_merged_environment(
    paths: Sequence[Path],
    *,
    directory: Path,
    overrides: Mapping[str, str] | None = None,
) -> Path:
    """Create a short-lived merged environment file for one subprocess."""

    values: Dict[str, str] = {}
    for path in paths:
        values.update(_read_env_file(path))
    if overrides:
        values.update({key: str(value) for key, value in overrides.items() if key})
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=".fairiagent_merged_",
        suffix=".env",
        dir=directory,
        delete=False,
    )
    try:
        for key, value in values.items():
            handle.write("%s=%s\n" % (key, value))
    finally:
        handle.close()
    return Path(handle.name)


def _parse_endpoint_pool(raw: str | None) -> list[str]:
    """Parse a comma-separated Ollama base-URL pool (empty when unset)."""

    if not raw or not str(raw).strip():
        return []
    endpoints: list[str] = []
    for part in str(raw).split(","):
        endpoint = part.strip().rstrip("/")
        if endpoint:
            endpoints.append(endpoint)
    return endpoints


def _endpoint_overrides_for_job(
    job: Mapping[str, Any],
    *,
    job_index: int,
    endpoint_pool: Sequence[str],
) -> Dict[str, str]:
    """Pin local Ollama jobs to a round-robin endpoint from the pool."""

    if not endpoint_pool:
        return {}
    model_id = str(job.get("model_id") or "")
    if not model_id.startswith(_LOCAL_MODEL_ID_PREFIXES):
        return {}
    endpoint = endpoint_pool[job_index % len(endpoint_pool)]
    return {
        "FAIRIFIER_LLM_BASE_URL": endpoint,
        "MEM0_OLLAMA_BASE_URL": endpoint,
    }


def _prepare_source_bundle(job: Mapping[str, Any]) -> tuple[Path, Path | None]:
    """Create a temporary source directory when supplementary files exist."""

    source = Path(str(job["source_path"]))
    supplementary = [Path(str(value)) for value in (job.get("supplementary_paths") or [])]
    if not supplementary:
        return source, None
    bundle_dir = Path(tempfile.mkdtemp(prefix="fairiagent_source_bundle_"))
    paths = [source, *supplementary]
    for index, path in enumerate(paths):
        target_name = "%03d_%s" % (index, path.name)
        target = bundle_dir / target_name
        try:
            target.symlink_to(path.resolve())
        except OSError:
            shutil.copy2(path, target)
    return bundle_dir, bundle_dir


def _agentic_result_envelope(
    job: Mapping[str, Any],
    *,
    status: str,
    run_dir: Path,
    latency_seconds: float,
    error: str | None = None,
) -> Dict[str, Any]:
    metadata_path = resolve_metadata_output_read_path(run_dir)
    parseable = False
    if metadata_path is not None:
        try:
            json.loads(metadata_path.read_text(encoding="utf-8"))
            parseable = True
        except (OSError, json.JSONDecodeError):
            parseable = False
    return {
        "schema_version": "fairiagent.result_envelope.v2",
        "run_id": job["run_id"],
        "instance_id": job["instance_id"],
        "condition_id": job["condition_id"],
        "model_id": job["model_id"],
        "repetition": job["repetition"],
        "status": status,
        "artifact": {
            "exists": metadata_path is not None,
            "parseable": parseable,
            "path": str(metadata_path or run_dir),
        },
        "validation": {
            "fairds_valid": False,
            "isa_round_trip_valid": False,
            "critical_errors": 0,
            "warnings": 0,
            "validation_status": "not_run",
        },
        "axes": {
            "information_coverage": 0.0,
            "value_accuracy": 0.0,
            "structural_fidelity": 0.0,
            "interoperability": 0.0,
        },
        "resources": {"latency_seconds": round(latency_seconds, 6)},
        "failure": {"category": error} if error else {},
        "provenance": {
            "runner": "evaluation.benchmark.agentic_campaign",
            "model_config_path": job["model_config_path"],
            "base_environment_path": job.get("base_environment_path"),
            "condition_environment_path": job["condition_environment_path"],
            "supplementary_paths": job.get("supplementary_paths") or [],
        },
    }


def _is_local_model_job(job: Mapping[str, Any]) -> bool:
    """Return True when the job targets a host-local model (Ollama panel)."""
    model_id = str(job.get("model_id") or "").strip().lower()
    if any(model_id.startswith(prefix) for prefix in _LOCAL_MODEL_ID_PREFIXES):
        return True
    config_path = job.get("model_config_path")
    if not config_path:
        return False
    try:
        text = Path(str(config_path)).read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        if line.startswith("LLM_PROVIDER="):
            return line.split("=", 1)[1].strip().lower() == "ollama"
    return False


def _resolve_execution_workers(
    jobs: Sequence[Mapping[str, Any]],
    workers: int,
    *,
    allow_local_parallel: bool = False,
) -> int:
    """Clamp parallelism: API-only partitions may use workers>1.

    Local Ollama jobs stay serial unless ``allow_local_parallel`` is set
    (e.g. multi-GPU hosts explicitly authorized for concurrent local runs).
    """
    if workers < 1:
        raise ValueError("workers must be >= 1")
    if workers == 1:
        return 1
    local_ids = sorted(
        {
            str(job.get("model_id"))
            for job in jobs
            if _is_local_model_job(job)
        }
    )
    if local_ids and not allow_local_parallel:
        logger.warning(
            "Requested workers=%s but partition includes local model(s) %s; "
            "forcing workers=1 to protect the shared Ollama host. "
            "Pass --allow-local-parallel to override on multi-GPU hosts.",
            workers,
            ", ".join(local_ids),
        )
        return 1
    if local_ids and allow_local_parallel:
        logger.info(
            "Allowing local-model parallelism: workers=%s models=%s",
            workers,
            ", ".join(local_ids),
        )
    return workers


def _execute_one_agentic_job(
    job: Mapping[str, Any],
    *,
    project_root: Path,
    env_overrides: Mapping[str, str] | None = None,
) -> Dict[str, Any]:
    """Run one CLI subprocess and return a result envelope (never raises)."""
    run_dir = Path(str(job["expected_output_dir"]))
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    merged_env: Path | None = None
    source_bundle: Path | None = None
    status = "failed"
    error: str | None = "unknown"
    try:
        source_argument, source_bundle = _prepare_source_bundle(job)
        environment_sources = [
            Path(str(value))
            for value in (
                job.get("base_environment_path"),
                job.get("condition_environment_path"),
                job.get("model_config_path"),
            )
            if value
        ]
        merged_env = _write_merged_environment(
            environment_sources,
            directory=run_dir,
            overrides=env_overrides,
        )
        command = [
            os.fspath(sys.executable),
            "-m",
            "fairifier.cli",
            "process",
            str(source_argument),
            "--output-dir",
            str(run_dir),
            "--project-id",
            str(job["run_id"]),
            "--env-file",
            str(merged_env),
        ]
        completed = subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=int(job.get("timeout_seconds") or 3600),
            check=False,
        )
        (run_dir / "cli_output.txt").write_text(
            "Command: %s\nReturn code: %s\n\n=== STDOUT ===\n%s\n\n=== STDERR ===\n%s\n"
            % (" ".join(command), completed.returncode, completed.stdout, completed.stderr),
            encoding="utf-8",
        )
        metadata_path = resolve_metadata_output_read_path(run_dir)
        status = "success" if completed.returncode == 0 and metadata_path is not None else "failed"
        error = None if status == "success" else "workflow_return_code:%s" % completed.returncode
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        error = "timeout:%s" % exc
    except Exception as exc:  # noqa: BLE001 - preserve the failed cell
        status = "infrastructure_error"
        error = "%s: %s" % (type(exc).__name__, exc)
    finally:
        if merged_env is not None:
            try:
                merged_env.unlink()
            except OSError:
                pass
        if source_bundle is not None:
            shutil.rmtree(source_bundle, ignore_errors=True)
    return _agentic_result_envelope(
        job,
        status=status,
        run_dir=run_dir,
        latency_seconds=time.perf_counter() - started,
        error=error,
    )


def execute_agentic_campaign(
    plan: Mapping[str, Any],
    *,
    manifest_path: Path,
    project_root: Path,
    output_dir: Path,
    approval_id: str,
    workers: int = 1,
    allow_local_parallel: bool = False,
    local_endpoint_pool: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """Execute a prepared plan after an explicit researcher approval.

    This is the only function in this module that starts a workflow. It writes
    the scoped manifest and run index before the first subprocess, preserves
    every failure, and never attaches/scorers metrics optimistically.

    ``workers`` > 1 runs jobs concurrently (separate subprocesses). Local
    Ollama partitions stay serial unless ``allow_local_parallel`` is true.
    When ``local_endpoint_pool`` is set, local jobs round-robin across those
    Ollama base URLs (one endpoint per physical GPU instance).
    """

    if not approval_id or not approval_id.strip():
        raise ValueError("approval_id is required before agentic execution")
    if plan.get("status") != "ready":
        raise ValueError("cannot execute a blocked campaign plan")
    jobs = list(plan.get("jobs") or [])
    if not jobs:
        raise ValueError("campaign plan contains no jobs")
    effective_workers = _resolve_execution_workers(
        jobs, workers, allow_local_parallel=allow_local_parallel
    )
    endpoint_pool = list(local_endpoint_pool or [])
    if (
        effective_workers > 1
        and any(str(job.get("model_id") or "").startswith(_LOCAL_MODEL_ID_PREFIXES) for job in jobs)
        and len(endpoint_pool) < 2
    ):
        logger.warning(
            "Local parallel workers=%s without a multi-endpoint pool; "
            "both jobs will share one Ollama host (no GPU pinning). "
            "Pass --local-endpoint-pool url1,url2 for dual-GPU.",
            effective_workers,
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    scoped_manifest = plan.get("scoped_manifest")
    if not isinstance(scoped_manifest, Mapping):
        raise ValueError("campaign plan has no scoped_manifest")
    scope_path = output_dir / "manifest_scope.json"
    scope_path.write_text(json.dumps(scoped_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    assets = collect_asset_checksums(
        scoped_manifest,
        scope_path,
        project_root=project_root,
        require_ground_truth=True,
    )
    run_index = create_run_index(
        scoped_manifest,
        # Keep the immutable production manifest identity stable across
        # resumable partitions.  The scoped manifest remains beside each
        # partition for inspection and asset resolution, but per-partition
        # paths would make merge_run_indices reject otherwise compatible
        # indexes.
        manifest_path=str(manifest_path),
        config_file="per-job-environment-sources",
        asset_checksums=assets,
        scheduled_jobs=[
            {
                key: job[key]
                for key in ("run_id", "instance_id", "condition_id", "model_id", "repetition")
            }
            for job in jobs
        ],
    )
    run_index["approval_id"] = approval_id
    run_index["mode"] = "executing"
    run_index["workers"] = effective_workers
    run_index["workers_requested"] = workers
    if endpoint_pool:
        run_index["local_endpoint_pool"] = endpoint_pool
    partition_path = plan.get("partition_path")
    if isinstance(partition_path, str) and partition_path:
        run_index["partition_path"] = partition_path
    run_index_path = output_dir / "run_index.json"
    run_index_path.write_text(json.dumps(run_index, indent=2, ensure_ascii=False), encoding="utf-8")

    index_lock = threading.Lock()

    def _commit(result: Mapping[str, Any]) -> None:
        with index_lock:
            record_result(run_index, result)
            run_index_path.write_text(
                json.dumps(run_index, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def _run_job(job: Mapping[str, Any], job_index: int) -> Dict[str, Any]:
        overrides = _endpoint_overrides_for_job(
            job,
            job_index=job_index,
            endpoint_pool=endpoint_pool,
        )
        if overrides:
            logger.info(
                "Pinning %s to %s",
                job.get("run_id"),
                overrides.get("FAIRIFIER_LLM_BASE_URL"),
            )
        return _execute_one_agentic_job(
            job,
            project_root=project_root,
            env_overrides=overrides or None,
        )

    if effective_workers == 1:
        for job_index, job in enumerate(jobs):
            _commit(_run_job(job, job_index))
    else:
        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            futures = {
                executor.submit(_run_job, job, job_index): job
                for job_index, job in enumerate(jobs)
            }
            for future in as_completed(futures):
                job = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - never drop a scheduled cell
                    result = _agentic_result_envelope(
                        job,
                        status="infrastructure_error",
                        run_dir=Path(str(job["expected_output_dir"])),
                        latency_seconds=0.0,
                        error="%s: %s" % (type(exc).__name__, exc),
                    )
                _commit(result)

    run_index["mode"] = "executed"
    run_index["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    run_index_path.write_text(json.dumps(run_index, indent=2, ensure_ascii=False), encoding="utf-8")
    return run_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a token-free agentic v2 campaign plan")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-config", action="append", default=[], metavar="MODEL_ID=PATH")
    parser.add_argument("--base-env", type=Path)
    parser.add_argument("--condition-env", action="append", default=[], metavar="CONDITION_ID=PATH")
    parser.add_argument("--condition", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true", help="Execute only with --approval-id")
    parser.add_argument("--approval-id")
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Zero-based start offset for a resumable execution partition.",
    )
    parser.add_argument(
        "--end-index",
        type=int,
        help="Exclusive end offset for a resumable execution partition.",
    )
    parser.add_argument(
        "--partition-path",
        type=Path,
        help="Recorded partition identifier used by merge_run_indices.py.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Parallel subprocess workers (default: 1). Local Ollama jobs force "
            "workers=1 unless --allow-local-parallel is also set."
        ),
    )
    parser.add_argument(
        "--allow-local-parallel",
        action="store_true",
        help=(
            "Permit --workers > 1 for partitions that include local Ollama "
            "models (multi-GPU hosts only)."
        ),
    )
    parser.add_argument(
        "--local-endpoint-pool",
        type=str,
        default="",
        help=(
            "Comma-separated Ollama base URLs for local-model GPU pinning "
            "(e.g. http://127.0.0.1:11434,http://127.0.0.1:11435). "
            "Jobs round-robin across the pool."
        ),
    )
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    try:
        model_configs = _parse_assignments(args.model_config, label="--model-config")
        condition_envs = _parse_assignments(args.condition_env, label="--condition-env")
        plan = build_agentic_campaign_plan(
            manifest,
            args.manifest,
            project_root=args.project_root,
            output_dir=args.output_dir,
            model_configs=model_configs,
            base_env=args.base_env,
            condition_envs=condition_envs,
            selected_conditions=args.condition or None,
            timeout_seconds=args.timeout,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.start_index < 0 or (args.end_index is not None and args.end_index < args.start_index):
        parser.error("partition indexes must satisfy 0 <= start <= end")
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    jobs = list(plan.get("jobs") or [])
    if args.start_index > len(jobs):
        parser.error("--start-index is beyond the scheduled agentic jobs")
    selected_jobs = jobs[args.start_index : args.end_index]
    if not selected_jobs:
        parser.error("selected execution partition contains no agentic jobs")
    plan["jobs"] = selected_jobs
    plan["scheduled_count"] = len(selected_jobs)
    plan["planned_job_count"] = len(selected_jobs)
    plan["workers_requested"] = args.workers
    plan["workers"] = _resolve_execution_workers(
        selected_jobs,
        args.workers,
        allow_local_parallel=args.allow_local_parallel,
    )
    endpoint_pool = _parse_endpoint_pool(args.local_endpoint_pool)
    if endpoint_pool:
        plan["local_endpoint_pool"] = endpoint_pool
    scoped_manifest = dict(plan.get("scoped_manifest") or {})
    scoped_manifest["scheduled_runs"] = [
        {
            key: job[key]
            for key in ("run_id", "instance_id", "condition_id", "model_id", "repetition")
        }
        for job in selected_jobs
    ]
    plan["scoped_manifest"] = scoped_manifest
    if args.partition_path:
        plan["partition_path"] = str(args.partition_path)
    rendered = json.dumps(plan, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if not args.execute:
        print(rendered)
        return 0 if plan["status"] == "ready" else 2
    if not args.approval_id:
        parser.error("--execute requires --approval-id after budget review")
    if plan["status"] != "ready":
        print(rendered)
        return 2
    run_index = execute_agentic_campaign(
        plan,
        manifest_path=args.manifest,
        project_root=args.project_root,
        output_dir=args.output_dir,
        approval_id=args.approval_id,
        workers=args.workers,
        allow_local_parallel=args.allow_local_parallel,
        local_endpoint_pool=endpoint_pool,
    )
    print(
        json.dumps(
            {
                "status": "executed",
                "scheduled_count": run_index["scheduled_count"],
                "observed_count": run_index["observed_count"],
                "workers": run_index.get("workers"),
                "workers_requested": run_index.get("workers_requested"),
                "local_endpoint_pool": run_index.get("local_endpoint_pool"),
                "run_index": str(args.output_dir / "run_index.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
