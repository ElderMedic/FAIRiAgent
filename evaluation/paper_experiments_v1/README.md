# FAIRiAgent Paper Experiments v1

This directory is the working root for the FAIRiAgent manuscript package. All paper-facing artifacts should be organized here: analysis outputs, figure/table assets, manuscript drafts, and process records.

## Directory Layout

See **`ASSETS.md`** for the full asset map and regeneration commands.

- `analysis/`: machine-readable metrics exports generated from evaluation runs.
- `figures/`: manuscript figures (`fig3`, `fig4`, `supp_fig1`) in `.png` and `.pdf`.
- `figures/presentation/`: seminar / slide experiment panels (`exp1`–`exp3`, poster combined).
- `tables/`: manuscript tables in `.csv` and future export-ready formats.
- `sync_presentation_assets.py`: copies canonical figures into `docs/fairiagent-presentation/presentation-v2/public/figs/`.
- `manuscript/`: assembled paper draft and report text.
- `records/`: provenance, run inventories, implementation status, and asset manifests.
- `logs/`: future experiment logs and execution transcripts for manuscript runs.
- `run_paper_analysis.py`: analysis entrypoint for the current preliminary dataset bundle.
- `generate_figures.py`: figure generator for the current preliminary dataset bundle.
- `results/`: validated intermediate result summaries derived from real run artifacts.

## Canonical Inputs

The current `v1` bundle is built from:

- `evaluation/datasets/annotated/values/ground_truth_*_values.json`
- `evaluation/runs/docinputs/`
- `evaluation/runs/compare_20260503/`
- `evaluation/runs/loop_v1/`
- `evaluation/runs/loop_v2/`

CompBioBench runs under `evaluation/runs/compbiobench/` are recorded in the manifest but are not the primary source for the current manuscript figures.

## Model Policy

For manuscript execution in this workspace, the following **5 local Ollama models** are required:

| # | Model | Ollama tag | Type | Config |
|---|-------|-----------|------|--------|
| M1 | Qwen 3.5 9B | `qwen3.5:9b` | 9B dense | `ollama_qwen3.5-9b_v1.4.0.env` |
| M2 | Qwen 3.6 27B | `qwen3.6:27b` | 27B dense | `ollama_qwen3.6-27b_v1.4.0.env` |
| M3 | Qwen 3.6 35B | `qwen3.6:35b` | 35B A3B MoE | `ollama_qwen3.6-35b_v1.4.0.env` |
| M4 | Gemma 4 31B | `gemma4:31b` | 31B dense | `ollama_gemma4-31b_v1.4.0.env` |
| M5 | GPT-OSS 20B | `gpt-oss:20b` | 20B dense | `ollama_gpt-oss-20b_v1.5.0.env` |

Configs at `evaluation/config/model_configs/`. Batch runner: `evaluation/scripts/run_batch_evaluation.py --model-configs <configs...>`.

The full run matrix: see `docs/manuscript/IMPLEMENTATION_TODO.md` § "Total experiment run matrix".

## Current Status (2026-05-07)

- **Benchmark refined.** Main benchmark = **8 documents** (Tier A: 6 peer-reviewed papers; Tier B: biosensor + earthworm). `biorem` and `pomato` are Phase-0 only and reported in Supplementary. `compbiobench` is a separate research direction. See `records/IMPLEMENTATION_STATUS.md` and `evaluation/datasets/DATASET_README.md`.
- **Run strategy is now broad-then-deep.** Phase 0 = 5 models × 8 docs × 4 conditions × N=1 = 160 runs. Phase 1 / Phase 2 follow. Total revised manuscript run budget ≈ 930 (down from 2,370).
- **G1 baseline evidence exists.** B1 completed on all 10 (now 8 main + 2 supp.) documents with `qwen3.6:27b`; B2 and B3 have smaller validated subsets. See `results/`.
- **G3 (statistical tests)**: implemented and tested.
- **G5 (ablation toggles)**: implemented and tested.
- **G9 (Makefile + smoke runner)**: scaffolded.
- **Row-aware full-pipeline contract fixed in code.** `metadata.json` now embeds `columns/rows` per ISA sheet and a top-level `isa_values` block, removing the earlier comparison mismatch with baselines.
- **Mapper fallback fix landed (2026-05-07).** `ISAValueMapper` rejects empty agentic matrices and falls back to deterministic `entity_id` grouping. Regression-tested.
- **Active blockers:**
  1. Local Ollama hangs on the `ISAValueMapper` LLM call for multi-file inputs (run_6 / run_7 both aborted after 46 min). Affects all Phase-0 Full-pipeline runs on multi-source documents until mitigated.
  2. M5 (`gpt-oss:20b`) is not yet registered in `run_baseline_b1.py::MODEL_CONFIGS`. Prerequisite for Phase 0.
- **Remaining manuscript gaps:** G2 standalone Hierarchical-F1 evaluator, G4 ambiguity labels, G7 Sankey, G8 cost unification, balanced full-pipeline reruns across the model matrix.
- Execution tracking: `records/IMPLEMENTATION_STATUS.md`.

Any new paper-facing output should be added here rather than scattered across `docs/`, `output/`, or ad hoc evaluation subdirectories.