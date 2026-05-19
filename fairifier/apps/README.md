# FAIRiAgent Apps

Web UI and REST API for FAIRiAgent. Implementation lives in `frontend/` (React + TypeScript + Vite) and `fairifier/apps/api/` (FastAPI, versioned under `/api/v1`).

Full API reference: [FAIRiAgent REST API Manual](../../docs/en/development/FAIRIFIER_API_MANUAL.md).

---

## Quick start

### Production Web UI

Serves the built React app and API on one port (default **8000**):

```bash
python run_fairifier.py webui
# → http://localhost:8000
# → API docs: http://localhost:8000/docs
```

Build the frontend first if `frontend/dist/` is missing:

```bash
cd frontend && npm install && npm run build && cd ..
```

Custom port:

```bash
python run_fairifier.py webui --port 8080
```

### Development mode

Runs the API with hot-reload and the Vite dev server separately:

```bash
python run_fairifier.py dev
```

| Service | Default URL | Notes |
|---------|-------------|--------|
| Backend API | `http://localhost:3000` | Uvicorn with `--reload` |
| Frontend (Vite) | `http://localhost:5173` | Proxies `/api` → backend |

Use the **frontend URL** in the browser during development. Override the backend port with `python run_fairifier.py dev --port 3000`.

For remote dev hosts, ensure `frontend/vite.config.ts` lists the hostname under `server.allowedHosts` (e.g. `bioind4.wur.nl`).

### API only

```bash
python run_fairifier.py api
# → http://localhost:8000/docs
```

No static UI is served unless `frontend/dist/index.html` exists.

---

## Architecture

```text
frontend/              React SPA (Vite)
fairifier/apps/api/    FastAPI application
  main.py              App factory, CORS, optional SPA mount
  routers/v1.py        /api/v1 routes
  models.py            Pydantic request/response schemas
  storage/             SQLite project store (projects.db)
  services/            Workflow runner, SSE event bus
```

- **Project state**: SQLite at `fairifier/apps/api/data/projects.db`
- **Progress updates**: SSE at `GET /api/v1/projects/{id}/events`
- **Artifacts**: Written to `output/<project_id>/` and exposed via the artifacts API
- **Sessions**: Browser clients send `X-FAIRifier-Session-Id` (UUID) to isolate project lists

---

## API endpoints (summary)

| Method | Path | Session required |
|--------|------|------------------|
| `GET` | `/api/v1/health` | No |
| `GET` | `/api/v1/demo-options` | No |
| `GET` | `/api/v1/system/status` | No |
| `GET` | `/api/v1/system/resource-load` | Yes |
| `GET` | `/api/v1/system/ollama-models` | No |
| `GET` | `/api/v1/fairds/statistics` | No |
| `POST` | `/api/v1/projects` | Yes |
| `GET` | `/api/v1/projects` | Yes |
| `GET` | `/api/v1/projects/{id}` | Yes |
| `DELETE` | `/api/v1/projects/{id}` | Yes |
| `POST` | `/api/v1/projects/{id}/stop` | Yes |
| `GET` | `/api/v1/projects/{id}/artifacts` | Yes |
| `GET` | `/api/v1/projects/{id}/artifacts/{name}` | Yes |
| `GET` | `/api/v1/projects/{id}/memory-cloud` | Yes |
| `GET` | `/api/v1/projects/{id}/events` | Yes (SSE) |

OpenAPI: `/docs` on the API host.

See the [API Manual](../../docs/en/development/FAIRIFIER_API_MANUAL.md) for request bodies, examples, and SSE event types.
