# Production overlays

Overlay env files applied on top of a model's base env (which holds endpoints
and keys). They remove test-era caps so the models run at their documented
capacity. Pass one with `run_petase_parallel.py --overlay <file>`.

Sources for the model limits (checked 2026-11-18):
- Qwen3.8-27B model card: 262,144-token native context; reasoning up to
  262,144 and final output up to 131,072 tokens; thinking-mode sampling
  temperature 1.0, top_p 0.95, top_k 20, presence_penalty 0.0.
- DeepSeek API docs (`deepseek-flash` = DeepSeek-V4.1-Flash): 1M context,
  thinking on by default (effort `high`), context caching automatic.

`LLM_MAX_TOKENS=0` means no client-side output cap: Ollama gets
`num_predict=-1` and DeepSeek receives no `max_tokens`; generation ends at the
model's own stop or the context window. Per-call caps in the code are ignored
in that mode.
