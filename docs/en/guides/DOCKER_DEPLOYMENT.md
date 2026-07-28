# FAIRiAgent Docker Deployment Guide

Canonical Compose and Dockerfiles live under [`docker/`](../../../docker/). Prefer those files over copying snippets by hand.

## 1. Complete System Deployment (Docker Compose)

Recommended path: run the checked-in compose file so FAIR-DS, Qdrant, and the FAIRiAgent API start together (Docker socket is mounted for BioContainers).

```bash
cd docker
# Optional: set LLM_PROVIDER / API keys / FAIRIFIER_LLM_BASE_URL in docker/.env
docker compose up -d --build
```

| Service | URL |
| --- | --- |
| FAIRiAgent API / Web UI | http://localhost:8000 |
| FAIR-DS | http://localhost:8083 |
| Qdrant | http://localhost:6333 |

Notes for new users:

- **Apple Silicon**: `fairds` is pinned to `platform: linux/amd64` (official image has no arm64 manifest).
- **Healthcheck**: the FAIR-DS image has no `curl`; compose probes the port with bash `/dev/tcp`.
- **Storage**: host `docker/fairds_storage` → container `/root/fairds_storage`.
- **Ollama on the host**: default `FAIRIFIER_LLM_BASE_URL=http://host.docker.internal:11434`.
- **MinerU**: off by default (`MINERU_ENABLED=false`).

Equivalent service definition (keep in sync with `docker/compose.yaml`):

```yaml
services:
  fairds:
    image: docker-registry.wur.nl/m-unlock/docker/fairds:latest
    platform: linux/amd64
    ports:
      - "8083:8083"
    environment:
      JAVA_TOOL_OPTIONS: ${FAIRDS_JAVA_TOOL_OPTIONS:--Xmx2g}
    volumes:
      - ./fairds_storage:/root/fairds_storage
    healthcheck:
      test: ["CMD-SHELL", "bash -c 'exec 3<>/dev/tcp/127.0.0.1/8083'"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 90s
    restart: unless-stopped

  fairifier-api:
    build:
      context: ..
      dockerfile: ${FAIRIFIER_DOCKERFILE:-Dockerfile}
    ports:
      - "8000:8000"
    environment:
      LLM_PROVIDER: ${LLM_PROVIDER:-qwen}
      FAIRIFIER_LLM_MODEL: ${FAIRIFIER_LLM_MODEL:-qwen-flash}
      FAIRIFIER_LLM_BASE_URL: ${FAIRIFIER_LLM_BASE_URL:-http://host.docker.internal:11434}
      QWEN_API_BASE_URL: ${QWEN_API_BASE_URL:-https://dashscope-intl.aliyuncs.com/compatible-mode/v1}
      LLM_API_KEY: ${LLM_API_KEY:-}
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY:-}
      GOOGLE_API_KEY: ${GOOGLE_API_KEY:-}
      GEMINI_API_KEY: ${GEMINI_API_KEY:-}
      LLM_ENABLE_THINKING: ${LLM_ENABLE_THINKING:-false}
      FAIRIFIER_ENABLE_DEEP_AGENTS: ${FAIRIFIER_ENABLE_DEEP_AGENTS:-true}
      FAIR_DS_API_URL: ${FAIRIFIER_COMPOSE_FAIR_DS_URL:-http://fairds:8083}
      MINERU_ENABLED: ${MINERU_ENABLED:-false}
      MINERU_SERVER_URL: ${MINERU_SERVER_URL:-http://host.docker.internal:30000}
      CHECKPOINTER_BACKEND: ${CHECKPOINTER_BACKEND:-sqlite}
      QDRANT_URL: ${QDRANT_URL:-http://qdrant:6333}
      MEM0_ENABLED: ${MEM0_ENABLED:-false}
      MEM0_QDRANT_HOST: ${MEM0_QDRANT_HOST:-qdrant}
      MEM0_QDRANT_PORT: ${MEM0_QDRANT_PORT:-6333}
      MEM0_EMBEDDING_PROVIDER: ${MEM0_EMBEDDING_PROVIDER:-openai}
      MEM0_EMBEDDING_MODEL: ${MEM0_EMBEDDING_MODEL:-text-embedding-v4}
      MEM0_EMBEDDING_BASE_URL: ${MEM0_EMBEDDING_BASE_URL:-https://dashscope-intl.aliyuncs.com/compatible-mode/v1}
      MEM0_EMBEDDING_API_KEY: ${MEM0_EMBEDDING_API_KEY:-}
      MEM0_EMBEDDING_DIMS: ${MEM0_EMBEDDING_DIMS:-1024}
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ../output:/app/output
      - ../kb:/app/kb
      - ../examples:/app/examples:ro
      - /var/run/docker.sock:/var/run/docker.sock
    depends_on:
      fairds:
        condition: service_healthy
      qdrant:
        condition: service_started
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:v1.13.0
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage
    restart: unless-stopped

volumes:
  qdrant_data:
```

---

## 2. Minimal FAIRiAgent Dockerfile

Use [`docker/Dockerfile.minimal`](../../../docker/Dockerfile.minimal) for a lighter image without Playwright browsers (still includes Docker CLI for BioContainers).

```bash
cd docker
export FAIRIFIER_DOCKERFILE=docker/Dockerfile.minimal
docker compose up -d --build fairifier-api
```

`FAIRIFIER_DOCKERFILE` is resolved relative to the **repository root** (`build.context: ..`), so the value must be `docker/Dockerfile.minimal`, not `Dockerfile.minimal`.

To refresh a local FAIR-DS JAR (optional):

```bash
./scripts/update_fairds_jar.sh
```
