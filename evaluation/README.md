# FAIRiAgent Evaluation Framework

Standalone evaluation system for assessing FAIRiAgent's metadata extraction quality, comparing LLM models, and generating publication-ready results.

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
  --output datasets/annotated/ground_truth_v1.json

# Validate ground truth format
python scripts/prepare_ground_truth.py validate \
  --ground-truth datasets/annotated/ground_truth_v1.json
```

### 3. Run Batch Evaluation

```bash
# Run FAIRiAgent on all papers with all model configs
# Automatically tracked in LangSmith
python scripts/run_batch_evaluation.py \
  --env-file config/env.evaluation \
  --model-configs config/model_configs/*.env \
  --ground-truth datasets/annotated/ground_truth_v1.json \
  --output-dir runs/run_$(date +%Y%m%d) \
  --workers 2
```

### 4. Evaluate Outputs

```bash
# Compute all metrics, correlations, LLM-judge scores
python scripts/evaluate_outputs.py \
  --env-file config/env.evaluation \
  --run-dir runs/run_$(date +%Y%m%d) \
  --ground-truth datasets/annotated/ground_truth_v1.json
```

### 5. Generate Report & Visualizations

```bash
# Generate publication-ready materials
python scripts/generate_report.py \
  --results-dir runs/run_$(date +%Y%m%d)/results \
  --output-dir runs/run_$(date +%Y%m%d)/manuscript_materials \
  --langsmith-project fairifier-evaluation
```

## Directory Structure

```
evaluation/
├── datasets/
│   ├── raw/                    # Your PDF papers
│   └── annotated/              # Ground truth annotations
├── runs/                       # Evaluation runs
│   └── {run_id}/
│       ├── outputs/            # FAIRiAgent outputs per document
│       └── results/            # Evaluation results
├── scripts/                    # Automation scripts
├── evaluators/                 # Evaluation modules
├── visualizations/             # Plotting scripts
├── config/                     # Configuration files
└── README.md                   # This file
```

## What You Need to Provide

### Required
- ✅ 20-50 PDF papers in `datasets/raw/`
- ✅ Ground truth annotations (tool-assisted)
- ✅ LangSmith API key
- ✅ LLM API keys (Anthropic, OpenAI, or Ollama setup)

### Provided by System
- ✅ Ground truth annotation tools
- ✅ All evaluation metrics
- ✅ LangSmith tracking
- ✅ Visualizations and reports
- ✅ Statistical analysis

## Ground Truth Annotation Standards

When annotating papers, follow these guidelines:

1. **Required Fields**: Annotate ALL required fields (investigation title, study description, etc.)
2. **Recommended Fields**: Annotate where present in document
3. **Optional Fields**: Annotate if time permits (improves evaluation)
4. **Variations**: Include acceptable phrasings for each field
5. **Evidence**: Note where in document the information appears

See `datasets/annotated/ground_truth_template.json` for structure.

## Evaluation Metrics

### Quality Metrics
- **Completeness**: Field coverage (overall, required, by ISA sheet)
- **Correctness**: Exact match, semantic match, F1 scores
- **Schema Compliance**: JSON structure, required fields, data types
- **Ontology Alignment**: Term usage, validity, appropriateness

### Internal Metric Validation
- Correlation: Critic score vs correctness
- Correlation: Confidence vs correctness
- Correlation: Overall confidence vs quality

### Efficiency Metrics
- Runtime per document
- Token usage per model
- Cost per template
- Retry patterns

## LangSmith Integration

All evaluation runs are automatically tracked in LangSmith:

- Each model gets separate project: `fairifier-eval-{provider}-{model}`
- Filter by `document_id` to compare models on one paper
- Filter by `model_config` to see one model across all papers
- Access token counts, latency, error rates directly

Visit https://smith.langchain.com/ after running evaluations.

## Output Files

After running full evaluation, you'll have:

```
runs/run_20251121/
├── outputs/                    # All FAIRiAgent outputs
│   ├── anthropic_claude_sonnet_4/
│   │   └── paper_001/
│   │       ├── metadata_json.json
│   │       ├── workflow_report.json
│   │       └── processing_log.jsonl
│   └── openai_gpt_4o/
│       └── paper_001/
│           └── ...
├── results/
│   ├── evaluation_results.json     # All metrics
│   ├── model_comparison.json       # Model vs model
│   └── correlations.json           # Internal metric validation
└── manuscript_materials/
    ├── figures/                    # PNG + PDF plots
    │   ├── model_comparison_heatmap.pdf
    │   ├── confidence_calibration.pdf
    │   └── ...
    ├── tables/                     # LaTeX tables
    │   ├── model_comparison.tex
    │   └── metrics_summary.tex
    ├── evaluation_summary.md       # Manuscript-ready text
    └── evaluation_report.json      # Complete raw data
```

## Troubleshooting

### Ground Truth Validation Errors
```bash
# Check format
python scripts/prepare_ground_truth.py validate \
  --ground-truth datasets/annotated/ground_truth_v1.json
```

### LangSmith Connection Issues
- Verify `LANGSMITH_API_KEY` in `config/env.evaluation`
- Check https://smith.langchain.com/ for active projects

### Model Configuration Issues
- Ensure API keys are correct in `config/model_configs/*.env`
- For Ollama: Check `http://localhost:11434` is accessible

### Evaluation Fails on Specific Papers
- Check FAIRiAgent logs in `runs/{run_id}/outputs/{model}/{paper}/processing_log.jsonl`
- Review LangSmith trace for that specific run

## Dependencies

All dependencies should already be installed if you have FAIRiAgent working. Additional requirements:

```bash
pip install pandas matplotlib seaborn scikit-learn scipy jsonschema
```

## Support

For issues with:
- **FAIRiAgent core**: See main project README
- **Evaluation framework**: Check this README and configuration templates
- **LangSmith**: Visit https://docs.smith.langchain.com/

## Citation

If using this evaluation framework, please cite the FAIRiAgent project and mention the evaluation methodology in your manuscript.

