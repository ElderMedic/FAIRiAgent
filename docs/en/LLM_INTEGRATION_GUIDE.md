# LLM Integration Guide

## Overview

FAIRiAgent supports the following LLM providers:

- `ollama` for local models
- `openai`
- `qwen`
- `gemini`
- `anthropic`

The same workflow can be used across providers. The main differences are how API keys and model names are configured.

## Core Environment Variables

Use these variables in `.env` or your shell:

```bash
LLM_PROVIDER=qwen
FAIRIFIER_LLM_MODEL=qwen-flash
LLM_API_KEY=your_api_key_here
FAIRIFIER_LLM_BASE_URL=http://localhost:11434
```

Notes:

- `FAIRIFIER_LLM_BASE_URL` is mainly used for `ollama` and OpenAI-compatible endpoints.
- `gemini` and `anthropic` use their official SDK/API endpoints and ignore `FAIRIFIER_LLM_BASE_URL`.
- `LANGSMITH_API_KEY` is optional and only needed if you want tracing.

## Provider Examples

### Ollama

```bash
LLM_PROVIDER=ollama
FAIRIFIER_LLM_MODEL=qwen3:30b
FAIRIFIER_LLM_BASE_URL=http://localhost:11434
```

### OpenAI

```bash
LLM_PROVIDER=openai
FAIRIFIER_LLM_MODEL=gpt-5.4
LLM_API_KEY=your_openai_api_key
```

### Qwen

```bash
LLM_PROVIDER=qwen
FAIRIFIER_LLM_MODEL=qwen-flash
LLM_API_KEY=your_dashscope_api_key
# Optional fallback alias used by the app:
# DASHSCOPE_API_KEY=your_dashscope_api_key
```

### Gemini

```bash
LLM_PROVIDER=gemini
FAIRIFIER_LLM_MODEL=gemini-3.1-pro-preview

# Preferred aliases:
GOOGLE_API_KEY=your_google_api_key
# or
GEMINI_API_KEY=your_google_api_key

# Generic key also works:
# LLM_API_KEY=your_google_api_key
```

### Anthropic

```bash
LLM_PROVIDER=anthropic
FAIRIFIER_LLM_MODEL=claude-sonnet-4-6
LLM_API_KEY=your_anthropic_api_key
```

## Install Requirements

Install the project dependencies first:

```bash
pip install -r requirements.txt
```

Gemini support also relies on `langchain-google-genai`, which is already included in `pyproject.toml`.

## Quick Test

```bash
cp env.example .env
# edit .env

python run_fairifier.py process examples/inputs/earthworm_4n_paper_bioRxiv.pdf
```

For the web UI (settings alongside runs):

```bash
python run_fairifier.py webui
```

Supported LLM providers (configure via `.env` or the web UI where exposed):

- Qwen
- Gemini
- OpenAI
- Ollama
- Anthropic

## Recommended Defaults

- Structured extraction: keep `LLM_TEMPERATURE=0.3`
- Development and local testing:
  - `qwen-flash`
  - `gemini-3.1-pro-preview`
  - local Ollama models if you want offline/local runs
- Use `LANGSMITH_API_KEY` only when you want tracing and debugging

## Troubleshooting

### Provider not recognized

Use one of:

- `ollama`
- `openai`
- `qwen`
- `gemini`
- `anthropic`

Aliases normalized internally:

- `google` -> `gemini`
- `claude` -> `anthropic`

### Gemini API key not found

Set one of:

- `GOOGLE_API_KEY`
- `GEMINI_API_KEY`
- `LLM_API_KEY`

### Qwen API key not found

Set one of:

- `LLM_API_KEY`
- `DASHSCOPE_API_KEY`

### Base URL confusion

- `ollama`: uses `FAIRIFIER_LLM_BASE_URL`
- `openai`: optional custom base URL, otherwise official API
- `qwen`: uses Qwen/DashScope-compatible endpoint handling
- `gemini` and `anthropic`: official SDK/API path, no custom base URL needed

## Related Pages

- [Main Docs Index](../README.md)
- [Chinese LLM Guide](../zh/LLM_INTEGRATION_GUIDE.md)
- [Chinese Quick Start](../zh/guides/QUICKSTART.md)
- [Mem0 Quick Start](../MEM0_QUICKSTART.md)
