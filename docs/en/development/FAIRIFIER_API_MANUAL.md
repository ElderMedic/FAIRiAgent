# FAIRiAgent REST API Manual

**Version**: 2.0.2  
**Last Updated**: 2026-07-01  
**Base path**: `/api/v1`

The FAIRiAgent Web UI is backed by a FastAPI application (`fairifier.apps.api`). All versioned routes live under `/api/v1`. Interactive OpenAPI docs are served at `/docs` on the same host and port as the API.

> **Not to be confused with** the [FAIR-DS API Manual](FAIRDS_API_MANUAL.md), which documents the external FAIR Data Station metadata service that FAIRiAgent queries during workflow runs.

---

## Running the API

| Mode | Command | UI | API base URL |
|------|---------|----|--------------|
| **Production Web UI** | `python run_fairifier.py webui` | Built React SPA on same port | `http://localhost:8000` |
| **Development** | `python run_fairifier.py dev` | Vite dev server | Backend: `http://localhost:3000` · Frontend: `http://localhost:5173` |
| **API only** | `python run_fairifier.py api` | None (JSON root at `/`) | `http://localhost:8000` |

Development notes:

- The Vite dev server proxies `/api` to the backend (default `http://localhost:3000`).
- In dev mode the backend does **not** serve `frontend/dist`; use port **5173** for the browser UI.
- Override the dev backend port: `python run_fairifier.py dev --port 3000`.
- Override production/API port: `python run_fairifier.py webui --port 8080`.

Project state is persisted in SQLite at `fairifier/apps/api/data/projects.db`. Workflow progress is pushed to clients through **Server-Sent Events (SSE)**.

---

## Authentication and sessions

There is no login or API-key gate on the FAIRiAgent REST API itself. Instead, **browser sessions** isolate project lists and enforce access control per client.

### Required session header

| Header | Required | Description |
|--------|----------|-------------|
| `X-FAIRifier-Session-Id` | Yes (on project-scoped routes) | UUID string identifying the browser tab/session |
| `X-FAIRifier-Session-Started-At` | No | ISO-8601 timestamp when the session started |

Equivalent query parameters (fallback): `session_id` or `session`, and `session_started_at` or `ts`.

Routes that **require** a valid session context:

- `GET /projects`, `GET/DELETE /projects/{id}`, `POST /projects/{id}/stop`
- `GET /projects/{id}/artifacts`, `GET /projects/{id}/artifacts/{name}`
- `GET /projects/{id}/events`, `GET /projects/{id}/memory-cloud`
- `GET /system/resource-load` (session used to count active runs for this client)

Routes that do **not** require session headers:

- `GET /health`, `GET /demo-options`, `GET /system/status`
- `GET /system/ollama-models`, `GET /fairds/statistics`

`POST /projects` also requires session headers so new runs are owned by the caller's session.

---

## Endpoint reference

### Health and bootstrap

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check; returns `status`, `timestamp`, `version` |
| `GET` | `/demo-options` | Bundled demo documents and default Ollama settings for the UI |

**Example**

```bash
curl -s http://localhost:8000/api/v1/health | jq
```

---

### System status and resources

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/system/status` | Dependency health: Ollama, MinerU, FAIR-DS, Qdrant, mem0, plus active config snapshot |
| `GET` | `/system/resource-load` | CPU, memory, disk, optional GPU metrics; `active_runs` for current session |
| `GET` | `/system/ollama-models` | List models from an Ollama instance (`?base_url=` optional) |
| `GET` | `/fairds/statistics` | Aggregated FAIR-DS package/term statistics (`?refresh=`, `?top=`, `?packages=`) |

**Example — system status**

```bash
curl -s http://localhost:8000/api/v1/system/status | jq '.services[] | {name, status, message}'
```

**Example — FAIR-DS statistics**

```bash
curl -s 'http://localhost:8000/api/v1/fairds/statistics?refresh=false&top=10' | jq '.totals'
```

---

### Projects

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/projects` | Upload file(s) or select a demo document; starts workflow (201) |
| `GET` | `/projects` | List projects for the current session |
| `GET` | `/projects/{project_id}` | Project status, scores, artifacts summary |
| `DELETE` | `/projects/{project_id}` | Remove project record from store |
| `POST` | `/projects/{project_id}/stop` | Request graceful workflow stop |

#### `POST /projects` (multipart form)

| Field | Type | Description |
|-------|------|-------------|
| `file` | file | Single upload |
| `files` | file(s) | Multi-file upload (repeat field or array) |
| `project_name` | string | Optional display name |
| `config_overrides` | string (JSON) | Per-run overrides (see below) |
| `demo` | bool | Enable demo-mode workflow shortcuts |
| `sample_document` | string | Demo document key (e.g. `earthworm_paper`) instead of upload |

Provide **either** uploaded file(s) **or** `sample_document`, not both.

**`config_overrides` JSON fields** (all optional):

- `llm_provider`, `llm_model`, `llm_base_url`, `llm_api_key`
- `fair_ds_api_url`

**Example — create project from upload**

```bash
SESSION_ID="$(uuidgen)"
curl -s -X POST http://localhost:8000/api/v1/projects \
  -H "X-FAIRifier-Session-Id: ${SESSION_ID}" \
  -H "X-FAIRifier-Session-Started-At: $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -F "file=@examples/inputs/earthworm_4n_paper_bioRXiv.pdf" \
  -F 'project_name=Earthworm test' | jq
```

**Example — bundled demo document**

```bash
curl -s http://localhost:8000/api/v1/demo-options | jq '.documents'

curl -s -X POST http://localhost:8000/api/v1/projects \
  -H "X-FAIRifier-Session-Id: ${SESSION_ID}" \
  -F "sample_document=earthworm_paper" \
  -F "demo=true" | jq '.project_id, .status'
```

#### Project response fields (selected)

| Field | Description |
|-------|-------------|
| `status` | `pending`, `running`, `completed`, `failed`, etc. |
| `confidence_scores` | Per-agent or aggregate critic scores |
| `needs_review` | Set when workflow escalates for human review |
| `artifacts` | Summary list when populated |
| `execution_summary`, `quality_metrics` | Post-run analytics |
| `stop_requested` | True after `POST .../stop` |

---

### Artifacts

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/projects/{project_id}/artifacts` | List files under the run output directory |
| `GET` | `/projects/{project_id}/artifacts/{artifact_name}` | Download a single artifact (path-safe) |

Typical artifacts include `metadata.json`, `processing_log.jsonl`, `llm_responses.json`, `runtime_config.json`, and `validation_report.txt`.

Hidden files (path segments starting with `.`) are excluded from listings and downloads.

**Example**

```bash
curl -s -H "X-FAIRifier-Session-Id: ${SESSION_ID}" \
  "http://localhost:8000/api/v1/projects/${PROJECT_ID}/artifacts" | jq

curl -H "X-FAIRifier-Session-Id: ${SESSION_ID}" \
  -OJ "http://localhost:8000/api/v1/projects/${PROJECT_ID}/artifacts/metadata.json"
```

---

### Workflow events (SSE)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/projects/{project_id}/events` | `text/event-stream` of workflow events |

Event types include `log`, `progress`, `stage_change`, `stop_requested`, `completed`, and `error`. The stream sends `: keepalive` comments every 30 seconds when idle and closes after `completed` or `error`.

**Example**

```bash
curl -N -H "X-FAIRifier-Session-Id: ${SESSION_ID}" \
  "http://localhost:8000/api/v1/projects/${PROJECT_ID}/events"
```

Each SSE message uses the form:

```
event: progress
data: {"event_type":"progress","project_id":"...","data":{...},"timestamp":...}
```

---

### Memory cloud

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/projects/{project_id}/memory-cloud` | Word-frequency aggregates from mem0 (no raw memory text) |

Returns `session_words` (this run), `scope_words` (all runs in the browser session), and `memory_enabled`. When mem0 is disabled or unavailable, arrays are empty and `memory_enabled` is `false`.

---

## CORS and static frontend

- **CORS**: All origins, methods, and headers are allowed (suitable for local dev with Vite on another port).
- **Production Web UI**: When `frontend/dist/index.html` exists, the API serves the SPA and `/assets/*`; unknown paths fall back to `index.html` for client-side routing.
- **API-only root**: When no built frontend is present, `GET /` returns JSON with `message`, `version`, and `docs`.

---

## Error responses

Standard FastAPI/HTTP semantics:

| Code | Typical cause |
|------|----------------|
| `400` | Missing file, invalid session UUID, invalid `config_overrides` JSON |
| `404` | Project not found or not owned by session; missing artifact |
| `413` | Upload exceeds `max_document_size_mb` (from config) |

---

## Related documentation

- [Web UI Guide](../../../fairifier/apps/README.md) — entry points and directory layout
- [Docker Deployment](../guides/DOCKER_DEPLOYMENT.md) — containerized deployment
- [FAIR-DS API Manual](FAIRDS_API_MANUAL.md) — external metadata service consumed by the workflow
- [Mem0 Quick Start](../../MEM0_QUICKSTART.md) — optional memory layer behind `/memory-cloud`

OpenAPI schema: start the server and open `/docs` or `/openapi.json`.
