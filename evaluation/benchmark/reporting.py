"""Publication-facing score summaries and radar-chart data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


RADAR_AXES = (
    "information_coverage",
    "value_accuracy",
    "structural_fidelity",
    "interoperability",
    "reliability",
    "efficiency",
)
RADAR_LABELS = {
    "information_coverage": "Field recovery / presence",
    "value_accuracy": "GT-wide value score",
    "structural_fidelity": "ISA structural fidelity",
    "interoperability": "Standards and interoperability",
    "reliability": "Reliability",
    "efficiency": "Computational efficiency",
}


def radar_data(score: Mapping[str, Any]) -> Dict[str, Any]:
    """Return fixed-order radar data without hiding unavailable efficiency."""

    axes = score.get("axes") or {}
    values = [axes.get(axis) for axis in RADAR_AXES]
    return {
        "axis_order": list(RADAR_AXES),
        "axis_labels": [RADAR_LABELS[axis] for axis in RADAR_AXES],
        "values": values,
        "unavailable_axes": [axis for axis, value in zip(RADAR_AXES, values) if value is None],
        "scale": [0.0, 1.0],
    }


def markdown_summary(score: Mapping[str, Any]) -> str:
    axes = score.get("axes") or {}
    lines = [
        "# FAIRiAgent Benchmark Version 2 Score",
        "",
        "| Measure | Value |",
        "|---|---:|",
        "| Provisional Joint End-to-End Pass Rate (Benchmark Success Rate compatibility field) | %.4f |" % score.get("standard_success_rate", 0.0),
        "| Strict Joint End-to-End Pass Rate (provisional) | %.4f |" % score.get("strict_success_rate", 0.0),
        "| Provisional Joint Pass 95%% CI (Standard Success 95%% CI compatibility field) | %s |" % _format_interval(score.get("standard_success_rate_ci95")),
        "| Strict Joint Pass 95%% CI | %s |" % _format_interval(score.get("strict_success_rate_ci95")),
        "| Benchmark Quality Score | %.4f |" % score.get("benchmark_quality_score", 0.0),
        "| Reporting scope | %s |" % score.get("scope", "all"),
        "| Scheduled document-runs | %s |" % score.get("scheduled_count", 0),
        "| Observed document-runs | %s |" % score.get("observed_count", 0),
        "| Missing document-runs | %s |" % score.get("missing_count", 0),
        "| Excluded document-runs | %s |" % score.get("excluded_scheduled_count", 0),
        "",
        "## Radar axes",
        "",
        "| Axis | Value |",
        "|---|---:|",
    ]
    for axis in RADAR_AXES:
        value = axes.get(axis)
        lines.append("| %s | %s |" % (RADAR_LABELS[axis], "unavailable" if value is None else "%.4f" % value))
    lines.extend(
        [
            "",
            "## Reliability",
            "",
            "```json",
            json.dumps(score.get("pass_to_the_power_of_k", {}), indent=2),
            "```",
            "",
            "## Failure categories",
            "",
            "```json",
            json.dumps(score.get("failure_categories", {}), indent=2),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def _format_interval(interval: Any) -> str:
    if not isinstance(interval, (list, tuple)) or len(interval) != 2:
        return "unavailable"
    return "[%.4f, %.4f]" % (float(interval[0]), float(interval[1]))


def write_score_report(score: Mapping[str, Any], output_dir: Path) -> Dict[str, Path]:
    """Write machine-readable summary, Markdown summary, and radar data."""

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "score": output_dir / "benchmark_score.json",
        "summary": output_dir / "benchmark_summary.md",
        "radar": output_dir / "radar_data.json",
    }
    paths["score"].write_text(json.dumps(score, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["summary"].write_text(markdown_summary(score), encoding="utf-8")
    paths["radar"].write_text(json.dumps(radar_data(score), indent=2, ensure_ascii=False), encoding="utf-8")
    return paths


def write_radar_chart(score: Mapping[str, Any], output_path: Path) -> Path:
    """Render the fixed-axis radar chart when matplotlib is available."""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError("matplotlib is required to render radar charts") from exc

    data = radar_data(score)
    values = [0.0 if value is None else float(value) for value in data["values"]]
    count = len(RADAR_AXES)
    angles = [index / float(count) * 2.0 * 3.141592653589793 for index in range(count)]
    angles += angles[:1]
    values += values[:1]
    figure, axis = plt.subplots(figsize=(7, 7), subplot_kw={"polar": True})
    axis.plot(angles, values, linewidth=2)
    axis.fill(angles, values, alpha=0.18)
    axis.set_ylim(0, 1)
    axis.set_xticks(angles[:-1])
    axis.set_xticklabels(data["axis_labels"])
    axis.set_title("FAIRiAgent Benchmark Version 2")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)
    return output_path
