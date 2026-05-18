"""Tests for figure selectors used by the manuscript-grade figure pipeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from evaluation.paper_experiments_v1.figure_selectors import (  # type: ignore[attr-defined]
    select_main_result_points,
    select_manifest_summary,
    select_sheet_heatmap_rows,
)


def test_select_main_result_points_excludes_missing_cells():
    manifest = {
        "cells": [
            {
                "condition": "baseline_b1",
                "document": "earthworm",
                "model_key": "qwen3.6-27b",
                "included_main_text": True,
                "metric_row_mean_score": 0.62,
            },
            {
                "condition": "baseline_b1",
                "document": "pea_cold_stress",
                "model_key": "qwen3.6-27b",
                "included_main_text": False,
                "metric_row_mean_score": None,
            },
        ]
    }
    rows = select_main_result_points(manifest)
    assert rows == [
        {
            "condition": "B1",
            "document": "earthworm",
            "model_key": "qwen3.6-27b",
            "metric_row_mean_score": 0.62,
        }
    ]


def test_select_sheet_heatmap_rows_only_keeps_main_benchmark_rows():
    manifest = {
        "per_sheet_rows": [
            {
                "document": "earthworm",
                "sheet": "assay",
                "included_main_text": True,
                "metric_row_mean_score": 0.31,
            },
            {
                "document": "biorem",
                "sheet": "assay",
                "included_main_text": False,
                "metric_row_mean_score": 0.88,
            },
        ]
    }
    rows = select_sheet_heatmap_rows(manifest)
    assert rows == [
        {
            "document": "earthworm",
            "sheet": "assay",
            "metric_row_mean_score": 0.31,
        }
    ]


def test_select_manifest_summary_reports_main_figure_counts():
    manifest = {
        "cells": [
            {
                "condition": "baseline_b1",
                "document": "earthworm",
                "config_name": "ollama_qwen3.6-27b_v1.4.0",
                "included_main_text": True,
                "success": True,
                "source_kind": "phase0_run",
            },
            {
                "condition": "full_pipeline",
                "document": "pea_cold_stress",
                "config_name": "deepseek_v4-pro_v1.4.0",
                "included_main_text": False,
                "success": False,
                "source_kind": "phase0_run",
                "exclusion_reason": "run_not_successful",
            },
        ]
    }
    summary = select_manifest_summary(manifest)
    assert summary["included_cells"] == 1
    assert summary["condition_counts"]["B1"] == 1
    assert summary["timeout_exclusions"] == 1
