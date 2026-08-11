"""Descriptive, human-gated threshold calibration tests."""

from evaluation.benchmark.threshold_calibration import build_threshold_calibration_report


def test_calibration_reports_distribution_without_freezing_thresholds() -> None:
    score = {
        "benchmark_release": "fixture",
        "scope": "core",
        "scheduled_count": 2,
        "observed_count": 2,
        "missing_count": 0,
        "standard_runs": [
            {
                "axes": {
                    "information_coverage": 0.5,
                    "value_accuracy": 0.8,
                    "structural_fidelity": 1.0,
                    "interoperability": 0.9,
                }
            },
            {
                "axes": {
                    "information_coverage": 1.0,
                    "value_accuracy": 0.9,
                    "structural_fidelity": 1.0,
                    "interoperability": 1.0,
                }
            },
        ],
    }
    report = build_threshold_calibration_report(score)
    assert report["thresholds_frozen"] is False
    assert report["human_review_required"] is True
    assert report["axes"]["information_coverage"]["count"] == 2
    assert report["axes"]["information_coverage"]["floor_fraction"] == 0.0
    assert report["axes"]["structural_fidelity"]["ceiling_fraction"] == 1.0
    assert report["axes"]["value_accuracy"]["current_profile_hit_rates"]["standard"] == 1.0
