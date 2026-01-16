# FAIRiAgent Evaluation Framework

Comprehensive evaluation system for assessing FAIRiAgent's metadata extraction quality, comparing LLM models, and generating publication-ready results.

## Quick Start

### 1. Setup (One-time)

```bash
# Copy and configure main evaluation env
cp config/env.evaluation.template config/env.evaluation
# Edit config/env.evaluation and add your API keys

# Copy and configure model-specific envs
cp config/model_configs/anthropic.env.template config/model_configs/anthropic.env
cp config/model_configs/openai.env.template config/model_configs/openai.env
# Edit each and add your API keys
```

### 2. Prepare Ground Truth Dataset

```bash
# Place your PDF papers
cp /path/to/papers/*.pdf datasets/raw/

# Generate annotation templates from existing FAIRiAgent outputs
python scripts/prepare_ground_truth.py generate-template \
  --fairifier-output ../output/20251116_185736/metadata_json.json \
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
- **Completeness**: How many fields are extracted vs. ground truth
- **Correctness**: Precision, recall, and F1-score of extracted fields
- **LLM Judge Score**: Internal quality assessment from critic agent
- **Workflow Reliability**: Completion rates, retry rates, failure patterns
- **Runtime**: Time taken for extraction
- **Pass@k**: Probability of successful extraction in k attempts (similar to SWE-agent benchmark)

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

## Notes

- All runs are organized by model and document: `runs/{model_name}/{document_id}/run_X/`
- Each run directory contains:
  - `metadata_json.json`: Extracted metadata
  - `eval_result.json`: Evaluation results
  - `cli_output.txt`: CLI execution log
- Analysis automatically discovers and aggregates all runs
- Baseline comparisons are included when baseline runs are available
