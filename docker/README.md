# FAIRiAgent Docker Deployment

This folder contains the complete deployment ecosystem for FAIRiAgent. Below is a unified guide to understanding and running the Docker configurations provided here.

## 1. Official FAIR-DS Integration
We use the official FAIR Data Station Docker image provided by the M-Unlock team.
- **Image**: `docker-registry.wur.nl/m-unlock/docker/fairds:latest` *(WUR-internal registry; for public use, replace with a publicly accessible FAIR-DS image or contact the M-Unlock team)*
- **Platform**: `linux/amd64` (required on Apple Silicon; Compose sets this automatically)
- **Storage**: `./fairds_storage` is mounted at `/root/fairds_storage` so ontologies and cached packages persist across restarts

Whenever the official FAIR-DS team pushes an update, a simple `docker compose pull fairds` will keep your knowledge base backend up-to-date.

To refresh a local JAR copy (optional, not used by the default compose image path):

```bash
# from repo root
./scripts/update_fairds_jar.sh
# writes docker/fairds/fairds.jar
```

## 2. Complete System Deployment (`compose.yaml`)
`compose.yaml` is the all-in-one deployment script that sets up:
1. `fairds`: The FAIR Data Station API.
2. `qdrant`: The Vector database (v1.13.0+) required for Mem0 v3 hybrid search.
3. `fairifier-api`: The core Agent.

**BioContainers Support**: The `compose.yaml` includes a volume mount for `/var/run/docker.sock`. This allows the inner `BioMetadataAgent` to spawn independent Docker containers (like `samtools` from quay.io) directly on your host machine to analyze raw biological data without bloating the main image.

**To run the complete system:**
```bash
cd docker
cp .env.example .env   # set LLM_PROVIDER + API key (or Ollama)
docker compose up -d --build
```

Then follow the smoke checks in the root [README](../README.md#option-a--docker-compose-recommended).

API: http://localhost:8000 · FAIR-DS: http://localhost:8083 · Qdrant: http://localhost:6333  
If host port 8000 is busy: `FAIRIFIER_HOST_PORT=8001 docker compose up -d --build`.

**Host Ollama**: Compose defaults `FAIRIFIER_LLM_BASE_URL` to `http://host.docker.internal:11434`. Start Ollama on the host (`ollama serve`) and pull your model before processing documents. MinerU stays off by default (`MINERU_ENABLED=false`).

## 3. The Minimal Dockerfile (`Dockerfile.minimal`)
In addition to the main `Dockerfile` in the repository root (which includes Playwright for deep web scraping and complex PDF extraction), we provide `Dockerfile.minimal` here.

**Why use it?**
- **Zero Bloat**: It completely removes Playwright and heavy browser binaries.
- **Microservices Ready**: It relies entirely on external services (like MinerU) for heavy lifting, making the container start instantly and consume minimal space.
- **Bio-Ready**: It includes the lightweight `docker.io` CLI so it can still orchestrate external BioContainers.

**To use the minimal image with Docker Compose** (path is relative to the repo root because `build.context` is `..`):
```bash
cd docker
export FAIRIFIER_DOCKERFILE=docker/Dockerfile.minimal
docker compose up -d --build fairifier-api
```

## 4. More detail
See [Docker Deployment Guide](../docs/en/guides/DOCKER_DEPLOYMENT.md).
