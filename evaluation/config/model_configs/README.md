# Optional: per-model env files

All evaluation and FAIRiAgent model settings live in **env.evaluation.template** (copy to `env.evaluation`). You only need that one file.

If a script expects `--model-configs` or looks for `model_configs/*.env`, you can copy `env.evaluation` here as e.g. `my_model.env` so that script sees one config. For single-model runs, passing `--env-file config/env.evaluation --model-configs config/env.evaluation` (same file) also works where supported.

## Ollama presets (local)

| Config file | Model | Notes |
|---|---|---|
| `ollama_qwen3.5-9b_v1.4.0.env` | `qwen3.5:9b` | baseline small |
| `ollama_qwen3.6-27b_v1.4.0.env` | `qwen3.6:27b` | primary eval |
| `ollama_qwen3.6-35b_v1.4.0.env` | `qwen3.6:35b` | primary eval |
| `ollama_gemma4-31b_v1.4.0.env` | `gemma4:31b` | primary eval |
| `ollama_gpt-oss-20b_v1.5.0.env` | `gpt-oss:20b` | MoE reasoning |
| `ollama_gemma4-12b_v1.4.0.env` | `gemma4:12b` | new, ~7.6GB |
| `ollama_gemma4-26b_v1.4.0.env` | `gemma4:26b` | new, ~18GB |
| `ollama_granite4.1-8b_v1.4.0.env` | `granite4.1:8b` | new, ~5.3GB |
| `ollama_lfm2.5-8b_v1.4.0.env` | `lfm2.5:8b` | new, ~5.2GB |
| `ollama_laguna-xs-2.1_v1.4.0.env` | `laguna-xs-2.1` | new, ~20GB |
| `ollama_nemotron-cascade-2-30b_v1.4.0.env` | `nemotron-cascade-2:30b` | new, ~24GB |
| `ollama_qwen3-14b_v1.4.0.env` | `qwen3:14b` | new, ~9.3GB |

### Quick smoke (single document)

```bash
# Fast text smoke (~minutes) on sample_study.txt
mamba run -n FAIRiAgent python -m fairifier.cli process examples/inputs/sample_study.txt \
  --output-dir output/smoke_granite4.1-8b \
  --env-file evaluation/config/model_configs/ollama_granite4.1-8b_v1.4.0.env \
  --project-id smoke_granite4.1-8b

# Paper-bundle smoke (earthworm PDF, one model)
mamba run -n FAIRiAgent python evaluation/paper_experiments_v1/run_local_paper_smoke.py \
  --doc earthworm --models granite4.1-8b --repeats 1 --workers 1 --timeout 7200

# Batch: multiple new models on earthworm
mamba run -n FAIRiAgent python evaluation/paper_experiments_v1/run_local_paper_smoke.py \
  --doc earthworm --models gemma4-12b qwen3-14b granite4.1-8b lfm2.5-8b --repeats 1
```
