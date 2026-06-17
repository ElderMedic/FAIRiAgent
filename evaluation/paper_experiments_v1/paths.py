"""Canonical paths for paper experiments and presentation asset sync."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAPER_EXP_ROOT = PROJECT_ROOT / "evaluation" / "paper_experiments_v1"

# Phase-0 / manuscript figures (fig3, fig4, supp_fig1)
MANUSCRIPT_FIGURES_DIR = PAPER_EXP_ROOT / "figures"

# Seminar / slide experiment figures (exp1–exp3, poster combined)
PRESENTATION_FIGURES_DIR = MANUSCRIPT_FIGURES_DIR / "presentation"

# Static concept art for slides (architecture, FAIR-DS screenshot, etc.)
CONCEPT_FIGURES_DIR = PROJECT_ROOT / "docs" / "fairiagent-presentation" / "figs"

# Vite app public assets (sync target — do not edit by hand)
VITE_PUBLIC_FIGS_DIR = (
    PROJECT_ROOT / "docs" / "fairiagent-presentation" / "presentation-v2" / "public" / "figs"
)

# Analysis exports
ANALYSIS_DIR = PAPER_EXP_ROOT / "analysis"
TABLES_DIR = PAPER_EXP_ROOT / "tables"
RESULTS_DIR = PAPER_EXP_ROOT / "results"
RUNS_DIR = PAPER_EXP_ROOT / "runs"
