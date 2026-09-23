# 快速开始

两条路径都可以。**Docker Compose** 最省事，一次拉起 FAIR-DS 和 API，不需要 MinerU。想在本机用 Python 跑，用后面的 conda / mamba 路径。

## 方式 A — Docker Compose（推荐）

**前提：** Docker Desktop 或带 Compose v2 的 Docker Engine。FAIR-DS 默认拉取官方镜像，清单里只有 `linux/amd64`。第一次拉取前先检查本机架构。

```bash
git clone https://github.com/ElderMedic/FAIRiAgent.git
cd FAIRiAgent/docker

# 处理文档前必须配置 LLM
cp .env.example .env
# 编辑 .env：云端填写 LLM_PROVIDER 和 LLM_API_KEY，或按文件里的注释改成宿主机 Ollama

./check_fairds_platform.sh
docker compose up -d --build
```

云端提供商不要把 `FAIRIFIER_LLM_BASE_URL` 改成厂商地址。Compose 里的 `http://host.docker.internal:11434` 只表示宿主机 Ollama；Qwen、DeepSeek、智谱会改用各自的官方 API。显式覆盖用 `QWEN_API_BASE_URL`、`DEEPSEEK_API_BASE_URL` 或 `ZHIPU_API_BASE_URL`。

**安装检查：**

```bash
# FAIR-DS
curl -sf http://localhost:8083/api/package | head

# FAIRiAgent API
curl -sf http://localhost:8000/api/v1/health

# 容器内预检（FAIR-DS + LLM）
docker compose exec fairifier-api python run_fairifier.py validate-document --env-only
```

预检里的 Embeddings 如果是 warning，表示没装 `sentence-transformers`。词法检索仍然可用，这不阻止运行。

**第一次跑通（不需要 MinerU）：**

```bash
docker compose exec fairifier-api python run_fairifier.py process \
  /app/examples/quickstart/earthworm_4n_paper_bioRxiv.md --verbose
```

- API 文档：http://localhost:8000/docs
- 8000 端口被占用时：`FAIRIFIER_HOST_PORT=8001 docker compose up -d`，然后打开 http://localhost:8001
- Apple Silicon 没有官方 arm64 清单。不带平台参数的 `docker pull` 会报 `no matching manifest for linux/arm64`。Compose 固定 `platform: linux/amd64`，由 Docker 模拟运行。不想模拟时，在 `docker/` 里构建原生镜像，或改走下面的本机 Java / conda：

```bash
FAIRDS_PLATFORM=linux/arm64 docker compose \
  -f compose.yaml -f compose.fairds-jar.yaml up -d --build fairds
```

- 细节：[docker/README.md](../../../docker/README.md) · [Docker 部署指南](../../en/guides/DOCKER_DEPLOYMENT.md)

只构建轻量 API 镜像时，在 `docker/` 目录执行：

```bash
export FAIRIFIER_DOCKERFILE=docker/Dockerfile.minimal
docker compose up -d --build fairifier-api
```

## 方式 B — 本机 conda / mamba

- Python 3.11+
- 只有需要 Web UI 时才要 Node.js 18+
- FAIR-DS 在 `http://localhost:8083`，或在 `.env` 里改成你的端口

**不用 Docker、直接跑 JAR：**

```bash
# 下载一次，写入 docker/fairds/fairds.jar
./scripts/update_fairds_jar.sh

# 需要 Java 21。默认端口 8083；被占用就改端口，并同步改 .env 里的 FAIR_DS_API_URL
java -Dserver.port=8083 -jar docker/fairds/fairds.jar
```

**只把 FAIR-DS 放进 Docker，FAIRiAgent 仍在本机：** `cd docker && docker compose up -d fairds`

```bash
git clone https://github.com/ElderMedic/FAIRiAgent.git
cd FAIRiAgent

mamba create -n FAIRiAgent python=3.11 -y
mamba activate FAIRiAgent
pip install -r requirements.txt

cp env.example .env
# 编辑 .env：LLM_PROVIDER、LLM_API_KEY（或 Ollama）、FAIR_DS_API_URL=http://localhost:8083
# 下面的 Markdown 快速开始不需要 MinerU：MINERU_ENABLED=false

# 预检
mamba run -n FAIRiAgent python run_fairifier.py validate-document --env-only

# 多来源快速开始（Markdown + Excel，不需要 MinerU）
mamba run -n FAIRiAgent python run_fairifier.py process examples/quickstart/earthworm_4n_paper_bioRxiv.md --verbose

# Web UI（第一次运行会构建前端）
mamba run -n FAIRiAgent python run_fairifier.py webui
# 打开 http://localhost:8000
```

默认安装不包含 `sentence-transformers`，因此不会拉下 CUDA / Triton。本机已经装过这个包时，本地向量嵌入会自动启用；没装时预检给出 warning，检索退回词法匹配。

### 本机 LLM 示例

写在仓库根目录的 `.env` 里。模型变量名是 `FAIRIFIER_LLM_MODEL`。

```bash
# Ollama
LLM_PROVIDER=ollama
FAIRIFIER_LLM_MODEL=qwen3:8b
FAIRIFIER_LLM_BASE_URL=http://localhost:11434

# Qwen
LLM_PROVIDER=qwen
FAIRIFIER_LLM_MODEL=qwen-flash
LLM_API_KEY=your_dashscope_api_key

# DeepSeek
LLM_PROVIDER=deepseek
FAIRIFIER_LLM_MODEL=deepseek-v4-pro
LLM_API_KEY=your_deepseek_api_key

# Zhipu (GLM)
LLM_PROVIDER=zhipu
FAIRIFIER_LLM_MODEL=glm-5.2
LLM_API_KEY=your_zhipu_api_key

# Gemini
LLM_PROVIDER=gemini
FAIRIFIER_LLM_MODEL=gemini-3.1-pro-preview
GOOGLE_API_KEY=your_google_api_key

# Anthropic
LLM_PROVIDER=anthropic
FAIRIFIER_LLM_MODEL=claude-sonnet-4-6
LLM_API_KEY=your_anthropic_api_key
```

宿主机 Ollama 需要先启动并拉模型：

```bash
ollama serve
ollama pull qwen3:8b
```

LangSmith 默认关闭。要打开追踪，同时设置 `LANGSMITH_API_KEY` 和 `LANGCHAIN_TRACING_V2=true`。只写 key 不会开始追踪。

## 查看结果

命令结束时会打印本次输出目录，一般是 `output/<YYYYMMDD_HHMMSS>/`。

```bash
# 元数据
cat output/*/deliverables/metadata.json | jq '.'

# 处理日志
cat output/*/logs/processing_log.jsonl | head -20

# LLM 交互
cat output/*/logs/llm_responses.json | jq '.[0]'

# 工作流报告
cat output/*/reports/workflow_report.json | jq '.performance'
```

目录里有很多历史运行时，改成 CLI 打印的那一个具体目录。

跑通的标志是：`validate-document --env-only` 没有失败项，`process` 结束，并且该次目录下存在 `deliverables/metadata.json`。Critic 分数和 LangSmith 追踪都不是安装是否成功的条件。

## 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| API 超时或 LLM 报错 | 密钥或网络不对 | 在 `docker/.env`（Compose）或仓库根 `.env`（本机）设置 `LLM_PROVIDER` 和 `LLM_API_KEY`，再跑 `validate-document --env-only` |
| FAIR-DS 连不上 | 服务还没起来 | `cd docker && docker compose up -d fairds`，等到 healthy，再 `curl http://localhost:8083/api/package` |
| `fairifier-api` 一直不起 | 在等 FAIR-DS 健康检查 | `docker compose ps` 和 `docker compose logs fairds`。第一次启动大约 1–2 分钟 |
| 找不到 Ollama 模型 | 本机没有这个模型 | `ollama pull <model_name>`，例如 `ollama pull qwen3:8b`。容器里访问宿主机用 `FAIRIFIER_LLM_BASE_URL=http://host.docker.internal:11434` |
| LLM 429 或余额不足 | 云端额度用完 | 给账户充值，或把 `docker/.env` 改成可用密钥 / 本机 Ollama。先预检，再 `process` |
| 8000 端口被占用 | 已有进程占用 | 在 `docker/` 下执行 `FAIRIFIER_HOST_PORT=8001 docker compose up -d` |
| 容器访问不到宿主机 Ollama 或 MinerU | 容器网络 | 使用 `host.docker.internal`。Compose 已经配置了 `extra_hosts` |

## 可选：记忆层（mem0）

Compose 已经带了 Qdrant，默认 `MEM0_ENABLED=false`。要打开记忆，在 `docker/.env` 或本机 `.env` 里设置 `MEM0_ENABLED=true`。本机单独跑时再启动 Qdrant，不要和 Compose 抢 6333 端口。

说明见 [Mem0 快速开始](MEM0_QUICKSTART.md)。

## 下一步

- [测试指南](TEST_GUIDE.md)
- [系统架构与工作流](../ARCHITECTURE_AND_FLOW.md)
- [LLM 集成指南](../LLM_INTEGRATION_GUIDE.md)
