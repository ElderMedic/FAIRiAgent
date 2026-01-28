# Docker Deployment Guide

This guide covers deploying FAIRiAgent using Docker and Docker Compose.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose v2.0+

## Quick Start

### Using Docker Compose (Recommended)

The easiest way to deploy FAIRiAgent with all dependencies:

```bash
# Navigate to docker directory
cd docker

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

This will start:
- **FAIRiAgent API** (http://localhost:8000)
- **FAIRiAgent UI** (http://localhost:8501)
- **Qdrant** vector database (optional)

### Using Dockerfile Only

For standalone deployment:

```bash
# Build the image
docker build -t fairiagent:latest .

# Run API server
docker run -d -p 8000:8000 \
  -e LLM_PROVIDER=ollama \
  -e FAIRIFIER_LLM_MODEL=qwen3:30b \
  fairiagent python run_fairifier.py api

# Run UI
docker run -d -p 8501:8501 \
  -e LLM_PROVIDER=ollama \
  -e FAIRIFIER_LLM_MODEL=qwen3:30b \
  fairiagent python run_fairifier.py ui

# Run CLI for one-time processing
docker run --rm \
  -v $(pwd)/document.pdf:/app/document.pdf \
  -v $(pwd)/output:/app/output \
  fairiagent python run_fairifier.py process /app/document.pdf
```

## Configuration

### Environment Variables

Create a `.env` file in the project root or set environment variables:

```bash
# LLM Configuration
LLM_PROVIDER=ollama              # Options: ollama, openai, qwen, anthropic
FAIRIFIER_LLM_MODEL=qwen3:30b    # Model name
FAIRIFIER_LLM_BASE_URL=http://localhost:11434  # For Ollama
LLM_API_KEY=your_api_key         # For OpenAI/Qwen/Anthropic
LLM_TEMPERATURE=0.5
LLM_MAX_TOKENS=100000

# FAIR Data Station API (external)
FAIR_DS_API_URL=http://host.docker.internal:8083

# Optional Services
QDRANT_URL=http://qdrant:6333

# MinerU (optional PDF converter)
MINERU_ENABLED=false
MINERU_SERVER_URL=http://host.docker.internal:30000

# LangSmith (optional tracing)
LANGSMITH_API_KEY=your_langsmith_key
LANGSMITH_PROJECT=fairifier
```

### Docker Compose Configuration

The `docker/compose.yaml` file includes:

```yaml
services:
  fairifier-api:
    build:
      context: ..
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - LLM_PROVIDER=${LLM_PROVIDER:-ollama}
      - FAIRIFIER_LLM_MODEL=${FAIRIFIER_LLM_MODEL}
      - LLM_API_KEY=${LLM_API_KEY}
    volumes:
      - ../output:/app/output
      - ../kb:/app/kb
    command: ["python", "run_fairifier.py", "api"]

  fairifier-ui:
    # ... similar configuration
    command: ["python", "run_fairifier.py", "ui"]
```

## Architecture

### Services

1. **fairifier-api** (Port 8000)
   - FastAPI server
   - Processes metadata extraction requests
   - Health check: `/docs`

2. **fairifier-ui** (Port 8501)
   - Streamlit web interface
   - Interactive document processing
   - Configuration management

3. **qdrant** (Port 6333, Optional)
   - Vector database for embeddings
   - Used for future RAG features

### Network

All services run on the default Docker network. Services can communicate using their service names:
- `http://fairifier-api:8000`
- `http://qdrant:6333`

## Volumes

### Persistent Data

Docker Compose creates these volumes:

```yaml
volumes:
  qdrant_data:  # Qdrant vector database storage
```

### Mounted Directories

Host directories mounted into containers:

```yaml
volumes:
  - ../output:/app/output   # Generated metadata outputs
  - ../kb:/app/kb           # Knowledge base files
```

## Development

### Hot Reload

For development with code changes reflected immediately:

```bash
# Mount source code as volume
docker run -p 8000:8000 \
  -v $(pwd)/fairifier:/app/fairifier \
  -v $(pwd)/kb:/app/kb \
  fairiagent python run_fairifier.py api
```

### Building from Source

```bash
# Build with custom tag
docker build -t fairiagent:dev .

# Build without cache
docker build --no-cache -t fairiagent:latest .

# Build for specific platform
docker build --platform linux/amd64 -t fairiagent:latest .
```

## Production Deployment

### Best Practices

1. **Use specific tags**: Don't use `:latest` in production
   ```bash
   docker build -t fairiagent:v1.0.0 .
   ```

2. **Set resource limits**:
   ```yaml
   services:
     fairifier-api:
       deploy:
         resources:
           limits:
             cpus: '2'
             memory: 4G
   ```

3. **Use secrets for sensitive data**:
   ```yaml
   services:
     fairifier-api:
       secrets:
         - llm_api_key
   secrets:
     llm_api_key:
       file: ./secrets/llm_api_key.txt
   ```

4. **Configure logging**:
   ```yaml
   services:
     fairifier-api:
       logging:
         driver: "json-file"
         options:
           max-size: "10m"
           max-file: "3"
   ```

5. **Use health checks**:
   ```yaml
   services:
     fairifier-api:
       healthcheck:
         test: ["CMD", "curl", "-f", "http://localhost:8000/docs"]
         interval: 30s
         timeout: 10s
         retries: 3
   ```

### Scaling

Scale specific services:

```bash
# Scale API to 3 instances
docker-compose up -d --scale fairifier-api=3

# Use load balancer (e.g., nginx) in front
```

## Troubleshooting

### Port Conflicts

If ports are already in use:

```yaml
# In compose.yaml, change port mappings
ports:
  - "8001:8000"  # Host port 8001 -> Container port 8000
```

### Memory Issues

If containers are killed due to OOM:

```yaml
# Increase memory limits
deploy:
  resources:
    limits:
      memory: 8G
```

### Connection to External Services

To access services running on the host machine:

```bash
# Use special DNS name
FAIR_DS_API_URL=http://host.docker.internal:8083
MINERU_SERVER_URL=http://host.docker.internal:30000
```

On Linux, you may need to add `--add-host=host.docker.internal:host-gateway`.

### Viewing Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f fairifier-api

# Last 100 lines
docker-compose logs --tail=100

# Save logs to file
docker-compose logs > logs.txt
```

### Container Not Starting

```bash
# Check container status
docker-compose ps

# Inspect container
docker inspect fairiagent_fairifier-api_1

# Check build logs
docker-compose build --no-cache

# Run container interactively
docker run -it --entrypoint /bin/bash fairiagent
```

## Advanced Usage

### Custom Network

Create a custom network for better isolation:

```yaml
networks:
  fairiagent-net:
    driver: bridge

services:
  fairifier-api:
    networks:
      - fairiagent-net
```

### Persistent Configuration

Mount configuration files:

```yaml
volumes:
  - ./custom-config.yaml:/app/config.yaml:ro
  - ./.env:/app/.env:ro
```

### Using with Ollama

If using Ollama for LLMs:

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama

  fairifier-api:
    environment:
      - LLM_PROVIDER=ollama
      - FAIRIFIER_LLM_BASE_URL=http://ollama:11434
    depends_on:
      - ollama
```

### CI/CD Integration

Example GitHub Actions workflow:

```yaml
name: Build and Push Docker Image

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Build Docker image
        run: docker build -t fairiagent:${{ github.ref_name }} .
      
      - name: Run tests
        run: docker run fairiagent:${{ github.ref_name }} pytest
      
      - name: Push to registry
        run: |
          docker tag fairiagent:${{ github.ref_name }} registry.example.com/fairiagent:${{ github.ref_name }}
          docker push registry.example.com/fairiagent:${{ github.ref_name }}
```

## Security

### Best Practices

1. **Don't include secrets in images**
   - Use `.env` files or Docker secrets
   - Add `.env` to `.dockerignore`

2. **Run as non-root user**:
   ```dockerfile
   # Add to Dockerfile
   RUN useradd -m -u 1000 fairiagent
   USER fairiagent
   ```

3. **Scan images for vulnerabilities**:
   ```bash
   docker scan fairiagent:latest
   ```

4. **Use official base images**:
   ```dockerfile
   FROM python:3.11-slim  # Official Python image
   ```

## References

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Dockerfile Best Practices](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)
- [FAIRiAgent GitHub Repository](https://github.com/your-repo/FAIRiAgent)

## Related Documentation

- [Installation Guide](../../../README.md#installation)
- [Configuration Guide](../../../README.md#configuration)
- [LangGraph Studio Setup](./LANGGRAPH_STUDIO_SETUP.md)
- [LLM Integration Guide](../LLM_INTEGRATION_GUIDE.md)
