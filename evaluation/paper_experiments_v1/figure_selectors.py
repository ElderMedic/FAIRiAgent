"""Selectors that convert the validated manifest into figure-specific rows."""

from __future__ import annotations

from collections import Counter

from evaluation.paper_experiments_v1.figure_manifest_lib import normalize_condition_name


def select_main_result_points(manifest: dict) -> list[dict]:
    """Return included rows for the main condition-comparison figure."""
    rows: list[dict] = []
    for cell in manifest.get("cells", []):
        if not cell.get("included_main_text"):
            continue
        metric = cell.get("metric_row_mean_score")
        if metric is None:
            continue
        rows.append(
            {
                "condition": normalize_condition_name(cell["condition"]),
                "document": cell["document"],
                "model_key": cell["model_key"],
                "metric_row_mean_score": metric,
            }
        )
    return rows


def select_sheet_heatmap_rows(manifest: dict) -> list[dict]:
    """Return included per-sheet rows for the ISA-structure heatmap."""
    rows: list[dict] = []
    for row in manifest.get("per_sheet_rows", []):
        if not row.get("included_main_text"):
            continue
        rows.append(
            {
                "document": row["document"],
                "sheet": row["sheet"],
                "metric_row_mean_score": row["metric_row_mean_score"],
            }
        )
    return rows


def select_manifest_summary(manifest: dict) -> dict:
    """Return inclusion/exclusion counts used in figure annotations."""
    cells = manifest.get("cells", [])
    included = [cell for cell in cells if cell.get("included_main_text")]
    condition_counts = Counter(normalize_condition_name(cell["condition"]) for cell in included)

    excluded = [cell for cell in cells if not cell.get("included_main_text")]
    exclusion_counts = Counter(cell.get("exclusion_reason") or "unspecified" for cell in excluded)

    timeout_exclusions = sum(
        1
        for cell in excluded
        if cell.get("condition") == "full_pipeline"
        and cell.get("config_name") == "deepseek_v4-pro_v1.4.0"
        and cell.get("document") == "pea_cold_stress"
        and cell.get("success") is False
    )

    unsuccessful_exclusions = sum(
        1
        for cell in excluded
        if cell.get("success") is False and cell.get("exclusion_reason") == "run_not_successful"
    )

    return {
        "total_cells": len(cells),
        "included_cells": len(included),
        "excluded_cells": len(excluded),
        "condition_counts": dict(condition_counts),
        "exclusion_counts": dict(exclusion_counts),
        "timeout_exclusions": timeout_exclusions,
        "unsuccessful_exclusions": unsuccessful_exclusions,
    }

