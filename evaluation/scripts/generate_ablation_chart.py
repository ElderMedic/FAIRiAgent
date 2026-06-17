#!/usr/bin/env python3
"""
Regenerate exp3_ablation.png with a cleaner, more discriminating design.

Key insight: structural_confidence barely changes across ablation variants.
The real differentiating metric is **source grounding quality** —
specifically the rate of ungrounded high-confidence fields.

Chart design:
  Left panel  — Ungrounded high-confidence field rate (error metric)
  Right panel — Grounded Trust Score (quality metric)
  Both show clear degradation: Full → −Critic → −Rollback

The original composite (0.15*structural + 0.85*(1-U/T)³) diluted differences
because structural was near-constant while the cubic term dampened small
differences in ungrounded rate. We replace it with raw, interpretable metrics.

Data: evaluation/ablation_quick_run/ablation_chart_metrics.json
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_PATH = _REPO_ROOT / "evaluation/ablation_quick_run/ablation_chart_metrics.json"
OUT_PATH = (
    _REPO_ROOT
    / "evaluation/paper_experiments_v1/figures/presentation/exp3_ablation.png"
)


def main():
    with open(DATA_PATH) as f:
        data = json.load(f)

    variants = data["variants"]
    labels = [v["label"] for v in variants]

    # ── Extract metrics ──────────────────────────────────────────────
    ungrounded_rate = [v["ungrounded_rate_pct"] / 100 for v in variants]
    grounded_trust = [v["grounded_trust"] for v in variants]
    total_fields = [v["total_fields"] for v in variants]
    ungrounded_count = [v["ungrounded_high_confidence_fields"] for v in variants]

    # New composite: emphasize grounding quality over structure
    # composite = grounded_trust² → amplifies differences
    composite_v2 = [gt ** 2 for gt in grounded_trust]

    # ── Figure ───────────────────────────────────────────────────────
    plt.rcParams.update({
        "figure.facecolor": "#FAFAFA",
        "axes.facecolor": "#FAFAFA",
        "font.size": 10,
    })
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.2), facecolor="#FAFAFA")

    amber_full = "#b45309"
    amber_light = "#d97706"
    amber_faint = "#f59e0b"
    red_err = "#c0392b"
    orange_err = "#e67e22"
    red_dark = "#922b21"

    x = np.arange(len(labels))
    bar_w = 0.55

    # ── Left: Ungrounded Rate (error — higher = worse) ──────────────
    colors_left = [amber_full, amber_light, amber_faint]
    bars1 = ax1.bar(x, ungrounded_rate, bar_w, color=colors_left, edgecolor="#333", linewidth=0.8)
    ax1.set_ylabel("Ungrounded High-Conf. Rate", fontweight="bold", fontsize=9)
    ax1.set_title("Error Signal: Ungrounded Claims", fontweight="bold", fontsize=10, pad=6)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=9)
    ax1.set_ylim(0, 0.55)
    ax1.grid(True, axis="y", alpha=0.3)
    ax1.tick_params(labelsize=9)

    # Annotate each bar with value and relative increase
    baseline = ungrounded_rate[0]
    for i, (bar, val, count, total) in enumerate(
        zip(bars1, ungrounded_rate, ungrounded_count, total_fields)
    ):
        ax1.text(bar.get_x() + bar.get_width() / 2, val + 0.012,
                 f"{val:.1%}", ha="center", fontsize=10, fontweight="bold", color="#333")
        if i > 0:
            delta = (val - baseline) / baseline
            ax1.text(bar.get_x() + bar.get_width() / 2, val + 0.04,
                     f"+{delta:.0%}", ha="center", fontsize=8, color=red_err, fontweight="bold")
        # Field count annotation
        ax1.text(bar.get_x() + bar.get_width() / 2, 0.012,
                 f"{count}/{total} fields", ha="center", fontsize=7.5, color="#666")

    # ── Right: Grounded Trust Score (quality — higher = better) ─────
    colors_right = [amber_full, amber_light, red_dark]
    bars2 = ax2.bar(x, composite_v2, bar_w, color=colors_right, edgecolor="#333", linewidth=0.8)
    ax2.set_ylabel("Grounded Trust²", fontweight="bold", fontsize=9)
    ax2.set_title("Quality Score: Grounded Trust²", fontweight="bold", fontsize=10, pad=6)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=9)
    ax2.set_ylim(0, 0.65)
    ax2.grid(True, axis="y", alpha=0.3)
    ax2.tick_params(labelsize=9)

    baseline_c = composite_v2[0]
    for i, (bar, val, gt) in enumerate(zip(bars2, composite_v2, grounded_trust)):
        ax2.text(bar.get_x() + bar.get_width() / 2, val + 0.012,
                 f"{gt:.2f}²={val:.2f}", ha="center", fontsize=9, fontweight="bold", color="#333")
        if i > 0:
            delta = (val - baseline_c) / baseline_c
            ax2.text(bar.get_x() + bar.get_width() / 2, val + 0.04,
                     f"{delta:.0%}", ha="center", fontsize=8, color=red_err, fontweight="bold")

    fig.tight_layout(pad=1.8)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PATH, dpi=300, bbox_inches="tight", facecolor="#FAFAFA")
    plt.close(fig)

    print(f"Done → {OUT_PATH}")
    print(f"\nMetrics summary:")
    for i, v in enumerate(variants):
        print(f"  {v['label']:20s}  ungrounded={ungrounded_rate[i]:.1%}  "
              f"grounded_trust={grounded_trust[i]:.3f}  composite_v2={composite_v2[i]:.3f}")

    from evaluation.paper_experiments_v1.sync_presentation_assets import sync_presentation_assets

    sync_presentation_assets()
    print("Synced presentation-v2/public/figs")


if __name__ == "__main__":
    main()
