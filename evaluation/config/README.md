# Evaluation configuration

- **env.evaluation.template** – Single template. Copy to `env.evaluation` (or `.env` in evaluation context) and fill in: FAIRiAgent model (`LLM_PROVIDER`, `FAIRIFIER_LLM_MODEL`, `LLM_API_KEY`), judge keys, paths. LangSmith tracing is off by default; opt in with `LANGCHAIN_TRACING_V2=true` plus a key. Covers both which model FAIRiAgent uses and evaluation/judge settings.

All `*.env` and `*.env.*` files under `evaluation/config/` are gitignored; do not commit files that contain API keys. Only `*.template` and `*.example` are tracked.

## Env-file aliases (`phase4_tuned`, `shadow`, …)

These filenames are 2026-07 hybrid-retrieval rollout labels. They are **not**
benchmark v2 condition IDs. Publication language stays in
`evaluation/schemas/condition_registry.json` (for example Complete FAIRiAgent
system). Do not put `phase4` or `tuned` on figures or manifests.

| Env file | What it actually is |
|---|---|
| `env.evaluation.shadow` | Hybrid is computed, but the LLM prompt still sees lexical snippets (`FAIRIFIER_RETRIEVAL_SHADOW_MODE=true`). |
| `env.evaluation.phase4` | First hybrid-**in-prompt** env (`SHADOW_MODE=false`). Wider snippet/rerank budget than tuned. |
| `env.evaluation.phase4_tuned` | Same hybrid-in-prompt as phase4, plus lexical-priority blend and a tighter budget: `FAIRIFIER_RETRIEVAL_FINAL_SNIPPETS=5`, `FAIRIFIER_METADATA_MAX_EVIDENCE_SNIPPETS_PER_FIELD=3`, `FAIRIFIER_RETRIEVAL_RERANK_CANDIDATES=12`, `FAIRIFIER_RETRIEVAL_SEMANTIC_MAX_HITS=16`. Usual v2 **complete-system `--base-env`**. |
| `env.evaluation.shadow_tuned` | Same tuned budget as `phase4_tuned`, still lexical-in-prompt (A/B control). |

`dimfix` / `auto` are later engineering checkpoints in historical run names,
not new publication conditions. Parameter history:
[Hybrid Retrieval and Coverage Upgrade Plan](../../docs/en/development/HYBRID_RETRIEVAL_AND_COVERAGE_UPGRADE_PLAN.md)
§10.3–10.4.
