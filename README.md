<div align="center">

# 🧬 FAIRiAgent

### *FAIR Metadata Generation Framework*

**Generate FAIR-DS compatible metadata from research documents / 从研究文献中自动生成符合 FAIR 规范的元数据**

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green.svg)](https://langchain-ai.github.io/langgraph/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![FAIR-DS](https://img.shields.io/badge/FAIR--DS-Compatible-orange.svg)](https://fairds.fairbydesign.nl/)

[🚀 Quick Start / 快速开始](#-quick-start--快速开始) • [📖 Documentation / 详细文档](#-documentation--详细文档) • [🌐 Web UI](#-web-ui--网页端)

---

![FAIRiAgent Banner](docs/figures/wide_greetings.png)

*PDF in, FAIR metadata out.*

</div>

---

## 🎯 Overview / 概述

<div align="center">

![FAIRiAgent in Action](docs/figures/manga_fair.png)

</div>

**FAIRiAgent** is a CLI-first, multi-agent framework built with LangGraph and LangChain. It automatically extracts structured details from scientific documents (PDFs/text) and generates standardized, **FAIR-DS compatible JSON metadata**. Every field contains clear evidence, confidence levels, and provenance paths.

**FAIRiAgent** 是一个基于 LangGraph 与 LangChain 构建的、命令行优先的多 Agent 框架。它能自动提取科学文献（PDF/文本）中的结构化字段，生成标准化的、符合 **FAIR-DS 规范的 JSON 元数据**，并对提取的每个字段保留可追溯的证据链与置信度。

---

## 📖 Documentation / 详细文档

For detailed architecture, agent configurations, and developer manuals, please see:
详细的系统架构、Agent 逻辑与接口手册请参阅：

*   **English Guides**:
    *   [Architecture & Flow](docs/en/ARCHITECTURE_AND_FLOW.md) – Detailed agent nodes, ρ-mechanism, checkpointers.
    *   [LLM Integration Guide](docs/en/LLM_INTEGRATION_GUIDE.md) – Provider configuration (Ollama, OpenAI, Gemini, Qwen).
    *   [Docker Deployment](docs/en/guides/DOCKER_DEPLOYMENT.md) – Run using Docker Compose.
    *   [API Manual](docs/en/development/FAIRIFIER_API_MANUAL.md) – FastAPI endpoints and SSE event streaming.
*   **中文版指南**:
    *   [系统架构与工作流](docs/zh/ARCHITECTURE_AND_FLOW.md) – Agent 节点设计、重试、持久化。
    *   [LLM 集成指南](docs/zh/LLM_INTEGRATION_GUIDE.md) – Ollama、国内/云端大模型配置。
    *   [快速开始指南](docs/zh/guides/QUICKSTART.md) – 中文上手与本地部署说明。
    *   [测试指南](docs/zh/guides/TEST_GUIDE.md) – 开发人员测试流程。

---

## 🚀 Quick Start / 快速开始

### 1. Installation / 安装步骤

```bash
# Clone repository / 克隆项目
git clone https://github.com/ElderMedic/FAIRiAgent.git
cd FAIRiAgent

# Create and activate conda environment / 创建并激活环境
mamba create -n FAIRiAgent python=3.11 -y
mamba activate FAIRiAgent

# Install Python dependencies / 安装依赖
pip install -r requirements.txt

# Configure environment / 配置环境变量
cp env.example .env
# Update your keys in .env (e.g. LLM_PROVIDER, LLM_API_KEY) / 编辑 .env 写入大模型 Key 与配置
```

### 2. Basic Commands / 基础命令

```bash
# CLI: Process a scientific PDF / 命令行提取 PDF 元数据
python run_fairifier.py process examples/inputs/earthworm_4n_paper_bioRXiv.pdf

# Web UI: Start local web application / 启动网页版 UI 与服务
python run_fairifier.py webui
# Access at http://localhost:8000
```

---

## 🐛 Troubleshooting / 常见排错

| Issue / 问题 | Cause / 原因 | Solution / 解决方法 |
| :--- | :--- | :--- |
| **API connection timeout / LLM 报错** | Invalid API keys or network connection error. / API Key 错误或网络阻断。 | Check `.env` and verify provider endpoint. / 检查 `.env` 中的 Key 与对应 provider 是否配置正确。 |
| **FAIR-DS connection failed / 连接服务失败** | The local FAIR-DS service is not running. / FAIR-DS 数据站服务未启动。 | Ensure service is started: `curl http://localhost:8083/api/package`. / 确保依赖已启动。若采用 Docker, 可运行 `docker compose up -d`. |
| **Ollama Model not found / 模型缺失** | Ollama lacks the selected model. / 本地缺少配置的模型。 | Run `ollama pull <model_name>` (e.g., `ollama pull qwen3:8b`). / 手动拉取所需模型。 |
| **Docker container networking / 容器通信受阻** | The API container cannot connect to local port. / 容器内应用无法访问宿主机端口。 | Use `http://host.docker.internal:11434` instead of `localhost` in Docker env. / 容器配置中使用内部宿主机域名。 |

---

## 🔒 Security Notice / 安全性提示

> [!IMPORTANT]
> Keep your configuration files (`.env`, `api_keys.txt`) private. Do not check these files or experimental evaluation run files into public Git repositories.
>
> 请妥善保管您的配置文件（`.env`、`api_keys.txt`）以及本地评测结果数据。它们已被加入 `.gitignore`，请勿提交到公开 GitHub 仓库。

---

## 🤝 License & Contact / 授权与联系

- **Contact**: Changlin Ke — [Changlin.ke@wur.nl](mailto:Changlin.ke@wur.nl) (Wageningen University & Research)
- **License**: MIT License - Free for academic and research use.
