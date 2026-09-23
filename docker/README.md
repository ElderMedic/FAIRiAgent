# FAIRiAgent Docker Deployment

This folder contains the complete deployment ecosystem for FAIRiAgent. Below is a unified guide to understanding and running the Docker configurations provided here.

## 1. FAIR-DS Integration
The default Compose service pulls the official image:

`docker-registry.wur.nl/m-unlock/docker/fairds:latest`

That manifest is **linux/amd64 only**. Check the host before the first pull:

```bash
./check_fairds_platform.sh
docker compose up -d --build
```

- **amd64 hosts** match the image and pull it directly.
- **Apple Silicon and other ARM hosts** get `no matching manifest for linux/arm64` from a plain `docker pull`. Compose sets `platform: linux/amd64`, so Docker Desktop runs the same image under emulation.
- **No emulation, or the pull still fails:** build the public JAR for this CPU, or skip the container and use Java 21 / conda.

```bash
# Native JAR image (set FAIRDS_PLATFORM=linux/arm64 on Apple Silicon)
FAIRDS_PLATFORM=linux/arm64 docker compose \
  -f compose.yaml -f compose.fairds-jar.yaml up -d --build fairds
```

```bash
# From the repository root, no FAIR-DS container
./scripts/update_fairds_jar.sh
java -Dserver.port=8083 -jar docker/fairds/fairds.jar
```

Storage for the container stays at `./fairds_storage` → `/root/fairds_storage`.

To refresh a local JAR copy (host Java, or the optional native image):

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
