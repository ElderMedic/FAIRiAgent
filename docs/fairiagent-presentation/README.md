# FAIRiAgent Presentation Assets

## Where things live (single source of truth)

| What | Canonical path | Notes |
|------|----------------|-------|
| **Phase-0 manuscript figures** | `evaluation/paper_experiments_v1/figures/` | `fig3_*`, `fig4_*`, `supp_fig1_*` |
| **Seminar / experiment figures** | `evaluation/paper_experiments_v1/figures/presentation/` | `exp1_*`, `exp2_*`, `exp3_*`, `poster_fig3_fig4_combined` |
| **Analysis tables & JSON** | `evaluation/paper_experiments_v1/tables/`, `analysis/` | Phase-0 metrics |
| **Written result summaries** | `evaluation/paper_experiments_v1/results/` | B1/B2/B3 markdown + JSON |
| **Concept / static art** | `docs/fairiagent-presentation/figs/` | Architecture, LLMvsAgent, FAIR-DS screenshot |
| **Slide web app (source)** | `docs/fairiagent-presentation/presentation-v2/` | Vite + React |
| **Slide web app (built)** | `presentation-v2/dist/index.html` | Run `npm run build` in `presentation-v2/` |

`presentation-v2/public/figs/` is a **sync target only**. Regenerate via:

```bash
python evaluation/paper_experiments_v1/sync_presentation_assets.py
```

Or run any figure generator (`generate_figures.py`, `generate_presentation_exp1.py`, …) — they call sync automatically.

## Regenerate figures

```bash
# Manuscript Phase-0 figures (fig3, fig4, supp)
python evaluation/paper_experiments_v1/build_figure_manifest.py
python evaluation/paper_experiments_v1/generate_figures.py

# Seminar experiment panels (biosensor + earthworm subset)
python evaluation/generate_presentation_exp1.py
python evaluation/generate_presentation_exp2_3.py

# Poster combined panel (v2 metrics)
python evaluation/scripts/evaluate_agent_quality.py
```

## Talk scripts

- `outline.md` — slide structure (English headings)
- `script.md` — speaker notes
- `speaker-script-bilingual.md` — bilingual notes

## Removed (2026-06-05 cleanup)

- `presentation/` — duplicate exp2/exp3 copies (merged into `figures/presentation/`)
- `presentation_20260511/` under `paper_experiments_v1/` — obsolete snapshot
- Synthetic placeholder charts (`metadata_generation_f1_presentation.png`, `value_extraction_accuracy_presentation.png`)
