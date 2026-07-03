"""Visualizations for retrieval coverage and shadow-mode comparison."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


class RetrievalCoverageVisualizer:
    """Publication-style plots for retrieval rollout metrics."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        plt.style.use("seaborn-v0_8-paper")
        sns.set_palette("Set2")
        self.figsize = (10, 7)
        self.dpi = 300

    def plot_section_coverage_by_document(
        self,
        df: pd.DataFrame,
        filename: str = "retrieval_section_coverage_by_document",
    ) -> Optional[Path]:
        if df.empty:
            return None
        pivot = df.pivot_table(
            index="document_id",
            columns="model_name",
            values="section_coverage_ratio",
            aggfunc="mean",
        )
        fig, ax = plt.subplots(figsize=self.figsize)
        sns.heatmap(pivot, annot=True, fmt=".2f", cmap="YlGnBu", ax=ax, vmin=0, vmax=1)
        ax.set_title("Section Coverage Ratio by Document and Model")
        ax.set_xlabel("Model")
        ax.set_ylabel("Document")
        out = self.output_dir / f"{filename}.png"
        fig.tight_layout()
        fig.savefig(out, dpi=self.dpi, bbox_inches="tight")
        plt.close(fig)
        return out

    def plot_legacy_vs_hybrid_gain(
        self,
        summary_df: pd.DataFrame,
        filename: str = "retrieval_legacy_vs_hybrid_gain",
    ) -> Optional[Path]:
        if summary_df.empty:
            return None
        plot_df = summary_df.melt(
            id_vars=["model_name"],
            value_vars=["mean_legacy_only_fields", "mean_semantic_only_fields", "mean_hybrid_gain_fields"],
            var_name="metric",
            value_name="count",
        )
        fig, ax = plt.subplots(figsize=self.figsize)
        sns.barplot(data=plot_df, x="model_name", y="count", hue="metric", ax=ax)
        ax.set_title("Legacy-only vs Semantic-only vs Hybrid Gain (Shadow Telemetry)")
        ax.set_xlabel("Model")
        ax.set_ylabel("Mean fields per document")
        ax.tick_params(axis="x", rotation=30)
        out = self.output_dir / f"{filename}.png"
        fig.tight_layout()
        fig.savefig(out, dpi=self.dpi, bbox_inches="tight")
        plt.close(fig)
        return out
