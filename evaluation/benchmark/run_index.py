"""Run-index helpers for resumable, denominator-preserving benchmark batches."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping, Sequence

from .contracts import validate_result


def validate_run_index(run_index: Mapping[str, Any]) -> list[str]:
    """Return structural errors for a persisted v2 run index.

    Counts and scheduled identities are checked before evaluator attachment or
    scoring.  This prevents a hand-edited index from silently dropping runs.
    """

    errors: list[str] = []
    if run_index.get("schema_version") != "fairiagent.run_index.v2":
        errors.append("schema_version must be fairiagent.run_index.v2")
    scheduled = run_index.get("scheduled_runs")
    results = run_index.get("results")
    if not isinstance(scheduled, list):
        errors.append("scheduled_runs must be a list")
        scheduled = []
    if not isinstance(results, list):
        errors.append("results must be a list")
        results = []
    scheduled_ids = [item.get("run_id") for item in scheduled if isinstance(item, Mapping)]
    if len(scheduled_ids) != len(set(scheduled_ids)):
        errors.append("scheduled_runs contains duplicate run_id values")
    scheduled_set = {value for value in scheduled_ids if isinstance(value, str)}
    result_ids = [item.get("run_id") for item in results if isinstance(item, Mapping)]
    if len(result_ids) != len(set(result_ids)):
        errors.append("results contains duplicate run_id values")
    for index, result in enumerate(results):
        if not isinstance(result, Mapping):
            errors.append("results[%d] must be an object" % index)
            continue
        run_id = result.get("run_id")
        if run_id not in scheduled_set:
            errors.append("results[%d] is not scheduled: %s" % (index, run_id))
        else:
            scheduled_item = next(
                item for item in scheduled
                if isinstance(item, Mapping) and item.get("run_id") == run_id
            )
            for key in ("instance_id", "condition_id", "model_id", "repetition"):
                if result.get(key) != scheduled_item.get(key):
                    errors.append(
                        "results[%d].%s does not match scheduled run %s"
                        % (index, key, run_id)
                    )
        result_errors = validate_result(result)
        errors.extend("results[%d].%s" % (index, error) for error in result_errors)
    scheduled_count = run_index.get("scheduled_count")
    observed_count = run_index.get("observed_count")
    missing_count = run_index.get("missing_count")
    if scheduled_count != len(scheduled):
        errors.append("scheduled_count does not match scheduled_runs")
    if observed_count != len(results):
        errors.append("observed_count does not match results")
    if isinstance(scheduled_count, int) and isinstance(observed_count, int):
        expected_missing = scheduled_count - observed_count
        if missing_count != expected_missing:
            errors.append("missing_count does not equal scheduled_count-observed_count")
        if expected_missing < 0:
            errors.append("observed_count exceeds scheduled_count")
    return errors


def create_run_index(
    manifest: Mapping[str, Any],
    *,
    manifest_path: str,
    config_file: str,
    asset_checksums: Mapping[str, Any],
    scheduled_jobs: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Create the immutable scheduling record before any model call."""

    if not isinstance(asset_checksums, Mapping) or not asset_checksums:
        raise ValueError("asset_checksums are required before creating a run index")
    for instance in manifest.get("instances", []):
        instance_id = instance.get("instance_id")
        assets = asset_checksums.get(instance_id) if isinstance(instance_id, str) else None
        if not isinstance(assets, Mapping):
            raise ValueError("asset checksums are missing for instance: %s" % instance_id)
        for required_asset in ("source", "ground_truth"):
            digest = (assets.get(required_asset) or {}).get("sha256")
            if not isinstance(digest, str) or len(digest) != 64:
                raise ValueError(
                    "asset checksum is missing or invalid for %s.%s" % (instance_id, required_asset)
                )

    return {
        "schema_version": "fairiagent.run_index.v2",
        "benchmark_release": manifest["benchmark_release"],
        "manifest_path": manifest_path,
        "config_file": config_file,
        "created_at": datetime.now().isoformat(),
        "asset_checksums": dict(asset_checksums),
        "scheduled_count": len(scheduled_jobs),
        "observed_count": 0,
        "missing_count": len(scheduled_jobs),
        "scheduled_runs": [dict(job) for job in scheduled_jobs],
        "results": [],
    }


def record_result(run_index: Dict[str, Any], result: Mapping[str, Any]) -> None:
    """Append one observed result while keeping scheduling counts explicit."""

    run_id = result.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run result must contain run_id")
    scheduled = {
        item.get("run_id"): item
        for item in run_index.get("scheduled_runs", [])
        if isinstance(item, Mapping) and item.get("run_id")
    }
    if run_id not in scheduled:
        raise ValueError("run result is not scheduled: %s" % run_id)
    expected = scheduled[run_id]
    identity = {key: result.get(key) for key in ("instance_id", "condition_id", "model_id", "repetition")}
    expected_identity = {key: expected.get(key) for key in identity}
    if identity != expected_identity:
        raise ValueError("run result identity does not match schedule: %s" % run_id)
    errors = validate_result(result)
    if errors:
        raise ValueError("run result is not a canonical envelope:\n- " + "\n- ".join(errors))
    if any(item.get("run_id") == run_id for item in run_index["results"]):
        raise ValueError("duplicate run result: %s" % run_id)
    run_index["results"].append(dict(result))
    run_index["observed_count"] = len(run_index["results"])
    run_index["missing_count"] = run_index["scheduled_count"] - run_index["observed_count"]


def merge_run_indices(indices: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Merge disjoint execution partitions into one denominator-preserving index.

    Each partition must use the same benchmark release, manifest path, and
    immutable asset checksums.  Scheduled identities may be split across
    partitions but may not overlap; observed result identities may likewise
    appear at most once.  The merged index is therefore safe to pass to the
    evaluator without silently dropping a failed or unfinished cell.
    """

    if not indices:
        raise ValueError("at least one run index is required")
    required_keys = ("schema_version", "benchmark_release", "manifest_path", "asset_checksums")
    first = indices[0]
    for key in required_keys:
        if key not in first:
            raise ValueError("run index is missing required key: %s" % key)
    for position, index in enumerate(indices):
        if not isinstance(index, Mapping):
            raise ValueError("run index %d must be an object" % position)
        for key in required_keys:
            if index.get(key) != first.get(key):
                raise ValueError("run index %d differs in immutable field: %s" % (position, key))
        if index.get("schema_version") != "fairiagent.run_index.v2":
            raise ValueError("run index %d has unsupported schema_version" % position)
        errors = validate_run_index(index)
        if errors:
            raise ValueError("run index %d is invalid:\n- %s" % (position, "\n- ".join(errors)))

    scheduled_by_id: Dict[str, Dict[str, Any]] = {}
    results_by_id: Dict[str, Dict[str, Any]] = {}
    partitions: list[str] = []
    for index in indices:
        partition_path = index.get("partition_path")
        if isinstance(partition_path, str) and partition_path:
            partitions.append(partition_path)
        for item in index.get("scheduled_runs", []):
            run_id = item.get("run_id") if isinstance(item, Mapping) else None
            if not isinstance(run_id, str) or not run_id:
                raise ValueError("partition contains a scheduled run without run_id")
            if run_id in scheduled_by_id:
                raise ValueError("scheduled run overlaps partitions: %s" % run_id)
            scheduled_by_id[run_id] = dict(item)
        for result in index.get("results", []):
            run_id = result.get("run_id") if isinstance(result, Mapping) else None
            if not isinstance(run_id, str) or not run_id:
                raise ValueError("partition contains a result without run_id")
            if run_id in results_by_id:
                raise ValueError("result overlaps partitions: %s" % run_id)
            results_by_id[run_id] = dict(result)

    merged = {
        "schema_version": "fairiagent.run_index.v2",
        "benchmark_release": first["benchmark_release"],
        "manifest_path": first["manifest_path"],
        "config_file": "merged execution partitions",
        "created_at": datetime.now().isoformat(),
        "asset_checksums": dict(first["asset_checksums"]),
        "scheduled_count": len(scheduled_by_id),
        "observed_count": len(results_by_id),
        "missing_count": len(scheduled_by_id) - len(results_by_id),
        "scheduled_runs": [scheduled_by_id[key] for key in sorted(scheduled_by_id)],
        "results": [results_by_id[key] for key in sorted(results_by_id)],
        "partitioned_from": partitions,
    }
    errors = validate_run_index(merged)
    if errors:
        raise ValueError("merged run index is invalid:\n- %s" % "\n- ".join(errors))
    return merged
