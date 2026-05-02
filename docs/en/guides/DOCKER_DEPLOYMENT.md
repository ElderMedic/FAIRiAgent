# FAIRiAgent Docker Deployment Guide

To keep the project root clean, all Docker configurations have been consolidated into this single reference guide. You can copy the sections below to create the files necessary for your specific deployment needs.

## 1. Complete System Deployment (Docker Compose)
This is the recommended way to run FAIRiAgent. It spins up the `fairifier-api`, the `FAIR-DS` knowledge base backend, and `Qdrant` (for Mem0 v3 vector memory) all in one go. It also maps the Docker socket so that the `BioMetadataAgent` can spawn BioContainers on the host machine.

Create a file named `docker-compose.yml`:

```yaml
services:
  # FAIR Data Station API (Official Image)
  fairds:
    image: docker-registry.wur.nl/m-unlock/docker/fairds:latest
    ports:
      - "8083:8083"
    environment:
      JAVA_TOOL_OPTIONS: ${FAIRDS_JAVA_TOOL_OPTIONS:--Xmx2g}
    volumes:
      - ./fairds_storage:/fairds_storage
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8083/api/package"]
      interval: 20s
      timeout: 10s
      retries: 40
      start_period: 120s
    restart: unless-stopped

  # FAIRiAgent Core API
  fairifier-api:
    build:
      context: .
      dockerfile: ${FAIRIFIER_DOCKERFILE:-Dockerfile}
    ports:
      - "8000:8000"
    environment:
      LLM_PROVIDER: ${LLM_PROVIDER:-qwen}
      FAIRIFIER_LLM_MODEL: ${FAIRIFIER_LLM_MODEL:-qwen-flash}
      QWEN_API_BASE_URL: ${QWEN_API_BASE_URL:-https://dashscope-intl.aliyuncs.com/compatible-mode/v1}
      LLM_API_KEY: ${LLM_API_KEY:-}
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY:-}
      GOOGLE_API_KEY: ${GOOGLE_API_KEY:-}
      GEMINI_API_KEY: ${GEMINI_API_KEY:-}
      LLM_ENABLE_THINKING: ${LLM_ENABLE_THINKING:-false}
      FAIRIFIER_ENABLE_DEEP_AGENTS: ${FAIRIFIER_ENABLE_DEEP_AGENTS:-true}
      FAIR_DS_API_URL: ${FAIR_DS_API_URL:-http://fairds:8083}
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
      - ./output:/app/output
      - ./kb:/app/kb
      - ./examples:/app/examples:ro
      # Required for BioMetadataAgent to spawn BioContainers on the host
      - /var/run/docker.sock:/var/run/docker.sock  
    depends_on:
      fairds:
        condition: service_healthy
      qdrant:
        condition: service_started
    restart: unless-stopped

  # Vector Database for Mem0 v3
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

### Running the System
1. Save the above block as `docker-compose.yml` in the root of the repository.
2. Run `docker compose up -d --build`.

---

## 2. Minimal FAIRiAgent Dockerfile
If you only want to build the core FAIRiAgent microservice without heavy dependencies (e.g., stripping out Playwright browser binaries) but still retaining the ability to trigger external Docker instances (like BioContainers), use this Dockerfile.

Create a file named `Dockerfile.minimal`:

```dockerfile
# ==============================================================================
# FAIRiAgent Minimal Core Dockerfile
# ==============================================================================
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ==============================================================================
FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Install the absolute minimum runtime dependencies.
# Docker CLI is installed so the container can spawn BioContainers on the host 
# via a mounted /var/run/docker.sock volume.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Copy Core FAIRiAgent Code
COPY fairifier/ ./fairifier/
COPY kb/ ./kb/
COPY run_fairifier.py .

RUN mkdir -p output logs

EXPOSE 8000

ENTRYPOINT ["python", "run_fairifier.py"]
CMD ["config-info"]
```

### Using the Minimal Image
To instruct the `docker-compose.yml` to use this lightweight image instead of the default heavy one, simply export the environment variable before running:
```bash
export FAIRIFIER_DOCKERFILE=Dockerfile.minimal
docker compose up -d --build
```