# FAIRiAgent Docker Deployment

This directory contains Docker configurations for deploying FAIRiAgent.

## Quick Start

### 1. Build the Image

```bash
# From project root
docker build -t fairiagent:latest -f Dockerfile .
```

### 2. Run with Docker Compose

```bash
# Start all services (FAIRiAgent API + Qdrant)
cd docker
docker-compose up -d

# Check logs
docker-compose logs -f fairifier-api

# Stop services
docker-compose down
```

### 3. Run Standalone (CLI Mode)

```bash
# Process a document
docker run --rm \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/kb:/app/kb \
  fairiagent:latest python run_fairifier.py process kb/example.pdf

# Show help
docker run --rm fairiagent:latest python run_fairifier.py --help
```

## Available Images

### Latest Stable
- `fairiagent:latest` - Latest stable build
- `fairiagent:1.1.0-mem0` - Version 1.1.0 with mem0 integration

### Version History
- See `DOCKER_VERSION_1.1.0-mem0.md` for version 1.1.0-mem0 details
- See `CHANGELOG.md` in project root for full history

## Configuration

### Environment Variables

Create a `.env` file in the `docker/` directory:

```bash
# LLM Configuration
LLM_PROVIDER=qwen
FAIRIFIER_LLM_MODEL=qwen-max
LLM_API_KEY=your-api-key-here
LLM_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1

# FAIR-DS API (external)
FAIR_DS_API_URL=http://host.docker.internal:8083

# mem0 Configuration (optional)
MEM0_ENABLED=false
MEM0_QDRANT_HOST=qdrant
MEM0_QDRANT_PORT=6333

# LangSmith (optional)
LANGSMITH_API_KEY=your-langsmith-key
LANGSMITH_PROJECT=fairifier
```

### Volume Mounts

Default mounts in `compose.yaml`:
- `../output:/app/output` - Processing results
- `../kb:/app/kb` - Knowledge base files

Add custom mounts as needed:
```yaml
volumes:
  - ../output:/app/output
  - ../kb:/app/kb
  - ../custom-data:/app/data  # Custom mount
```

## Service Architecture

### FAIRiAgent API
- **Port**: 8000
- **Health Check**: http://localhost:8000/docs
- **Depends On**: Qdrant (if mem0 enabled)

### Qdrant Vector Database
- **Port**: 6333
- **Web UI**: http://localhost:6333/dashboard
- **Purpose**: mem0 memory storage (optional)

## Advanced Usage

### Custom Dockerfile Builds

```bash
# Build with specific Python version
docker build --build-arg PYTHON_VERSION=3.11 -t fairiagent:py311 .

# Build without cache
docker build --no-cache -t fairiagent:latest .
```

### Multi-Stage Deployment

For production deployments, consider:

1. **Separate services**:
   - FAIRiAgent API
   - FAIR-DS API (external)
   - Qdrant (if using mem0)
   - LLM provider (Ollama or cloud service)

2. **Resource limits**:
```yaml
services:
  fairifier-api:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
```

3. **Persistent storage**:
```yaml
volumes:
  - fairifier-output:/app/output
  - qdrant-data:/qdrant/storage
```

### Health Checks

Monitor service health:
```bash
# Check FAIRiAgent API
curl http://localhost:8000/docs

# Check Qdrant
curl http://localhost:6333/
```

### Debugging

```bash
# Access container shell
docker exec -it fairiagent_api bash

# View logs
docker logs -f fairiagent_api

# Inspect configuration
docker exec fairiagent_api python run_fairifier.py config-info
```

## Testing

### Quick Test

```bash
# Test CLI help
docker run --rm fairiagent:latest python run_fairifier.py --help

# Test with sample document
docker run --rm \
  -v $(pwd)/output:/app/output \
  fairiagent:latest python run_fairifier.py process /app/kb/sample.pdf
```

### Integration Test with docker-compose

```bash
cd docker

# Start services
docker-compose up -d

# Wait for services to be ready
sleep 30

# Test API
curl http://localhost:8000/docs

# Run test script (if available)
./test-cli.sh
```

## Troubleshooting

### Common Issues

1. **Port already in use**
   ```bash
   # Change port in compose.yaml
   ports:
     - "8001:8000"  # Map to different host port
   ```

2. **Qdrant connection failed**
   ```bash
   # Check Qdrant is running
   docker ps | grep qdrant
   
   # Check network
   docker network inspect docker_default
   ```

3. **Out of memory**
   ```bash
   # Increase Docker memory limit
   # Docker Desktop → Settings → Resources → Memory
   ```

4. **Volume permission issues**
   ```bash
   # Fix permissions
   sudo chown -R $(id -u):$(id -g) output/
   ```

### Log Collection

```bash
# Collect all logs
docker-compose logs > logs/docker-compose-$(date +%Y%m%d_%H%M%S).log

# Export container info
docker inspect fairiagent_api > logs/container-info.json
```

## Production Deployment

### Recommended Setup

1. **Use external databases**:
   - Deploy Qdrant separately
   - Use managed vector DB service

2. **Configure secrets**:
   - Use Docker secrets or env files
   - Never commit `.env` files

3. **Enable monitoring**:
   - Add Prometheus metrics
   - Configure logging aggregation

4. **Set up backups**:
   - Regular backup of Qdrant data
   - Archive processing outputs

### Example Production Compose

```yaml
version: '3.8'

services:
  fairifier-api:
    image: fairiagent:1.1.0-mem0
    restart: always
    environment:
      - LLM_PROVIDER=${LLM_PROVIDER}
      - FAIRIFIER_LLM_MODEL=${FAIRIFIER_LLM_MODEL}
      - LLM_API_KEY=${LLM_API_KEY}
    volumes:
      - fairifier-output:/app/output:rw
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/docs"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

volumes:
  fairifier-output:
    driver: local
```

## Updates

To update to a new version:

```bash
# Pull new image
docker pull fairiagent:latest

# Or rebuild
docker build -t fairiagent:latest .

# Restart services
docker-compose down
docker-compose up -d
```

## Support

- Documentation: `../docs/`
- Version details: `DOCKER_VERSION_*.md` files
- Issues: Check project repository

