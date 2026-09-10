# Optional: per-model env files

The release-specific model profiles are the five env files selected by the
benchmark plan. Their sampling values are derived from the official cards in
`../model_card_registry.json`; do not silently replace them with the generic
defaults in `env.evaluation.template`.

### Thinking default (new profiles)

Enable `LLM_ENABLE_THINKING=true` for thinking-capable models and use that
card's **thinking-mode** sampler. Set `false` only for no-think models.
Frozen 2026-07-21 panel files below that pin non-think are historical; do not
copy that pin onto a later thinking-capable profile (for example Qwen3.8).
Sonnet 5 / Kimi K3 keep the flag false so the harness does not bind invalid
extras; those APIs still think natively.

`phase4_tuned` in comments below is a **complete-system base env**, not a
model-card or publication condition. Glossary: [evaluation/config/README.md](../README.md).

The current provisional panel is:

| Profile | Model-card capabilities used by the harness | Fixed sampling protocol |
|---|---|---|
| `deepseek_v4-flash_v1.4.0.env` | reasoning, tools, structured output; non-think/think/think-max | `temperature=1.0`, `top_p=1.0`, non-think (Preview-era panel id) |
| `deepseek_v4-flash_0731.env` | same API id `deepseek-v4-flash`, official 0731 post-train | `temperature=1.0`, `top_p=1.0`, non-think; phase4_tuned complete system |
| `deepseek_v4-pro_v1.4.0.env` | reasoning, tools, structured output; non-think/think/think-max | `temperature=1.0`, `top_p=1.0`, non-think |
| `ollama_gpt-oss.env` | reasoning, tools, function calling, structured output; low/medium/high effort | `temperature=1.0`, `top_p=1.0`, thinking disabled |
| `ollama_qwen3.6-27b_v1.4.0.env` | text/image, reasoning, tools, function calling, structured output | non-thinking card profile: `temperature=0.7`, `top_p=0.80`, `top_k=20`, `presence_penalty=1.5`, `repeat_penalty=1.0` |
| `ollama_qwen3.8-27b.env` | text/image/video, reasoning, tools, function calling, structured output | **thinking on** (default for this hybrid-thinking model); thinking-mode card: `temperature=1.0`, `top_p=0.95`, `top_k=20`, `presence_penalty=0.0`, `repeat_penalty=1.0` (PETase-3 complete-system trial; not in the 2026-07-21 frozen panel) |
| `ollama_gemma4-26b_v1.4.0.env` | text/image, reasoning, tools, function calling, structured output | `temperature=1.0`, `top_p=0.95`, `top_k=64`, thinking disabled |

### Thinking-Enabled Local & API Variants (For Independent Evaluation Runs)

These are the correct defaults for **new** runs of thinking-capable models.
The frozen 2026-07-21 non-think panel files above remain historical.

- `ollama_qwen3.6-27b_v1.4.0_thinking.env`: `LLM_ENABLE_THINKING=true`, `LLM_THINKING_BUDGET=8192`
- `ollama_gemma4-26b_v1.4.0_thinking.env`: `LLM_ENABLE_THINKING=true`, `LLM_THINKING_BUDGET=8192`
- `ollama_gpt-oss_thinking.env`: `LLM_ENABLE_THINKING=true`, `LLM_THINKING_BUDGET=8192`
- `deepseek_v4-flash_v1.4.0_thinking.env`: `LLM_ENABLE_THINKING=true`, `LLM_THINKING_BUDGET=8192`
- `ollama_qwen3.8-27b.env`: thinking on; not a `_thinking` suffix because that is already the default for this model

The capability labels are hypotheses from the cards, not evidence that a
particular serving endpoint accepts every parameter. The approval-gated
preflight must still pass endpoint reachability, context, structured-output,
and tool-contract probes before the panel is frozen. For the two Ollama
profiles, the local tag digest and quantization are recorded separately from
the static card metadata.

The Qwen3.6 profile maps the card's `repetition_penalty=1.0` to Ollama's
`repeat_penalty` through `LLM_REPEAT_PENALTY`, and passes its
`presence_penalty=1.5` through the adapter's per-call `options` mapping.

### Anthropic / Kimi backup profiles
- `anthropic_sonnet5.env`: Claude Sonnet 5 (`claude-sonnet-5`). Adaptive
  thinking on by default; `LLM_TEMPERATURE=1.0` (API default — non-default
  sampling returns 400); `LLM_MAX_TOKENS=128000`; keep
  `LLM_ENABLE_THINKING=false` so the harness does not send removed
  `budget_tokens` extended-thinking. Steer depth via API `output_config.effort`
  (`high` default; `medium` for cost-saving).
- `anthropic_sonnet.env` / `anthropic_haiku.env`: older Claude profiles
  (legacy sampling `temperature=0.2`).
- `kimi_k3.env`: Moonshot Kimi K3 via OpenAI-compatible API
  (`OPENAI_API_BASE_URL=https://api.moonshot.ai/v1`, model `kimi-k3`).
  Fixed `temperature=1.0`; thinking always on (API default
  `reasoning_effort=max`); keep `LLM_ENABLE_THINKING=false` so the harness
  does not bind invalid `reasoning_effort=medium`.
- `openai_gpt-5.6-luna.env` (and other official OpenAI reasoning profiles):
  set `LLM_REASONING_EFFORT=high` (or low/medium). FAIRiAgent auto-routes
  official `api.openai.com` traffic to the **Responses API** so Deep ReAct
  can use function tools with non-none reasoning effort. Override with
  `LLM_USE_RESPONSES_API=false` only for debugging.

For ad-hoc evaluations, all shared FAIRiAgent settings can still be copied
from **env.evaluation.template** (to `env.evaluation`). The selected release
profiles remain the source of truth for model-specific parameters.

If a script expects `--model-configs` or looks for `model_configs/*.env`, you can copy `env.evaluation` here as e.g. `my_model.env` so that script sees one config. For single-model runs, passing `--env-file config/env.evaluation --model-configs config/env.evaluation` (same file) also works where supported.
