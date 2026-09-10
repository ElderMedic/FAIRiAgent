# Evaluation Reports

Main reports for sharing/pushing.

## Final Report

- `FINAL_EVALUATION_RESULTS.md` — legacy benchmark report for the earlier multi-model comparison campaign

## Where results live (quick map)

| Location | What it is |
|----------|------------|
| `evaluation/runs/` | Raw batch outputs per model/campaign (each run dir: `metadata.json` or legacy `metadata_json.json`, `workflow_report.json`, `eval_result.json`, …) |
| `evaluation/runs/archive/` | Older or ad hoc batches (including small API smoke dirs and `openai_test`) |
| `evaluation/analysis/output/` | Regenerated analysis: `key_figures/`, `figures/`, `tables/`, `biological_insights.json` |
| `evaluation/analysis/output/archive/` | Older analysis snapshots, smoke runs, archived reports under `archive/reports/` |
| `evaluation/reports/` | Human-written summaries (this folder) |
| `evaluation/harness/runs/` | Harness / presentation-oriented campaign outputs |
| `evaluation/harness/private/reports/` | Curated presentation packs; see `README.md` there |

## Current result walkthrough

For a workflow-oriented tutorial, start from:

- `evaluation/analysis/README.md`
- `evaluation/runs/qwen35_pomato_publication_fix/workflow_report.json`
- `evaluation/runs/qwen35_pomato_publication_fix/metadata.json` (or `metadata_json.json` on older runs)

Campaign score packs and manuscript figures stay local and are not listed here.

## Key Figures

- `evaluation/analysis/output/key_figures/evaluation_summary.png`
- `evaluation/analysis/output/key_figures/field_analysis_report.png`

These reflect the earlier benchmark-oriented comparison. Do not mix them with later v2 campaign scores.

See `evaluation/DOCUMENTATION_INDEX.md` for full navigation.
