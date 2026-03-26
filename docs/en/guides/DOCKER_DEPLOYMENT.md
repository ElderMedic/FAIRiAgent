# Docker Deployment Guide

This guide covers the current Docker deployment path for FAIRiAgent. The compose stack exposes the FastAPI service and an optional local Qdrant instance for mem0.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose v2
- Access to an LLM provider and, if used, a FAIR-DS API endpoint

## Compose Deployment

From the repository root:

```bash
docker build -t fairiagent:latest -f Dockerfile .
cd docker
cp ../env.example .env
```

Edit `docker/.env` and set at least:

```bash
LLM_PROVIDER=qwen
FAIRIFIER_LLM_MODEL=qwen-flash
QWEN_API_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=your_dashscope_key
FAIR_DS_API_URL=http://host.docker.internal:8083
```

Start the stack:

```bash
docker compose up -d
docker compose logs -f fairifier-api
curl http://localhost:8000/health
```

The compose stack starts:
- `fairifier-api` on `http://localhost:8000`
- `qdrant` on `http://localhost:6333`

`host.docker.internal` is mapped in compose so the container can reach FAIR-DS or MinerU running on the host.

## One-Shot CLI Processing

Use the same image for batch processing:

```bash
docker run --rm \
  -v "$(pwd)/examples:/app/examples:ro" \
  -v "$(pwd)/output:/app/output" \
  -e LLM_PROVIDER=qwen \
  -e FAIRIFIER_LLM_MODEL=qwen-flash \
  -e QWEN_API_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1 \
  -e LLM_API_KEY=your_dashscope_key \
  -e FAIR_DS_API_URL=http://host.docker.internal:8083 \
  fairiagent:latest \
  python run_fairifier.py process /app/examples/inputs/earthworm_4n_paper_bioRxiv.pdf
```

## Mem0 in Docker

Enable mem0 only if Qdrant and embeddings are configured consistently:

```bash
MEM0_ENABLED=true
MEM0_QDRANT_HOST=qdrant
MEM0_QDRANT_PORT=6333
MEM0_EMBEDDING_PROVIDER=openai
MEM0_EMBEDDING_MODEL=text-embedding-v4
MEM0_EMBEDDING_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
MEM0_EMBEDDING_DIMS=1024
```

If Crossref is used, set `CROSSREF_MAILTO` to a real contact email.

## Operational Notes

- The Docker image serves the API with `uvicorn` directly; it does not run auto-reload inside the container.
- Health checks use `/health`, not `/docs`.
- Local development still prefers the `mamba activate FAIRiAgent` environment. Docker is a deployment/runtime path, not the primary dev environment.

## Troubleshooting

- If `fairifier-api` cannot reach FAIR-DS, verify the host service is listening on `0.0.0.0` or reachable via `host.docker.internal`.
- If mem0 fails, confirm Qdrant is up and the embedding dimension matches the configured model.
- If the health check fails, inspect logs with `docker compose logs fairifier-api`.
