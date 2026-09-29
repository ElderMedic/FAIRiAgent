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

## Run catalog

`evaluation/reports/run_catalog/` is a generated inventory of local runs, split into `evaluation_runs.csv` and `output_runs.csv`. Refresh it with:

```bash
mamba run -n FAIRiAgent python evaluation/scripts/build_run_catalog.py
```

The CSV files are overwritten on each refresh. `result_status=complete` means metadata exists and the workflow or eval record succeeded. `deliverable_only` means metadata exists without that success record. The script does not open `runtime_config.json` (those files hold API keys); model identity comes from the path, `eval_result.json`, and `run_index.json`. Campaign-level scores are copied onto each matching document and marked `score_scope=campaign_document`; `score_shared_across_runs=true` means that number is not unique to one repetition. Benchmark v2 axes from `run_index.json` are separate columns. This directory is gitignored.

## Key Figures

- `evaluation/analysis/output/key_figures/evaluation_summary.png`
- `evaluation/analysis/output/key_figures/field_analysis_report.png`

These reflect the earlier benchmark-oriented comparison. Do not mix them with later v2 campaign scores.

See [evaluation/README.md](../README.md) and [docs/INDEX.md](../../docs/INDEX.md).
