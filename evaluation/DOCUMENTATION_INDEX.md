# Evaluation Framework Documentation Index

**Purpose**: Minimal navigation for maintainable, push-ready evaluation docs  
**Last Updated**: 2026-01-30

---

## Core Reading Path

1. `evaluation/README.md` - run/evaluation entry
2. `evaluation/reports/FINAL_EVALUATION_RESULTS.md` - merged final result report (includes validation + meeting-response summary)

---

## Main Reports (Keep)

Location: `evaluation/reports/`

- `FINAL_EVALUATION_RESULTS.md`
- `README.md` (report index)

---

## Key Figures (Keep)

Location: `evaluation/analysis/key_figures/`

- `evaluation_summary.png`
- `field_analysis_report.png`

Generation scripts:
- `evaluation/scripts/generate_key_figures.py`
- `evaluation/scripts/generate_final_report.py`

---

## Technical Docs (Keep)

- `evaluation/EVALUATION_IMPROVEMENT_PLAN.md`
- `evaluation/analysis/MODEL_CLASSIFICATION.md`

---

## Supplementary Outputs

- `evaluation/analysis/output/figures/` (additional plots)
- `evaluation/analysis/output/tables/` (CSV tables)
- `evaluation/analysis/output/biological_insights.json` (main analysis data source)

---

## Archived / Non-primary

- `evaluation/archive/docs/` (historical or redundant summaries)
- `evaluation/analysis/output/archive/` (timestamped JSON snapshots)

---

## Notes for Clean Git Push

- Generated heavy directories are ignored by `.gitignore`:
  - `evaluation/analysis/comprehensive_output/`
  - `evaluation/analysis/improved_output_*/`
  - `evaluation/analysis/output/`
  - `evaluation/runs/`
- Keep commits focused on code + core docs + key figures only.
 