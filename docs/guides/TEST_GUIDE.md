# 🧪 测试运行指南

## 📋 准备工作

### 1. 环境配置

#### 创建 `.env` 文件
```bash
cd /Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent
cp env.example .env
```

#### 编辑 `.env` 文件
```bash
# LangSmith 配置（必需）
LANGSMITH_API_KEY=your_actual_langsmith_api_key
LANGSMITH_PROJECT=fairifier-test
LANGSMITH_ENDPOINT=https://api.smith.langchain.com

# LLM 配置
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:8b
LLM_BASE_URL=http://localhost:11434

# FAIR-DS API（必需）
FAIR_DS_API_URL=http://localhost:8083
```

### 2. 检查依赖服务

#### a. 检查 Ollama 是否运行
```bash
curl http://localhost:11434/api/tags
# 应该返回模型列表

# 确保有 qwen3:8b 模型
ollama list | grep qwen3

# 如果没有，拉取模型
ollama pull qwen3:8b
```

#### b. 检查 FAIR-DS API 是否运行
```bash
curl http://localhost:8083/api/packages | jq '.[0:2]'
# 应该返回 JSON 格式的 packages 数据

curl http://localhost:8083/api/terms | jq '.[0:2]'
# 应该返回 JSON 格式的 terms 数据
```

如果返回 HTML 或错误，需要启动 FAIR-DS API。

### 3. 激活环境
```bash
mamba activate test
cd /Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent
```

---

## 📝 创建测试文档

### 方法 1: 使用示例文档（推荐）
```bash
# 检查是否有示例文档
ls examples/inputs/

# 使用 test_document.txt（如果存在）
cat examples/inputs/test_document.txt
```

### 方法 2: 创建新的测试文档
```bash
cat > examples/inputs/my_test_doc.txt << 'EOF'
Title: Microbial Diversity Analysis in Alpine Soil Ecosystems

Authors: Dr. John Smith, Dr. Jane Doe, Prof. Alice Johnson

Abstract: This study investigates the microbial community composition and diversity 
in alpine grassland soils across different elevation gradients in the Swiss Alps. 
We employed shotgun metagenomics sequencing to characterize bacterial and archaeal 
populations at three distinct altitude zones (2000m, 2500m, and 3000m).

Keywords: metagenomics, alpine ecology, soil microbiome, microbial diversity, 
elevation gradient, Swiss Alps, bacterial communities

Study Site: 
- Location: Grindelwald region, Swiss Alps
- Coordinates: 46.62°N, 8.04°E
- Elevation range: 2000-3000 meters above sea level
- Habitat: Alpine grassland

Sampling Design:
- Three elevation zones: Low (2000m), Mid (2500m), High (3000m)
- Three replicate sites per zone
- Total samples: 9 soil cores
- Sampling depth: 0-10 cm
- Sampling period: Summer 2024

Environmental Parameters:
- Temperature range: 5-15°C (summer)
- pH range: 5.5-6.5
- Soil type: Alpine brown soil
- Vegetation: Mixed alpine grasses and herbs

Methods:
- DNA extraction: DNeasy PowerSoil Kit (Qiagen)
- Sequencing platform: Illumina NovaSeq 6000
- Sequencing type: Shotgun metagenomics
- Read length: 2x150bp paired-end
- Coverage: ~10 Gbp per sample
- Quality filtering: Trimmomatic (Q>20)
- Assembly: metaSPAdes v3.15
- Taxonomic classification: Kraken2 + Bracken
- Functional annotation: KEGG, COG databases

Expected Outcomes:
- Characterization of microbial community structure
- Analysis of diversity patterns along elevation gradient
- Identification of cold-adapted microbial taxa
- Functional potential of alpine microbiomes
EOF
```

---

## 🚀 运行测试

### 基本运行（启用 LangSmith）

```bash
# 确保在项目根目录
cd /Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent

# 激活环境
mamba activate test

# 设置 LangSmith 环境变量（如果没有 .env 文件）
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_PROJECT=fairifier-cli-test
export LANGSMITH_API_KEY=your_key_here

# 运行 CLI
python -m fairifier.cli process examples/inputs/my_test_doc.txt
```

### 带详细输出的运行

```bash
# 使用 verbose 模式查看详细日志
python -m fairifier.cli process examples/inputs/my_test_doc.txt --verbose

# 指定输出目录
python -m fairifier.cli process examples/inputs/my_test_doc.txt \
  --output-dir output_test_$(date +%Y%m%d_%H%M%S) \
  --verbose
```

### 使用项目 ID 运行

```bash
# 指定项目 ID 方便追踪
python -m fairifier.cli process examples/inputs/my_test_doc.txt \
  --project-id alpine_soil_test_001 \
  --output-dir output_alpine_test \
  --verbose
```

---

## 🔍 查看输出

### CLI 输出示例

你会看到类似这样的输出：

```
======================================================================
🚀 FAIRifier - Automated FAIR Metadata Generation
======================================================================
📄 Document: examples/inputs/my_test_doc.txt
📁 Output: output_alpine_test
🤖 LLM: qwen3:8b (ollama)
🌐 FAIR-DS API: http://localhost:8083
📊 LangSmith: ✅ Enabled (Project: fairifier-cli-test)
======================================================================

🔄 Starting processing (Project ID: alpine_soil_test_001)

======================================================================
📋 Step: DocumentParser
   Parse and extract information from document
======================================================================
▶️  Executing DocumentParser...
📄 📖 Reading document: examples/inputs/my_test_doc.txt
📄 ✅ Read 2847 characters from text file
📄 🤖 Using LLM for intelligent, adaptive extraction...
📄 ✅ LLM extracted: ['title', 'authors', 'abstract', 'keywords', ...]
📄 ✅ Parsing completed!
   - Title: True
   - Authors: 3
   - Keywords: 7
   - Location: Swiss Alps, Grindelwald region
   - Coordinates: 46.62°N, 8.04°E
   - Confidence: 92%

🔍 Calling Critic to evaluate DocumentParser output...
📊 Critic Decision: ACCEPT (confidence: 0.92)
   Feedback: Document parsing looks good. All critical information extracted.
✅ DocumentParser completed successfully

======================================================================
📋 Step: KnowledgeRetriever
   Retrieve FAIR-DS knowledge and ontology terms
======================================================================
▶️  Executing KnowledgeRetriever...
🔍 🌐 Fetching metadata from FAIR-DS API...
🔍    📡 GET /api/packages...
🔍    📡 GET /api/terms...
🔍 ✅ Retrieved from API: 45 packages, 523 terms
🔍 🏗️  Retrieved FAIR-DS hierarchical structure (FAIR-DS-API):
🔍    📊 investigation: 15 terms, 5 packages
🔍    📊 study: 25 terms, 12 packages
🔍    📊 assay: 35 terms, 18 packages
...

🔍 Calling Critic to evaluate KnowledgeRetriever output...
📊 Critic Decision: ACCEPT (score: 0.85)
✅ KnowledgeRetriever completed successfully

[继续显示其他步骤...]

======================================================================
📊 Processing Results
======================================================================

🎯 Confidence Scores:
  ✅ critic: 0.88
  ✅ structural: 0.81
  ✅ validation: 1.00
  ✅ overall: 0.90

📋 quality_metrics:
  - field_completion_ratio: 0.92
  - evidence_coverage_ratio: 0.85
  - avg_field_confidence: 0.88

📈 Status: COMPLETED
⏱️  Duration: 45.23 seconds

💾 Saving artifacts...
  ✓ metadata_json.json (15.2 KB)
  ✓ processing_log.jsonl (8.3 KB)
  ✓ llm_responses.json (25.1 KB)

💡 Tip: Check llm_responses.json to see LLM's thinking process

======================================================================
✨ Processing complete!
📁 Output saved to: output_alpine_test
======================================================================
```

### 输出文件

检查生成的文件：

```bash
ls -lh output_alpine_test/

# 查看元数据 JSON
cat output_alpine_test/metadata_json.json | jq '.'

# 查看处理日志
cat output_alpine_test/processing_log.jsonl | jq '.'

# 查看 LLM 响应
cat output_alpine_test/llm_responses.json | jq '.[0]'

# 查看执行历史（如果有）
cat output_alpine_test/workflow_results.json | jq '.execution_history'
```

---

## 🔎 在 LangSmith 中查看

### 1. 访问 LangSmith Dashboard
```
https://smith.langchain.com/
```

### 2. 选择你的项目
- 点击左侧 "Projects"
- 找到 `fairifier-cli-test` 项目

### 3. 查看 Traces
你会看到完整的执行链：
```
FAIRifierLangGraphApp
├─ ReadFile
├─ DocumentParser → LLM.ExtractDocumentInfo
├─ Critic.EvaluateDocumentParsing
├─ PlanWorkflow（输出 special_instructions）
├─ KnowledgeRetriever
│  ├─ LLM.SelectPackages
│  └─ LLM.SelectFieldsByISASheet
├─ Critic.EvaluateKnowledgeRetrieval
├─ JSONGenerator
│  ├─ LLM.SelectRelevantFields
│  └─ LLM.GenerateMetadata
└─ Critic.EvaluateJSONGeneration
```

### 4. 深入分析
- 点击任何步骤查看详细信息
- 查看 LLM 的 prompt 和 response
- 检查执行时间和 token 使用
- 查看错误和警告

---

## 🐛 Debug 技巧

### 1. 查看详细日志
```bash
# 使用 verbose 模式
python -m fairifier.cli process document.txt --verbose 2>&1 | tee run.log

# 检查日志
grep "❌" run.log  # 查找错误
grep "⚠️" run.log   # 查找警告
grep "Critic" run.log  # 查找 Critic 评估
```

### 2. 查看 LLM 响应
```bash
# 查看所有 LLM 交互
cat output_*/llm_responses.json | jq '.[] | {operation, response: .response[0:200]}'

# 查看特定操作
cat output_*/llm_responses.json | jq '.[] | select(.operation == "extract_document_info")'
```

### 3. 检查执行历史
```bash
# 如果使用 test_reflective_workflow.py
cat output_*/workflow_results.json | jq '.execution_history[] | {
  agent: .agent_name,
  attempt: .attempt,
  decision: .critic_evaluation.decision,
  score: .critic_evaluation.score,
  improvements: .critic_evaluation.improvement_ops
}'
```

### 4. 检查 Critic 反馈
```bash
# 查看所有 Critic 评估
cat output_*/workflow_results.json | jq '.execution_history[] | 
  select(.critic_evaluation != null) | 
  {
    agent: .agent_name,
    decision: .critic_evaluation.decision,
    issues: .critic_evaluation.issues,
    suggestions: .critic_evaluation.suggestions
  }'
```

---

## 🔧 常见问题

### 问题 1: FAIR-DS API 连接失败
```
❌ FAIR-DS API client not available
```

**解决方案：**
```bash
# 检查 FAIR-DS 是否运行
curl http://localhost:8083/api/packages

# 如果没有运行，启动 FAIR-DS
# (根据你的 FAIR-DS 安装方式)
```

### 问题 2: Ollama 模型不可用
```
Error: model 'qwen3:8b' not found
```

**解决方案：**
```bash
# 拉取模型
ollama pull qwen3:8b

# 或使用其他模型
export LLM_MODEL=llama2:7b
```

### 问题 3: LangSmith 未追踪
```
📊 LangSmith: ⚠️  Enabled but no API key
```

**解决方案：**
```bash
# 设置 API key
export LANGSMITH_API_KEY=your_actual_key

# 或在 .env 文件中设置
echo "LANGSMITH_API_KEY=your_key" >> .env
```

### 问题 4: 内存不足
```
Error: Out of memory
```

**解决方案：**
```bash
# 使用更小的模型
export LLM_MODEL=qwen3:4b

# 或减少文档大小
head -c 5000 large_document.pdf > small_doc.txt
```

---

## 📊 测试不同场景

### 场景 1: 基因组学研究
```bash
cat > examples/inputs/genomics_test.txt << 'EOF'
Title: De novo Genome Assembly of Tetraploid Earthworm

Authors: Smith et al.

Abstract: Whole genome sequencing and assembly of Eisenia fetida 4n strain...

Methods: PacBio Sequel II, Illumina HiSeq, MAKER annotation pipeline...
EOF

python -m fairifier.cli process examples/inputs/genomics_test.txt --verbose
```

### 场景 2: 生态学野外调查
```bash
cat > examples/inputs/ecology_test.txt << 'EOF'
Title: Biodiversity Survey of Alpine Meadows

Location: Swiss National Park
Coordinates: 46.7°N, 10.2°E

Methods: Quadrat sampling, species identification, environmental measurements...
EOF

python -m fairifier.cli process examples/inputs/ecology_test.txt --verbose
```

### 场景 3: 方法学论文
```bash
cat > examples/inputs/methods_test.txt << 'EOF'
Title: Novel Protocol for Environmental DNA Extraction from Soil Samples

Abstract: We present an optimized method for extracting high-quality environmental 
DNA from various soil types...

Protocol Steps:
1. Sample collection and preservation
2. DNA extraction procedure
3. Quality control
...
EOF

python -m fairifier.cli process examples/inputs/methods_test.txt --verbose
```

---

## ✅ 成功标志

运行成功应该看到：

1. ✅ 所有步骤都显示 "ACCEPT" 或最多 1-2 次 "RETRY"
2. ✅ 整体置信度 > 0.75
3. ✅ 生成的 `metadata_json.json` 包含 15-25 个字段
4. ✅ 所有字段都有 `evidence` 和 `confidence`
5. ✅ LangSmith 显示完整的 trace

---

## 📚 下一步

1. **分析结果** - 检查生成的元数据质量
2. **调整配置** - 根据需要调整置信度阈值
3. **测试更多文档** - 尝试不同类型的研究文档
4. **查看 LangSmith** - 深入分析 LLM 决策过程
5. **优化 Prompts** - 根据结果改进 prompts

---

## 🎯 快速测试命令（一键运行）

```bash
#!/bin/bash
# quick_test.sh - 快速测试脚本

# 激活环境
mamba activate test

# 设置环境变量
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_PROJECT=fairifier-quick-test
# export LANGSMITH_API_KEY=your_key  # 取消注释并填入你的 key

# 创建输出目录
OUTPUT_DIR="output_test_$(date +%Y%m%d_%H%M%S)"

# 运行测试
echo "🚀 Starting FAIRifier test..."
python -m fairifier.cli process examples/inputs/test_document.txt \
  --output-dir "$OUTPUT_DIR" \
  --project-id "test_$(date +%H%M%S)" \
  --verbose

echo ""
echo "✅ Test complete!"
echo "📁 Output directory: $OUTPUT_DIR"
echo "🔍 View in LangSmith: https://smith.langchain.com/"
```

保存并运行：
```bash
chmod +x quick_test.sh
./quick_test.sh
```

