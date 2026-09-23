"""Token-free statistical summaries for benchmark releases.

The functions operate on persisted scored runs and never inspect model
responses. Bootstrap resampling uses an explicit seed so a report can be
reconstructed exactly from the run index.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot compute a quantile of an empty sequence")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def bootstrap_mean_interval(
    values: Iterable[float],
    *,
    resamples: int = 2000,
    confidence: float = 0.95,
    seed: int = 0,
) -> Dict[str, Any]:
    """Return mean and percentile-bootstrap interval for a finite sample."""

    observations = [float(value) for value in values]
    if not observations:
        return {"n": 0, "mean": None, "ci": None, "resamples": 0, "seed": seed}
    if resamples < 1:
        raise ValueError("resamples must be positive")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    rng = random.Random(seed)
    means = [
        sum(rng.choice(observations) for _ in observations) / len(observations)
        for _ in range(resamples)
    ]
    alpha = (1.0 - confidence) / 2.0
    return {
        "n": len(observations),
        "mean": sum(observations) / len(observations),
        "ci": [_quantile(means, alpha), _quantile(means, 1.0 - alpha)],
        "confidence": confidence,
        "resamples": resamples,
        "seed": seed,
    }


def _sample_standard_deviation(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def paired_comparison(
    baseline_runs: Sequence[Mapping[str, Any]],
    treatment_runs: Sequence[Mapping[str, Any]],
    *,
    axes: Sequence[str] = (
        "information_coverage",
        "value_accuracy",
        "structural_fidelity",
        "interoperability",
    ),
    resamples: int = 2000,
    seed: int = 0,
) -> Dict[str, Any]:
    """Compare two conditions on matched instance/model/repetition cells."""

    def key(run: Mapping[str, Any]) -> Tuple[Any, ...]:
        return (
            run.get("instance_id"),
            run.get("model_id"),
            run.get("repetition"),
        )

    baseline_by_key = {key(run): run for run in baseline_runs}
    treatment_by_key = {key(run): run for run in treatment_runs}
    common_keys = sorted(set(baseline_by_key) & set(treatment_by_key), key=str)
    output: Dict[str, Any] = {
        "matched_cells": len(common_keys),
        "unmatched_baseline_cells": len(set(baseline_by_key) - set(treatment_by_key)),
        "unmatched_treatment_cells": len(set(treatment_by_key) - set(baseline_by_key)),
        "axes": {},
    }
    for axis in axes:
        differences = []
        for cell in common_keys:
            baseline_axis = (baseline_by_key[cell].get("axes") or {}).get(axis)
            treatment_axis = (treatment_by_key[cell].get("axes") or {}).get(axis)
            if isinstance(baseline_axis, (int, float)) and isinstance(treatment_axis, (int, float)):
                differences.append(float(treatment_axis) - float(baseline_axis))
        summary = bootstrap_mean_interval(
            differences,
            resamples=resamples,
            seed=seed + len(output["axes"]),
        )
        std = _sample_standard_deviation(differences)
        summary["median"] = _quantile(differences, 0.5) if differences else None
        summary["standard_deviation"] = std
        summary["standardized_mean_difference"] = (
            summary["mean"] / std if summary["mean"] is not None and std > 0 else None
        )
        output["axes"][axis] = summary
    return output


def stratified_axis_summary(
    scored_runs: Sequence[Mapping[str, Any]],
    instance_metadata: Mapping[str, Mapping[str, Any]],
    *,
    axis: str,
    stratum: str = "domain",
) -> Dict[str, Any]:
    """Report macro means by a declared instance stratum."""

    groups: Dict[str, List[float]] = defaultdict(list)
    for run in scored_runs:
        value = (run.get("axes") or {}).get(axis)
        metadata = instance_metadata.get(str(run.get("instance_id"))) or {}
        strata = metadata.get("strata") or {}
        label = str(strata.get(stratum) or "unspecified")
        if isinstance(value, (int, float)):
            groups[label].append(float(value))
    return {
        label: {
            "n": len(values),
            "mean": sum(values) / len(values) if values else None,
            "ci": bootstrap_mean_interval(values, seed=index)["ci"] if values else None,
        }
        for index, (label, values) in enumerate(sorted(groups.items()))
    }


def pareto_frontier(points: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Return quality-maximizing/cost-minimizing nondominated points."""

    valid = [
        point
        for point in points
        if isinstance(point.get("quality"), (int, float))
        and isinstance(point.get("cost"), (int, float))
    ]
    frontier: List[Dict[str, Any]] = []
    for candidate in valid:
        dominated = any(
            (float(other["quality"]) >= float(candidate["quality"]))
            and (float(other["cost"]) <= float(candidate["cost"]))
            and (
                float(other["quality"]) > float(candidate["quality"])
                or float(other["cost"]) < float(candidate["cost"])
            )
            for other in valid
        )
        if not dominated:
            frontier.append(dict(candidate))
    return sorted(frontier, key=lambda point: (float(point["cost"]), -float(point["quality"])))
