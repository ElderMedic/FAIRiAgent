# 🚀 快速开始

## 最简单的测试步骤

### 1️⃣ 配置环境变量

```bash
cd /path/to/FAIRiAgent
mamba activate FAIRiAgent

# 复制配置文件
cp env.example .env

# 编辑 .env 文件（用你喜欢的编辑器）
nano .env
# 或
vim .env
# 或
code .env
```

**最小配置（写在 `.env` 中）：**
```bash
# LLM（最少需要一个 provider）
LLM_PROVIDER=ollama
FAIRIFIER_LLM_MODEL=qwen3:8b

# FAIR-DS
FAIR_DS_API_URL=http://localhost:8083

# LangSmith（可选）
# LANGSMITH_API_KEY=your_langsmith_key
# LANGSMITH_PROJECT=fairifier-test
```

**常见 provider 示例：**
```bash
# Qwen
LLM_PROVIDER=qwen
FAIRIFIER_LLM_MODEL=qwen-flash
LLM_API_KEY=your_dashscope_api_key

# Gemini
LLM_PROVIDER=gemini
FAIRIFIER_LLM_MODEL=gemini-3.1-pro-preview
GOOGLE_API_KEY=your_google_api_key

# Anthropic
LLM_PROVIDER=anthropic
FAIRIFIER_LLM_MODEL=claude-sonnet-4-6
LLM_API_KEY=your_anthropic_api_key
```

### 2️⃣ 启动依赖服务

#### 启动 Ollama（如果还没运行）
```bash
# 检查是否运行
curl http://localhost:11434/api/tags

# 如果没运行，启动它
ollama serve

# 确保有模型
ollama list
# 如果没有 qwen3:8b
ollama pull qwen3:8b
```

#### 启动 FAIR-DS API（如果还没运行）

**方式 A — Docker Compose（推荐，一次拉起 API + FAIR-DS + Qdrant）**

参见英文文档 [Docker Deployment Guide](../../en/guides/DOCKER_DEPLOYMENT.md)：在仓库根目录构建镜像后，进入 `docker/` 配置 `.env` 并执行 `docker compose up -d --build`。Compose 中的 `fairds` 服务会在容器网络内提供 `http://fairds:8083`，一般无需再手写 `FAIR_DS_API_URL`。

**方式 B — 本机 JAR**

```bash
# 检查是否运行
curl http://localhost:8083/api/package

# 若无响应：下载并启动 FAIR-DS（与主 README 相同）
# wget http://download.systemsbiology.nl/unlock/fairds-latest.jar
# java -jar fairds-latest.jar
```

也可使用 `docker/pack-fairds-jar.sh` 将 `~/Downloads` 下最新的 `fairds*.jar` 复制到 `docker/fairds/fairds.jar`，并在 `docker/.env` 中设置 `FAIRDS_DOCKERFILE=Dockerfile.from-local` 后仅重建 `fairds` 镜像（JAR 体积大，默认不纳入 git）。

### 3️⃣ 运行快速测试

```bash
# 激活环境
mamba activate FAIRiAgent

# 方式 1: 使用测试脚本（推荐）
./quick_test.sh

# 方式 2: 直接使用 CLI
python -m fairifier.cli process examples/inputs/earthworm_4n_paper_bioRxiv.pdf --verbose
```

### 4️⃣ 可选：启用记忆层（mem0）

如果你想测试 session memory / persistent memory：

```bash
# 安装依赖
pip install mem0ai qdrant-client

# 启动 Qdrant
docker run -d -p 6333:6333 qdrant/qdrant

# 在 .env 中启用
MEM0_ENABLED=true
MEM0_QDRANT_URL=http://localhost:6333
```

详细说明见：[Mem0 快速开始](MEM0_QUICKSTART.md)

---

## 📊 查看结果

### CLI 输出
你会看到实时的进度输出，包括：
- ✅ 每个步骤的执行状态
- 🔍 Critic/LLM-as-Judge 的评估结果
- 📊 置信度分数（critic / structural / validation / overall）
- 💾 生成的文件列表

示例片段：
```
🎯 Confidence Scores:
  ✅ critic: 0.78
  ⚠️ structural: 0.62
  ✅ validation: 1.00
  ⚠️ overall: 0.76

quality_metrics:
  field_completion_ratio: 0.80
  evidence_coverage_ratio: 0.70
  avg_field_confidence: 0.83
```

### 查看生成的文件
```bash
# 列出输出文件
ls -lh output_test_*/

# 查看元数据（美化 JSON）
cat output_test_*/metadata_json.json | jq '.'

# 查看前 5 个字段
cat output_test_*/metadata_json.json | jq '.metadata[0:5]'

# 查看处理日志
cat output_test_*/processing_log.jsonl | head -20

# 查看 LLM 交互
cat output_test_*/llm_responses.json | jq '.[0]'
```

### 在 LangSmith 查看（可选）
1. 打开浏览器访问：https://smith.langchain.com/
2. 登录你的账号
3. 选择项目：`fairifier-test`
4. 查看最新的 trace

你会看到完整的执行流程：
```
FAIRifierLangGraphApp
├─ read_file
├─ parse_document → Critic → ✅ ACCEPT
├─ plan_workflow （生成指导指令）
├─ retrieve_knowledge → Critic → ✅ ACCEPT
├─ generate_json → Critic → ✅ ACCEPT
└─ finalize
```

---

## 🎯 测试不同的文档

### 创建你自己的测试文档
```bash
cat > examples/inputs/my_research.txt << 'EOF'
Title: 你的研究标题

Authors: 作者姓名

Abstract: 研究摘要...

Keywords: 关键词1, 关键词2...

[添加更多内容...]
EOF

# 测试你的文档
python -m fairifier.cli process examples/inputs/my_research.txt --verbose
```

---

## 🐛 常见问题快速解决

### 问题 1: LangSmith 没有追踪数据
```bash
# 检查环境变量
echo $LANGCHAIN_TRACING_V2  # 应该是 "true"
echo $LANGSMITH_API_KEY     # 应该显示你的 key

# 如果没有，重新设置
export LANGCHAIN_TRACING_V2=true
export LANGSMITH_API_KEY=your_key
```

### 问题 2: FAIR-DS 连接失败
```bash
# 检查 FAIR-DS API
curl http://localhost:8083/api/package

# 如果返回 HTML 或错误，检查 FAIR-DS 是否正确启动
```

### 问题 3: Ollama 模型找不到
```bash
# 拉取模型
ollama pull qwen3:8b

# 或使用其他模型
export LLM_MODEL=llama2:7b
```

---

## ✅ 成功的标志

运行成功后，你应该看到：

1. ✅ 所有步骤显示 "ACCEPT" 决策
2. ✅ 整体置信度 > 75%
3. ✅ 生成了 3-4 个输出文件
4. ✅ LangSmith 显示完整的 trace
5. ✅ `metadata_json.json` 包含 15-25 个字段

---

## 📞 需要帮助？

### 查看详细日志
```bash
# 使用 verbose 模式
python -m fairifier.cli process your_doc.txt --verbose 2>&1 | tee debug.log

# 查找错误
grep "❌" debug.log
grep "Error" debug.log

# 查找警告
grep "⚠️" debug.log
```

### 检查系统状态
```bash
# 检查配置
python -m fairifier.cli config-info

# 验证文档
python -m fairifier.cli validate-document your_doc.txt
```

---

## 🎉 下一步

测试成功后：
1. 📖 阅读 `TEST_GUIDE.md` 了解更多测试选项
2. 🔍 在 LangSmith 深入分析 LLM 的决策过程
3. 📝 尝试处理你的真实研究文档
4. ⚙️ 根据需要调整配置和阈值
5. 🧠 如果要测试记忆能力，继续阅读 `MEM0_QUICKSTART.md`

**祝测试顺利！** 🚀
