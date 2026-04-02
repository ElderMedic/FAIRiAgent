# FAIRiAgent Apps

This directory contains the current web interfaces and API components.

## React Web UI

Default entry point:

```bash
python run_fairifier.py webui
```

Open `http://localhost:8000`.

For local development:

```bash
python run_fairifier.py dev
```

This runs:
- backend on `8000`
- Vite dev server on `5173`

## API

```text
frontend/           React + TypeScript + Vite
fairifier/apps/api/ FastAPI backend under /api/v1
```

Project state is stored in SQLite. Progress updates are streamed with SSE. Result files are served from each run's output directory.

Common routes:

| Method | Path |
| --- | --- |
| `GET` | `/api/v1/health` |
| `POST` | `/api/v1/projects` |
| `GET` | `/api/v1/projects/{id}` |
| `GET` | `/api/v1/projects/{id}/artifacts` |
| `GET` | `/api/v1/projects/{id}/events` |

OpenAPI docs are available at `/docs`.

## Streamlit UI

The legacy Streamlit UI is still available:

```bash
python run_fairifier.py ui
```

Open `http://localhost:8501`.
