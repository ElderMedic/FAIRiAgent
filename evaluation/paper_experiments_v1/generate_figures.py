#!/usr/bin/env python3
"""Generate manuscript-grade quantitative figures from the latest validated manifest."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from textwrap import fill

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "paper_experiments_v1"
os.environ.setdefault("MPLCONFIGDIR", str(OUTPUT_DIR / ".matplotlib"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from evaluation.paper_experiments_v1.figure_selectors import (
    select_main_result_points,
    select_manifest_summary,
)
from evaluation.paper_experiments_v1.figure_style import (
    CONDITION_COLORS,
    ISA_SHEET_LABELS,
    apply_publication_style,
)

MANIFEST_PATH = OUTPUT_DIR / "analysis" / "figure_manifest_phase0.json"
FIG_DIR = OUTPUT_DIR / "figures"
MANUSCRIPT_DIR = OUTPUT_DIR / "manuscript"
CONDITION_ORDER = ["B1", "B2", "B3", "Full"]
SHEET_ORDER = ["investigation", "study", "observationunit", "sample", "assay"]

FIG3_NOTE = (
    "Row-aligned mean field score first best-matches predicted and ground-truth rows within each "
    "ISA sheet, then averages field-level token-overlap scores over all non-empty ground-truth fields. "
    "Each point is one successful included model x document cell from the 8-document main benchmark. "
    "This draft plotting metric is row-aware, but it is not yet the final Hierarchical-F1."
)

FIG4_NOTE = (
    "Heatmap values use the same row-aligned draft metric family as Fig. 3; higher values indicate "
    "better row-aware agreement with ground truth. The displayed n denotes successful included cells "
    "per condition."
)

SUPP_NOTE = (
    "Main-text quantitative figures are built from the current 8-document benchmark manifest only. "
    "Supplementary-only datasets (biorem, pomato, and compbiobench) remain outside this "
    "main-benchmark aggregation contract."
)


def load_manifest() -> dict:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def _footnote(fig: plt.Figure, text: str, y: float = 0.055) -> None:
    fig.text(0.06, y, fill(text, width=135), fontsize=7.2, color="#52606d", va="bottom", ha="left")


def _note_block(ax: plt.Axes, title: str, lines: list[str], facecolor: str = "#f8fafc") -> None:
    body = "\n".join(fill(line, width=46) for line in lines)
    ax.text(
        0.03,
        0.95,
        f"{title}\n{body}",
        va="top",
        ha="left",
        fontsize=9,
        color="#1f2933",
        bbox={"boxstyle": "round,pad=0.5", "facecolor": facecolor, "edgecolor": "#d9e2ec", "linewidth": 0.8},
        transform=ax.transAxes,
    )


def write_figure_notes(manifest: dict) -> None:
    summary = select_manifest_summary(manifest)
    notes = f"""# Figure Notes

## Fig. 3

{FIG3_NOTE}

Main-text inclusion summary: {summary['included_cells']} included successful cells across the 8-document benchmark. Condition counts: B1={summary['condition_counts'].get('B1', 0)}, B2={summary['condition_counts'].get('B2', 0)}, B3={summary['condition_counts'].get('B3', 0)}, Full={summary['condition_counts'].get('Full', 0)}. Incomplete or failed cells are excluded rather than imputed. The timed-out `full_pipeline / deepseek_v4-pro / pea_cold_stress` run remains excluded.

## Fig. 4

{FIG4_NOTE}

Interpretation guide: `investigation` and `study` are top-level sheets and remain partly recoverable, whereas `observationunit`, `sample`, and `assay` require correct row binding and remain much weaker in the current run bundle.

## Supp. Fig. 1

This figure documents the main-text inclusion contract behind `Fig. 3` and `Fig. 4`: only successful evaluable cells from the current 8-document benchmark enter the aggregate quantitative comparisons. Current counts: total manifest cells={summary['total_cells']}, included={summary['included_cells']}, excluded={summary['excluded_cells']}, unsuccessful exclusions={summary['unsuccessful_exclusions']}, timed-out DeepSeek pea full-pipeline exclusion={summary['timeout_exclusions']}.

{SUPP_NOTE}
"""
    (MANUSCRIPT_DIR / "FIGURE_NOTES.md").write_text(notes, encoding="utf-8")


def fig3_condition_comparison(manifest: dict) -> None:
    """Main-text quantitative figure: row-aligned condition comparison."""
    apply_publication_style()
    points = select_main_result_points(manifest)
    summary = select_manifest_summary(manifest)
    by_condition: dict[str, list[dict]] = defaultdict(list)
    for row in points:
        by_condition[row["condition"]].append(row)

    fig, ax = plt.subplots(figsize=(8.2, 5.8))
    fig.subplots_adjust(top=0.8, bottom=0.24, left=0.1, right=0.98)
    positions = np.arange(1, len(CONDITION_ORDER) + 1)
    rng = np.random.default_rng(7)
    medians: dict[str, float] = {}

    for idx, cond in enumerate(CONDITION_ORDER, start=1):
        rows = by_condition.get(cond, [])
        vals = [r["metric_row_mean_score"] for r in rows]
        if not vals:
            continue

        bp = ax.boxplot(
            vals,
            positions=[idx],
            widths=0.5,
            patch_artist=True,
            showfliers=False,
            medianprops={"color": "#1f2933", "linewidth": 1.2},
            boxprops={"facecolor": CONDITION_COLORS[cond], "alpha": 0.32, "edgecolor": CONDITION_COLORS[cond], "linewidth": 1.0},
            whiskerprops={"color": CONDITION_COLORS[cond], "linewidth": 0.9},
            capprops={"color": CONDITION_COLORS[cond], "linewidth": 0.9},
        )
        jitter = rng.uniform(-0.16, 0.16, size=len(vals))
        ax.scatter(
            np.full(len(vals), idx) + jitter,
            vals,
            s=26,
            alpha=0.85,
            color=CONDITION_COLORS[cond],
            edgecolors="white",
            linewidth=0.5,
            zorder=3,
        )
        median = float(np.median(vals))
        medians[cond] = median
        ax.text(idx, median + 0.025, f"n={len(vals)}", ha="center", va="bottom", fontsize=7, color="#52606d")

    ax.set_xticks(positions)
    ax.set_xticklabels(CONDITION_ORDER)
    ax.set_ylabel("Row-aligned mean field score")
    ax.set_ylim(0, 1.0)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.grid(axis="y")
    fig.suptitle("Metadata quality across extraction conditions", x=0.47, y=0.96, fontsize=13)
    fig.text(
        0.1,
        0.885,
        "8-document main benchmark; each point is one successful included model x document cell from the latest completed runs",
        fontsize=8,
        color="#52606d",
    )

    if "B1" in medians:
        ax.annotate(
            "B1 currently has the\nstrongest overall distribution.",
            xy=(1, medians["B1"]),
            xytext=(0.55, 0.72),
            textcoords="axes fraction",
            arrowprops={"arrowstyle": "-", "color": "#52606d", "lw": 0.8},
            fontsize=7.5,
            color="#1f2933",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#d9e2ec", "linewidth": 0.8},
        )
    if "Full" in medians:
        ax.annotate(
            "Full includes only completed\nsuccessful runs; failures are excluded.",
            xy=(4, medians["Full"]),
            xytext=(0.68, 0.52),
            textcoords="axes fraction",
            arrowprops={"arrowstyle": "-", "color": "#52606d", "lw": 0.8},
            fontsize=7.5,
            color="#1f2933",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#d9e2ec", "linewidth": 0.8},
        )
    ax.text(
        0.98,
        0.97,
        (
            f"Included cells: {summary['included_cells']}\n"
            f"DeepSeek pea full timeout excluded: {summary['timeout_exclusions']}"
        ),
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=7.5,
        color="#52606d",
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "#f8fafc", "edgecolor": "#d9e2ec", "linewidth": 0.8},
    )

    _footnote(fig, FIG3_NOTE)

    fig.savefig(FIG_DIR / "fig3_condition_comparison.png")
    fig.savefig(FIG_DIR / "fig3_condition_comparison.pdf")
    plt.close(fig)


def fig4_isa_structure_heatmap(manifest: dict) -> None:
    """Main-text explanatory figure: ISA-sheet difficulty by condition."""
    apply_publication_style()
    agg: dict[tuple[str, str], list[float]] = defaultdict(list)

    # Use raw manifest rows here so condition is retained.
    agg_rows = [r for r in manifest.get("per_sheet_rows", []) if r.get("included_main_text")]
    for row in agg_rows:
        cond = row["condition"]
        display = {"baseline_b1": "B1", "baseline_b2": "B2", "baseline_b3": "B3", "full_pipeline": "Full"}.get(cond, cond)
        key = (row["sheet"], display)
        agg[key].append(row["metric_row_mean_score"])

    matrix = np.zeros((len(SHEET_ORDER), len(CONDITION_ORDER)))
    annot = [["" for _ in CONDITION_ORDER] for _ in SHEET_ORDER]
    for i, sheet in enumerate(SHEET_ORDER):
        for j, cond in enumerate(CONDITION_ORDER):
            vals = agg.get((sheet, cond), [])
            if vals:
                mean_val = sum(vals) / len(vals)
                matrix[i, j] = mean_val
                annot[i][j] = f"{mean_val:.2f}\n(n={len(vals)})"
            else:
                matrix[i, j] = np.nan
                annot[i][j] = "—"

    fig, ax = plt.subplots(figsize=(8.0, 5.8))
    fig.subplots_adjust(top=0.83, bottom=0.22, left=0.16, right=0.94)
    cmap = plt.cm.Blues.copy()
    cmap.set_bad(color="#f5f7fa")
    im = ax.imshow(matrix, cmap=cmap, aspect="auto", vmin=0.0, vmax=1.0)

    ax.set_xticks(range(len(CONDITION_ORDER)))
    ax.set_xticklabels(CONDITION_ORDER)
    ax.set_yticks(range(len(SHEET_ORDER)))
    ax.set_yticklabels([ISA_SHEET_LABELS[s] for s in SHEET_ORDER])
    fig.suptitle("Where structure is lost: ISA-layer score by condition", x=0.43, y=0.96, fontsize=13)
    fig.text(
        0.16,
        0.885,
        "Top-level metadata remains partly recoverable; row-preserving ISA structure is the main failure point",
        fontsize=8,
        color="#52606d",
    )

    for i in range(len(SHEET_ORDER)):
        for j in range(len(CONDITION_ORDER)):
            val = matrix[i, j]
            text_color = "#1f2933" if np.isnan(val) or val < 0.65 else "white"
            ax.text(j, i, annot[i][j], ha="center", va="center", fontsize=7, color=text_color)

    ax.text(
        4.45,
        0.55,
        "Higher-level sheets\npartly recoverable",
        fontsize=7.5,
        color="#1f2933",
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#d9e2ec", "linewidth": 0.8},
    )
    ax.text(
        4.45,
        3.6,
        "Row-level sheets stay weak\nacross all conditions",
        fontsize=7.5,
        color="#1f2933",
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#d9e2ec", "linewidth": 0.8},
    )

    cbar = fig.colorbar(im, ax=ax, shrink=0.88)
    cbar.set_label("Mean row-aligned score")
    cbar.ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))

    _footnote(fig, FIG4_NOTE)

    fig.savefig(FIG_DIR / "fig4_isa_structure_heatmap.png")
    fig.savefig(FIG_DIR / "fig4_isa_structure_heatmap.pdf")
    plt.close(fig)


def supp_fig1_manifest_coverage(manifest: dict) -> None:
    """Supplementary provenance figure for inclusion/exclusion rules."""
    apply_publication_style()
    summary = select_manifest_summary(manifest)

    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.8))
    fig.subplots_adjust(top=0.82, bottom=0.18, left=0.05, right=0.98, wspace=0.16)
    fig.suptitle("Supplementary provenance: main-text figure inclusion contract", x=0.43, y=0.96, fontsize=13)
    fig.text(
        0.05,
        0.885,
        "This figure documents how the current manifest is narrowed to the cells used in Fig. 3 and Fig. 4.",
        fontsize=8,
        color="#52606d",
    )

    for ax in axes:
        ax.axis("off")

    _note_block(
        axes[0],
        "Inclusion flow",
        [
            f"Manifest cells discovered: {summary['total_cells']}",
            "Scope contract: 8-document main benchmark only",
            "Keep only successful evaluable cells with metadata",
            (
                "Final main-text set: "
                f"{summary['included_cells']} cells "
                f"(B1={summary['condition_counts'].get('B1', 0)}, "
                f"B2={summary['condition_counts'].get('B2', 0)}, "
                f"B3={summary['condition_counts'].get('B3', 0)}, "
                f"Full={summary['condition_counts'].get('Full', 0)})"
            ),
        ],
    )
    _note_block(
        axes[1],
        "Exclusion summary",
        [
            f"Excluded from main-text aggregation: {summary['excluded_cells']} cells",
            f"Missing metadata / incomplete artifacts: {summary['exclusion_counts'].get('missing_metadata', 0)}",
            f"Unsuccessful runs: {summary['unsuccessful_exclusions']}",
            f"Timed-out DeepSeek pea full-pipeline run: {summary['timeout_exclusions']}",
            "Supplementary-only datasets (biorem, pomato, compbiobench) are excluded upstream from this main-benchmark manifest.",
        ],
        facecolor="#fffaf0",
    )

    _footnote(fig, SUPP_NOTE, y=0.05)

    fig.savefig(FIG_DIR / "supp_fig1_manifest_coverage.png")
    fig.savefig(FIG_DIR / "supp_fig1_manifest_coverage.pdf")
    plt.close(fig)


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    MANUSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    fig3_condition_comparison(manifest)
    fig4_isa_structure_heatmap(manifest)
    supp_fig1_manifest_coverage(manifest)
    write_figure_notes(manifest)
    print(f"[OK] wrote manuscript figures to {FIG_DIR}")


if __name__ == "__main__":
    main()
