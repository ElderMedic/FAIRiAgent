# FAIRiAgent Docker Deployment

Deploy FAIRiAgent using Docker and Docker Compose.

## Files

- **`../Dockerfile`** - Main Dockerfile (supports CLI and API modes)
- **`compose.yaml`** - Docker Compose configuration
- **`../.dockerignore`** - Docker build ignore file

## Quick Start

### Using Docker Compose (Recommended)

```bash
# Start all services (API, Qdrant, GROBID)
cd docker
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

### Using Dockerfile Directly

```bash
# Build image
docker build -t fairiagent .

# Run CLI
docker run --rm -v $(pwd)/document.pdf:/app/document.pdf fairiagent \
  python run_fairifier.py process document.pdf

# Run API (default mode)
docker run -p 8000:8000 fairiagent
```

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# LLM Configuration
LLM_PROVIDER=ollama  # or openai, qwen, anthropic
FAIRIFIER_LLM_MODEL=qwen3:30b
LLM_API_KEY=your_api_key_here

# FAIR-DS API (external service)
FAIR_DS_API_URL=http://localhost:8083

# Optional services
QDRANT_URL=http://qdrant:6333
GROBID_URL=http://grobid:8070

# LangSmith (optional)
LANGSMITH_API_KEY=your_key
LANGSMITH_PROJECT=fairifier
```

## Services

- **fairifier-api** - FastAPI server (port 8000)
- **qdrant** - Vector database (port 6333, optional)
- **grobid** - PDF parsing service (port 8070, optional)

## Access Points

After starting services:

- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Qdrant Dashboard**: http://localhost:6333/dashboard

## Data Persistence

Docker Compose creates persistent volumes:
- `qdrant_data` - Qdrant vector database storage

## Development Mode

For development with hot-reload, source code is mounted as volumes:

```yaml
volumes:
  - ../output:/app/output
  - ../kb:/app/kb
```

## Troubleshooting

### Port Conflicts

If ports are already in use, modify port mappings in `compose.yaml`:

```yaml
ports:
  - "8001:8000"  # Use 8001 instead of 8000
```

### FAIR-DS API

FAIR-DS API is expected to run externally (not in Docker Compose). If running on the host machine, use `http://host.docker.internal:8083` to access it from containers.
