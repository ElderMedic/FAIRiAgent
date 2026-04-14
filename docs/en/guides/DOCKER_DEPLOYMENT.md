# Docker Deployment Guide

This guide covers Docker deployment for FAIRiAgent: the Compose stack runs the FastAPI app, **FAIR Data Station (FAIR-DS)** for metadata packages/terms, and **Qdrant** for optional mem0 embeddings.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose v2
- Network access to download the FAIR-DS JAR at image build time (default: `fairds-latest.jar` from the same URL as the main README), unless you build from a local JAR (see below)
- Access to an LLM provider (API keys in `.env`)

## Compose deployment (recommended)

From the repository root:

```bash
docker build -t fairiagent:latest -f Dockerfile .
cd docker
cp ../env.example .env
```

Edit `docker/.env` and set at least your LLM provider and keys. **You usually do not need to set `FAIR_DS_API_URL`**: Compose wires the API container to the in-stack `fairds` service (`http://fairds:8083`).

Example (Qwen):

```bash
LLM_PROVIDER=qwen
FAIRIFIER_LLM_MODEL=qwen-flash
QWEN_API_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=your_dashscope_key
# FAIR_DS_API_URL=http://fairds:8083   # default in compose; omit unless you use an external FAIR-DS
```

Gemini example:

```bash
LLM_PROVIDER=gemini
FAIRIFIER_LLM_MODEL=gemini-3.1-pro-preview
GEMINI_API_KEY=your_gemini_key
```

Start the stack:

```bash
docker compose up -d --build
docker compose logs -f fairifier-api
curl http://localhost:8000/health
```

The compose stack starts:

- `fairifier-api` on `http://localhost:8000`
- `fairds` (FAIR Data Station) on `http://localhost:8083` (Swagger: `/swagger-ui/index.html`)
- `qdrant` on `http://localhost:6333`

`extra_hosts` maps `host.docker.internal` so the API can still reach **MinerU** or other tools on the host when you point env vars at them.

### FAIR-DS image: public JAR vs local JAR

- **Default:** `docker/fairds/Dockerfile` downloads `fairds-latest.jar` at build time. Nothing large is stored in git.
- **Optional local/dev JAR:** run `./pack-fairds-jar.sh` from `docker/` (copies the newest `fairds*.jar` from `~/Downloads` into `docker/fairds/fairds.jar`, gitignored), then set in `docker/.env`:

  ```bash
  FAIRDS_DOCKERFILE=Dockerfile.from-local
  ```

  Rebuild with `docker compose build fairds`.

### External FAIR-DS on the host

If you already run FAIR-DS on the host on port **8083**, stop the compose `fairds` service or change its host port mapping to avoid a bind conflict. Point the API to the host:

```bash
FAIR_DS_API_URL=http://host.docker.internal:8083
```

On Linux, Compose already adds `host.docker.internal` via `extra_hosts` in `compose.yaml`.

## One-shot CLI processing

The standalone image does **not** include FAIR-DS. Point to FAIR-DS on the host or on another container:

```bash
docker run --rm \
  -v "$(pwd)/examples:/app/examples:ro" \
  -v "$(pwd)/output:/app/output" \
  --add-host=host.docker.internal:host-gateway \
  -e LLM_PROVIDER=qwen \
  -e FAIRIFIER_LLM_MODEL=qwen-flash \
  -e QWEN_API_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1 \
  -e LLM_API_KEY=your_dashscope_key \
  -e FAIR_DS_API_URL=http://host.docker.internal:8083 \
  fairiagent:latest \
  python run_fairifier.py process /app/examples/inputs/earthworm_4n_paper_bioRXiv.pdf
```

## Publish to GitHub Container Registry (GHCR)

For repository `ElderMedic/FAIRiAgent`, publish to `ghcr.io/eldermedic/fairiagent`:

```bash
gh auth token | docker login ghcr.io -u ElderMedic --password-stdin

docker build -f Dockerfile \
  -t ghcr.io/eldermedic/fairiagent:latest \
  -t ghcr.io/eldermedic/fairiagent:1.3.1 \
  .

docker push ghcr.io/eldermedic/fairiagent:latest
docker push ghcr.io/eldermedic/fairiagent:1.3.1
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

## Operational notes

- The Docker image serves the API with `uvicorn` directly; it does not run auto-reload inside the container.
- Health checks use `/health`, not `/docs`.
- FAIR-DS may take one to two minutes to become ready on first start; `fairifier-api` waits for the `fairds` health check.
- Local development still prefers the `mamba activate FAIRiAgent` environment. Docker is a deployment/runtime path, not the primary dev environment.

## Troubleshooting

- If `fairifier-api` cannot reach FAIR-DS, run `docker compose logs fairds` and confirm `curl http://localhost:8083/api/package` from the host works while `fairds` is up.
- If mem0 fails, confirm Qdrant is up and the embedding dimension matches the configured model.
- If the API health check fails, inspect logs with `docker compose logs fairifier-api`.
- **Port 8083 in use:** another FAIR-DS instance may already be bound; stop it or remap the `fairds` ports in `compose.yaml`.
