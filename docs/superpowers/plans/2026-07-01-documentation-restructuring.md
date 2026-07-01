# Documentation Restructuring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the root `README.md` into a clean bilingual portal while archiving all technical details into English and Chinese sub-documents, ensuring all sensitive results/keys remain local and ignored.

**Architecture:** Split the documentation into (1) high-level compact bilingual homepage (`README.md`), (2) detailed English architecture and development guide (`docs/en/ARCHITECTURE_AND_FLOW.md`), and (3) detailed Chinese architecture and development guide (`docs/zh/ARCHITECTURE_AND_FLOW.md`), keeping both versions in sync.

**Tech Stack:** Markdown (GitHub Flavored), Git, Mermaid diagrams.

---

### Task 1: Verify Git Ignored Status & Secret Safeguards

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Check untracked/deleted status of confidential reports**
  Run: `git status`
  Expected: Confirm `evaluation/reports/FINAL_EVALUATION_RESULTS.md`, `evaluation/archive/docs/FINAL_ANALYSIS_RESULTS.md`, and `evaluation/paper_experiments_v1/EXPERIMENT_SUMMARY.md` show up as `deleted` in changes to be committed, and do not appear in untracked files.

- [ ] **Step 2: Commit gitignore and deletion of results**
  Run:
  ```bash
  git commit -m "chore(security): gitignore and untrack confidential evaluation results"
  ```
  Expected: Commits successfully.

---

### Task 2: Update English Technical Documentation `docs/en/ARCHITECTURE_AND_FLOW.md`

**Files:**
- Modify: `docs/en/ARCHITECTURE_AND_FLOW.md`

- [ ] **Step 1: Rewrite ARCHITECTURE_AND_FLOW.md with merged details**
  Write the complete, comprehensive technical guidelines containing the detailed 6-agent system, Critic logic, ρ-mechanism rollback, SQLite checkpointers, outputs, and local provisional extensions.
  Content to write:
  ```markdown
  # FAIRiAgent System Architecture & Workflow

  This document illustrates the detailed architecture, agent configurations, interaction flows, and developer setups for **FAIRiAgent**.

  ---

  ## 1. System Architecture Diagram

  The system uses a **LangGraph-based multi-agent workflow** with API-aware evaluation and intelligent self-correction:

  ```mermaid
  flowchart TD
      subgraph INPUT["📥 Input Layer"]
          A[📄 PDF Document]
          M[🔧 MinerU Parser]
          A --> M
      end
      
      subgraph ORCHESTRATOR["🎯 Orchestrator (LangGraph)"]
          direction TB
          
          subgraph PARSE["Step 1: Document Parsing"]
              B[🔍 Document Parser<br/>LLM Extraction]
              C1[🧑‍⚖️ Critic]
              B --> C1
          end
          
          subgraph BIO["Step 2: Bioinformatics (conditional)"]
              G[🧬 BioMetadataAgent<br/>Containerised tools]
          end
          
          subgraph PLAN["Step 3: Planning"]
              D[📋 Planner<br/>Agent-specific guidance]
          end
          
          subgraph RETRIEVE["Step 4: Knowledge Retrieval"]
              E[🧠 Knowledge Retriever<br/>FAIR-DS API + Local KB]
              C2[🧑‍⚖️ Critic]
              E --> C2
          end
          
          subgraph GENERATE["Step 5: JSON Generation"]
              F[📝 JSON Generator<br/>ISA-Tab Mapping]
              C3[🧑‍⚖️ Critic]
              F --> C3
          end
          
          subgraph MAP["Step 6: ISA Value Mapping"]
              H[🔗 ISA Value Mapper<br/>Entity Grouping + Terms]
          end
      end
      
      subgraph EXTERNAL["🌐 External Services"]
          API[🗄️ FAIR-DS API<br/>59 Packages, 892 Terms]
          FAIR[📊 FAIR-DS Validator<br/>ShEx Schema]
      end
      
      subgraph OUTPUT["📤 Output Layer"]
          J[📊 FAIR Metadata JSON]
          R[📋 Workflow Report<br/>Confidence + Evidence]
      end
      
      M --> B
      C1 -->|ACCEPT| G
      C1 -->|RETRY| B
      G --> D
      D --> E
      API -.->|packages, terms| E
      E -.->|api_capabilities| C2
      C2 -->|ACCEPT| F
      C2 -->|RETRY| E
      C3 -->|ACCEPT| H
      C3 -->|RETRY| F
      H --> J
      J --> R
      FAIR -.->|validate| J
      
      style A fill:#e3f2fd,stroke:#1565c0
      style J fill:#c8e6c9,stroke:#2e7d32
      style C1 fill:#fff9c4,stroke:#f9a825
      style C2 fill:#fff9c4,stroke:#f9a825
      style C3 fill:#fff9c4,stroke:#f9a825
      style API fill:#e8f5e9,stroke:#43a047
      style R fill:#f3e5f5,stroke:#8e24aa
  ```

  ---

  ## 2. Agent & Node Breakdown

  1. **Document Parser**: Extracts structured information from documents using LLM.
     - Routed to **Critic evaluation** → ACCEPT / RETRY (up to 2×)
  2. **BioMetadataAgent** *(conditional)*: Recovers metadata from raw bioinformatics files (BAM, VCF, FASTQ) using Dockerised biocontainers (Samtools, Bcftools) from `quay.io/biocontainers`.
  3. **Planner**: Analyzes document domain and generates per-agent guidance instructions.
  4. **Knowledge Retriever**: Queries FAIR-DS API (59 packages, 892 terms) + local knowledge base.
     - Reports **API capabilities** for Critic awareness.
     - Routed to **Critic evaluation** → ACCEPT / RETRY / ESCALATE.
  5. **JSON Generator**: Maps extracted info to ISA-Tab metadata.
     - **Recursive Batch Splitting**: Auto-detects truncation and splits batches (16→8→4→2→1 fields) to prevent token window overflow.
     - Routed to **Critic evaluation** → ACCEPT / RETRY.
     - **Cross-layer rollback** (ρ mechanism): JSON hard-gate failure triggers KnowledgeRetriever redo.
  6. **ISA Value Mapper**: Assigns entity_id grouping, maps values to standardised ISA terms.
     - **Cardinality gate**: Skips expensive deep-agent loop when >12 entity groups to save costs.
  7. **Critic Agent**: Embedded after most nodes; rubric-driven LLM-as-Judge.

  ---

  ## 3. Self-Correction & Retry Loop Logic

  - **Retry Attempts**: Up to 2 retries per agent (configurable via `max_step_retries`).
  - **Global Limit**: Maximum total retries across all agents (configurable via `max_global_retries`).
  - **No-Progress Exit**: If the score is unchanged for 2 consecutive attempts, the workflow accepts the output with a review flag to prevent infinite loops.
  - **Cross-Layer Rollback (ρ)**: A validation failure in JSON generation routes feedback back to the Knowledge Retriever rather than just retrying JSON mapping.
  - **Feedback Deduplication**: Limits guidelines to 10 items per agent to prevent token accumulation.

  ---

  ## 4. State Persistence & Checkpointers

  FAIRiAgent uses a checkpointer backend to persist state, enabling workflow resume.
  - `none`: Stateless.
  - `memory`: In-memory (dev/testing only).
  - `sqlite`: Persistent SQLite database (production-ready, defaults to `output/.checkpoints.db`).

  ### Resource Management Snippet

  ```python
  # Recommended for scripts using context manager
  from fairifier.graph import FAIRifierLangGraphApp

  with FAIRifierLangGraphApp() as workflow:
      result = await workflow.run(document_path, project_id)
      # Auto-cleanup of database connections on exit
  ```

  ---

  ## 5. Local Provisional Extensions

  Add custom terms to local knowledge base at `kb/`:

  ```python
  from fairifier.services.local_knowledge import initialize_local_kb, LocalTerm
  from pathlib import Path

  local_kb = initialize_local_kb(Path("kb"))
  local_kb.add_term(LocalTerm(
      name="custom_field",
      label="Custom Field",
      description="Project-specific metadata field",
      source="local",
      status="provisional",
      confidence=0.7
  ))
  ```

  ---

  ## 6. Output Files & Formats

  Outputs are saved to `output/<project_id>/`:
  1. **`metadata.json`**: Standardized FAIR-DS JSON.
  2. **`processing_log.jsonl`**: Real-time structured log events.
  3. **`llm_responses.json`**: Complete record of all LLM requests/responses.
  4. **`runtime_config.json`**: Environment and config variables used in the run.
  5. **`validation_report.txt`**: Shex/validator report.

  ### Output JSON Schema Example

  ```json
  {
    "fairifier_version": "V2.0.2",
    "generated_at": "2026-07-01T18:00:00",
    "document_source": "paper.pdf",
    "overall_confidence": 0.85,
    "metadata": [
      {
        "field_name": "project_name",
        "value": "Soil Metagenomics Study",
        "evidence": "Extracted from title",
        "confidence": 0.95,
        "origin": "document_parser",
        "package_source": "MIMAG",
        "status": "confirmed"
      }
    ]
  }
  ```

  ---

  ## 7. Developer Tracing & LangSmith

  To debug multi-agent trajectories, configure LangSmith:
  ```bash
  export LANGCHAIN_TRACING_V2="true"
  export LANGSMITH_API_KEY="your_api_key"
  export LANGSMITH_PROJECT="fairifier-testing"
  ```
  Or launch locally via LangGraph Studio:
  ```bash
  langgraph dev
  # Studio open at http://localhost:8123
  ```
  ```

- [ ] **Step 2: Commit ARCHITECTURE_AND_FLOW.md changes**
  Run:
  ```bash
  git add docs/en/ARCHITECTURE_AND_FLOW.md
  git commit -m "docs(en): merge advanced agent and config details into ARCHITECTURE_AND_FLOW"
  ```
  Expected: Commits successfully.

---

### Task 3: Create Chinese Technical Documentation `docs/zh/ARCHITECTURE_AND_FLOW.md`

**Files:**
- Create: `docs/zh/ARCHITECTURE_AND_FLOW.md`

- [ ] **Step 1: Write Chinese architecture documentation**
  Write translated equivalents of the Architecture & Flow guide.
  Content to write:
  ```markdown
  # FAIRiAgent 系统架构与工作流

  本文件详细说明 **FAIRiAgent** 的系统架构、Agent 节点设计、交互逻辑以及开发者相关的配置指南。

  ---

  ## 1. 系统架构图

  本系统使用基于 **LangGraph 的多 Agent 工作流**，具有感知 API 限制的评估机制与智能自我校正机制：

  ```mermaid
  flowchart TD
      subgraph INPUT["📥 输入层"]
          A[📄 PDF 文档]
          M[🔧 MinerU 解析器]
          A --> M
      end
      
      subgraph ORCHESTRATOR["🎯 编排器 (LangGraph)"]
          direction TB
          
          subgraph PARSE["步骤 1: 文档解析"]
              B[🔍 文档解析器 Agent<br/>LLM 信息提取]
              C1[🧑‍⚖️ 评估器 Critic]
              B --> C1
          end
          
          subgraph BIO["步骤 2: 生物信息学处理 (可选)"]
              G[🧬 生物元数据 Agent<br/>容器化工具分析]
          end
          
          subgraph PLAN["步骤 3: 规划生成"]
              D[📋 规划器 Planner<br/>生成定制指导指令]
          end
          
          subgraph RETRIEVE["步骤 4: 知识检索"]
              E[🧠 知识检索器 Agent<br/>FAIR-DS API + 本地 KB]
              C2[🧑‍⚖️ 评估器 Critic]
              E --> C2
          end
          
          subgraph GENERATE["步骤 5: JSON 生成"]
              F[📝 JSON 生成器 Agent<br/>ISA-Tab 格式映射]
              C3[🧑‍⚖️ 评估器 Critic]
              F --> C3
          end
          
          subgraph MAP["步骤 6: ISA 值映射"]
              H[🔗 ISA 值映射器 Agent<br/>实体分组与术语标准化]
          end
      end
      
      subgraph EXTERNAL["🌐 外部服务"]
          API[🗄️ FAIR-DS API<br/>59个程序包, 892个术语]
          FAIR[📊 FAIR-DS 验证器<br/>ShEx 模式验证]
      end
      
      subgraph OUTPUT["📤 输出层"]
          J[📊 FAIR 元数据 JSON]
          R[📋 工作流执行报告<br/>置信度 + 证据链]
      end
      
      M --> B
      C1 -->|接受 ACCEPT| G
      C1 -->|重试 RETRY| B
      G --> D
      D --> E
      API -.->|程序包, 术语| E
      E -.->|api_capabilities| C2
      C2 -->|接受 ACCEPT| F
      C2 -->|重试 RETRY| E
      C3 -->|接受 ACCEPT| H
      C3 -->|重试 RETRY| F
      H --> J
      J --> R
      FAIR -.->|验证| J
      
      style A fill:#e3f2fd,stroke:#1565c0
      style J fill:#c8e6c9,stroke:#2e7d32
      style C1 fill:#fff9c4,stroke:#f9a825
      style C2 fill:#fff9c4,stroke:#f9a825
      style C3 fill:#fff9c4,stroke:#f9a825
      style API fill:#e8f5e9,stroke:#43a047
      style R fill:#f3e5f5,stroke:#8e24aa
  ```

  ---

  ## 2. Agent 节点与模块说明

  1. **文档解析器 (Document Parser)**：利用大语言模型提取研究文档中的结构化信息。
     - 连接 **Critic 评估** → ACCEPT（接受） / RETRY（最多重试2次）。
  2. **生物元数据 Agent (BioMetadataAgent)** *（根据输入条件触发）*：通过 **quay.io/biocontainers** 的容器化工具（如 Samtools, Bcftools）直接从原始生物学文件（BAM, VCF, FASTQ）中补充缺失的元数据。
  3. **规划器 (Planner)**：分析文档研究领域，为各个子 Agent 生成特定的提取指导原则。
  4. **知识检索器 (Knowledge Retriever)**：检索 FAIR-DS API（包含 59 个程序包，892 个术语）和本地知识库。
     - 动态反馈 **API 能力限制**（如包不支持等），使 Critic 能够进行感知的多维评估。
     - 连接 **Critic 评估** → ACCEPT / RETRY / ESCALATE。
  5. **JSON 生成器 (JSON Generator)**：将提取的信息映射到符合 ISA-Tab 兼容的元数据中。
     - **递归分批拆分**：在检测到生成内容被截断时，自动将字段数量进行二分拆分（16→8→4→2→1）以避免超出上下文限制。
     - 连接 **Critic 评估** → ACCEPT / RETRY。
     - **跨层回滚 (ρ 机制)**：当 JSON 硬性验证失败时，直接回滚至知识检索节点，携带反馈重新检索。
  6. **ISA 值映射器 (ISA Value Mapper)**：分配 entity_id 分组并将字段值映射到标准术语中。
     - **基数门控机制 (Cardinality gate)**：当检测到实体组数量大于 12 个时，自动使用轻量级策略跳过高成本的 ReAct 循环，以节省算力成本。
  7. **评估器 Agent (Critic Agent)**：在大多数关键节点之后充当 LLM-as-Judge 裁判，按照评分规则对产物进行打分。

  ---

  ## 3. 自我修正与重试逻辑

  - **重试次数**：每个 Agent 最多 2 次（可通过 `.env` 中 `max_step_retries` 调整）。
  - **全局重试上限**：所有 Agent 总计的最大重试次数（通过 `max_global_retries` 调整）。
  - **无进展自动退出**：如果连续 2 次重试分数没有提升，工作流将接受现有输出但会打上 `review` 标签，以防止死循环。
  - **反馈去重**：历史指导意见限制在 10 项以内，避免 Token 堆积。

  ---

  ## 4. 状态持久化与 Checkpointers

  FAIRiAgent 提供状态持久化，允许在发生中断后继续执行。
  - `none`: 无状态。
  - `memory`: 仅保存在内存中（用于开发和测试）。
  - `sqlite`: 写入持久的 SQLite 数据库（默认路径为 `output/.checkpoints.db`，适用于生产）。

  ### 资源管理 Python 代码示例

  ```python
  from fairifier.graph import FAIRifierLangGraphApp

  # 推荐在脚本中使用上下文管理器以自动释放连接
  with FAIRifierLangGraphApp() as workflow:
      result = await workflow.run(document_path, project_id)
  ```

  ---

  ## 5. 本地临时扩展 (Provisional Extensions)

  您可以通过 Python 脚本向本地知识库 (`kb/` 目录) 添加自定义术语：

  ```python
  from fairifier.services.local_knowledge import initialize_local_kb, LocalTerm
  from pathlib import Path

  local_kb = initialize_local_kb(Path("kb"))
  local_kb.add_term(LocalTerm(
      name="custom_field",
      label="Custom Field",
      description="项目特定的元数据字段",
      source="local",
      status="provisional",
      confidence=0.7
  ))
  ```

  ---

  ## 6. 输出文件与格式

  生成的产物保存在 `output/<project_id>/` 目录下：
  1. **`metadata.json`**：标准 FAIR-DS 兼容元数据。
  2. **`processing_log.jsonl`**：结构化实时处理日志。
  3. **`llm_responses.json`**：该次运行的所有大模型 API 交互详情。
  4. **`runtime_config.json`**：该次运行的所有环境变量和运行时参数。
  5. **`validation_report.txt`**：模式校验报告。

  ---

  ## 7. 开发者追踪与调试

  配置 LangSmith 进行调试：
  ```bash
  export LANGCHAIN_TRACING_V2="true"
  export LANGSMITH_API_KEY="your_api_key"
  export LANGSMITH_PROJECT="fairifier-testing"
  ```
  或直接使用本地 LangGraph Studio：
  ```bash
  langgraph dev
  # 访问本地 Studio 可视化界面 http://localhost:8123
  ```
  ```

- [ ] **Step 2: Commit new Chinese architecture guide**
  Run:
  ```bash
  git add docs/zh/ARCHITECTURE_AND_FLOW.md
  git commit -m "docs(zh): create Chinese architecture and workflow guide"
  ```
  Expected: Commits successfully.

---

### Task 4: Rewrite Root `README.md` to be Compact and Bilingual

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite root README.md**
  Write a clean, compact homepage, keeping only the first 2 cartoons (`wide_greetings.png` and `manga_fair.png`), basic commands, quick navigation, security notice, and a basic troubleshooting section.
  Content to write:
  ```markdown
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
  ```

- [ ] **Step 2: Commit modified README.md**
  Run:
  ```bash
  git add README.md
  git commit -m "docs: simplify root README to be compact and bilingual"
  ```
  Expected: Commits successfully.

---

### Task 5: Optimize Documentation Indexes

**Files:**
- Modify: `docs/README.md`
- Modify: `docs/INDEX.md`

- [ ] **Step 1: Update docs/README.md**
  Update the links in `docs/README.md` to reference the newly updated architecture and flow docs.
  Content to replace around lines 13-19:
  ```markdown
  ### Core Documentation
  - [**Architecture & Flow**](en/ARCHITECTURE_AND_FLOW.md): Detailed 6-agent system architecture, ρ-mechanism, and checkpointer configurations.
  - [**Evaluation Methodology**](en/EVALUATION_METHODOLOGY.md): Details on how the system is evaluated.
  ```
  Content to replace around lines 40-42:
  ```markdown
  ### 核心文档 (Core)
  - [**系统架构与工作流**](zh/ARCHITECTURE_AND_FLOW.md): 详细的 6-Agent 节点设计、自校正 ρ 回滚与 Checkpointer 状态持久化配置。
  - [**LLM 集成指南**](zh/LLM_INTEGRATION_GUIDE.md): 如何配置和使用不同的 LLM 提供商。
  ```

- [ ] **Step 2: Update docs/INDEX.md**
  Update the table reference for Architecture & Flow in `docs/INDEX.md`.
  Content to replace around lines 47-48:
  ```markdown
  | [Architecture & Flow](en/ARCHITECTURE_AND_FLOW.md) | Detailed 6-agent nodes, ρ-mechanism, checkpointer |
  ```

- [ ] **Step 3: Commit docs index updates**
  Run:
  ```bash
  git add docs/README.md docs/INDEX.md
  git commit -m "docs(index): update index links to reflect sub-doc updates"
  ```
  Expected: Commits successfully.

---

### Task 6: Final Verification

- [ ] **Step 1: Check status to ensure clean state**
  Run: `git status`
  Expected: Shows only documented markdown edits and gitignore changes. No untracked `.env` or key files.

- [ ] **Step 2: Push changes to main (optional - prepare PR)**
  Run: `git diff --stat HEAD~3`
  Expected: Prints clean summary of files modified.
