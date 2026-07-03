# FAIRiAgent Evaluation Framework

Comprehensive evaluation system for assessing FAIRiAgent's metadata extraction quality, comparing LLM models, and generating publication-ready results.

## Quick Start

### 1. Setup (One-time)

```bash
# Copy and configure main evaluation env
cp config/env.evaluation.template config/env.evaluation
# Edit config/env.evaluation and add your API keys

# Optional: create one or more per-model env files
cp config/env.evaluation config/model_configs/my-model.env
# Edit only the model-specific keys that should differ for that run
```

### 2. Prepare Ground Truth Dataset

```bash
# Place your PDF papers
cp /path/to/papers/*.pdf datasets/raw/

# Generate annotation templates from existing FAIRiAgent outputs
python scripts/prepare_ground_truth.py generate-template \
  --fairifier-output ../output/20251116_185736/metadata.json \
  --output datasets/annotated/paper_001_template.json

# Annotate papers (interactive guided process)
python scripts/prepare_ground_truth.py annotate \
  --template datasets/annotated/paper_001_template.json \
  --pdf datasets/raw/paper_001.pdf \
  --output datasets/annotated/paper_001_ground_truth.json

# Merge all annotations into single ground truth file
python scripts/prepare_ground_truth.py merge \
  --input-dir datasets/annotated/ \
  --output datasets/annotated/ground_truth_filtered.json

# Validate ground truth format
python scripts/prepare_ground_truth.py validate \
  --ground-truth datasets/annotated/ground_truth_filtered.json
```

### 3. Run Batch Evaluation

```bash
# Run FAIRiAgent on all papers with all model configs
python scripts/run_batch_evaluation.py \
  --env-file config/env.evaluation \
  --model-configs config/model_configs/*.env \
  --ground-truth datasets/annotated/ground_truth_filtered.json \
  --output-dir runs/batch_$(date +%Y%m%d_%H%M%S) \
  --repeats 10 \
  --workers 5 \
  --exclude-documents biorem
```

**Note (v1.2.2+)**: Each run uses isolated memory (unique `--project-id` per run). This ensures consistent, independent evaluation. See [Memory System](#memory-system-v122) for details.

### 4. Run Analysis

```bash
# Generate comprehensive analysis reports, visualizations, and tables
python analysis/run_analysis.py \
  --runs-dir runs \
  --output-dir analysis/output
```

Results will be saved to `analysis/output/`:
- **Figures**: `figures/*.png` - All visualizations
- **Tables**: `tables/*.csv`, `tables/*.tex` - LaTeX-ready tables
- **Data**: `data/*.csv` - Processed data for further analysis
- **Summary**: `analysis_summary.json` - Complete analysis summary

## Directory Structure

```
evaluation/
├── analysis/              # Analysis framework
│   ├── analyzers/         # Analysis logic
│   ├── data_loaders/      # Data loading and aggregation
│   ├── reports/           # Report generation
│   ├── visualizations/    # Plotting and visualization
│   ├── output/            # Generated results
│   └── run_analysis.py    # Main analysis entry point
├── config/                # Configuration files
│   ├── env.evaluation     # Main evaluation config
│   └── model_configs/     # Model-specific configs
├── datasets/              # Ground truth and raw data
│   ├── annotated/         # Ground truth JSON files
│   └── raw/               # Original PDF papers
├── evaluators/            # Evaluation metrics
├── runs/                  # Evaluation run outputs
│   ├── archive/           # Archived old runs
│   └── {model_name}/      # Current runs by model
│       └── {document}/    # Runs by document
│           └── run_X/     # Individual run directories
├── scripts/               # Utility scripts
│   ├── run_batch_evaluation.py    # Main batch runner
│   ├── run_baseline_batch.py     # Baseline evaluation
│   ├── evaluate_outputs.py        # Evaluation orchestrator
│   ├── rerun_failed.sh            # Rerun missing runs
│   ├── merge_rerun_to_main.py     # Merge rerun results
│   └── cleanup_incomplete_runs.py # Cleanup script
└── archive/               # Archived files
    ├── docs/              # Old documentation
    ├── scripts/           # Old/one-time scripts
    ├── logs/              # Old log files
    └── runs/              # Old run directories
```

## Key Scripts

### Batch Evaluation
- **`run_batch_evaluation.py`**: Main script for running evaluations on multiple documents with multiple models
- **`run_baseline_batch.py`**: Run baseline (single-prompt) evaluations

### Analysis
- **`analysis/run_analysis.py`**: Generate comprehensive analysis reports with visualizations and tables

### Utilities
- **`rerun_failed.sh`**: Rerun missing or failed runs to complete evaluation sets
- **`merge_rerun_to_main.py`**: Merge rerun results into main runs directory
- **`cleanup_incomplete_runs.py`**: Remove incomplete/timeout runs
- **`reorganize_runs.py`**: Reorganize runs into clean directory structure

## Evaluation Metrics

The framework evaluates:
- **Completeness / Layer 1 (metadata extraction headline)**: What fraction of GT field *names* were extracted -- see **Layer 1 headline metrics** below; extra (non-GT) fields are **not** penalized at this layer
- **Correctness (Layer 1, diagnostic)**: `field_coverage_precision` / `field_coverage_f1` -- optional diagnostics for output cleanliness, not the metadata-extraction headline
- **Value Accuracy (Layer 2)**: Whether extracted field *values* actually match ground truth
- **Structural/Hierarchical F1 (Layer 3)**: Whether fields/rows are placed in the correct ISA sheet and correctly aligned to distinct real-world entities
- **Novel Field Classification (Layer 4)**: Evidence-grounded classification of non-GT fields (beneficial discovery / domain insight / unsupported fabrication)
- **LLM Judge Score**: Internal quality assessment from critic agent
- **Workflow Reliability**: Completion rates, retry rates, failure patterns
- **Runtime**: Time taken for extraction
- **Pass@k**: Probability of successful extraction in k attempts (similar to SWE-agent benchmark)

### Layer 1 headline metrics (metadata extraction)

For **metadata extraction** benchmarking, Layer 1 is settled on **GT coverage
only** -- how much of the annotated field list was extracted. Extra fields
(beyond GT) reflect generalization, not failure, and are **not** subtracted
from the headline score.

**Report these as Layer 1 headline numbers:**

| Metric | Formula | Use |
|---|---|---|
| `overall_completeness` | `\|extracted ∩ GT\| / \|GT\|` (unique field names) | Primary headline -- same numerator/denominator as recall |
| `required_completeness` | required GT fields covered / total required | Mandatory-field coverage |
| `recommended_completeness` | recommended GT fields covered / total recommended | Recommended-field coverage |
| `field_coverage_recall` | `TP / (TP + FN)` on field **names** | Same as `overall_completeness` when GT is a flat field-name list |
| `missing_fields` / `missing_required_fields` | lists from `CompletenessEvaluator` | Which GT names were not extracted |
| `gt_field_populated_rate` | GT fields with any non-empty value / total GT | Fill rate (not value correctness) |

**Diagnostic only (do not use as metadata-extraction headline):**

| Metric | Why diagnostic |
|---|---|
| `field_coverage_precision` | Penalizes every non-GT field name (`TP / (TP+FP)`) |
| `field_coverage_f1` | Harmonic mean of recall and precision -- dominated by precision when many extras exist |

Pass@k presets (`moderate` / `strict` / `very_strict`) gate on **completeness /
recall**, not F1 or precision. Layers 2-4 remain available for value/structure/
fabrication audits when needed.

### Layer 2 headline metrics (value accuracy)

Layer 2 scores **how similar each extracted value is to GT**, on a continuous
0-1 scale per field. Semantically close but not identical strings (different
ID formats, paraphrased titles, shorthand enzyme names) receive **partial
credit** via graded scorers in ``evaluation/evaluators/_value_matching.py`` --
they are not forced into binary right/wrong except for strict controlled
vocabulary (``categorical``) fields.

**Report these as Layer 2 headline numbers:**

| Metric | Use |
|---|---|
| `value_mean_score` / `value_partial_credit_score` | Mean per-field match score (primary headline; identical formulas) |
| `match_count` / `partial_count` / `wrong_count` / `missing_count` | Diagnostic bins (thresholds 0.75 / 0.35) |

**Diagnostic:** `value_match_rate` (fraction with score ≥ 0.75 only).

### Metrics Glossary (evaluation-metrics redesign, 2026-07)

This benchmark's metrics are split into independent layers so that "did we
find the field name", "is the value correct", "is it in the right place",
and "is this extra field legitimate" are never silently conflated into one
opaque score. For every metric below: **name**, **exact formula**, **what
layer/aspect it measures**, and **how non-GT fields are treated**.

| Metric | Formula | Layer / What it measures | Non-GT fields |
|---|---|---|---|
| `field_coverage_precision` | `TP / (TP + FP)` on field **names** | Layer 1 **diagnostic** -- output cleanliness | Counted as FP (name-level only) |
| `field_coverage_recall` | `TP / (TP + FN)` on field **names** | Layer 1 **headline** -- GT field-name coverage | n/a |
| `field_coverage_f1` | harmonic mean of the two above | Layer 1 **diagnostic** | n/a |
| `gt_field_populated_rate` | (GT fields with any non-empty value) / (total GT fields) | Layer 1 -- **NOT** a correctness check, just "is it non-empty" (renamed from the old, misleading `gt_value_accuracy`) | n/a |
| `value_mean_score` | mean of `match_value(pred, gt, match_type)` per GT-populated field, type-aware; **continuous** in [0, 1] | Layer 2 **headline** -- graded value similarity (not binned right/wrong) | Not applicable (GT-populated fields only) |
| `value_match_rate` | `match_count / n_gt_populated_fields` (score ≥ 0.75 threshold) | Layer 2 diagnostic -- strict "full match" rate | Not applicable |
| `value_partial_credit_score` | same as `value_mean_score` (mean per-field score) | Layer 2 headline alias -- proportional partial credit | Not applicable |
| `sheet_placement_accuracy` | fraction of extracted fields whose `(field_name, isa_sheet)` matches GT | Layer 3a -- structural placement only, no value check | Fields not in GT for any sheet are excluded from this check |
| `row_alignment_recall` / `_precision` / `_f1` | CEAF-style (Hungarian-algorithm) optimal 1:1 GT-row ↔ predicted-row matching, then recall/precision/F1 over matched pairs | Layer 3b -- did the agent recognize the right *number* of distinct entities (didn't merge/split samples)? | Unmatched predicted rows count against precision |
| `row_count_ratio` | `pred_rows / gt_rows` across multi-row sheets | Layer 3b diagnostic -- quickly separates over-fragmentation (`>>1`) from granularity mismatch (`≈1` but low F1) | n/a |
| `value_accuracy_given_correct_structure` | Layer-2 value scoring recomputed only within correctly-aligned row pairs | Layer 3 diagnostic -- isolates value errors from alignment errors | n/a |
| `missing_field_rate_given_correct_structure` / `wrong_value_rate_given_correct_structure` | within aligned pairs: fraction of GT fields missing in pred vs present but wrong | Layer 3 diagnostic -- separates sparse rows from wrong values | n/a |
| `row_alignment_by_sheet.*.diagnostics` | per-sheet unmatched rows, avg fields/row, `fragmentation_hint` | Layer 3b drill-down for debugging petase-style fragmentation | n/a |
| `discovery_rate` | (evidence-grounded, in-FAIR-DS-vocabulary non-GT fields) / (# GT fields) | Layer 4 -- **not penalized**; genuinely useful novel fields | n/a |
| `untracked_insight_rate` | (evidence-grounded, out-of-vocabulary non-GT fields) / (# GT fields) | Layer 4 -- neutral; candidates for future schema/package extension ("may inspire researchers") | n/a |
| `precision_excl_discoveries` | `TP / (TP + unsupported_fabrication_count)` | Layer 4 -- fabrication-adjusted precision; **only** ungrounded extra fields are penalized, not all extras | Grounded extras excluded from the penalty; ungroundable (no source text available) excluded from both numerator and denominator |
| `ece` / `brier_score` | Expected Calibration Error / Brier score of self-reported field confidence vs. Layer-2 correctness | Layer 5 (fast-follow) -- confidence calibration diagnostic, not a quality score | n/a |
| `aggregate_score` | weighted sum of field-coverage recall (20%) + value accuracy (35%) + structural F1 (15%) + schema compliance (10%) + fabrication-adjusted precision (20%); see `WEIGHT_*` constants in `evaluation/scripts/evaluate_outputs.py` | Composite headline ranking number -- **not** a replacement for looking at the layers individually | `discovery_rate`/`untracked_insight_rate` are intentionally excluded from the composite (diagnostic only) |

**What replaced what:** the old `gt_value_accuracy` (`correctness_evaluator.py`)
only checked whether a GT field had *any* non-empty value -- it never
compared the value against ground truth, despite being weighted 35% of the
old aggregate score. It is now `gt_field_populated_rate` (Layer 1, clearly
labeled as non-correctness) with real value comparison moved to
`value_accuracy_evaluator.py` (Layer 2). The old confidence-based
`adjusted_precision`/`high_conf_excess`/`discovery_bonus` (exempting extra
fields from the precision penalty based on the model's own self-reported
confidence) is replaced by `novel_field_evaluator.py`'s evidence-grounded
classification (Layer 4), since self-reported confidence is not a
defensible signal for whether an extra field is actually legitimate.

### Retrieval Coverage Metrics (hybrid rollout)

The hybrid retrieval / section-map-reduce upgrade plan
(`docs/en/development/HYBRID_RETRIEVAL_AND_COVERAGE_UPGRADE_PLAN.md`) adds a
retrieval-focused evaluation layer that complements field presence metrics.
The goal is to measure whether the system actually *found* the source spans
needed for values, not only whether a field appears in `metadata.json`.

**Implemented:** `RetrievalCoverageEvaluator`, `evaluation/analysis/analyzers/retrieval_coverage.py`,
`evaluation/scripts/run_retrieval_shadow_pilot.py`, and env knobs in
`evaluation/config/env.evaluation.template`. Local shadow-gate repro configs:
`env.evaluation.shadow` + `deepseek_v4-flash_v1.4.0_fairds8083_localpkg_shadow.env`
(see plan §10.2).

Core metrics:

| Metric | Meaning |
|--------|---------|
| `section_coverage_ratio` | processed sections / planned sections, excluding duplicate-skipped sections |
| `fields_with_source_refs` | generated fields whose evidence contains a source reference |
| `fields_with_semantic_only_candidates` | fields where semantic retrieval found evidence not found by legacy lexical search |
| `fields_with_legacy_only_candidates` | fields where legacy lexical search found evidence missed by semantic retrieval |
| `qdrant_fallback_used` | whether the run continued without semantic retrieval because Qdrant was unavailable |
| `rerank_timeout_rate` | fraction of rerank batches that timed out and fell back to RRF order |

When running batch evaluation for this upgrade, remember that
`--workers` controls document-level concurrency while
`FAIRIFIER_MAPREDUCE_MAX_PARALLEL_WORKERS` controls within-document section
worker concurrency. Their product drives total LLM/API pressure.

### Pass@k Metrics

Pass@k measures the probability of at least one successful run in k attempts. Success is defined by configurable criteria:

| Preset | Fields | Required Completeness | F1 Score | Description |
|--------|--------|----------------------|----------|-------------|
| `basic` | ≥1 | 0% | 0 | Any output counts as success |
| `lenient` | ≥5 | ≥20% | 0 | Minimal quality threshold |
| `moderate` | ≥10 | ≥50% | ≥0.3 | Recommended default |
| `strict` | ≥15 | ≥70% | ≥0.5 | High quality threshold |
| `very_strict` | ≥20 | ≥80% | ≥0.6 | Publication-ready quality |

Run standalone pass@k analysis:

```bash
python scripts/calculate_pass_at_k.py \
  --runs-dir runs \
  --preset moderate \
  --output analysis/output/pass_at_k_report.md
```

### Ablation methodology recommendation (compute-normalized baseline comparison)

Layers 1-4 measure extraction *quality*; they do not by themselves attribute
quality gains to the multi-agent architecture. 2026 multi-agent-vs-single-agent
evaluation literature (e.g. "Single-Agent LLMs Outperform Multi-Agent Systems
on Multi-Hop Reasoning Under Equal Thinking Token Budgets"; "Do More Agents
Help? Controlled and Protocol-Aligned Evaluation of LLM Agent Workflows";
MASEval) converges on one finding: reported MAS gains are frequently
artifacts of **unnormalized compute/token/retry budget**, not the
architecture itself. The existing baseline-vs-agentic comparison
(`evaluation/archive/docs/BASELINE_VS_AGENTIC_COMPARISON.md`; agentic
~500s/run with up to 5 retries vs. baseline ~15s/run, one shot) is exactly
the kind of comparison that literature would flag as confounded.

**Recommendation for the next baseline-vs-agentic re-run** (methodology
only -- no new evaluator code needed beyond what Layers 1-4 plus existing
`workflow_report.json` runtime/token logging already produce):

1. Report quality **per unit of compute** alongside raw quality numbers --
   e.g. `value_partial_credit_score` per LLM call, per 1K tokens, or per
   second of wall-clock time.
2. Where feasible, add a **compute-matched single-agent control** (e.g.
   single-shot extraction with self-consistency/majority-voting sampled to
   roughly the same token/latency budget as the agentic pipeline) as a
   second baseline arm, so the "agentic architecture helps" claim survives a
   compute-normalization challenge, not just a "more filled-in fields"
   challenge.


## Analysis Outputs

### Visualizations
- Model comparison heatmaps and rankings
- Baseline vs. agentic workflow comparisons
- Workflow reliability metrics
- Failure pattern analysis
- Document-specific performance

### Tables
- Model rankings (CSV and LaTeX)
- Reliability summaries
- Agent-specific metrics
- Failure statistics
- Pass@k summaries by criteria preset (lenient/moderate/strict)
- Pass@k by document
- Multi-criteria comparison

### Data Files
- Model-level performance metrics
- Document-level performance metrics
- Workflow reliability data

## Configuration

### Excluded Models/Documents
Edit `analysis/config.py` to exclude specific models or documents from analysis:
- `EXCLUDED_MODELS`: Models to exclude (e.g., ['opus'])
- `EXCLUDED_DOCUMENTS`: Documents to exclude (e.g., ['biorem'])

### Model Display Names
Customize model names in visualizations via `MODEL_DISPLAY_NAMES` in `analysis/config.py`.

## Improved Analysis (2026-01-30)

### Meeting Feedback Implementation

Based on meeting feedback (2026-01-16), we implemented major evaluation improvements:

**1. Success Criterion: 100% Mandatory Field Coverage**
- Runs without all mandatory fields are not publication-ready
- New evaluator: `evaluators/mandatory_coverage_evaluator.py`
- Filters successful vs. failed runs

**2. Field Presence Matrix**
- Shows which fields are extracted by which models across runs
- Highlights mandatory/recommended/optional categories
- Identifies hallucinations (extra fields not in ground truth)
- Visualizer: `analysis/visualizations/field_presence_matrix.py`

**3. Stability-Completeness Trade-off Analysis**
- Answers: "Why different terms when same completeness score?"
- Core fields (100% presence) vs. variable fields
- Pattern classification: IDEAL, CONSERVATIVE, EXPLORATORY, POOR
- Analyzer: `analysis/analyzers/stability_completeness.py`

**4. Package Selection Quality**
- Evaluates if models make appropriate package choices
- Domain-package alignment analysis
- Analyzer: `analysis/analyzers/package_selection_quality.py`

**5. Hallucination Detection**
- Identifies extra fields (not in ground truth)
- Categorizes: Legitimate, Near-miss, Hallucination
- Per-model hallucination rates

### Running Improved Analysis

```bash
# Run improved analysis on existing runs
python evaluation/scripts/run_improved_analysis.py \
  --runs-dir evaluation/runs/ollama_20260129 \
  --ground-truth evaluation/datasets/annotated/ground_truth_filtered.json \
  --output-dir evaluation/analysis/improved_output

# Outputs:
# - figures/ - Publication-ready visualizations
# - tables/ - CSV data for supplementary materials  
# - ANALYSIS_SUMMARY.md - Key findings and insights
```

**Generated Visualizations:**
- Field presence matrices (with category coloring)
- Stability-completeness scatter plots
- Core fields summary by category
- Model field coverage comparisons
- Mandatory field consistency analysis
- Document-level comparisons

**For Paper:**
- Focus on success rate (% runs meeting 100% mandatory criterion)
- Field presence matrices show consensus vs. model-specific extraction
- Stability analysis explains consistency patterns
- Package selection demonstrates domain understanding

See `evaluation/EVALUATION_IMPROVEMENT_PLAN.md` for complete specification.

---

## Notes

- All runs are organized by model and document: `runs/{model_name}/{document_id}/run_X/`
- Ad hoc / tiny smoke batches (e.g. early `api_20260116_*` single-dir runs, `openai_test`) are kept under `runs/archive/` so the top-level `runs/` list stays readable.
- Each run directory contains:
  - `metadata.json`: Extracted metadata (older runs may use `metadata_json.json`)
  - `eval_result.json`: Evaluation results
  - `cli_output.txt`: CLI execution log
- Analysis automatically discovers and aggregates all runs
- Baseline comparisons are included when baseline runs are available

---

## Memory System (v1.2.2+)

FAIRiAgent v1.2.2+ includes an intelligent memory system that learns from each workflow run. The system stores and retrieves:
- Document patterns (organism types, experimental designs)
- Workflow decisions (metadata packages, ontology selections)
- Quality insights (what leads to high-quality metadata)

### Memory Isolation in Evaluation (Default)

By default, evaluation runs use **isolated memory** to ensure consistent, independent results:

```python
# Each run gets unique project-id (in run_batch_evaluation.py):
--project-id f"eval_{config_name}_{doc_id}_run{run_idx}"

# Example:
#   eval_anthropic_earthworm_run1  ← Isolated memory
#   eval_anthropic_earthworm_run2  ← Isolated memory
```

This ensures:
- ✅ Each run starts fresh (no memory contamination)
- ✅ Consistent baseline for comparison
- ✅ Fair comparison across models and documents

### Optional: Testing Memory Accumulation

To test memory learning effects, modify project-id to share memory:

```python
# Edit run_batch_evaluation.py line 438:
--project-id f"eval_{config_name}_{doc_id}"  # Shared across runs

# This allows analyzing:
#   - Run 1: Cold start (no memory)
#   - Runs 2-10: Warm start (with accumulated knowledge)
```

### Expected Effects

| Scenario | Memory | Expected Completeness |
|----------|--------|---------------------|
| **Cold Start** | Empty | 70-80% |
| **Warm Start** | Accumulated | 75-85% |
| **10+ Runs** | Rich | 80-90% |

For more details, see `../docs/MEMORY_GUIDE.md` and `EVALUATION_UPDATE_v122.md`.

---

## Langfuse Observability (Optional)

Langfuse can be enabled alongside LangSmith to provide an additional observability layer during batch evaluation. Both local Ollama and API-based models are traced in the same way — no separate configuration needed.

### Enable Langfuse for Evaluation Runs

Set the following environment variables before running the batch scripts, or add them to your evaluation `.env` file:

```bash
# Required: Langfuse credentials
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_PUBLIC_KEY="pk-lf-..."

# Optional: self-hosted Langfuse (default: cloud.langfuse.com)
# export LANGFUSE_HOST="http://localhost:3000"
```

With these set, every `fairifier.cli process` call (including those launched by `run_batch_evaluation.py`) will send traces to Langfuse in addition to any LangSmith tracing.

### Correlating Traces with Evaluation Results

Each batch run now includes a `project_id` field in `eval_result.json` (e.g. `eval_anthropic_earthworm_run1`). The same identifier is passed as `--project-id` to the FAIRifier CLI and appears in LangSmith/Langfuse trace metadata, allowing you to link a specific evaluation run to its full LLM call trace.

### Disabling Langfuse

To turn off Langfuse without removing the env variables:

```bash
export LANGFUSE_DISABLE=1
```
