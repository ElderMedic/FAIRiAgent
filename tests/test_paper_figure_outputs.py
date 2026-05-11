"""Smoke test for manuscript-grade figure generation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_generate_figures_writes_main_text_assets():
    build = subprocess.run(
        [
            "mamba",
            "run",
            "-n",
            "FAIRiAgent",
            sys.executable,
            "evaluation/paper_experiments_v1/build_figure_manifest.py",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr

    result = subprocess.run(
        [
            "mamba",
            "run",
            "-n",
            "FAIRiAgent",
            sys.executable,
            "evaluation/paper_experiments_v1/generate_figures.py",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    fig_dir = PROJECT_ROOT / "evaluation" / "paper_experiments_v1" / "figures"
    assert (fig_dir / "fig3_condition_comparison.png").exists()
    assert (fig_dir / "fig3_condition_comparison.pdf").exists()
    assert (fig_dir / "fig4_isa_structure_heatmap.png").exists()
    assert (fig_dir / "fig4_isa_structure_heatmap.pdf").exists()
