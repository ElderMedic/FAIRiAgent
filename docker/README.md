# FAIRiAgent Docker Deployment

This folder contains the complete deployment ecosystem for FAIRiAgent. Below is a unified guide to understanding and running the Docker configurations provided here.

## 1. Official FAIR-DS Integration
We use the official FAIR Data Station Docker image provided by the M-Unlock team. 
- **Image**: `docker-registry.wur.nl/m-unlock/docker/fairds:latest`
- **Storage**: The `compose.yaml` automatically mounts `./fairds_storage` to ensure your ontologies and cached packages persist across container restarts.

Whenever the official FAIR-DS team pushes an update, a simple `docker compose pull fairds` will keep your knowledge base backend up-to-date.

## 2. Complete System Deployment (`compose.yaml`)
`compose.yaml` is the all-in-one deployment script that sets up:
1. `fairds`: The FAIR Data Station API.
2. `qdrant`: The Vector database (v1.13.0+) required for Mem0 v3 hybrid search.
3. `fairifier-api`: The core Agent.

**BioContainers Support**: The `compose.yaml` includes a volume mount for `/var/run/docker.sock`. This allows the inner `BioMetadataAgent` to spawn independent Docker containers (like `samtools` from quay.io) directly on your host machine to analyze raw biological data without bloating the main image.

**To run the complete system:**
```bash
cd docker
docker compose up -d --build
```

## 3. The Minimal Dockerfile (`Dockerfile.minimal`)
In addition to the main `Dockerfile` in the repository root (which includes Playwright for deep web scraping and complex PDF extraction), we provide `Dockerfile.minimal` here. 

**Why use it?**
- **Zero Bloat**: It completely removes Playwright and heavy browser binaries.
- **Microservices Ready**: It relies entirely on external services (like MinerU) for heavy lifting, making the container start instantly and consume minimal space.
- **Bio-Ready**: It includes the lightweight `docker.io` CLI so it can still orchestrate external BioContainers.

**To use the minimal image with Docker Compose:**
```bash
cd docker
export FAIRIFIER_DOCKERFILE=Dockerfile.minimal
docker compose up -d --build fairifier-api
```
