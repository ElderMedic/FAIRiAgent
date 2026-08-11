"""Reporting contract tests."""

from pathlib import Path

from evaluation.benchmark.reporting import markdown_summary, radar_data, write_score_report


def _score():
    return {
        "standard_success_rate": 0.5,
        "strict_success_rate": 0.25,
        "standard_success_rate_ci95": [0.2, 0.8],
        "strict_success_rate_ci95": [0.1, 0.6],
        "benchmark_quality_score": 42.0,
        "scope": "core",
        "scheduled_count": 4,
        "observed_count": 3,
        "missing_count": 1,
        "excluded_scheduled_count": 2,
        "axes": {
            "information_coverage": 0.8,
            "value_accuracy": 0.7,
            "structural_fidelity": 0.6,
            "interoperability": 0.9,
            "reliability": 0.5,
            "efficiency": None,
        },
        "pass_to_the_power_of_k": {"1": {"estimate": 0.5}},
        "failure_categories": {"artifact_missing": 1},
    }


def test_radar_axis_order_is_fixed_and_marks_unavailable_efficiency() -> None:
    data = radar_data(_score())
    assert data["axis_order"][-1] == "efficiency"
    assert data["values"][-1] is None
    assert data["unavailable_axes"] == ["efficiency"]


def test_report_writes_machine_and_human_outputs(tmp_path: Path) -> None:
    paths = write_score_report(_score(), tmp_path)
    assert all(path.is_file() for path in paths.values())
    assert "Benchmark Success Rate" in markdown_summary(_score())
    assert "Standard Success 95% CI" in markdown_summary(_score())
    assert "Reporting scope" in markdown_summary(_score())
    assert "Excluded document-runs" in markdown_summary(_score())
