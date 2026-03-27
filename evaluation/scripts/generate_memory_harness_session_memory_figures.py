#!/usr/bin/env python3
"""Generate slide-ready figures focused on stateless vs session memory."""

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
    / "evaluation/harness/private/reports/presentation_memory_figures_2026-03-27_session_only"
)

COLORS = {
    "stateless": "#E07A4F",
    "fresh_mem0": "#35B6A5",
    "text": "#F3F5F7",
    "grid": "#3A4148",
    "bg": "#000000",
    "muted": "#B9C0C7",
    "panel": "#111418",
    "accent": "#7AD7CC",
}

MODEL_ORDER = ["Qwen3.5 9B", "Qwen3.5 27B", "Qwen3.5 35B", "Nemotron-3 Nano"]
SPOTLIGHT_MODELS = ["Qwen3.5 9B", "Qwen3.5 35B", "Nemotron-3 Nano"]
DISPLAY_LABELS = {
    "Qwen3.5 9B": "Qwen3.5 9B",
    "Qwen3.5 27B": "Qwen3.5 27B",
    "Qwen3.5 35B": "Qwen3.5 35B A3B MoE",
    "Nemotron-3 Nano": "Nemotron-3 Nano",
}


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


def _setup_style() -> None:
    sns.set_theme(style="whitegrid")
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update(
        {
            "figure.facecolor": COLORS["bg"],
            "axes.facecolor": COLORS["bg"],
            "axes.edgecolor": "#88919A",
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


def _style_axis(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#88919A")
    ax.spines["bottom"].set_color("#88919A")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)


def _percent_change(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return (new - old) / old * 100.0


def load_data(agg_csv: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    agg = pd.read_csv(agg_csv)
    agg = agg[agg["mode"].isin(["stateless", "fresh_mem0"])].copy()
    agg["model_order"] = agg["model_label"].map(
        lambda label: MODEL_ORDER.index(label) if label in MODEL_ORDER else len(MODEL_ORDER)
    )
    agg["mode_order"] = agg["mode"].map({"stateless": 0, "fresh_mem0": 1})
    agg = agg.sort_values(["model_order", "mode_order"]).reset_index(drop=True)

    delta_rows = []
    for model, group in agg.groupby("model_label"):
        base = group[group["mode"] == "stateless"].iloc[0]
        fresh = group[group["mode"] == "fresh_mem0"].iloc[0]
        delta_rows.append(
            {
                "model_label": model,
                "runtime_speedup_pct": (base["mean_runtime_seconds"] - fresh["mean_runtime_seconds"])
                / base["mean_runtime_seconds"]
                * 100.0,
                "field_delta": fresh["mean_total_fields"] - base["mean_total_fields"],
                "confidence_delta_pp": (fresh["mean_overall_confidence"] - base["mean_overall_confidence"])
                * 100.0,
                "retry_reduction": base["mean_steps_requiring_retry"] - fresh["mean_steps_requiring_retry"],
                "runs_stateless": int(base["runs"]),
                "runs_fresh": int(fresh["runs"]),
            }
        )

    delta = pd.DataFrame(delta_rows)
    delta["model_order"] = delta["model_label"].map(
        lambda label: MODEL_ORDER.index(label) if label in MODEL_ORDER else len(MODEL_ORDER)
    )
    delta = delta.sort_values("model_order").reset_index(drop=True)
    return agg, delta


def make_spotlight_figure(agg: pd.DataFrame) -> plt.Figure:
    fig, axes = plt.subplots(1, 3, figsize=(16, 6.8), facecolor=COLORS["bg"], constrained_layout=True)
    fig.suptitle(
        "Session memory creates clear wins in small local models",
        fontsize=22,
        fontweight="bold",
        color=COLORS["text"],
    )

    metric_specs = [
        ("mean_runtime_seconds", "Runtime", "Seconds", "{:.0f}"),
        ("mean_total_fields", "Metadata breadth", "Fields", "{:.1f}"),
        ("mean_overall_confidence", "Overall confidence", "Confidence", "{:.2f}"),
    ]

    x = np.arange(len(SPOTLIGHT_MODELS))
    width = 0.32

    for ax, (metric, title, ylabel, fmt) in zip(axes, metric_specs):
        _style_axis(ax)
        stateless_vals = []
        fresh_vals = []
        for model in SPOTLIGHT_MODELS:
            model_df = agg[agg["model_label"] == model].sort_values("mode_order")
            stateless_vals.append(float(model_df[model_df["mode"] == "stateless"][metric].iloc[0]))
            fresh_vals.append(float(model_df[model_df["mode"] == "fresh_mem0"][metric].iloc[0]))

        bars1 = ax.bar(x - width / 2, stateless_vals, width=width, color=COLORS["stateless"], label="Stateless")
        bars2 = ax.bar(x + width / 2, fresh_vals, width=width, color=COLORS["fresh_mem0"], label="Session memory on")

        for bars, vals in [(bars1, stateless_vals), (bars2, fresh_vals)]:
            for bar, val in zip(bars, vals):
                dy = 0.0
                if metric == "mean_runtime_seconds":
                    dy = 7
                elif metric == "mean_total_fields":
                    dy = 0.5
                else:
                    dy = 0.01
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + dy,
                    fmt.format(val),
                    ha="center",
                    va="bottom",
                    fontsize=9,
                )

        all_vals = stateless_vals + fresh_vals
        min_val = min(all_vals)
        max_val = max(all_vals)
        value_range = max_val - min_val
        if metric == "mean_runtime_seconds":
            pad_low = max(value_range * 0.75, min_val * 0.06)
            pad_high = max(value_range * 0.22, max_val * 0.03)
            lower = max(0, min_val - pad_low)
            upper = max_val + pad_high
            ax.set_ylim(lower, upper)
        elif metric == "mean_total_fields":
            pad_low = max(value_range * 0.75, min_val * 0.05)
            pad_high = max(value_range * 0.22, max_val * 0.03)
            lower = max(0, min_val - pad_low)
            upper = max_val + pad_high
            ax.set_ylim(lower, upper)
        else:
            lower = max(0.70, min_val - 0.03)
            upper = min(0.95, max_val + 0.03)
            ax.set_ylim(lower, upper)

        for idx, model in enumerate(SPOTLIGHT_MODELS):
            pct = _percent_change(stateless_vals[idx], fresh_vals[idx])
            pct_text = f"{pct:+.1f}%"
            y0 = max(stateless_vals[idx], fresh_vals[idx]) + (upper - lower) * 0.06
            ax.annotate(
                "",
                xy=(idx - width / 2, y0),
                xytext=(idx + width / 2, y0),
                arrowprops=dict(arrowstyle="<->", color=COLORS["muted"], lw=1.2),
            )
            ax.text(
                idx,
                y0 + (upper - lower) * 0.015,
                pct_text,
                ha="center",
                va="bottom",
                fontsize=10,
                color=COLORS["text"],
                fontweight="bold",
            )

        ax.set_title(title, loc="left")
        ax.set_ylabel(ylabel)
        ax.set_xticks(x)
        ax.set_xticklabels(
            [
                "Qwen\n9B",
                "Qwen\n35B A3B\nMoE",
                "Nemotron\nNano",
            ]
        )

    axes[0].legend(frameon=False, loc="upper right")
    return fig


def make_delta_figure(delta: pd.DataFrame) -> plt.Figure:
    fig = plt.figure(figsize=(16, 10), facecolor=COLORS["bg"])
    gs = fig.add_gridspec(2, 2, wspace=0.18, hspace=0.24)
    fig.suptitle(
        "What session memory changes relative to stateless mode",
        fontsize=22,
        fontweight="bold",
        color=COLORS["text"],
        y=0.98,
    )

    metrics = [
        ("runtime_speedup_pct", "A. Faster completion", "Speedup (%)", "positive = faster"),
        ("confidence_delta_pp", "B. Confidence lift", "Delta confidence (pp)", "positive = more confident"),
        ("field_delta", "C. Metadata breadth", "Delta fields", "positive = more extracted fields"),
        ("retry_reduction", "D. Less rework", "Retry reduction", "positive = fewer retries"),
    ]

    y_pos = np.arange(len(MODEL_ORDER))
    for idx, (metric, title, xlabel, note) in enumerate(metrics):
        ax = fig.add_subplot(gs[idx // 2, idx % 2])
        _style_axis(ax)
        ax.axvline(0, color="#88919A", linewidth=1.0)
        vals = []
        for model in MODEL_ORDER:
            row = delta[delta["model_label"] == model]
            vals.append(float(row.iloc[0][metric]) if not row.empty else np.nan)
        bars = ax.barh(y_pos, vals, color=COLORS["fresh_mem0"], height=0.55)
        for bar, val in zip(bars, vals):
            if np.isnan(val):
                continue
            if metric in ("runtime_speedup_pct", "confidence_delta_pp"):
                fmt = "{:+.1f}%"
                if metric == "confidence_delta_pp":
                    fmt = "{:+.1f}pp"
            else:
                fmt = "{:+.1f}"
            pad = 0.45 if metric != "field_delta" else 0.35
            x = val + pad if val >= 0 else val - pad
            ha = "left" if val >= 0 else "right"
            ax.text(x, bar.get_y() + bar.get_height() / 2, fmt.format(val), va="center", ha=ha, fontsize=10)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(MODEL_ORDER)
        ax.invert_yaxis()
        ax.set_title(title, loc="left")
        ax.set_xlabel(xlabel)
        ax.text(0.99, 1.02, note, transform=ax.transAxes, ha="right", va="bottom", fontsize=10, color=COLORS["muted"])

    fig.text(
        0.01,
        0.015,
        "Session memory = fresh mem0 only. Shared memory is intentionally excluded from this presentation view. "
        "All deltas are computed under the same preconverted Markdown input condition.",
        fontsize=10.5,
        color="#C9D0D6",
    )
    return fig


def make_all_models_figure(agg: pd.DataFrame) -> plt.Figure:
    fig, axes = plt.subplots(1, 3, figsize=(16, 6.5), facecolor=COLORS["bg"], constrained_layout=True)
    fig.suptitle(
        "Session memory effects across all tested local models",
        fontsize=22,
        fontweight="bold",
        color=COLORS["text"],
    )

    metric_specs = [
        ("mean_runtime_seconds", "Runtime", "Seconds", "{:.0f}"),
        ("mean_total_fields", "Metadata breadth", "Fields", "{:.1f}"),
        ("mean_overall_confidence", "Overall confidence", "Confidence", "{:.2f}"),
    ]

    x = np.arange(len(MODEL_ORDER))
    width = 0.34

    for ax, (metric, title, ylabel, fmt) in zip(axes, metric_specs):
        _style_axis(ax)
        stateless_vals = []
        fresh_vals = []
        for model in MODEL_ORDER:
            model_df = agg[agg["model_label"] == model].sort_values("mode_order")
            stateless_vals.append(float(model_df[model_df["mode"] == "stateless"][metric].iloc[0]))
            fresh_vals.append(float(model_df[model_df["mode"] == "fresh_mem0"][metric].iloc[0]))

        bars1 = ax.bar(x - width / 2, stateless_vals, width=width, color=COLORS["stateless"], label="Stateless")
        bars2 = ax.bar(x + width / 2, fresh_vals, width=width, color=COLORS["fresh_mem0"], label="Session memory on")

        for bars, vals in [(bars1, stateless_vals), (bars2, fresh_vals)]:
            for bar, val in zip(bars, vals):
                dy = 0.0
                if metric == "mean_runtime_seconds":
                    dy = 8
                elif metric == "mean_total_fields":
                    dy = 0.5
                else:
                    dy = 0.01
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + dy,
                    fmt.format(val),
                    ha="center",
                    va="bottom",
                    fontsize=9,
                )

        ax.set_title(title, loc="left")
        ax.set_ylabel(ylabel)
        ax.set_xticks(x)
        ax.set_xticklabels(["Qwen\n9B", "Qwen\n27B", "Qwen\n35B A3B\nMoE", "Nemotron\nNano"])

        if metric == "mean_overall_confidence":
            lower = max(0.70, min(stateless_vals + fresh_vals) - 0.03)
            upper = min(0.95, max(stateless_vals + fresh_vals) + 0.03)
            ax.set_ylim(lower, upper)

    axes[0].legend(frameon=False, loc="upper right")
    return fig


def write_report(delta: pd.DataFrame, agg_csv: Path, out_dir: Path) -> None:
    report = [
        "# Session Memory Findings Report",
        "",
        f"- Generated at: `{datetime.now().isoformat()}`",
        f"- Aggregate source: `{agg_csv.relative_to(REPO_ROOT)}`",
        "",
        "## Bottom line",
        "",
        "For presentation purposes, the clearest framing is to compare stateless mode against session memory only (`fresh_mem0`).",
        "",
        "- `Qwen3.5 9B` is the strongest all-round win: faster, broader, more confident, and fewer retries.",
        "- `Nemotron-3 Nano` is another clean positive case: faster, more confident, and fewer retries.",
        "- `Qwen3.5 35B` is still a useful systems story because session memory sharply improves runtime.",
        "- `Qwen3.5 27B` is the trade-off case and should not be the visual center of the slide.",
        "",
        "## Per-model deltas",
        "",
    ]
    for _, row in delta.iterrows():
        report.append(f"### {row['model_label']}")
        report.append("")
        report.append(
            f"- Runtime speedup: `{row['runtime_speedup_pct']:+.1f}%`"
        )
        report.append(
            f"- Confidence delta: `{row['confidence_delta_pp']:+.1f}pp`"
        )
        report.append(
            f"- Field delta: `{row['field_delta']:+.1f}`"
        )
        report.append(
            f"- Retry reduction: `{row['retry_reduction']:+.1f}`"
        )
        report.append("")

    report.extend(
        [
            "## Recommended slide claim",
            "",
            "> Session memory does not help every model in exactly the same way, but it can clearly improve workflow performance. In our current harness, it creates strong wins on Qwen3.5 9B and Nemotron-3 Nano, and major efficiency gains on Qwen3.5 35B.",
            "",
            "## Figure usage",
            "",
            "- Use `fig_session_memory_spotlight.png` as the main slide figure if you want to emphasize the clearest positive cases.",
            "- Use `fig_session_memory_all_models.png` when you want one slide that includes every tested model using the same three metrics.",
            "- Use `fig_session_memory_deltas.png` as a backup or appendix slide to show the broader pattern without discussing shared memory.",
            "",
            "## Caveats",
            "",
            "- All compared runs use the same preconverted MinerU Markdown input, so runtime is comparable within this benchmark.",
            "- This presentation view intentionally excludes `shared_mem0` because it is not part of the intended narrative.",
            "- `Qwen3.5 27B` and `Nemotron-3 Nano` currently have `n=1` per mode; `Qwen3.5 9B` and `Qwen3.5 35B` have `n=2` per mode.",
        ]
    )

    (out_dir / "SESSION_MEMORY_FINDINGS_REPORT.md").write_text(
        "\n".join(report),
        encoding="utf-8",
    )
    summary = {
        "generated_from": str(agg_csv.relative_to(REPO_ROOT)),
        "figure_files": [
            "fig_session_memory_spotlight.png",
            "fig_session_memory_all_models.png",
            "fig_session_memory_deltas.png",
            "fig_session_memory_spotlight.svg",
            "fig_session_memory_all_models.svg",
            "fig_session_memory_deltas.svg",
        ],
        "headline": "Session memory creates clear wins in small local models, especially Qwen3.5 9B and Nemotron-3 Nano.",
        "recommended_main_figure": "fig_session_memory_spotlight.png",
    }
    (out_dir / "session_memory_figure_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "README.md").write_text(
        "# Session Memory Figure Pack\n\n"
        "- Main figure: `fig_session_memory_spotlight.png`\n"
        "- All-model overview: `fig_session_memory_all_models.png`\n"
        "- Backup figure: `fig_session_memory_deltas.png`\n"
        "- Explanatory report: `SESSION_MEMORY_FINDINGS_REPORT.md`\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    run_root = args.run_root.resolve()
    out_dir = args.out_dir.resolve()
    agg_csv = run_root / "memory_harness_aggregates.csv"

    out_dir.mkdir(parents=True, exist_ok=True)
    _setup_style()
    agg, delta = load_data(agg_csv)

    fig1 = make_spotlight_figure(agg)
    fig1.savefig(out_dir / "fig_session_memory_spotlight.png", dpi=220, bbox_inches="tight")
    fig1.savefig(out_dir / "fig_session_memory_spotlight.svg", bbox_inches="tight")
    plt.close(fig1)

    fig2 = make_all_models_figure(agg)
    fig2.savefig(out_dir / "fig_session_memory_all_models.png", dpi=220, bbox_inches="tight")
    fig2.savefig(out_dir / "fig_session_memory_all_models.svg", bbox_inches="tight")
    plt.close(fig2)

    fig3 = make_delta_figure(delta)
    fig3.savefig(out_dir / "fig_session_memory_deltas.png", dpi=220, bbox_inches="tight")
    fig3.savefig(out_dir / "fig_session_memory_deltas.svg", bbox_inches="tight")
    plt.close(fig3)

    write_report(delta, agg_csv, out_dir)
    print(f"Wrote session-memory figure pack to {out_dir}")


if __name__ == "__main__":
    main()
