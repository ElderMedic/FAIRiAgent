# Manual Evaluation Guide

## Quick Start

### 1. Setup API Keys

#### For Qwen Models:
```bash
cd /Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent
./evaluation/scripts/setup_qwen_configs.sh your_dashscope_api_key
```

#### For OpenAI Models:
```bash
cd /Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent
./evaluation/scripts/setup_openai_configs.sh your_openai_api_key
```

### 2. Run Single Model Evaluation

```bash
mamba activate FAIRiAgent

# Single model, single document
python evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation \
  --model-configs evaluation/config/model_configs/openai_gpt4o.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_v1.json \
  --output-dir evaluation/runs/manual_$(date +%Y%m%d_%H%M%S) \
  --repeats 3 \
  --workers 3
```

### 3. Run Parallel Evaluation (Multiple Models)

#### Qwen Models:
```bash
./evaluation/scripts/run_parallel_evaluation.sh
```

#### OpenAI Models:
```bash
./evaluation/scripts/run_openai_evaluation.sh [repeats] [workers]
# Example: ./evaluation/scripts/run_openai_evaluation.sh 3 5
```

#### Anthropic Models:
```bash
./evaluation/scripts/run_anthropic_evaluation.sh [repeats] [workers]
# Example: ./evaluation/scripts/run_anthropic_evaluation.sh 3 5
```

### 4. Monitor Progress

```bash
# View all logs (OpenAI)
tail -f evaluation/runs/openai_parallel_*/{gpt5,gpt4.1,gpt4o,o3}.log

# View all logs (Anthropic)
tail -f evaluation/runs/anthropic_parallel_*/{sonnet,haiku}.log

# Check running processes
ps aux | grep run_batch_evaluation

# View specific log
tail -f evaluation/runs/openai_parallel_*/gpt4o.log
```

### 5. Run Evaluation Metrics

After all runs complete, evaluation metrics are automatically computed. To manually run:

```bash
python evaluation/scripts/evaluate_outputs.py \
  --run-dir evaluation/runs/openai_parallel_YYYYMMDD_HHMMSS \
  --ground-truth evaluation/datasets/annotated/ground_truth_v1.json \
  --env-file evaluation/config/env.evaluation
```

### 6. Calculate Pass@k Metrics

Calculate pass@k metrics (probability of success in k attempts):

```bash
# Using preset criteria
python evaluation/scripts/calculate_pass_at_k.py \
  --runs-dir evaluation/runs \
  --preset moderate

# Using custom criteria
python evaluation/scripts/calculate_pass_at_k.py \
  --runs-dir evaluation/runs \
  --min-fields 10 \
  --min-req-comp 0.5 \
  --min-f1 0.3

# Save to file
python evaluation/scripts/calculate_pass_at_k.py \
  --runs-dir evaluation/runs \
  --preset moderate \
  --format json \
  --output evaluation/analysis/output/pass_at_k.json
```

Available presets:
- `basic`: Any output (fields≥1)
- `lenient`: Minimal quality (fields≥5, req_comp≥20%)
- `moderate`: Recommended (fields≥10, req_comp≥50%, F1≥0.3)
- `strict`: High quality (fields≥15, req_comp≥70%, F1≥0.5)
- `very_strict`: Publication-ready (fields≥20, req_comp≥80%, F1≥0.6)

### 7. Run Full Analysis

Generate comprehensive analysis report including pass@k:

```bash
python evaluation/analysis/run_analysis.py \
  --runs-dir evaluation/runs \
  --output-dir evaluation/analysis/output
```

## Available Model Configs

### Qwen Models (Dashscope API)
- `qwen_max.env` - Qwen Max
- `qwen_plus.env` - Qwen Plus
- `qwen_flash.env` - Qwen Flash

### OpenAI Models
- `openai_gpt5.env` - GPT-5 (may not exist yet)
- `openai_gpt4.1.env` - GPT-4.1 (may not exist yet)
- `openai_gpt4o.env` - GPT-4o
- `openai_o3.env` - O3 (may be o1 or o3-mini)

### Anthropic Models
- `anthropic_sonnet.env` - Claude Sonnet 4.5
- `anthropic_haiku.env` - Claude Haiku 4.5
- `anthropic_opus.env.disabled` - Claude Opus 4.1 (temporarily disabled)

## Model Name Notes

If a model doesn't exist, you may need to update the `FAIRIFIER_LLM_MODEL` in the config file:

- **o3** → Try `o1` or `o3-mini`
- **gpt-4.1** → Try `gpt-4-turbo` or `gpt-4`
- **gpt-5** → Try `gpt-4o` (if gpt-5 doesn't exist yet)

Check available models: https://platform.openai.com/docs/models

## Troubleshooting

### Model Not Found
If you get "model not found" errors:
1. Check the model name in the config file
2. Verify the model exists in OpenAI's API
3. Update `FAIRIFIER_LLM_MODEL` in the config file

### JSON Parsing Errors
If you see JSON parsing failures:
- This is often a model capability issue
- Try a more capable model (e.g., gpt-4o instead of gpt-4o-mini)
- Check logs for specific error details

### MinerU Not Working
- Ensure MinerU server is running: `mineru server start`
- Check `MINERU_SERVER_URL` in config matches your setup
- Verify MinerU is accessible: `curl http://localhost:30000/health`
