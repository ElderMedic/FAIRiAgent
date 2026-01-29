# Optional: per-model env files

All evaluation and FAIRiAgent model settings live in **env.evaluation.template** (copy to `env.evaluation`). You only need that one file.

If a script expects `--model-configs` or looks for `model_configs/*.env`, you can copy `env.evaluation` here as e.g. `my_model.env` so that script sees one config. For single-model runs, passing `--env-file config/env.evaluation --model-configs config/env.evaluation` (same file) also works where supported.
