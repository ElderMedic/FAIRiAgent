"""Benchmark version 2 scoring over the canonical run envelope.

This scorer intentionally operates on every scheduled run. A missing result is
converted to an explicit ``not_observed`` failure, so a caller cannot improve a
benchmark result by selecting only successful repetitions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .contracts import RESULT_SCHEMA_VERSION, validate_manifest, validate_result


class ScoreError(ValueError):
    """Raised when a score matrix is inconsistent with its manifest."""


REPORTING_SCOPES = {"core", "supplemental", "stress"}


@dataclass(frozen=True)
class BenchmarkProfile:
    """Hard requirements for one declared benchmark success profile."""

    name: str
    minimum_coverage: float
    minimum_value_accuracy: float
    minimum_structural_fidelity: float
    minimum_interoperability: float
    require_fairds_validation: bool = True
    require_isa_round_trip: bool = True
    require_zero_critical_errors: bool = True


# Compatibility name retained for the v2 result-envelope schema. Publication
# reports must label this as the provisional joint end-to-end profile until the
# development calibration decision is frozen.
STANDARD_PROFILE = BenchmarkProfile(
    name="standard",
    minimum_coverage=0.70,
    minimum_value_accuracy=0.75,
    minimum_structural_fidelity=0.75,
    minimum_interoperability=0.90,
)

STRICT_PROFILE = BenchmarkProfile(
    name="strict",
    minimum_coverage=0.85,
    minimum_value_accuracy=0.90,
    minimum_structural_fidelity=0.90,
    minimum_interoperability=1.00,
)


def _as_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def _geometric_mean(values: Iterable[float], weights: Iterable[float]) -> float:
    pairs = [(_as_float(value), float(weight)) for value, weight in zip(values, weights)]
    if not pairs or any(weight <= 0 for _, weight in pairs):
        return 0.0
    if any(value <= 0 for value, _ in pairs):
        return 0.0
    total_weight = sum(weight for _, weight in pairs)
    return math.exp(sum(weight * math.log(value) for value, weight in pairs) / total_weight)


def _wilson_interval(successes: int, trials: int, z: float = 1.96) -> List[float] | None:
    """Return a two-sided Wilson 95% interval for a binomial proportion."""

    if trials <= 0:
        return None
    proportion = successes / trials
    denominator = 1.0 + (z * z / trials)
    center = (proportion + z * z / (2.0 * trials)) / denominator
    half_width = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / trials
            + z * z / (4.0 * trials * trials)
        )
        / denominator
    )
    return [round(max(0.0, center - half_width), 6), round(min(1.0, center + half_width), 6)]


def _missing_result(run_spec: Mapping[str, Any]) -> Dict[str, Any]:
    """Create the explicit failure for a scheduled run with no result."""

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "run_id": run_spec["run_id"],
        "instance_id": run_spec["instance_id"],
        "condition_id": run_spec["condition_id"],
        "model_id": run_spec["model_id"],
        "repetition": run_spec["repetition"],
        "status": "not_observed",
        "artifact": {"exists": False, "parseable": False},
        "validation": {
            "fairds_valid": False,
            "isa_round_trip_valid": False,
            "critical_errors": 0,
        },
        "axes": {
            "information_coverage": 0.0,
            "value_accuracy": 0.0,
            "structural_fidelity": 0.0,
            "interoperability": 0.0,
        },
        "failure": {"category": "missing_result"},
    }


def _gate_result(result: Mapping[str, Any], profile: BenchmarkProfile) -> List[str]:
    artifact = result["artifact"]
    validation = result["validation"]
    axes = result["axes"]
    reasons: List[str] = []
    if result.get("status") != "success":
        reasons.append("status:%s" % result.get("status"))
    if not artifact["exists"]:
        reasons.append("artifact_missing")
    if not artifact["parseable"]:
        reasons.append("artifact_unparseable")
    if profile.require_fairds_validation and not validation["fairds_valid"]:
        reasons.append("fairds_validation_failed")
    if profile.require_isa_round_trip and not validation["isa_round_trip_valid"]:
        reasons.append("isa_round_trip_failed")
    if profile.require_zero_critical_errors and validation["critical_errors"] != 0:
        reasons.append("critical_errors:%s" % validation["critical_errors"])
    thresholds = (
        ("information_coverage", profile.minimum_coverage),
        ("value_accuracy", profile.minimum_value_accuracy),
        ("structural_fidelity", profile.minimum_structural_fidelity),
        ("interoperability", profile.minimum_interoperability),
    )
    for axis, minimum in thresholds:
        if axes[axis] < minimum:
            reasons.append("%s_below_threshold" % axis)
    return reasons


def score_run(
    result: Mapping[str, Any],
    profile: BenchmarkProfile = STANDARD_PROFILE,
) -> Dict[str, Any]:
    """Score one canonical result without changing its raw diagnostics."""

    errors = validate_result(result)
    if errors:
        raise ScoreError("Invalid result %s:\n- %s" % (result.get("run_id"), "\n- ".join(errors)))
    axes = result["axes"]
    normalized_axes = {
        "information_coverage": _as_float(axes["information_coverage"]),
        "value_accuracy": _as_float(axes["value_accuracy"]),
        "structural_fidelity": _as_float(axes["structural_fidelity"]),
        "interoperability": _as_float(axes["interoperability"]),
    }
    normalized_efficiency = axes.get("efficiency")
    reasons = _gate_result(
        {
            **result,
            "axes": normalized_axes,
        },
        profile,
    )
    return {
        "run_id": result["run_id"],
        "instance_id": result["instance_id"],
        "condition_id": result["condition_id"],
        "model_id": result["model_id"],
        "repetition": result["repetition"],
        "status": result["status"],
        "axes": normalized_axes,
        "efficiency": _as_float(normalized_efficiency) if normalized_efficiency is not None else None,
        "success": not reasons,
        "failure_reasons": reasons,
    }


def _index_results(results: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    if isinstance(results, Mapping):
        values = list(results.values())
    else:
        values = list(results)
    indexed: Dict[str, Mapping[str, Any]] = {}
    for result in values:
        run_id = result.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ScoreError("Every result must have a non-empty run_id")
        if run_id in indexed:
            raise ScoreError("Duplicate result run_id: %s" % run_id)
        indexed[run_id] = result
    return indexed


def score_batch(
    manifest: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]],
    *,
    standard_profile: BenchmarkProfile = STANDARD_PROFILE,
    strict_profile: BenchmarkProfile = STRICT_PROFILE,
    scope: str | None = None,
) -> Dict[str, Any]:
    """Score scheduled runs, optionally restricted to a reporting role.

    ``scope=None`` preserves the historical all-instance behavior. A scoped
    score requires every manifest instance to declare ``reporting_role`` and
    excludes other roles from the denominator while still accepting their
    persisted results in the same run index.
    """

    manifest_errors = validate_manifest(manifest)
    if manifest_errors:
        raise ScoreError("Invalid benchmark manifest:\n- " + "\n- ".join(manifest_errors))
    all_scheduled = manifest["scheduled_runs"]
    if scope is not None and scope not in REPORTING_SCOPES:
        raise ScoreError("scope must be one of %s" % sorted(REPORTING_SCOPES))
    role_by_instance = {
        str(instance.get("instance_id")): instance.get("reporting_role")
        for instance in manifest.get("instances", [])
        if isinstance(instance, Mapping) and instance.get("instance_id")
    }
    if scope is not None:
        missing_roles = sorted(
            instance_id
            for instance_id, role in role_by_instance.items()
            if not isinstance(role, str) or not role
        )
        if missing_roles:
            raise ScoreError(
                "scope=%s requires reporting_role for every instance: %s"
                % (scope, ", ".join(missing_roles))
            )
        scheduled = [
            run
            for run in all_scheduled
            if role_by_instance.get(str(run.get("instance_id"))) == scope
        ]
        if not scheduled:
            raise ScoreError("scope=%s has no scheduled runs" % scope)
    else:
        scheduled = list(all_scheduled)
    expected_ids = {run["run_id"] for run in all_scheduled}
    indexed = _index_results(results)
    extra_ids = sorted(set(indexed) - expected_ids)
    if extra_ids:
        raise ScoreError("Results contain runs absent from manifest: %s" % ", ".join(extra_ids))

    complete_results: List[Mapping[str, Any]] = []
    missing_count = 0
    for run_spec in scheduled:
        result = indexed.get(run_spec["run_id"])
        if result is None:
            result = _missing_result(run_spec)
            missing_count += 1
        else:
            identity = {
                key: result.get(key)
                for key in ("instance_id", "condition_id", "model_id", "repetition")
            }
            expected = {key: run_spec[key] for key in identity}
            if identity != expected:
                raise ScoreError("Result identity does not match manifest for %s" % run_spec["run_id"])
        complete_results.append(result)

    standard_runs = [score_run(result, standard_profile) for result in complete_results]
    strict_runs = [score_run(result, strict_profile) for result in complete_results]
    axis_names = (
        "information_coverage",
        "value_accuracy",
        "structural_fidelity",
        "interoperability",
    )

    def aggregate_axes(scored_runs: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
        return {
            axis: round(sum(run["axes"][axis] for run in scored_runs) / len(scored_runs), 6)
            for axis in axis_names
        }

    def success_rate(scored_runs: Sequence[Mapping[str, Any]]) -> float:
        return sum(1 for run in scored_runs if run["success"]) / len(scored_runs)

    def pass_to_power_k(scored_runs: Sequence[Mapping[str, Any]], k: int) -> Dict[str, Any]:
        """Estimate the probability that all k repetitions pass.

        Groups are document-condition-model cells. Repetitions are ordered by
        the manifest's repetition number; cells with fewer than k scheduled
        repetitions are excluded from the pass-to-the-power-of-k denominator.
        ``k=1`` is the ordinary scheduled-run success rate.
        """

        if k < 1:
            raise ValueError("k must be positive")
        if k == 1:
            passed = sum(1 for run in scored_runs if run["success"])
            return {
                "k": 1,
                "eligible_groups": len(scored_runs),
                "passed_groups": passed,
                "estimate": success_rate(scored_runs),
                "ci95": _wilson_interval(passed, len(scored_runs)),
            }
        groups: Dict[tuple[str, str, str], List[Mapping[str, Any]]] = defaultdict(list)
        for run in scored_runs:
            groups[(run["instance_id"], run["condition_id"], run["model_id"])].append(run)
        eligible = 0
        passed = 0
        for group in groups.values():
            ordered = sorted(group, key=lambda run: run["repetition"])
            if len(ordered) < k:
                continue
            eligible += 1
            passed += int(all(run["success"] for run in ordered[:k]))
        return {
            "k": k,
            "eligible_groups": eligible,
            "passed_groups": passed,
            "estimate": passed / eligible if eligible else None,
            "ci95": _wilson_interval(passed, eligible),
        }

    axes = aggregate_axes(standard_runs)
    reliability = success_rate(standard_runs)
    standard_passes = sum(1 for run in standard_runs if run["success"])
    strict_passes = sum(1 for run in strict_runs if run["success"])
    efficiency_values = [run["efficiency"] for run in standard_runs if run["efficiency"] is not None]
    axes["reliability"] = round(reliability, 6)
    axes["efficiency"] = round(sum(efficiency_values) / len(efficiency_values), 6) if efficiency_values else None
    quality_score = 100.0 * _geometric_mean(
        (
            axes["information_coverage"],
            axes["value_accuracy"],
            axes["structural_fidelity"],
            axes["interoperability"],
            axes["reliability"],
        ),
        (0.20, 0.30, 0.20, 0.20, 0.10),
    )

    return {
        "schema_version": "fairiagent.benchmark_score.v2",
        "benchmark_release": manifest["benchmark_release"],
        "scope": scope or "all",
        "scheduled_count": len(scheduled),
        "observed_count": sum(1 for run in scheduled if run["run_id"] in indexed),
        "missing_count": missing_count,
        "excluded_scheduled_count": len(all_scheduled) - len(scheduled),
        "standard_success_rate": round(success_rate(standard_runs), 6),
        "strict_success_rate": round(success_rate(strict_runs), 6),
        "standard_success_rate_ci95": _wilson_interval(standard_passes, len(standard_runs)),
        "strict_success_rate_ci95": _wilson_interval(strict_passes, len(strict_runs)),
        "axes": axes,
        "benchmark_quality_score": round(quality_score, 6),
        "pass_to_the_power_of_k": {
            str(k): pass_to_power_k(standard_runs, k) for k in (1, 3, 5)
        },
        "failure_categories": dict(
            Counter(
                reason.split(":", 1)[0]
                for run in standard_runs
                for reason in run["failure_reasons"]
            )
        ),
        "standard_runs": standard_runs,
        "strict_runs": strict_runs,
    }
