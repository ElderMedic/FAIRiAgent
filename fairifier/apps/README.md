# FAIRiAgent Apps

This directory contains the web interfaces and API components for FAIRiAgent.

## 🌐 React Web UI (Recommended)

A modern, front-end-separated React SPA served by the FastAPI backend. Designed for local LAN access.

### Quick Start

```bash
# Production mode (auto-builds frontend, serves everything on one port)
python run_fairifier.py webui

# Access at http://localhost:8000
# LAN access: http://<your-ip>:8000
```

### Development Mode

```bash
# Runs backend (port 8000) + Vite dev server (port 5173) simultaneously
python run_fairifier.py dev
```

### Features

- 📄 **Drag-and-drop Upload**: PDF, TXT, Markdown support
- ⚙️ **Configuration**: LLM provider, model, API keys (all optional, uses server defaults)
- 🔄 **Real-time Processing**: SSE-powered live progress and activity logs
- 📊 **Results Dashboard**: Confidence scores, execution summary, artifact downloads
- 🧬 **Bio-themed Design**: Animated molecular/cellular background with Meta-style enterprise UI
- 📱 **Responsive**: Works on desktop and mobile
- ♿ **Accessible**: Respects `prefers-reduced-motion`; all animations can be disabled

### Architecture

```
frontend/          → React + TypeScript + Vite (SPA)
fairifier/apps/api/ → FastAPI backend with /api/v1 versioned endpoints
```

- **API versioning**: All endpoints under `/api/v1/`
- **Storage**: SQLite persistence (survives server restarts)
- **Real-time events**: Server-Sent Events (SSE) for workflow progress
- **Artifacts**: File-based, served directly from output directories

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Health check |
| `POST` | `/api/v1/projects` | Upload file & start workflow |
| `GET` | `/api/v1/projects` | List all projects |
| `GET` | `/api/v1/projects/{id}` | Get project details |
| `DELETE` | `/api/v1/projects/{id}` | Delete a project |
| `GET` | `/api/v1/projects/{id}/artifacts` | List artifacts |
| `GET` | `/api/v1/projects/{id}/artifacts/{name}` | Download artifact |
| `GET` | `/api/v1/projects/{id}/events` | SSE event stream |

OpenAPI docs available at `/docs` when the API is running.

## 🎨 Streamlit Web UI (Legacy)

The original Streamlit-based interface. Still functional but no longer the primary UI.

```bash
python run_fairifier.py ui
# Access at http://localhost:8501
```

## 📝 Notes

- The React Web UI is the recommended way to interact with FAIRiAgent
- Both UIs can coexist (they use different ports)
- All configurations can be managed through the web UI or `.env` file
- Runtime configurations are automatically saved for each run
