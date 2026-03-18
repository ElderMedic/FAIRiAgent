# Evaluation Framework Documentation Index

**Purpose**: Minimal navigation for maintainable, push-ready evaluation docs  
**Last Updated**: 2026-03-13

---

## Core Reading Path

### Current workflow result tutorial

1. `evaluation/analysis/README.md` - start here for a non-technical walkthrough
2. `evaluation/runs/qwen35_pomato_publication_fix/workflow_report.json` - easiest example result
3. `evaluation/runs/qwen35_pomato_publication_fix/metadata_json.json` - example generated metadata
4. `evaluation/runs/qwen35_no_langfuse_eval_all_pubfix/results/evaluation_results.json` - latest aggregate evaluation

### Historical benchmark reports

1. `evaluation/reports/FINAL_EVALUATION_RESULTS.md` - legacy benchmark report for earlier multi-model comparisons
2. `evaluation/analysis/key_figures/evaluation_summary.png`
3. `evaluation/analysis/key_figures/field_analysis_report.png`

---

## Main Reports (Keep)

Location: `evaluation/reports/`

- `FINAL_EVALUATION_RESULTS.md` (legacy benchmark summary; useful for historical comparison)
- `README.md` (report index)

---

## Key Figures (Keep)

Location: `evaluation/analysis/key_figures/`

- `evaluation_summary.png` (legacy benchmark-oriented summary figure)
- `field_analysis_report.png` (legacy benchmark-oriented field analysis figure)

Generation scripts:
- `evaluation/scripts/generate_key_figures.py`
- `evaluation/scripts/generate_final_report.py`

---

## Technical Docs (Keep)

- `evaluation/EVALUATION_IMPROVEMENT_PLAN.md`
- `evaluation/analysis/MODEL_CLASSIFICATION.md`
- `evaluation/analysis/README.md` (now includes the recommended user tutorial)

---

## Supplementary Outputs

- `evaluation/analysis/output/figures/` (additional plots)
- `evaluation/analysis/output/tables/` (CSV tables)
- `evaluation/analysis/output/biological_insights.json` (main analysis data source)

---

## Archived / Non-primary

- `evaluation/archive/docs/` (historical or redundant summaries, including `ACTION_PLAN_LEGACY.md`)
- `evaluation/analysis/output/archive/` (timestamped JSON snapshots)

---

## Notes for Clean Git Push

- Generated heavy directories are ignored by `.gitignore`:
  - `evaluation/analysis/comprehensive_output/`
  - `evaluation/analysis/improved_output_*/`
  - `evaluation/analysis/output/`
  - `evaluation/runs/`
- Keep commits focused on code + core docs + key figures only.

## Current Recommended Result Example

If you need to explain the workflow to a non-computational user, use:

- `evaluation/runs/qwen35_pomato_publication_fix/`

Why this example:

- it is a complete run
- it is visually inspectable
- it represents a hard real-world case
- it shows both structured output and evaluation evidence
 