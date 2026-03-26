# FAIRiAgent Docker Deployment

This directory contains the container build, compose stack, and smoke-test scripts for FAIRiAgent.

## Quick Start

### Build the image

```bash
docker build -t fairiagent:latest -f Dockerfile .
```

### Run the API with Docker Compose

```bash
cd docker
cp ../env.example .env
# Edit .env and set at least: LLM_PROVIDER, FAIRIFIER_LLM_MODEL, LLM_API_KEY
docker compose up -d
docker compose logs -f fairifier-api
```

Services exposed by the compose stack:
- API: `http://localhost:8000`
- Health: `http://localhost:8000/health`
- Qdrant: `http://localhost:6333`

### Run one-shot CLI processing

```bash
docker run --rm \
  -v "$(pwd)/output:/app/output" \
  -v "$(pwd)/examples:/app/examples:ro" \
  -e LLM_PROVIDER=qwen \
  -e FAIRIFIER_LLM_MODEL=qwen-flash \
  -e QWEN_API_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1 \
  -e LLM_API_KEY=your_dashscope_key \
  -e FAIR_DS_API_URL=http://host.docker.internal:8083 \
  fairiagent:latest \
  python run_fairifier.py process /app/examples/inputs/earthworm_4n_paper_bioRxiv.pdf
```

## Recommended Environment

For the current project setup, the container defaults assume:
- `LLM_PROVIDER=qwen`
- `FAIRIFIER_LLM_MODEL=qwen-flash`
- `LLM_ENABLE_THINKING=false`
- `FAIRIFIER_ENABLE_DEEP_AGENTS=true`

Optional mem0 settings for API embeddings:

```bash
MEM0_ENABLED=true
MEM0_QDRANT_HOST=qdrant
MEM0_QDRANT_PORT=6333
MEM0_EMBEDDING_PROVIDER=openai
MEM0_EMBEDDING_MODEL=text-embedding-v4
MEM0_EMBEDDING_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
MEM0_EMBEDDING_DIMS=1024
```

Set `CROSSREF_MAILTO` to a real contact email if Crossref lookups are enabled.

## Useful Commands

```bash
docker run --rm fairiagent:latest python run_fairifier.py --help
docker run --rm fairiagent:latest python run_fairifier.py config-info
docker compose exec fairifier-api python run_fairifier.py validate-document --env-only
curl http://localhost:8000/health
```

## Troubleshooting

- If FAIR-DS runs on the host, keep `FAIR_DS_API_URL=http://host.docker.internal:8083`.
- If MinerU runs on the host, set `MINERU_ENABLED=true` and `MINERU_SERVER_URL=http://host.docker.internal:30000`.
- On Linux, compose injects `host.docker.internal:host-gateway`; keep that mapping unless you use host networking.
- If mem0 is enabled, ensure Qdrant is reachable and the embedding dimensions match the configured model.
