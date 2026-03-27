#!/usr/bin/env python3
"""Generate slide/poster-ready presentation figures from curated FAIRiAgent results."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Patch


REPO_ROOT = Path(__file__).resolve().parents[2]
CURATED_JSON = (
    REPO_ROOT
    / "evaluation/harness/private/reports/presentation_curated_evidence_2026-03-26.json"
)
BRIEF_PATH = (
    REPO_ROOT
    / "development/UNLOCK_SCIENCE_MEETING_SLIDES_BRIEF_2026-03-26.md"
)
OUTPUT_DIR = (
    REPO_ROOT / "evaluation/harness/private/reports/presentation_figures_2026-03-26"
)


COLORS = {
    "peat": "#5A4636",
    "moss": "#5E8B5A",
    "teal": "#0F6B6D",
    "deep_teal": "#0B4043",
    "warm": "#F7F3EA",
    "amber": "#C98A2E",
    "mist": "#D9E6DE",
    "clay": "#A67952",
    "ink": "#16312F",
    "rose": "#9E5A59",
}


def _setup_theme() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": COLORS["warm"],
            "axes.facecolor": COLORS["warm"],
            "savefig.facecolor": COLORS["warm"],
            "axes.edgecolor": COLORS["deep_teal"],
            "axes.labelcolor": COLORS["ink"],
            "xtick.color": COLORS["ink"],
            "ytick.color": COLORS["ink"],
            "text.color": COLORS["ink"],
            "axes.titlecolor": COLORS["deep_teal"],
            "font.size": 11,
            "axes.titlesize": 20,
            "axes.labelsize": 12,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.fontsize": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": "#D7D1C5",
            "grid.alpha": 0.6,
            "grid.linestyle": "--",
            "axes.grid": True,
        }
    )


def _load_curated() -> Dict:
    return json.loads(CURATED_JSON.read_text(encoding="utf-8"))


def _pick_memory_aggregates() -> Path | None:
    candidates = [
        REPO_ROOT
        / "evaluation/harness/private/runs/memory_harness_local_qwen9b_earthworm_r2b/memory_harness_aggregates.csv",
        REPO_ROOT
        / "evaluation/harness/private/runs/memory_harness_phase1_live/memory_harness_aggregates.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _artifacts_by_id(curated: Dict) -> Dict[str, Dict]:
    items = {}
    for section in ("included_quantitative", "included_qualitative", "excluded"):
        for item in curated.get(section, []):
            items[item["artifact_id"]] = item
    return items


def _save(fig: plt.Figure, stem: str) -> List[str]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    png = OUTPUT_DIR / f"{stem}.png"
    svg = OUTPUT_DIR / f"{stem}.svg"
    fig.savefig(png, dpi=300, bbox_inches="tight")
    fig.savefig(svg, bbox_inches="tight")
    plt.close(fig)
    return [str(png), str(svg)]


def make_required_completeness_chart(artifacts: Dict[str, Dict], manifest: Dict) -> None:
    labels = ["Earthworm", "Biosensor", "Pomato"]
    baseline = [0.0, 0.0, 0.0]
    agentic = [
        artifacts["phase1_earthworm_agentic"]["required_completeness"],
        artifacts["phase1_biosensor_agentic"]["required_completeness"],
        artifacts["phase1_pomato_agentic"]["required_completeness"],
    ]

    x = np.arange(len(labels))
    width = 0.34
    fig, ax = plt.subplots(figsize=(13.33, 7.5))

    ax.bar(
        x - width / 2,
        baseline,
        width,
        label="Single-prompt baseline",
        color=COLORS["clay"],
        edgecolor=COLORS["peat"],
        linewidth=1.5,
        hatch="//",
        zorder=3,
    )
    ax.bar(
        x + width / 2,
        agentic,
        width,
        label="FAIRiAgent workflow",
        color=COLORS["teal"],
        edgecolor=COLORS["deep_teal"],
        linewidth=1.5,
        zorder=3,
    )

    for xi, value in zip(x + width / 2, agentic):
        ax.text(xi, value + 0.03, f"{value:.3f}", ha="center", va="bottom", fontweight="bold")
    for xi in x - width / 2:
        ax.text(xi, 0.03, "0.000", ha="center", va="bottom", color=COLORS["peat"])

    ax.set_ylim(0, 1.1)
    ax.set_ylabel("Required completeness")
    ax.set_title("Baseline vs FAIRiAgent on Required Metadata Coverage")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(frameon=False, ncol=2, loc="upper right")
    ax.text(
        0.01,
        0.98,
        "Same task, same model family, different harness",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=12,
        color=COLORS["deep_teal"],
        fontweight="bold",
    )
    ax.text(
        0.01,
        -0.16,
        "Source: Phase 1 current-branch evaluation on qwen-flash. Baseline fails to meet the FAIR curation target; "
        "FAIRiAgent reaches full required coverage on two paper-style cases and partially improves the hardest case.",
        transform=ax.transAxes,
        fontsize=10,
        color=COLORS["peat"],
    )

    manifest["fig01_required_completeness"] = {
        "title": "Baseline vs agentic required completeness",
        "files": _save(fig, "fig01_required_completeness_grouped"),
        "supports_slide": 12,
    }


def make_phase1_dashboard(artifacts: Dict[str, Dict], manifest: Dict) -> None:
    baseline = artifacts["phase1_baseline_qwenflash_aggregate"]
    agentic = artifacts["phase1_agentic_qwenflash_aggregate"]
    metrics = ["Aggregate score", "Completeness", "Correctness F1", "Schema"]
    base_vals = [
        baseline["aggregate_score"],
        baseline["overall_completeness"],
        baseline["correctness_f1"],
        baseline["schema_compliance"],
    ]
    agent_vals = [
        agentic["aggregate_score"],
        agentic["overall_completeness"],
        agentic["correctness_f1"],
        agentic["schema_compliance"],
    ]

    fig = plt.figure(figsize=(13.33, 7.5))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.4, 1.0], wspace=0.28)
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])

    y = np.arange(len(metrics))
    ax1.barh(y + 0.18, agent_vals, height=0.32, color=COLORS["teal"], label="FAIRiAgent", zorder=3)
    ax1.barh(y - 0.18, base_vals, height=0.32, color=COLORS["clay"], label="Baseline", zorder=3)
    ax1.set_yticks(y)
    ax1.set_yticklabels(metrics)
    ax1.set_xlim(0, 1.05)
    ax1.invert_yaxis()
    ax1.set_title("Phase 1 Quality Gap")
    ax1.legend(frameon=False, loc="lower right")
    for yi, v in zip(y + 0.18, agent_vals):
        ax1.text(v + 0.02, yi, f"{v:.3f}", va="center", fontweight="bold")
    for yi, v in zip(y - 0.18, base_vals):
        ax1.text(v + 0.02, yi, f"{v:.3f}", va="center", color=COLORS["peat"])

    runtime_vals = [18.5, 161.9]
    bars = ax2.bar(
        ["Baseline", "FAIRiAgent"],
        runtime_vals,
        color=[COLORS["clay"], COLORS["teal"]],
        edgecolor=[COLORS["peat"], COLORS["deep_teal"]],
        linewidth=1.5,
        zorder=3,
    )
    ax2.set_title("Runtime Trade-off")
    ax2.set_ylabel("Mean runtime (seconds)")
    for bar, value in zip(bars, runtime_vals):
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            value + 6,
            f"{value:.1f}s",
            ha="center",
            fontweight="bold",
        )

    fig.suptitle("FAIRiAgent Trades Speed for Measurably Better Curation Quality", y=0.98, fontsize=22, color=COLORS["deep_teal"])
    fig.text(
        0.07,
        0.05,
        "Phase 1 aggregate: score improves 0.067 → 0.633, while schema compliance rises 0.600 → 0.933. "
        "The workflow is slower because it reads, retrieves, critiques, retries, and validates rather than answering in one shot.",
        fontsize=10.5,
        color=COLORS["peat"],
    )

    manifest["fig02_phase1_dashboard"] = {
        "title": "Phase 1 quality and runtime dashboard",
        "files": _save(fig, "fig02_phase1_quality_runtime_dashboard"),
        "supports_slide": 12,
    }


def make_isa_heatmap(manifest: Dict) -> None:
    docs = ["Earthworm", "Biosensor", "Pomato"]
    sheets = ["Investigation", "Study", "Assay", "Sample", "Observation Unit"]
    values = np.array(
        [
            [0.889, 0.750, 0.600, 0.889, 1.000],
            [0.875, 0.750, 0.846, 0.571, 1.000],
            [0.111, 0.500, np.nan, 0.212, 0.031],
        ]
    )

    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    cmap = plt.cm.YlGnBu.copy()
    cmap.set_bad(color="#EFE7D8")
    im = ax.imshow(values, cmap=cmap, vmin=0, vmax=1, aspect="auto")

    ax.set_xticks(np.arange(len(sheets)))
    ax.set_xticklabels(sheets)
    ax.set_yticks(np.arange(len(docs)))
    ax.set_yticklabels(docs)
    ax.set_title("Where Hard Documents Still Break Down Across ISA Levels")

    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            text = "No data" if np.isnan(values[i, j]) else f"{values[i, j]:.3f}"
            color = COLORS["peat"] if np.isnan(values[i, j]) or values[i, j] < 0.55 else "white"
            ax.text(j, i, text, ha="center", va="center", fontsize=11, color=color, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, shrink=0.9)
    cbar.set_label("Completeness by ISA level")
    legend_handles = [
        Patch(facecolor="#EFE7D8", edgecolor=COLORS["peat"], label="No data / sheet absent"),
        Patch(facecolor=cmap(0.85), edgecolor="none", label="High coverage"),
        Patch(facecolor=cmap(0.35), edgecolor="none", label="Low coverage"),
    ]
    ax.legend(handles=legend_handles, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=3)
    fig.text(
        0.07,
        0.04,
        "Values follow the slide brief: earthworm and biosensor are already strong across most ISA sheets, "
        "while pomato remains weak especially for investigation, sample, and observation-unit context.",
        fontsize=10.5,
        color=COLORS["peat"],
    )

    manifest["fig03_isa_heatmap"] = {
        "title": "ISA-level heatmap for hard-case honesty slide",
        "files": _save(fig, "fig03_isa_heatmap"),
        "supports_slide": 13,
    }


def make_pomato_frontier_tradeoff(artifacts: Dict[str, Dict], manifest: Dict) -> None:
    points = [
        {
            "label": "Qwen Max",
            "runtime": artifacts["phase2_pomato_qwen_max"]["runtime_seconds"],
            "required": artifacts["phase2_pomato_qwen_max"]["required_completeness"],
            "fields": artifacts["phase2_pomato_qwen_max"]["total_fields"],
            "confidence": artifacts["phase2_pomato_qwen_max"]["overall_confidence"],
            "color": COLORS["teal"],
            "marker": "o",
        },
        {
            "label": "GPT-5.4",
            "runtime": artifacts["phase2_pomato_gpt54"]["runtime_seconds"],
            "required": artifacts["phase2_pomato_gpt54"]["required_completeness"],
            "fields": artifacts["phase2_pomato_gpt54"]["total_fields"],
            "confidence": artifacts["phase2_pomato_gpt54"]["overall_confidence"],
            "color": COLORS["amber"],
            "marker": "s",
        },
        {
            "label": "Qwen3.5 35B (local)",
            "runtime": 522.8,
            "required": np.nan,
            "fields": 74,
            "confidence": 0.7718,
            "color": COLORS["moss"],
            "marker": "^",
        },
        {
            "label": "Qwen3.5 9B (local)",
            "runtime": 209.1,
            "required": np.nan,
            "fields": 46,
            "confidence": 0.8560,
            "color": COLORS["rose"],
            "marker": "D",
        },
    ]

    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    for point in points:
        y = point["required"] if not np.isnan(point["required"]) else 0.12
        alpha = 0.95 if not np.isnan(point["required"]) else 0.65
        ax.scatter(
            point["runtime"],
            y,
            s=point["fields"] * 9,
            color=point["color"],
            alpha=alpha,
            marker=point["marker"],
            edgecolor=COLORS["deep_teal"],
            linewidth=1.3,
            zorder=4,
        )
        label = (
            f"{point['label']}\nfields={point['fields']} | conf={point['confidence']:.3f}"
            if not np.isnan(point["required"])
            else f"{point['label']}\nworkflow-only evidence"
        )
        ax.text(point["runtime"] + 12, y + 0.015, label, fontsize=10, va="center")

    ax.set_xlim(150, 580)
    ax.set_ylim(0, 0.5)
    ax.set_xlabel("Runtime (seconds)")
    ax.set_ylabel("Required completeness on pomato")
    ax.set_title("Pomato Exposes a Real Coverage vs Stability vs Speed Trade-off")
    ax.axhline(0.315, color=COLORS["clay"], linestyle="--", linewidth=1.5, label="Phase 1 qwen-flash agentic baseline")
    legend_handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=COLORS["teal"], markeredgecolor=COLORS["deep_teal"], markersize=10, label="API model"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor=COLORS["moss"], markeredgecolor=COLORS["deep_teal"], markersize=10, label="Local model"),
        Patch(facecolor=COLORS["warm"], edgecolor="none", label="Bubble size = total fields"),
        Line2D([0], [0], color=COLORS["clay"], linestyle="--", label="Current branch Phase 1 reference"),
    ]
    ax.legend(handles=legend_handles, frameon=False, loc="upper left")
    fig.text(
        0.07,
        0.05,
        "Only the API runs have ground-truth-scored required completeness. Local runs remain useful as engineering evidence "
        "for reproducible demos, but should be presented separately from the main quantitative comparison.",
        fontsize=10.5,
        color=COLORS["peat"],
    )

    manifest["fig04_pomato_tradeoff"] = {
        "title": "Pomato frontier model trade-off chart",
        "files": _save(fig, "fig04_pomato_frontier_tradeoff"),
        "supports_slide": 13,
    }


def make_traceability_stack(manifest: Dict) -> None:
    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    items = [
        ("metadata_json.json", "Structured FAIR/ISA-linked output", COLORS["teal"]),
        ("workflow_report.json", "Execution summary, quality metrics, retries, timeline", COLORS["moss"]),
        ("processing_log.jsonl", "Stepwise machine-readable events", COLORS["amber"]),
        ("llm_responses.json", "Model outputs captured for inspection", COLORS["clay"]),
        ("runtime_config.json", "Run configuration and environment snapshot", COLORS["rose"]),
        ("optional traces", "LangSmith / Langfuse observability when enabled", COLORS["deep_teal"]),
    ]

    y_positions = np.linspace(0.82, 0.17, len(items))
    for (name, desc, color), y in zip(items, y_positions):
        box = FancyBboxPatch(
            (0.08, y - 0.055),
            0.84,
            0.09,
            boxstyle="round,pad=0.015,rounding_size=0.02",
            linewidth=1.5,
            edgecolor=COLORS["deep_teal"],
            facecolor=color,
            alpha=0.88,
        )
        ax.add_patch(box)
        ax.text(0.11, y + 0.01, name, fontsize=14, color="white", fontweight="bold", va="center")
        ax.text(0.11, y - 0.022, desc, fontsize=11, color="white", va="center")

    ax.text(
        0.08,
        0.95,
        "Every FAIRiAgent run leaves an auditable artifact trail",
        fontsize=22,
        color=COLORS["deep_teal"],
        fontweight="bold",
    )
    ax.text(
        0.08,
        0.08,
        "Recommended example run for screenshots or callouts: "
        "presentation_phase2_pomato_api_trio_r1 / qwen_max / pomato / run_1",
        fontsize=10.5,
        color=COLORS["peat"],
    )

    manifest["fig05_traceability_stack"] = {
        "title": "Traceability artifact stack",
        "files": _save(fig, "fig05_traceability_stack"),
        "supports_slide": 14,
    }


def make_historical_benchmark_chart(artifacts: Dict[str, Dict], manifest: Dict) -> None:
    rows = [
        artifacts["legacy_qwen_max_agentic_aggregate"],
        artifacts["legacy_gpt51_baseline_aggregate"],
    ]
    labels = ["qwen_max\nagentic", "gpt-5.1\nbaseline"]
    success = [rows[0]["success_rate"], rows[1]["success_rate"]]
    coverage = [rows[0]["mandatory_coverage"], rows[1]["mandatory_coverage"]]
    x = np.arange(len(labels))
    width = 0.34

    fig, ax = plt.subplots(figsize=(12.5, 7.0))
    ax.bar(x - width / 2, success, width=width, label="Success rate", color=COLORS["teal"], zorder=3)
    ax.bar(x + width / 2, coverage, width=width, label="Mandatory coverage", color=COLORS["amber"], zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Score")
    ax.set_title("Historical Benchmark: Workflow Design Changes the Ceiling")
    for xi, v in zip(x - width / 2, success):
        ax.text(xi, v + 0.03, f"{v:.2f}", ha="center", fontweight="bold")
    for xi, v in zip(x + width / 2, coverage):
        ax.text(xi, v + 0.03, f"{v:.2f}", ha="center", fontweight="bold")
    ax.legend(frameon=False, loc="upper right")
    fig.text(
        0.07,
        0.05,
        "Use as secondary support only. The workflow versions differ from the current branch, but the historical campaign still shows the same structural lesson: "
        "one-shot prompting underperforms iterative, FAIR-aware workflows on publication-ready metadata tasks.",
        fontsize=10.5,
        color=COLORS["peat"],
    )

    manifest["fig07_historical_benchmark"] = {
        "title": "Historical benchmark support figure",
        "files": _save(fig, "fig07_historical_benchmark"),
        "supports_slide": None,
    }


def make_local_model_ladder(manifest: Dict) -> None:
    models = ["qwen3.5:9b", "qwen3.5:35b", "qwen3.5 historic"]
    runtime = [209.1, 522.8, 171.3]
    fields = [46, 74, 80]
    confidence = [0.8560, 0.7718, 0.8530]
    colors = [COLORS["rose"], COLORS["moss"], COLORS["teal"]]

    fig, ax1 = plt.subplots(figsize=(13.33, 7.5))
    x = np.arange(len(models))
    bars = ax1.bar(x, runtime, color=colors, edgecolor=COLORS["deep_teal"], linewidth=1.3, zorder=3)
    ax1.set_ylabel("Runtime (seconds)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(models)
    ax1.set_title("Local Model Ladder on Pomato: Speed, Coverage, and Review Burden")

    ax2 = ax1.twinx()
    ax2.plot(x, fields, color=COLORS["amber"], marker="o", linewidth=2.5, label="Total fields", zorder=4)
    ax2.plot(x, confidence, color=COLORS["deep_teal"], marker="D", linewidth=2.0, label="Overall confidence", zorder=4)
    ax2.set_ylabel("Fields / confidence")
    ax2.set_ylim(0, max(fields) * 1.25)

    for bar, rt in zip(bars, runtime):
        ax1.text(bar.get_x() + bar.get_width() / 2, rt + 12, f"{rt:.0f}s", ha="center", fontweight="bold")
    for xi, f in zip(x, fields):
        ax2.text(xi, f + 3, f"{f}", ha="center", color=COLORS["amber"], fontweight="bold")

    legend_handles = [
        Patch(facecolor=COLORS["rose"], edgecolor=COLORS["deep_teal"], label="9B runtime"),
        Patch(facecolor=COLORS["moss"], edgecolor=COLORS["deep_teal"], label="35B runtime"),
        Patch(facecolor=COLORS["teal"], edgecolor=COLORS["deep_teal"], label="historic qwen3.5 runtime"),
        Line2D([0], [0], color=COLORS["amber"], marker="o", linewidth=2.5, label="Total fields"),
        Line2D([0], [0], color=COLORS["deep_teal"], marker="D", linewidth=2.0, label="Overall confidence"),
    ]
    ax1.legend(handles=legend_handles, frameon=False, loc="upper left")
    fig.text(
        0.07,
        0.05,
        "These are not all directly ground-truth-scored under the latest harness. Use them to show that local models are viable for reproducible demos, "
        "but trade speed, field breadth, and output cleanliness differently on the hardest case.",
        fontsize=10.5,
        color=COLORS["peat"],
    )

    manifest["fig08_local_model_ladder"] = {
        "title": "Local model comparison on pomato",
        "files": _save(fig, "fig08_local_model_ladder"),
        "supports_slide": None,
    }


def make_memory_chart_if_available(manifest: Dict) -> None:
    memory_aggregates = _pick_memory_aggregates()
    if memory_aggregates is None:
        manifest["fig06_memory_effects"] = {
            "title": "Memory harness panel",
            "status": "pending",
            "note": "memory_harness_aggregates.csv not yet available",
            "supports_slide": None,
        }
        return

    rows = list(csv.DictReader(memory_aggregates.read_text(encoding="utf-8").splitlines()))
    # Focus on qwen-flash first if present.
    candidates = [row for row in rows if row["config_name"] in {"presentation_qwen_flash", "local_memory_qwen35_9b"}]
    if not candidates:
        candidates = rows
    docs = []
    for row in candidates:
        if row["document_id"] not in docs:
            docs.append(row["document_id"])
    modes = ["stateless", "fresh_mem0", "shared_mem0"]

    runtime_map = {(r["document_id"], r["mode"]): float(r["mean_runtime_seconds"]) for r in candidates}
    conf_map = {(r["document_id"], r["mode"]): float(r["mean_overall_confidence"]) for r in candidates}

    fig, axes = plt.subplots(1, 2, figsize=(13.33, 7.5), constrained_layout=True)
    x = np.arange(len(docs))
    width = 0.24
    palette = [COLORS["clay"], COLORS["amber"], COLORS["teal"]]
    labels = ["Stateless", "Fresh mem0", "Shared mem0"]

    for idx, mode in enumerate(modes):
        vals = [runtime_map.get((doc, mode), np.nan) for doc in docs]
        axes[0].bar(x + (idx - 1) * width, vals, width=width, color=palette[idx], label=labels[idx], zorder=3)
        vals2 = [conf_map.get((doc, mode), np.nan) for doc in docs]
        axes[1].bar(x + (idx - 1) * width, vals2, width=width, color=palette[idx], label=labels[idx], zorder=3)

    axes[0].set_title("Memory effect on runtime")
    axes[0].set_ylabel("Mean runtime (seconds)")
    axes[1].set_title("Memory effect on overall confidence")
    axes[1].set_ylabel("Mean overall confidence")
    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels([doc.replace("_4n_paper_biorxiv", "").replace("_", " ").title() for doc in docs])
        ax.legend(frameon=False)
    fig.suptitle("Mem0 Benchmark: Stateless vs Within-run vs Persistent Memory", fontsize=22, color=COLORS["deep_teal"])

    manifest["fig06_memory_effects"] = {
        "title": "Memory harness effects chart",
        "files": _save(fig, "fig06_memory_effects"),
        "source": str(memory_aggregates),
        "supports_slide": None,
    }


def write_supporting_files(manifest: Dict) -> None:
    chart_data = {
        "generated_at": datetime.now().isoformat(),
        "source_brief": str(BRIEF_PATH),
        "source_curated_evidence": str(CURATED_JSON),
        "figures": manifest,
    }
    (OUTPUT_DIR / "presentation_chart_manifest.json").write_text(
        json.dumps(chart_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    md_lines = [
        "# Presentation Figure Index",
        "",
        "These figures were generated from the curated presentation evidence set and the current UNLOCK slides brief.",
        "",
        f"- Source brief: `{BRIEF_PATH}`",
        f"- Source curated evidence: `{CURATED_JSON}`",
        "",
        "## Figures",
        "",
    ]
    for key, item in manifest.items():
        md_lines.append(f"### {key}")
        md_lines.append("")
        md_lines.append(f"- Title: {item['title']}")
        if "supports_slide" in item and item["supports_slide"]:
            md_lines.append(f"- Slide: {item['supports_slide']}")
        if item.get("status") == "pending":
            md_lines.append(f"- Status: pending")
            md_lines.append(f"- Note: {item['note']}")
        else:
            for file in item["files"]:
                md_lines.append(f"- File: `{file}`")
        md_lines.append("")

    (OUTPUT_DIR / "FIGURE_INDEX.md").write_text("\n".join(md_lines), encoding="utf-8")


def main() -> None:
    _setup_theme()
    curated = _load_curated()
    artifacts = _artifacts_by_id(curated)
    manifest: Dict = {}
    make_required_completeness_chart(artifacts, manifest)
    make_phase1_dashboard(artifacts, manifest)
    make_isa_heatmap(manifest)
    make_pomato_frontier_tradeoff(artifacts, manifest)
    make_traceability_stack(manifest)
    make_historical_benchmark_chart(artifacts, manifest)
    make_local_model_ladder(manifest)
    make_memory_chart_if_available(manifest)
    write_supporting_files(manifest)
    print(f"Generated figures in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
