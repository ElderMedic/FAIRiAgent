# Baseline Single-Prompt Evaluation

## Overview

This baseline evaluation system provides a comparison point for our multi-agent agentic workflow. It uses a **single comprehensive prompt** to extract FAIR metadata, without:
- ❌ Iterative refinement
- ❌ Critic feedback loops
- ❌ Validation and correction cycles
- ❌ Multiple specialized agents

This represents the **conventional LLM chat interaction** approach that most researchers would use when trying to extract metadata from scientific documents.

## Model Selection

**Primary Baseline: GPT-4o**

We use **OpenAI GPT-4o** as the baseline model because:
- ✅ **Widely adopted**: Most commonly used in research and industry
- ✅ **No agent features**: Pure LLM without built-in agentic capabilities
- ✅ **No thinking mode**: Unlike O1/O3, operates in standard inference mode
- ✅ **Representative**: Best represents what researchers typically use
- ✅ **Strong performance**: Powerful baseline makes our comparison meaningful

**Why not other models?**
- ❌ **O3/O1**: Have built-in reasoning/thinking - not a fair comparison
- ❌ **GPT-5**: Too new, less representative of current practice
- ❌ **Haiku**: Too lightweight, less convincing as baseline

## Key Differences from Agentic Workflow

| Aspect | Baseline (Single Prompt) | Agentic Workflow |
|--------|--------------------------|------------------|
| **Interaction** | One-shot LLM call | Multi-step agent collaboration |
| **Refinement** | None | Iterative with critic feedback |
| **Validation** | None | Schema validation + error correction |
| **Structure** | Single comprehensive prompt | Specialized agents (Parser, Extractor, Validator, Critic) |
| **Error Handling** | No retry mechanism | Automatic retry with feedback |
| **Confidence** | No confidence scoring | Multi-level confidence tracking |

## Files

### Core Scripts

1. **`baseline_single_prompt.py`**
   - Single extraction runner
   - Takes document + config, produces metadata JSON
   - Same output format as agentic workflow

2. **`run_baseline_batch.py`**
   - Batch runner for multiple documents × multiple runs
   - Parallel execution with thread pool
   - Structured output matching agentic evaluation format

3. **`run_baseline_all.sh`**
   - Convenience script to run all baseline evaluations
   - Configurable models and parameters

## Usage

### Quick Start

Run baseline evaluation on all documents with default settings:

```bash
bash evaluation/scripts/run_baseline_all.sh
```

### Custom Configuration

Run baseline for a specific model:

```bash
python evaluation/scripts/run_baseline_batch.py \
  --config-file evaluation/config/model_configs/openai_gpt4o.env \
  --config-name baseline_gpt4o \
  --ground-truth evaluation/datasets/annotated/ground_truth_v2.json \
  --output-dir evaluation/runs/baseline_20251205/baseline_gpt4o \
  --workers 3 \
  --n-runs 10
```

### Single Document Test

Test on a single document:

```bash
python evaluation/scripts/baseline_single_prompt.py \
  evaluation/datasets/raw/earthworm/mineru_earthworm_4n_paper_bioRxiv/earthworm_4n_paper_bioRxiv/vlm/earthworm_4n_paper_bioRxiv.md \
  --output-dir evaluation/runs/test_baseline \
  --config-file evaluation/config/model_configs/openai_gpt4o.env \
  --run-idx 1
```

## Output Structure

The baseline evaluation produces outputs in the same format as the agentic workflow:

```
evaluation/runs/baseline_20251205_120000/
├── baseline_gpt4o/
│   ├── run_metadata.json              # Batch run metadata
│   └── outputs/
│       └── baseline_gpt4o/
│           ├── earthworm/
│           │   ├── run_1/
│           │   │   ├── metadata_json.json    # ⭐ Extracted metadata
│           │   │   ├── eval_result.json      # Run status
│           │   │   ├── llm_responses.json    # LLM interaction log
│           │   │   └── cli_output.txt        # Execution log
│           │   ├── run_2/
│           │   └── ... (run_3 to run_10)
│           ├── biosensor/
│           │   └── ... (run_1 to run_10)
│           └── biorem/
│               └── ... (run_1 to run_10)
└── baseline_sonnet/
    └── ... (same structure)
```

## Evaluation

Once baseline runs are complete, evaluate them using the same evaluators:

```bash
python evaluation/scripts/evaluate_outputs.py \
  --run-dir evaluation/runs/baseline_20251205_120000/baseline_gpt4o \
  --ground-truth evaluation/datasets/annotated/ground_truth_v2.json \
  --output-dir evaluation/runs/baseline_20251205_120000/baseline_gpt4o/evaluation_results
```

This will compute:
- ✅ **Completeness**: % of required fields extracted
- ✅ **Correctness**: Precision, Recall, F1-Score
- ✅ **Schema Validity**: JSON structure compliance

## Comparison Analysis

### Option 1: Use Existing Analysis Tools

The baseline results can be analyzed alongside agentic workflow results:

```bash
python evaluation/analysis/run_analysis.py
```

This will automatically discover and compare:
- Agentic workflow runs (e.g., `openai_parallel_*`)
- Baseline runs (e.g., `baseline_*`)

### Option 2: Manual Comparison

Compare key metrics:

```python
import json

# Load agentic results
with open('evaluation/runs/openai_parallel_20251121/results/evaluation_results.json') as f:
    agentic = json.load(f)

# Load baseline results  
with open('evaluation/runs/baseline_20251205/baseline_gpt4o/evaluation_results.json') as f:
    baseline = json.load(f)

# Compare
print(f"Agentic F1: {agentic['overall_metrics']['f1_score']:.3f}")
print(f"Baseline F1: {baseline['overall_metrics']['f1_score']:.3f}")
```

## Expected Results

Based on our hypothesis, we expect:

| Metric | Baseline | Agentic | Improvement |
|--------|----------|---------|-------------|
| **Completeness** | ~60-70% | ~80-90% | +20-30% |
| **Correctness (F1)** | ~0.50-0.65 | ~0.70-0.85 | +0.15-0.25 |
| **Precision** | ~0.60-0.75 | ~0.75-0.90 | +0.10-0.20 |
| **Recall** | ~0.45-0.60 | ~0.65-0.80 | +0.15-0.25 |
| **Success Rate** | ~70-80% | ~85-95% | +10-20% |

### Why Agentic Should Be Better

1. **Iterative Refinement**: Critic agent catches errors and provides feedback
2. **Schema Validation**: Automatic validation prevents malformed output
3. **Specialized Agents**: Each agent focuses on specific aspects
4. **Error Recovery**: Retry mechanism with targeted feedback
5. **Confidence Tracking**: Multi-level confidence assessment guides human review

## Configuration

### Adjusting Baseline Prompt

Edit `BASELINE_PROMPT_TEMPLATE` in `baseline_single_prompt.py` to:
- Change instruction style
- Add/remove field requirements
- Modify output format constraints

### Testing Different Models

Add new model configs to `run_baseline_all.sh`:

```bash
declare -a CONFIGS=(
    "openai_gpt4o:evaluation/config/model_configs/openai_gpt4o.env"
    "anthropic_sonnet:evaluation/config/model_configs/anthropic_sonnet.env"
    "openai_o3:evaluation/config/model_configs/openai_o3.env"  # Add this
)
```

### Adjusting Parameters

In `run_baseline_all.sh`:
- `N_RUNS`: Number of repetitions per document (default: 10)
- `WORKERS`: Parallel workers (default: 3)
- `GROUND_TRUTH`: Path to ground truth file

## Troubleshooting

### Issue: "No module named 'fitz'"

Ensure you're in the correct conda environment:

```bash
conda activate FAIRiAgent
pip install -r requirements.txt
```

### Issue: All runs failing with JSON parsing errors

The LLM might not be following the JSON format. Check:
1. `llm_responses.json` in a failed run
2. Model supports `response_format={"type": "json_object"}`
3. Prompt is clear about JSON-only output

### Issue: Baseline seems too slow

Reduce workers or check:
- LLM API rate limits
- Network connectivity
- Token limits (prompt is truncated to 30K chars)

## Next Steps for Manuscript

1. ✅ Run baseline on same 3 documents (earthworm, biosensor, biorem)
2. ✅ Run 10 repetitions per document per model
3. ✅ Evaluate using same metrics as agentic workflow
4. 📊 Generate comparison visualizations
5. 📝 Statistical significance testing (t-test, Mann-Whitney U)
6. 📈 Create comparison tables and figures for paper

## Citation

When comparing to our agentic workflow in your manuscript:

> To establish a baseline, we compared our multi-agent agentic workflow against a conventional single-prompt LLM interaction. The baseline used a comprehensive prompt containing all schema requirements and instructions, but without iterative refinement, critic feedback, or validation loops. This represents the typical approach researchers would use when applying LLMs to metadata extraction tasks.

