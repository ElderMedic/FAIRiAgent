# Evaluation configuration

- **env.evaluation.template** – Single template. Copy to `env.evaluation` (or `.env` in evaluation context) and fill in: LangSmith keys, FAIRiAgent model (`LLM_PROVIDER`, `FAIRIFIER_LLM_MODEL`, `LLM_API_KEY`), judge keys, paths. Covers both which model FAIRiAgent uses and evaluation/judge settings.

All `*.env` and `*.env.*` files under `evaluation/config/` are gitignored; do not commit files that contain API keys. Only `*.template` and `*.example` are tracked.
