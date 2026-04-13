#!/usr/bin/env python3
"""
Single poster panel: **embedded** pass@k figure (left ~2/3) + stacked F1 / completeness
boxplots (right ~1/3).

The pass@k panel is rasterized from `docs/figures/poster_fig3_passk.png` so curves, legend,
and annotations (arrows / callouts) stay **identical** to the standalone poster asset.

Right column: same data path as `generate_poster_fig4_baseline_agentic_boxplots.py`
(CSV agentic + baseline dirs, on-the-fly metrics). No footer under boxplots.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_SCRIPTS_DIR))

from add_evaluation_metrics import evaluate_single_run, load_ground_truth  # noqa: E402


def _iter_baseline_run_dirs(baselines_runs: Path) -> list[Path]:
    out: list[Path] = []
    if not baselines_runs.is_dir():
        return out
    for eval_path in baselines_runs.rglob("eval_result.json"):
        run_dir = eval_path.parent
        if run_dir.name.startswith("run_") and (run_dir / "metadata_json.json").exists():
            out.append(run_dir)
    return sorted(set(out), key=lambda p: str(p))


def _load_agentic_table(csv_path: Path, documents: set[str]) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df = df[df["document_id"].isin(documents)].copy()
    df["arm"] = "Agentic"
    return df


def _load_baseline_metrics(
    baselines_runs: Path,
    ground_truth_docs: dict,
    documents: set[str],
) -> pd.DataFrame:
    rows = []
    for run_dir in _iter_baseline_run_dirs(baselines_runs):
        updated = evaluate_single_run(
            run_dir, ground_truth_docs, env_file=None, persist=False
        )
        if not updated:
            continue
        doc_id = updated.get("document_id")
        if doc_id not in documents:
            continue
        comp = updated.get("completeness") or {}
        corr = updated.get("correctness") or {}
        rows.append(
            {
                "document_id": doc_id,
                "f1_score": float(corr.get("f1_score", 0.0) or 0.0),
                "completeness": float(comp.get("overall_completeness", 0.0) or 0.0),
                "arm": "Baseline",
            }
        )
    return pd.DataFrame(rows)


def _panel_letter(
    ax,
    letter: str,
    *,
    fontsize: float = 11,
) -> None:
    """Bold (a)/(b)/(c) label; light box so it stays readable on the pass@k raster."""
    ax.text(
        0.012,
        0.988,
        f"({letter})",
        transform=ax.transAxes,
        fontsize=fontsize,
        fontweight="bold",
        va="top",
        ha="left",
        color="#111111",
        bbox={
            "boxstyle": "round,pad=0.12",
            "facecolor": "white",
            "alpha": 0.92,
            "edgecolor": "#cccccc",
            "linewidth": 0.35,
        },
        zorder=10,
    )


def _boxplot_panel(
    ax,
    data: pd.DataFrame,
    ycol: str,
    ylabel: str,
    title: str,
    *,
    f1_threshold_line: bool = False,
    fontsize: int = 8,
) -> None:
    arms = ["Agentic", "Baseline"]
    series = [data.loc[data["arm"] == a, ycol].dropna().values for a in arms]
    colors = ["#27ae60", "#95a5a6"]
    bp = ax.boxplot(
        series,
        tick_labels=arms,
        patch_artist=True,
        widths=0.55,
        showfliers=True,
    )
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c)
        patch.set_alpha(0.75)
        patch.set_edgecolor("#333333")
    for el in ("whiskers", "caps", "medians"):
        for line in bp[el]:
            line.set_color("#222222")
            line.set_linewidth(1.0)
    ax.set_ylabel(ylabel, fontweight="bold", fontsize=fontsize + 1)
    ax.set_title(title, fontweight="bold", fontsize=fontsize + 1, pad=3)
    ax.set_ylim(-0.02, 1.05)
    ax.tick_params(axis="both", labelsize=fontsize)
    if f1_threshold_line:
        ax.axhline(0.65, color="#c0392b", linestyle=":", linewidth=0.9, alpha=0.75)
    ax.grid(True, axis="y", alpha=0.35)


def generate_combined(
    passk_image: Path,
    csv_path: Path,
    baselines_runs: Path,
    ground_truth_path: Path,
    documents: set[str],
    out_path: Path,
    *,
    fig_w: float = 12.0,
    fig_h: float = 4.85,
    wspace: float = 0.02,
    hspace: float = 0.22,
) -> None:
    if not passk_image.is_file():
        raise SystemExit(f"Pass@k image not found: {passk_image}")

    gt = load_ground_truth(ground_truth_path)
    agentic_df = _load_agentic_table(csv_path, documents)
    baseline_df = _load_baseline_metrics(baselines_runs, gt, documents)
    if baseline_df.empty:
        raise SystemExit("No baseline runs with computable metrics found.")

    img = mpimg.imread(str(passk_image))

    plt.rcParams.update(
        {
            "figure.facecolor": "#FAFAFA",
            "axes.facecolor": "#FAFAFA",
            "font.size": 9,
        }
    )
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor="#FAFAFA")
    gs = fig.add_gridspec(
        2,
        2,
        width_ratios=[2, 1],
        wspace=wspace,
        hspace=hspace,
    )
    ax_pass = fig.add_subplot(gs[:, 0])
    ax_f1 = fig.add_subplot(gs[0, 1])
    ax_cmp = fig.add_subplot(gs[1, 1])

    ax_pass.imshow(img, interpolation="nearest", aspect="equal")
    ax_pass.set_axis_off()
    _panel_letter(ax_pass, "a")

    data = pd.concat([agentic_df, baseline_df], ignore_index=True)
    _boxplot_panel(
        ax_f1,
        data,
        "f1_score",
        "Field-level F1",
        "Extraction quality (F1 vs ground truth)",
        f1_threshold_line=True,
        fontsize=7,
    )
    _panel_letter(ax_f1, "b", fontsize=10)
    _boxplot_panel(
        ax_cmp,
        data,
        "completeness",
        "Overall completeness",
        "Ground-truth field coverage",
        f1_threshold_line=False,
        fontsize=7,
    )
    _panel_letter(ax_cmp, "c", fontsize=10)

    fig.subplots_adjust(left=0.01, right=0.99, top=0.94, bottom=0.05)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="#FAFAFA")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--passk-image",
        type=Path,
        default=_REPO_ROOT / "docs/figures/poster_fig3_passk.png",
        help="Raster pass@k figure to embed unchanged (default: poster_fig3_passk.png).",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=_REPO_ROOT
        / "evaluation/analysis/output/tables/all_runs_data_20260116_005441.csv",
    )
    parser.add_argument(
        "--baselines-runs",
        type=Path,
        default=_REPO_ROOT / "evaluation/baselines/runs",
    )
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=_REPO_ROOT
        / "evaluation/datasets/annotated/ground_truth_filtered.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_REPO_ROOT / "docs/figures/poster_fig3_fig4_combined.png",
    )
    parser.add_argument("--wspace", type=float, default=0.02)
    parser.add_argument("--hspace", type=float, default=0.22)
    args = parser.parse_args()

    generate_combined(
        args.passk_image,
        args.csv,
        args.baselines_runs,
        args.ground_truth,
        {"earthworm", "biosensor"},
        args.output,
        wspace=args.wspace,
        hspace=args.hspace,
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
