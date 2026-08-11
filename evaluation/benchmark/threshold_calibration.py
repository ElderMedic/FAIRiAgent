"""Token-free score-distribution report for human threshold calibration.

The report is deliberately descriptive.  It never edits the benchmark
profiles or selects a threshold automatically; a researcher must review the
pilot error severity and freeze the resulting profiles in a later release.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


AXES = (
    "information_coverage",
    "value_accuracy",
    "structural_fidelity",
    "interoperability",
)


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 6)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 6)


def _values(score: Mapping[str, Any], axis: str) -> list[float]:
    runs = score.get("standard_runs")
    if not isinstance(runs, list):
        raise ValueError("score input must contain standard_runs")
    values: list[float] = []
    for index, run in enumerate(runs):
        if not isinstance(run, Mapping):
            raise ValueError("standard_runs[%d] must be an object" % index)
        raw = (run.get("axes") or {}).get(axis)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        values.append(max(0.0, min(1.0, float(raw))))
    return values


def build_threshold_calibration_report(
    score: Mapping[str, Any],
    *,
    current_profiles: Mapping[str, Mapping[str, float]] | None = None,
) -> Dict[str, Any]:
    """Describe pilot distributions and current threshold hit rates."""

    profile_map = dict(current_profiles or {
        "standard": {
            "information_coverage": 0.70,
            "value_accuracy": 0.75,
            "structural_fidelity": 0.75,
            "interoperability": 0.90,
        },
        "strict": {
            "information_coverage": 0.85,
            "value_accuracy": 0.90,
            "structural_fidelity": 0.90,
            "interoperability": 1.00,
        },
    })
    axes: Dict[str, Any] = {}
    for axis in AXES:
        values = _values(score, axis)
        axis_report: Dict[str, Any] = {
            "count": len(values),
            "minimum": round(min(values), 6) if values else None,
            "maximum": round(max(values), 6) if values else None,
            "mean": round(sum(values) / len(values), 6) if values else None,
            "quantiles": {
                "p05": _quantile(values, 0.05),
                "p10": _quantile(values, 0.10),
                "p25": _quantile(values, 0.25),
                "p50": _quantile(values, 0.50),
                "p75": _quantile(values, 0.75),
                "p90": _quantile(values, 0.90),
                "p95": _quantile(values, 0.95),
            },
            "unique_value_count": len(set(values)),
            "ceiling_fraction": round(sum(value >= 1.0 for value in values) / len(values), 6)
            if values
            else None,
            "floor_fraction": round(sum(value <= 0.0 for value in values) / len(values), 6)
            if values
            else None,
            "current_profile_hit_rates": {},
        }
        for profile_name, thresholds in profile_map.items():
            threshold = thresholds.get(axis)
            if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
                continue
            axis_report["current_profile_hit_rates"][profile_name] = (
                round(sum(value >= float(threshold) for value in values) / len(values), 6)
                if values
                else None
            )
        axes[axis] = axis_report
    return {
        "schema_version": "fairiagent.threshold_calibration_report.v1",
        "benchmark_release": score.get("benchmark_release"),
        "source_scope": score.get("scope", "all"),
        "profile_interpretation": "provisional_joint_end_to_end; not frozen",
        "task_decomposition": {
            "task_a": "metadata reconstruction / field recovery proxy",
            "task_b": "value filling requires an identical oracle package and field list",
            "joint_profile": "secondary end-to-end outcome; current value axis is GT-wide and includes missing fields as zero",
        },
        "scheduled_count": score.get("scheduled_count"),
        "observed_count": score.get("observed_count"),
        "missing_count": score.get("missing_count"),
        "axes": axes,
        "current_profiles": profile_map,
        "thresholds_frozen": False,
        "human_review_required": True,
        "model_or_api_calls_performed": False,
        "review_requirements": [
            "review pilot errors by severity rather than selecting a convenient quantile",
            "check that no axis has an unexplained floor, ceiling, or zero denominator",
            "record the approved Standard and Strict profiles in the benchmark release decision log",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Describe pilot score distributions for threshold review")
    parser.add_argument("--score", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    score = json.loads(args.score.read_text(encoding="utf-8"))
    report = build_threshold_calibration_report(score)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
