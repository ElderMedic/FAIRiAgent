<div align="center">

# 🧬 FAIRiAgent

### *FAIR Metadata Generation Framework*

**Generate FAIR-DS compatible metadata from research documents**

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green.svg)](https://langchain-ai.github.io/langgraph/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![FAIR-DS](https://img.shields.io/badge/FAIR--DS-Compatible-orange.svg)](https://fairds.fairbydesign.nl/)

[🚀 Quick Start](#-quick-start) • [📖 Documentation](#-documentation) • [🌐 Web UI](fairifier/apps/README.md) • [🇨🇳 中文版 / Chinese Version](docs/README.md)

---

![FAIRiAgent Banner](docs/figures/wide_greetings.png)

*PDF in, FAIR metadata out.*

</div>

---

## 🎯 What is FAIRiAgent?

<div align="center">

![FAIRiAgent in Action](docs/figures/manga_fair.png)

</div>

FAIRiAgent is a **multi-agent framework** built with LangGraph and LangChain that automatically extracts structured information from scientific research documents (PDFs/text) and generates standardized, **FAIR-DS compatible JSON metadata**. Every field includes clear evidence, confidence ratings, and provenance traces.

### 🌟 Why FAIRiAgent?

*   ⚡ **Fast**: Process complex documents in minutes, not hours.
*   🎯 **Accurate**: Multi-agent architecture with self-correcting critic loops.
*   📊 **Standards-compliant**: Directly outputs FAIR-DS compatible metadata.
*   🔍 **Evidence-based**: Every field includes source evidence, confidence score, and provenance.
*   🧠 **Intelligent**: LLM-as-Judge critic with rubric-driven quality assessment.
*   🎨 **Usable**: React Web UI for file upload, configuration, log streaming, and download.
*   🔧 **Flexible**: Supports local models (Ollama) and cloud providers (OpenAI, Gemini, Qwen, Anthropic, DeepSeek, Zhipu).
*   📂 **Multi-source aware**: Auto-discovers adjacent supplements/tables into a source workspace and can visualize hybrid retrieval in the Web UI.

### 📈 The Problem We Solve

Research metadata generation is **time-consuming** and **error-prone**. Scientists spend hours manually extracting metadata from papers, often missing critical fields or using inconsistent formats. 

<div align="center">

| ❌ **Before FAIRiAgent** | ✅ **With FAIRiAgent** |
|:---:|:---:|
| ⏱️ Hours of manual work | ⚡ Minutes of automated processing |
| ❌ Inconsistent formats | ✅ FAIR-DS compliant output |
| 🐛 Human errors | 🤖 AI-powered accuracy |
| 📝 Missing fields | 🔍 Comprehensive extraction |

</div>

**FAIRiAgent automates this process with:**
*   🤖 **Intelligent extraction** from complex PDF layouts.
*   🧠 **Knowledge enrichment** from FAIR Data Station and ontologies.
*   ✅ **Automatic validation** against schema standards.
*   🔄 **Self-correction** through reflective critic loops.

---

## 🚀 Quick Start

Two supported paths. **Docker Compose** is the simplest way to get FAIR-DS + API running together (MinerU not required). Use the local conda path if you prefer a host Python install.

### Option A — Docker Compose (recommended)

**Prerequisites:** Docker Desktop / Docker Engine with Compose v2.

```bash
git clone https://github.com/ElderMedic/FAIRiAgent.git
cd FAIRiAgent/docker

# Configure LLM (required for processing)
cp .env.example .env
# Edit .env: set LLM_PROVIDER + LLM_API_KEY (cloud), or Ollama settings (see comments in .env.example)

docker compose up -d --build
```

**Smoke checks (install / debug):**

```bash
# FAIR-DS knowledge backend
curl -sf http://localhost:8083/api/package | head

# FAIRiAgent API
curl -sf http://localhost:8000/api/v1/health

# Pre-flight inside the API container (FAIR-DS + LLM)
docker compose exec fairifier-api python run_fairifier.py validate-document --env-only
```

**First successful run (no MinerU):**

```bash
docker compose exec fairifier-api python run_fairifier.py process \
  /app/examples/quickstart/earthworm_4n_paper_bioRxiv.md --verbose
```

- API docs: http://localhost:8000/docs  
- If port 8000 is busy: `FAIRIFIER_HOST_PORT=8001 docker compose up -d` then use `http://localhost:8001`  
- Apple Silicon is supported (`fairds` runs as `linux/amd64`)  
- Details: [docker/README.md](docker/README.md) · [Docker Deployment Guide](docs/en/guides/DOCKER_DEPLOYMENT.md)

### Option B — Local conda / mamba

*   Python 3.11+
*   Node.js 18+ (only if you want the Web UI)
*   FAIR-DS at `http://localhost:8083` (or another port you configure in `.env`)

**FAIR-DS without Docker (JAR):**

```bash
# Download once (writes docker/fairds/fairds.jar)
./scripts/update_fairds_jar.sh

# Default port 8083. If that port is taken, pick another:
java -Dserver.port=8083 -jar docker/fairds/fairds.jar
# then set FAIR_DS_API_URL=http://localhost:8083 in .env
```

**FAIR-DS with Docker only for the backend** (FAIRiAgent still local): `cd docker && docker compose up -d fairds`

```bash
git clone https://github.com/ElderMedic/FAIRiAgent.git
cd FAIRiAgent

mamba create -n FAIRiAgent python=3.11 -y
mamba activate FAIRiAgent
pip install -r requirements.txt

cp env.example .env
# Edit .env: LLM_PROVIDER, LLM_API_KEY (or Ollama), FAIR_DS_API_URL=http://localhost:8083
# Quickstart Markdown path does not need MinerU: MINERU_ENABLED=false

# Smoke check
mamba run -n FAIRiAgent python run_fairifier.py validate-document --env-only

# Multi-source quickstart (Markdown + Excel; no MinerU)
mamba run -n FAIRiAgent python run_fairifier.py process examples/quickstart/earthworm_4n_paper_bioRxiv.md --verbose

# Web UI (builds frontend on first run)
mamba run -n FAIRiAgent python run_fairifier.py webui
# Open http://localhost:8000
```

---

## 📖 Documentation

For detailed guides, architecture diagrams, and developer manuals, please see:

*   [Architecture & Flow](docs/en/ARCHITECTURE_AND_FLOW.md) – Agent nodes, ρ-mechanism rollback, checkpointers.
*   [Source Workspace](docs/en/SOURCE_WORKSPACE.md) – Multi-file inputs, auto-discovery, evidence search.
*   [LLM Integration Guide](docs/en/LLM_INTEGRATION_GUIDE.md) – Provider configuration (Ollama, OpenAI, Gemini, Qwen, Anthropic, DeepSeek).
*   [Hybrid Retrieval Upgrade Plan](docs/en/development/HYBRID_RETRIEVAL_AND_COVERAGE_UPGRADE_PLAN.md) – Hybrid retrieval, auto mode, ISA structural sync (§12.1).
*   [Changelog](docs/CHANGELOG.md) – Release history (`v2.2.1` current).
*   [Docker Deployment Guide](docs/en/guides/DOCKER_DEPLOYMENT.md) – Docker Compose setup.
*   [FAIRiAgent REST API Manual](docs/en/development/FAIRIFIER_API_MANUAL.md) – FastAPI backend and SSE streaming.
*   [Memory Management Guide](docs/MEMORY_GUIDE.md) – mem0 semantic memory.
*   [Bilingual Documentation Catalog](docs/README.md) – English & Chinese index.

---

## 🐛 Troubleshooting

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| **API connection timeout / LLM Error** | Invalid API keys or network connection error. | Set `LLM_PROVIDER` and `LLM_API_KEY` in `docker/.env` (Compose) or root `.env` (local). Re-check with `validate-document --env-only`. |
| **FAIR-DS connection failed** | FAIR-DS is not running or not healthy yet. | `cd docker && docker compose up -d fairds`, wait until healthy, then `curl http://localhost:8083/api/package`. |
| **`fairifier-api` never starts** | Waiting on FAIR-DS healthcheck. | `docker compose ps` / `docker compose logs fairds`. First boot on Apple Silicon can take ~1–2 minutes. |
| **Ollama Model not found** | Ollama lacks the selected model locally. | `ollama pull <model_name>` (e.g. `ollama pull qwen3:8b`). In Docker set `FAIRIFIER_LLM_BASE_URL=http://host.docker.internal:11434`. |
| **LLM 429 / insufficient balance** | Cloud provider quota exhausted. | Top up the provider account, or switch `docker/.env` to a working key / local Ollama. Re-run `validate-document --env-only` then `process`. |
| **Port 8000 already in use** | Another process bound the API port. | `FAIRIFIER_HOST_PORT=8001 docker compose up -d` (from `docker/`). |
| **Docker container networking** | Container cannot reach host Ollama/MinerU. | Use `host.docker.internal` (Compose already sets `extra_hosts`). |

---

## 🔒 Security Notice

> [!IMPORTANT]
> Keep your configuration files (`.env`, `api_keys.txt`) private. Do not check these files or experimental evaluation run files into public Git repositories.
>
> Please ensure that no API keys or private evaluation results are committed. They are gitignored locally by default.

---

## 🤝 License & Contact

- **Contact**: Changlin Ke — [Changlin.ke@wur.nl](mailto:Changlin.ke@wur.nl) (Wageningen University & Research)
- **License**: MIT License - Free for academic and research use.

---

<div align="center">

### Star History

[![Star History Chart](https://api.star-history.com/svg?repos=ElderMedic/FAIRiAgent&type=Date)](https://star-history.com/#ElderMedic/FAIRiAgent&Date)

</div>
