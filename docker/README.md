# FAIRiAgent Docker Deployment

This directory contains the Compose stack, FAIR-DS image helpers, and smoke-test scripts.

## Quick start (API + FAIR-DS + Qdrant)

```bash
cd docker
docker build -t fairiagent:latest -f ../Dockerfile ..
cp ../env.example .env
# Edit .env: set LLM provider and API keys (FAIR_DS_API_URL defaults to the in-stack fairds service)
docker compose up -d --build
docker compose logs -f fairifier-api
curl http://localhost:8000/health
```

Services:

- **fairifier-api** — `http://localhost:8000`
- **fairds** — FAIR Data Station, `http://localhost:8083` (image builds from the public JAR URL by default)
- **qdrant** — `http://localhost:6333` (for mem0 when enabled)

### Local FAIR-DS JAR (optional)

JARs are large and not committed to git. To build the `fairds` image from a file on your machine (e.g. a dev-channel JAR from `~/Downloads`):

```bash
./pack-fairds-jar.sh
# In .env: FAIRDS_DOCKERFILE=Dockerfile.from-local
docker compose build fairds && docker compose up -d
```

### Build the API image only

From repository root:

```bash
docker build -t fairiagent:latest -f Dockerfile .
```

### Publish to GitHub Container Registry

```bash
gh auth token | docker login ghcr.io -u ElderMedic --password-stdin

# Run from repository root
docker build -f Dockerfile \
  -t ghcr.io/eldermedic/fairiagent:latest \
  -t ghcr.io/eldermedic/fairiagent:1.3.1 \
  .

docker push ghcr.io/eldermedic/fairiagent:latest
docker push ghcr.io/eldermedic/fairiagent:1.3.1
```

### One-shot CLI (no Compose)

The image does not bundle FAIR-DS; point `FAIR_DS_API_URL` at a running instance (often `host.docker.internal:8083`). See [Docker Deployment Guide](../docs/en/guides/DOCKER_DEPLOYMENT.md).

### Run one-shot CLI processing

```bash
docker run --rm \
  -v "$(pwd)/output:/app/output" \
  -v "$(pwd)/examples:/app/examples:ro" \
  --add-host=host.docker.internal:host-gateway \
  -e LLM_PROVIDER=gemini \
  -e FAIRIFIER_LLM_MODEL=gemini-3.1-pro-preview \
  -e GEMINI_API_KEY=your_gemini_key \
  -e FAIR_DS_API_URL=http://host.docker.internal:8083 \
  fairiagent:latest \
  python run_fairifier.py process /app/examples/inputs/earthworm_4n_paper_bioRXiv.pdf
```

## Recommended environment

For the current project setup, containers often use:

- `LLM_PROVIDER=qwen`
- `FAIRIFIER_LLM_MODEL=qwen-flash`
- `LLM_ENABLE_THINKING=false`
- `FAIRIFIER_ENABLE_DEEP_AGENTS=true`

Common API key variables:

- `LLM_API_KEY` (generic)
- `DASHSCOPE_API_KEY` (Qwen fallback)
- `GOOGLE_API_KEY` or `GEMINI_API_KEY` (Gemini fallback)

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

## Useful commands

```bash
docker run --rm fairiagent:latest python run_fairifier.py --help
docker run --rm fairiagent:latest python run_fairifier.py config-info
docker compose exec fairifier-api python run_fairifier.py validate-document --env-only
curl http://localhost:8000/health
```

## Troubleshooting

- If FAIR-DS runs on the host, either stop the compose `fairds` service or avoid port 8083 conflicts; set `FAIR_DS_API_URL=http://host.docker.internal:8083` when using only the host JAR.
- If MinerU runs on the host, set `MINERU_ENABLED=true` and `MINERU_SERVER_URL=http://host.docker.internal:30000`.
- On Linux, compose injects `host.docker.internal:host-gateway` for `fairifier-api` unless you change it.
- If mem0 is enabled, ensure Qdrant is reachable and embedding dimensions match the model.
- For `fairds` build failures (download), check network access to `http://download.systemsbiology.nl/unlock/fairds-latest.jar` or use `Dockerfile.from-local` after `./pack-fairds-jar.sh`.
