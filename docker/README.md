# FAIRiAgent Docker

Minimal Docker usage for CLI and API.

## Quick Start (CLI)

From the project root:

```bash
# 1) Copy config template
cp env.example .env

# 2) Build image (run from project root)
docker build -t fairiagent:latest .

# 3) Run CLI on a test file
cd docker
./test-cli.sh

# Or specify a test file
./test-cli.sh BIOREM_appendix2.pdf
```

## Quick Start (API)

```bash
# From docker directory
cd docker
docker-compose up -d

# API Docs: http://localhost:8000/docs
```

## Environment Variables

Use the root template: `env.example`. The script loads `docker/.env` first,
then falls back to the root `.env`.

Most users only need:
```bash
LLM_PROVIDER=ollama
FAIRIFIER_LLM_MODEL=qwen3:30b-a3b
FAIRIFIER_LLM_BASE_URL=http://host.docker.internal:11434
```

For OpenAI:
```bash
LLM_PROVIDER=openai
FAIRIFIER_LLM_MODEL=gpt-5.2-2025-12-11
LLM_API_KEY=your_api_key_here
```

## Notes

- Run `docker build` from the project root (not inside `docker/`).
- Test inputs are in `examples/inputs/`.
- For FAIR-DS on your host machine, set `FAIR_DS_API_URL=http://host.docker.internal:8083`.
