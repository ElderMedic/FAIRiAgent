"""Deterministic paired-analysis and Pareto reporting tests."""

from __future__ import annotations

import pytest

from evaluation.benchmark.statistics import (
    bootstrap_mean_interval,
    paired_comparison,
    pareto_frontier,
    stratified_axis_summary,
)


def _run(instance: str, repetition: int, value: float) -> dict:
    return {
        "instance_id": instance,
        "model_id": "model",
        "repetition": repetition,
        "axes": {
            "information_coverage": value,
            "value_accuracy": value,
            "structural_fidelity": value,
            "interoperability": value,
        },
    }


def test_bootstrap_is_reproducible_and_handles_empty_samples() -> None:
    first = bootstrap_mean_interval([1.0, 2.0, 3.0], resamples=200, seed=7)
    second = bootstrap_mean_interval([1.0, 2.0, 3.0], resamples=200, seed=7)
    assert first == second
    assert first["mean"] == pytest.approx(2.0)
    assert bootstrap_mean_interval([])["ci"] is None


def test_paired_comparison_matches_cells_and_reports_effect() -> None:
    baseline = [_run("a", 1, 0.4), _run("b", 1, 0.6)]
    treatment = [_run("a", 1, 0.6), _run("b", 1, 0.8), _run("c", 1, 1.0)]
    result = paired_comparison(baseline, treatment, resamples=100, seed=3)
    assert result["matched_cells"] == 2
    assert result["unmatched_treatment_cells"] == 1
    assert result["axes"]["value_accuracy"]["mean"] == pytest.approx(0.2)


def test_stratified_summary_and_pareto_frontier() -> None:
    runs = [_run("a", 1, 0.4), _run("b", 1, 0.8)]
    metadata = {
        "a": {"strata": {"domain": "enzyme"}},
        "b": {"strata": {"domain": "microbiome"}},
    }
    summary = stratified_axis_summary(runs, metadata, axis="value_accuracy")
    assert summary["enzyme"]["mean"] == pytest.approx(0.4)
    frontier = pareto_frontier(
        [
            {"label": "cheap", "quality": 0.7, "cost": 1.0},
            {"label": "best", "quality": 0.9, "cost": 2.0},
            {"label": "dominated", "quality": 0.6, "cost": 3.0},
        ]
    )
    assert [point["label"] for point in frontier] == ["cheap", "best"]
