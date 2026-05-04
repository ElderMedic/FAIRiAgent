# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FAIRiAgent is a CLI-first, multi-agent framework that extracts information from research documents (PDF/text) and generates **FAIR-DS compatible JSON metadata**. It uses LangGraph for orchestration and supports multiple LLM providers (Ollama, OpenAI, Qwen, Gemini, Anthropic/DeepSeek).

## Commands

### Environment Setup

```bash
# Activate conda environment (mamba)
mamba activate FAIRiAgent

# Install Python dependencies
pip install -r requirements.txt

# Install frontend dependencies
cd frontend && npm install && cd ..
```

### Running

```bash
# Process a document (CLI)
python run_fairifier.py process examples/inputs/earthworm_4n_paper_bioRXiv.pdf

# Run the Web UI (API + React frontend at http://localhost:8000)
python run_fairifier.py webui

# Show current configuration
python run_fairifier.py config-info

# Validate environment (no document needed)
python run_fairifier.py validate-document --env-only

# LangGraph Studio for workflow visualization
langgraph dev
```

### Testing

```bash
# Run all tests
python run_tests.py all

# Run fast unit tests only (~3s, no external services)
python run_tests.py fast
pytest tests/ -v -m "not integration and not slow"

# Run integration tests (requires FAIR-DS API and MinerU)
python run_tests.py integration
pytest tests/ -v -m "integration"

# Run a specific test file
pytest tests/test_critic_utils.py -v

# Run a specific test class
pytest tests/test_mineru_client.py::TestMinerUCLI -v

# Run with coverage
pytest tests/ --cov=fairifier --cov-report=html --cov-report=term-missing
```

### Code Quality

```bash
black fairifier/
isort fairifier/
flake8 fairifier/
mypy fairifier/
```

## Architecture

### LangGraph Workflow (`fairifier/graph/langgraph_app.py`)

The core is `FAIRifierLangGraphApp`, a LangGraph state machine. Nodes run sequentially with Critic evaluation after each agent. The shared state is `FAIRifierState` (TypedDict, defined in `fairifier/models.py`).

**Workflow nodes (in order):**
1. **DocumentParserAgent** (`agents/document_parser.py`) — LLM-based extraction from PDF/text
2. **BioMetadataAgent** (`agents/bio_metadata_agent.py`) — Tool-first Docker workflow for bioinformatics files (BAM, VCF, FASTQ) using biocontainers
3. **Planner node** (inline in `langgraph_app.py`) — LLM generates per-agent guidance
4. **KnowledgeRetrieverAgent** (`agents/knowledge_retriever.py`) — Queries FAIR-DS API (59 packages, 892 terms) and local KB; reports `api_capabilities` for critic awareness
5. **JSONGeneratorAgent** (`agents/json_generator.py`) — Maps extracted info to ISA-Tab compatible FAIR metadata
6. **ISAValueMapperAgent** (`agents/isa_value_mapper.py`) — Maps values to standardized ISA terms
7. **CriticAgent** (`agents/critic.py`) — Embedded after each agent; decides ACCEPT / RETRY / ESCALATE using LLM-as-Judge rubric from `docs/en/development/critic_rubric.yaml`

**Retry logic:** Up to 2 retries per agent, with no-progress detection (same score twice → auto-accept). Global retry cap via `max_global_retries`.

### Configuration (`fairifier/config.py`)

`FAIRifierConfig` dataclass loaded at import time from `.env`. All critical settings are overridable via environment variables prefixed `FAIRIFIER_`. Key settings:
- `LLM_PROVIDER` — `ollama | openai | qwen | gemini | anthropic | deepseek`
- `FAIRIFIER_LLM_MODEL` — model name
- `FAIR_DS_API_URL` — FAIR Data Station endpoint (default `http://localhost:8083`)
- `CHECKPOINTER_BACKEND` — `none | memory | sqlite` (default `sqlite`)
- `FAIRIFIER_ENABLE_DEEP_AGENTS` — enables inner ReAct loop in agents
- `FAIRIFIER_SOURCE_WORKSPACE_ENABLED` — multi-file agentic source search

### LLM Abstraction (`fairifier/utils/llm_helper.py`)

`get_llm_helper()` returns a unified `LLMHelper` that wraps any supported provider. All agents use this, so adding a provider only requires changes here.

### API + Web UI (`fairifier/apps/api/`)

FastAPI app created by `create_app()` in `main.py`. Routes are versioned under `/api/v1` (`routers/v1.py`). The React frontend is built to `frontend/dist/` and served as static files. SQLite project store at `fairifier/apps/api/data/projects.db`.

### Services (`fairifier/services/`)

| Service | Purpose |
|---|---|
| `fair_data_station.py` | HTTP client for FAIR-DS API |
| `fairds_api_parser.py` | Parses FAIR-DS API responses into structured terms/packages |
| `confidence_aggregator.py` | Blends critic score, structural coverage, validation health into overall confidence |
| `source_workspace.py` | Manages multi-file input manifests for agentic search |
| `mineru_client.py` | Optional MinerU PDF-to-Markdown conversion service |
| `mem0_service.py` | Optional mem0 + Qdrant persistent memory layer |
| `fairds_excel_export.py` | Exports metadata to FAIR-DS Excel format |

### Validation (`fairifier/validation/`)

- `json_schema.py` — FAIR-DS ShEx-based JSON schema validation with field normalization
- `metadata_json_format.py` — Output format validation

### Output

Each run produces `output/<project_id>/`:
- `metadata.json` — FAIR-DS compatible metadata
- `processing_log.jsonl` — JSON line event log
- `llm_responses.json` — All LLM interactions (auto-logged)
- `runtime_config.json` — Full runtime configuration snapshot
- `validation_report.txt` — Optional schema validation results

### Key Patterns

- **Every `MetadataField`** carries `field_name`, `value`, `evidence`, `confidence`, `origin`, `package_source`, `status`, `isa_sheet`, and `entity_id`. Fields sharing `(isa_sheet, entity_id)` belong to the same ISA row.
- **Critic evaluation output** is a `CriticEvaluation` Pydantic model with `score`, `critique`, `issues`, `suggestions`. The graph uses this to route: ACCEPT → next node, RETRY → same node with feedback, ESCALATE → terminal with review flag.
- **Resource cleanup**: Use `FAIRifierLangGraphApp` as a context manager or call `.close()` explicitly in long-running services to release SQLite checkpoint connections.
- **LangSmith tracing**: Enabled when `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT` are set. All major agent calls are decorated with `@traceable`.
