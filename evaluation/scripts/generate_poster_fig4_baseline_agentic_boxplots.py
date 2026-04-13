#!/usr/bin/env python3
"""
Poster Figure 4 — stacked boxplots: F1 (top) and overall completeness (bottom),
Agentic (8 backends, pooled) vs single-prompt baselines (pooled).

Reads agentic per-run metrics from the frozen analysis CSV. Computes baseline metrics
on the fly from metadata + ground truth (same harness as add_evaluation_metrics),
without writing to baseline eval_result.json files.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
                "completeness": float(
                    comp.get("overall_completeness", 0.0) or 0.0
                ),
                "arm": "Baseline",
            }
        )
    return pd.DataFrame(rows)


def _boxplot_panel(
    ax,
    data: pd.DataFrame,
    ycol: str,
    ylabel: str,
    title: str,
    *,
    f1_threshold_line: bool = False,
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
            line.set_linewidth(1.2)
    ax.set_ylabel(ylabel, fontweight="bold")
    ax.set_title(title, fontweight="bold", fontsize=11)
    ax.set_ylim(-0.02, 1.05)
    if f1_threshold_line:
        ax.axhline(0.65, color="#c0392b", linestyle=":", linewidth=1.0, alpha=0.7)
    ax.grid(True, axis="y", alpha=0.35)


def generate_figure(
    agentic_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    out_path: Path,
) -> None:
    data = pd.concat([agentic_df, baseline_df], ignore_index=True)

    plt.rcParams.update(
        {
            "figure.facecolor": "#FAFAFA",
            "axes.facecolor": "#FAFAFA",
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
        }
    )
    fig, axes = plt.subplots(2, 1, figsize=(5.2, 6.2), sharex=True)
    fig.patch.set_facecolor("#FAFAFA")

    _boxplot_panel(
        axes[0],
        data,
        "f1_score",
        "Field-level F1",
        "A. Extraction quality (F1 vs ground truth)",
        f1_threshold_line=True,
    )
    _boxplot_panel(
        axes[1],
        data,
        "completeness",
        "Overall completeness",
        "B. Ground-truth field coverage",
    )

    n_a = (data["arm"] == "Agentic").sum()
    n_b = (data["arm"] == "Baseline").sum()
    fig.suptitle(
        "Agentic vs single-prompt baseline (pooled runs)",
        fontsize=12,
        fontweight="bold",
        y=0.98,
    )
    fig.text(
        0.5,
        0.02,
        f"Agentic n={n_a}, Baseline n={n_b} · earthworm + biosensor · "
        "dotted line: F1 = 0.65 (high-quality pass@k threshold)",
        ha="center",
        fontsize=8,
        color="#444444",
    )
    plt.tight_layout(rect=[0, 0.06, 1, 0.94])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="#FAFAFA")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        type=Path,
        default=_REPO_ROOT
        / "evaluation/analysis/output/tables/all_runs_data_20260116_005441.csv",
        help="Frozen agentic per-run table (from quick_analysis).",
    )
    parser.add_argument(
        "--baselines-runs",
        type=Path,
        default=_REPO_ROOT / "evaluation/baselines/runs",
        help="Directory containing baseline campaign outputs.",
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
        default=_REPO_ROOT / "docs/figures/poster_fig4_boxplots.png",
    )
    args = parser.parse_args()

    documents = {"earthworm", "biosensor"}
    gt = load_ground_truth(args.ground_truth)

    agentic = _load_agentic_table(args.csv, documents)
    need_cols = {"f1_score", "completeness", "arm"}
    missing = need_cols - set(agentic.columns)
    if missing:
        raise SystemExit(f"CSV missing columns: {missing}")

    baseline = _load_baseline_metrics(args.baselines_runs, gt, documents)
    if baseline.empty:
        raise SystemExit("No baseline runs with computable metrics found.")

    generate_figure(agentic, baseline, args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
