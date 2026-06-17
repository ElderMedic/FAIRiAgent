#!/usr/bin/env python3
"""Sync canonical figures into the presentation-v2 Vite public/figs folder.

Source of truth:
  - Manuscript figures     -> evaluation/paper_experiments_v1/figures/
  - Presentation eval figs -> evaluation/paper_experiments_v1/figures/presentation/
  - Concept / static art   -> docs/fairiagent-presentation/figs/

Run after generate_figures.py or generate_presentation_exp*.py:
  python evaluation/paper_experiments_v1/sync_presentation_assets.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

from evaluation.paper_experiments_v1.paths import (
    CONCEPT_FIGURES_DIR,
    MANUSCRIPT_FIGURES_DIR,
    PRESENTATION_FIGURES_DIR,
    VITE_PUBLIC_FIGS_DIR,
)

# Presentation slides reference these basenames (see presentation-v2/src/chapters).
PRESENTATION_EVAL_ASSETS = (
    "exp1_hierarchical_f1.png",
    "exp2_pass_at_k.png",
    "exp3_ablation.png",
    "poster_fig3_fig4_combined.png",
    "fig3_condition_comparison.png",
    "fig4_isa_structure_heatmap.png",
)

CONCEPT_ASSETS = (
    "LLMvsAgent.png",
    "MemoryDesign.png",
    "memory fig.png",
    "fairds_screenshot.png",
    "poster_fig1_architecture_handdrawn_v5.jpg",
    "tracingexample.png",
)

# Deprecated synthetic placeholders — never copy these into public/figs.
DEPRECATED_ASSETS = frozenset(
    {
        "metadata_generation_f1_presentation.png",
        "value_extraction_accuracy_presentation.png",
    }
)


def _copy_if_exists(src: Path, dst_dir: Path) -> bool:
    if not src.is_file():
        return False
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst_dir / src.name)
    return True


def sync_presentation_assets() -> list[str]:
    copied: list[str] = []
    VITE_PUBLIC_FIGS_DIR.mkdir(parents=True, exist_ok=True)

    for name in PRESENTATION_EVAL_ASSETS:
        for src_dir in (PRESENTATION_FIGURES_DIR, MANUSCRIPT_FIGURES_DIR):
            if _copy_if_exists(src_dir / name, VITE_PUBLIC_FIGS_DIR):
                copied.append(name)
                break

    for name in CONCEPT_ASSETS:
        if _copy_if_exists(CONCEPT_FIGURES_DIR / name, VITE_PUBLIC_FIGS_DIR):
            copied.append(name)

    for stale in DEPRECATED_ASSETS:
        path = VITE_PUBLIC_FIGS_DIR / stale
        if path.exists():
            path.unlink()

    return copied


def main() -> None:
    copied = sync_presentation_assets()
    print(f"[OK] synced {len(copied)} assets -> {VITE_PUBLIC_FIGS_DIR}")
    for name in copied:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
