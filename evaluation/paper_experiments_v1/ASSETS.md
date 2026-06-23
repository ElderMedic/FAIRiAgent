# Paper & Evaluation Asset Map

All manuscript and seminar quantitative assets live under this directory.

```
paper_experiments_v1/
├── runs/              # Raw run artifacts (metadata.json, logs, eval_result.json)
├── analysis/          # figure_manifest_phase0.json, metrics_summary.json, CSV exports
├── figures/
│   ├── fig3_*.png/pdf           # Phase-0 condition comparison (manuscript)
│   ├── fig4_*.png/pdf           # ISA layer heatmap (manuscript)
│   ├── supp_fig1_*.png/pdf      # Inclusion / exclusion contract
│   └── presentation/            # Seminar panels (exp1–exp3, poster combined)
├── tables/            # table1–table9 (.md + .csv)
├── results/           # B1_RESULTS.md, JSON comparisons
├── records/           # IMPLEMENTATION_STATUS.md, ASSET_MANIFEST.md
└── manuscript/        # FIGURE_NOTES.md, research report draft
```

## Regenerate pipeline

```bash
# 1. Refresh manifest from runs/
python evaluation/paper_experiments_v1/build_figure_manifest.py

# 2. Manuscript figures + FIGURE_NOTES.md
python evaluation/paper_experiments_v1/generate_figures.py

# 3. Tables
python evaluation/paper_experiments_v1/generate_tables.py

# 4. Push figures to slide app
python evaluation/paper_experiments_v1/sync_presentation_assets.py
```

## Path helpers

`evaluation/paper_experiments_v1/paths.py` defines canonical directories for scripts.

## Legacy locations (do not use)

| Old path | Replacement |
|----------|-------------|
| `docs/fairiagent-presentation/presentation/` | `figures/presentation/` |
| `evaluation/analysis/figures/` | Does not exist — use `figures/` here |
| `evaluation/analysis/output/figures/` | Empty / archived — use `figures/` here |
| `evaluation/paper_experiments_v1/presentation_20260511/` | Removed |
| Synthetic `*_presentation.png` drafts | Removed — use real Phase-0 figures |
