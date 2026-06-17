"""Shared style helpers for manuscript-grade figures."""

from __future__ import annotations

import matplotlib.pyplot as plt


CONDITION_COLORS = {
    "Full": "#355C7D",
    "B1": "#8EA8C3",
    "B2": "#D8A15B",
    "B3": "#7FA38A",
}

ISA_SHEET_LABELS = {
    "investigation": "Investigation",
    "study": "Study",
    "observationunit": "Observation Unit",
    "sample": "Sample",
    "assay": "Assay",
}


def apply_publication_style() -> None:
    """Apply a restrained visual grammar for paper figures."""
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.8,
            "grid.alpha": 0.15,
            "grid.linewidth": 0.5,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.05,
        }
    )
