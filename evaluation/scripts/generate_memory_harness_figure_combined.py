#!/usr/bin/env python3
"""Generate slide-ready memory harness figures from the combined benchmark."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_ROOT = (
    REPO_ROOT
    / "evaluation/harness/private/runs/memory_harness_local_earthworm_9b_27b_35b_nemotron_r3_md_only"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "evaluation/harness/private/reports/presentation_memory_figures_2026-03-27_md_only"
)

COLORS = {
    "stateless": "#C56B3C",
    "fresh_mem0": "#2A9D8F",
    "shared_mem0": "#264653",
    "text": "#20313B",
    "grid": "#D8D2C7",
    "bg": "#FCFBF7",
    "accent": "#B23A48",
    "muted": "#6C757D",
}

MODE_LABELS = {
    "stateless": "Stateless",
    "fresh_mem0": "Fresh mem0",
    "shared_mem0": "Shared mem0",
}
MODE_ORDER = ["stateless", "fresh_mem0", "shared_mem0"]
MODEL_ORDER = ["Qwen3.5 9B", "Qwen3.5 35B", "Qwen3.5 27B", "Nemotron-3 Nano"]


def _setup_style() -> None:
    sns.set_theme(style="whitegrid")
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update(
        {
            "figure.facecolor": COLORS["bg"],
            "axes.facecolor": COLORS["bg"],
            "axes.edgecolor": "#A69F94",
            "axes.labelcolor": COLORS["text"],
            "xtick.color": COLORS["text"],
            "ytick.color": COLORS["text"],
            "text.color": COLORS["text"],
            "grid.color": COLORS["grid"],
            "font.size": 11,
            "axes.titlesize": 15,
            "axes.labelsize": 12,
            "legend.fontsize": 11,
        }
    )


def load_data(agg_csv: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    agg = pd.read_csv(agg_csv)
    agg["mode_order"] = agg["mode"].map({m: i for i, m in enumerate(MODE_ORDER)})
    agg["model_order"] = agg["model_label"].map(
        lambda label: MODEL_ORDER.index(label) if label in MODEL_ORDER else len(MODE_ORDER)
    )
    agg = agg.sort_values(["model_order", "mode_order"]).reset_index(drop=True)

    delta_rows = []
    for model, group in agg.groupby("model_label"):
        base = group[group["mode"] == "stateless"].iloc[0]
        for _, row in group.iterrows():
            if row["mode"] == "stateless":
                continue
            delta_rows.append(
                {
                    "model_label": model,
                    "mode": row["mode"],
                    "mode_label": MODE_LABELS[row["mode"]],
                    "input_sources": row["input_sources"],
                    "runs": int(row["runs"]),
                    "runtime_speedup_pct": (base["mean_runtime_seconds"] - row["mean_runtime_seconds"])
                    / base["mean_runtime_seconds"]
                    * 100.0,
                    "field_delta": row["mean_total_fields"] - base["mean_total_fields"],
                    "confidence_delta_pp": (row["mean_overall_confidence"] - base["mean_overall_confidence"])
                    * 100.0,
                }
            )

    delta = pd.DataFrame(delta_rows)
    delta["model_order"] = delta["model_label"].map(
        lambda label: MODEL_ORDER.index(label) if label in MODEL_ORDER else len(MODEL_ORDER)
    )
    delta["mode_order"] = delta["mode"].map({"fresh_mem0": 0, "shared_mem0": 1})
    delta = delta.sort_values(["model_order", "mode_order"]).reset_index(drop=True)
    return agg, delta


def _input_source_note(agg: pd.DataFrame) -> str:
    sources = sorted(
        {
            source.strip()
            for item in agg["input_sources"].dropna()
            for source in str(item).split(",")
            if source.strip()
        }
    )
    if sources == ["preconverted_markdown"]:
        return (
            "All compared runs use the same preconverted MinerU Markdown input, "
            "so runtime differences are directly comparable within this benchmark."
        )
    if len(sources) == 1:
        return f"All compared runs use the same input source: {sources[0]}."
    return (
        "Input sources are mixed across merged runs, so the delta view is more reliable than raw "
        "cross-model runtime comparison."
    )


def _style_axis(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#A69F94")
    ax.spines["bottom"].set_color("#A69F94")
    ax.grid(axis="x", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)


def make_delta_figure(delta: pd.DataFrame, agg: pd.DataFrame) -> plt.Figure:
    fig = plt.figure(figsize=(16, 10), facecolor=COLORS["bg"])
    gs = fig.add_gridspec(2, 2, width_ratios=[1.1, 1.1], height_ratios=[1.0, 1.0], wspace=0.18, hspace=0.24)

    fig.suptitle(
        "Does the memory system work?\nYes in some models, but the benefit is strongly model-dependent.",
        fontsize=22,
        fontweight="bold",
        color=COLORS["text"],
        y=0.98,
    )

    metrics = [
        ("runtime_speedup_pct", "A. Runtime improvement vs stateless", "Speedup (%)", True),
        ("field_delta", "B. Field-count change vs stateless", "Delta fields", False),
        ("confidence_delta_pp", "C. Confidence change vs stateless", "Delta confidence (pp)", False),
    ]

    y_base = np.arange(len(MODEL_ORDER))
    offsets = {"fresh_mem0": -0.16, "shared_mem0": 0.16}
    bar_height = 0.28

    for idx, (metric, title, xlabel, positive_is_good) in enumerate(metrics):
        ax = fig.add_subplot(gs[idx // 2, idx % 2])
        _style_axis(ax)
        ax.axvline(0, color="#888888", linewidth=1.0)
        for mode in ["fresh_mem0", "shared_mem0"]:
            subset = delta[delta["mode"] == mode]
            vals = []
            for model in MODEL_ORDER:
                row = subset[subset["model_label"] == model]
                vals.append(float(row.iloc[0][metric]) if not row.empty else np.nan)
            ypos = y_base + offsets[mode]
            bars = ax.barh(
                ypos,
                vals,
                height=bar_height,
                color=COLORS[mode],
                label=MODE_LABELS[mode],
            )
            for bar, val in zip(bars, vals):
                if np.isnan(val):
                    continue
                pad = 0.5 if metric == "runtime_speedup_pct" else 0.35
                x = val + pad if val >= 0 else val - pad
                ha = "left" if val >= 0 else "right"
                fmt = "{:+.1f}%"
                if metric == "field_delta":
                    fmt = "{:+.1f}"
                elif metric == "confidence_delta_pp":
                    fmt = "{:+.1f}pp"
                ax.text(x, bar.get_y() + bar.get_height() / 2, fmt.format(val), va="center", ha=ha, fontsize=10)
        ax.set_yticks(y_base)
        ax.set_yticklabels(MODEL_ORDER)
        ax.invert_yaxis()
        ax.set_title(title, loc="left")
        ax.set_xlabel(xlabel)
        if positive_is_good:
            ax.text(0.99, 1.02, "positive = faster", transform=ax.transAxes, ha="right", va="bottom", fontsize=10, color=COLORS["muted"])
        else:
            ax.text(0.99, 1.02, "positive = more metadata / confidence", transform=ax.transAxes, ha="right", va="bottom", fontsize=10, color=COLORS["muted"])
        if idx == 0:
            ax.legend(frameon=False, loc="lower right")

    ax_note = fig.add_subplot(gs[1, 1])
    ax_note.axis("off")
    note = (
        "Slide takeaway\n\n"
        "Qwen3.5 9B\n"
        "- clearest positive memory signal\n"
        "- fresh mem0: faster, broader output, fewer retries\n"
        "- shared mem0: best confidence\n\n"
        "Qwen3.5 35B\n"
        "- memory mostly helps runtime\n"
        "- quality uplift is weak or inconsistent\n\n"
        "Qwen3.5 27B\n"
        "- memory broadened output breadth\n"
        "- but it was slower and less confident\n"
        "- not a net positive in this run\n\n"
        "Nemotron-3 Nano\n"
        "- clear positive memory signal\n"
        "- fresh mem0: faster and much more confident\n"
        "- shared mem0: still faster and more confident"
    )
    ax_note.text(
        0.0,
        1.0,
        note,
        va="top",
        ha="left",
        fontsize=12,
        linespacing=1.45,
        bbox=dict(boxstyle="round,pad=0.75", facecolor="#F3EEE4", edgecolor="#D3C8B6"),
    )

    fig.text(
        0.01,
        0.015,
        "Deltas are computed within each model relative to its own stateless baseline. "
        + _input_source_note(agg),
        fontsize=10.5,
        color="#635E56",
    )
    return fig


def make_absolute_figure(agg: pd.DataFrame) -> plt.Figure:
    fig, axes = plt.subplots(1, 3, figsize=(17, 6.8), facecolor=COLORS["bg"], constrained_layout=True)
    metrics = [
        ("mean_runtime_seconds", "Runtime", "Seconds"),
        ("mean_total_fields", "Metadata breadth", "Fields"),
        ("mean_overall_confidence", "Overall confidence", "Confidence"),
    ]
    x = np.arange(len(MODEL_ORDER))
    width = 0.22

    for ax, (metric, title, ylabel) in zip(axes, metrics):
        _style_axis(ax)
        for idx, mode in enumerate(MODE_ORDER):
            subset = agg[agg["mode"] == mode]
            vals = []
            for model in MODEL_ORDER:
                row = subset[subset["model_label"] == model]
                vals.append(float(row.iloc[0][metric]) if not row.empty else np.nan)
            bars = ax.bar(
                x + (idx - 1) * width,
                vals,
                width=width,
                color=COLORS[mode],
                label=MODE_LABELS[mode],
            )
            for bar, val in zip(bars, vals):
                if np.isnan(val):
                    continue
                fmt = "{:.0f}"
                dy = 5
                if metric == "mean_total_fields":
                    fmt = "{:.1f}"
                    dy = 0.6
                if metric == "mean_overall_confidence":
                    fmt = "{:.2f}"
                    dy = 0.01
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + dy, fmt.format(val), ha="center", va="bottom", fontsize=9)
        ax.set_title(title, loc="left")
        ax.set_xticks(x)
        ax.set_xticklabels(["Qwen\n9B", "Qwen\n35B", "Qwen\n27B", "Nemotron\nNano"])
        ax.set_ylabel(ylabel)
        if metric == "mean_overall_confidence":
            ax.set_ylim(0.72, 0.94)

    axes[0].legend(frameon=False, loc="upper right")
    fig.suptitle(
        "Absolute view: memory does not dominate model behavior",
        fontsize=19,
        fontweight="bold",
        color=COLORS["text"],
    )
    fig.text(
        0.01,
        0.01,
        "Use this as a backup slide. The delta figure is better for answering 'does memory work?', while this one shows the absolute trade-off landscape. "
        + _input_source_note(agg),
        fontsize=10.5,
        color="#635E56",
    )
    return fig


def write_report(agg: pd.DataFrame, delta: pd.DataFrame, agg_csv: Path, out_dir: Path) -> None:
    report_path = out_dir / "MEMORY_FINDINGS_REPORT.md"
    delta_lines = []
    for model in MODEL_ORDER:
        sub = delta[delta["model_label"] == model]
        delta_lines.append(f"### {model}")
        delta_lines.append("")
        for _, row in sub.iterrows():
            delta_lines.append(
                f"- {MODE_LABELS[row['mode']]} vs stateless: "
                f"runtime `{row['runtime_speedup_pct']:+.1f}%`, "
                f"fields `{row['field_delta']:+.1f}`, "
                f"confidence `{row['confidence_delta_pp']:+.1f}pp`."
            )
        delta_lines.append("")

    report = [
        "# Memory Findings Report",
        "",
        f"- Generated at: `{datetime.now().isoformat()}`",
        f"- Aggregate source: `{agg_csv.relative_to(REPO_ROOT)}`",
        "",
        "## Bottom line",
        "",
        "The current evidence says the memory system can work, but the benefit is strongly model-dependent.",
        "",
        "- Strongest overall positive case: `Qwen3.5 9B`.",
        "- Another clear positive case: `Nemotron-3 Nano`, especially `fresh_mem0`.",
        "- Efficiency-first effect: `Qwen3.5 35B` gets large runtime gains, but quality gains are weak.",
        "- Trade-off case: `Qwen3.5 27B` produces more fields with memory, but becomes slower and less confident.",
        "",
        "## Interpretation",
        "",
        "Memory is better framed as a harness component that can preserve useful workflow context and reduce repeated work, but its value depends on the model using it.",
        "",
        "- It can reduce repeated work and retries.",
        "- It can produce clear quality gains on some smaller or weaker local models.",
        "- It does not guarantee better metadata quality on every model.",
        "- Some models mainly convert memory into efficiency gains.",
        "- Some models show a breadth-versus-confidence trade-off rather than a pure win.",
        "",
        "## Per-model evidence",
        "",
        *delta_lines,
        "## Slide wording",
        "",
        "Recommended sentence:",
        "",
        "> In our current harness, memory can help, but the effect is strongly model-dependent. We see clear wins on Qwen3.5 9B and Nemotron-3 Nano, mostly efficiency gains on Qwen3.5 35B, and a trade-off rather than a net win on Qwen3.5 27B.",
        "",
        "## Caveats",
        "",
        f"- {_input_source_note(agg)}",
        "- New models currently have `n=1` per mode; historical `9B/35B` have `n=2` per mode.",
        "- `Nemotron-3 Nano / fresh_mem0` completed successfully but logged one malformed Critic response before fallback acceptance.",
    ]
    report_path.write_text("\n".join(report), encoding="utf-8")

    summary = {
        "generated_from": str(agg_csv.relative_to(REPO_ROOT)),
        "figure_files": [
            "fig_memory_answer_deltas.png",
            "fig_memory_absolute_overview.png",
            "fig_memory_answer_deltas.svg",
            "fig_memory_absolute_overview.svg",
        ],
        "headline": "Memory can help, but the benefit is strongly model-dependent; the clearest wins are Qwen3.5 9B and Nemotron-3 Nano.",
        "best_case": "Qwen3.5 9B and Nemotron-3 Nano",
        "warning": "Do not oversell memory as a universal quality booster.",
    }
    (out_dir / "memory_figure_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "README.md").write_text(
        "# Combined Memory Figure Pack\n\n"
        "- Main answer figure: `fig_memory_answer_deltas.png`\n"
        "- Absolute backup figure: `fig_memory_absolute_overview.png`\n"
        "- Explanatory report: `MEMORY_FINDINGS_REPORT.md`\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=DEFAULT_RUN_ROOT,
        help="Combined run root containing memory_harness_aggregates.csv",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Output directory for figures and report",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_root = args.run_root.resolve()
    out_dir = args.out_dir.resolve()
    agg_csv = run_root / "memory_harness_aggregates.csv"

    out_dir.mkdir(parents=True, exist_ok=True)
    _setup_style()
    agg, delta = load_data(agg_csv)

    fig1 = make_delta_figure(delta, agg)
    fig1.savefig(out_dir / "fig_memory_answer_deltas.png", dpi=220, bbox_inches="tight")
    fig1.savefig(out_dir / "fig_memory_answer_deltas.svg", bbox_inches="tight")
    plt.close(fig1)

    fig2 = make_absolute_figure(agg)
    fig2.savefig(out_dir / "fig_memory_absolute_overview.png", dpi=220, bbox_inches="tight")
    fig2.savefig(out_dir / "fig_memory_absolute_overview.svg", bbox_inches="tight")
    plt.close(fig2)

    write_report(agg, delta, agg_csv, out_dir)
    print(f"Wrote combined memory figure pack to {out_dir}")


if __name__ == "__main__":
    main()
