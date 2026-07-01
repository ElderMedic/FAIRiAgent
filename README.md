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
*   🔧 **Flexible**: Supports local models (Ollama) and cloud providers (OpenAI, Gemini, Qwen, Anthropic).

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

### 1. Prerequisites & Installation

*   Python 3.11+
*   Node.js 18+ (optional, for Web UI)

```bash
# Clone the repository
git clone https://github.com/ElderMedic/FAIRiAgent.git
cd FAIRiAgent

# Create and activate conda environment
mamba create -n FAIRiAgent python=3.11 -y
mamba activate FAIRiAgent

# Install Python dependencies
pip install -r requirements.txt

# Configure environment variables
cp env.example .env
# Edit .env with your LLM provider credentials (e.g. LLM_PROVIDER, LLM_API_KEY)
```

### 2. Basic Commands

```bash
# CLI: Process a scientific PDF and extract metadata
python run_fairifier.py process examples/inputs/earthworm_4n_paper_bioRXiv.pdf

# Web UI: Start local web application
python run_fairifier.py webui
# Open http://localhost:8000 in your browser
```

---

## 📖 Documentation

For detailed guides, architecture diagrams, and developer manuals, please see:

*   [Architecture & Flow](docs/en/ARCHITECTURE_AND_FLOW.md) – Detailed agent nodes, ρ-mechanism rollback, checkpointers.
*   [LLM Integration Guide](docs/en/LLM_INTEGRATION_GUIDE.md) – Provider configuration (Ollama, OpenAI, Gemini, Qwen, Anthropic).
*   [Docker Deployment Guide](docs/en/guides/DOCKER_DEPLOYMENT.md) – Set up using Docker Compose.
*   [FAIRiAgent REST API Manual](docs/en/development/FAIRIFIER_API_MANUAL.md) – FastAPI backend manual and SSE event streaming.
*   [Memory Management Guide](docs/MEMORY_GUIDE.md) – Setup and configure mem0 semantic memory.
*   [Bilingual Documentation Catalog](docs/README.md) – Core index of English & Chinese documentation.

---

## 🐛 Troubleshooting

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| **API connection timeout / LLM Error** | Invalid API keys or network connection error. | Verify `LLM_PROVIDER` and `LLM_API_KEY` in `.env`. |
| **FAIR-DS connection failed** | Local FAIR-DS service is not running. | Start FAIR-DS: `curl http://localhost:8083/api/package`. If using Docker, run `docker compose up -d`. |
| **Ollama Model not found** | Ollama lacks the selected model locally. | Run `ollama pull <model_name>` (e.g., `ollama pull qwen3:8b`). |
| **Docker container networking** | The API container cannot reach host ports. | Use `http://host.docker.internal:11434` instead of `localhost` in Docker env. |

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
