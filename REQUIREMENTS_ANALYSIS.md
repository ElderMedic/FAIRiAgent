# FAIRiAgent 项目需求对照分析

## 📋 最小化需求 vs 当前实现

### ✅ 符合要求的部分

#### 1. **输入支持** ✅
- **要求**: 科学文档（PDF/Doc/纯文本），以科研论文/计划书为主
- **当前实现**: 
  - ✅ 支持 PDF (通过 PyMuPDF)
  - ✅ 支持纯文本 (.txt, .md)
  - ✅ 文档解析 Agent (DocumentParserAgent)
- **位置**: `fairifier/agents/document_parser.py`

#### 2. **Domain Context** ✅
- **要求**: 优先从 FAIR-DS API 拉取各层次已有 packages + terms
- **当前实现**:
  - ✅ FAIR-DS 客户端已实现 (`FAIRDataStationClient`)
  - ✅ 支持获取 packages 和 terms
  - ✅ 支持搜索和缓存
- **位置**: `fairifier/services/fair_data_station.py`

#### 3. **Agentic 架构** ✅
- **要求**: 实现 Agentic RAG 并保留传统 RAG 选项以比较
- **当前实现**:
  - ✅ 多 Agent 架构 (5个专业化 Agent)
  - ✅ LangGraph 工作流编排
  - ✅ 知识检索 Agent (KnowledgeRetrieverAgent)
- **位置**: `fairifier/graph/workflow.py`, `fairifier/agents/`

#### 4. **模型选择** ✅
- **要求**: Ollama（本地）/ OpenAI / Anthropic 三选一或兜底
- **当前实现**:
  - ✅ 配置支持 Ollama (默认)
  - ✅ 可通过环境变量切换
  - ⚠️ 需要添加 OpenAI/Anthropic 支持
- **位置**: `fairifier/config.py`

#### 5. **CLI 工具** ✅
- **要求**: 只做 CLI 工具和一个简单界面
- **当前实现**:
  - ✅ CLI 工具已实现 (`fairifier/cli.py`)
  - ✅ 支持文档处理、状态查询、配置查看
- **位置**: `fairifier/cli.py`

#### 6. **LangSmith 支持** ✅
- **要求**: 支持 langsmith 测试检查中间输出
- **当前实现**:
  - ✅ LangSmith 集成已完成
  - ✅ 测试脚本已创建
  - ✅ 配置支持已添加
- **位置**: `test_langsmith.py`, `fairifier/config.py`

---

### ❌ 不符合要求的部分

#### 1. **输出格式** ❌ **重要**
- **要求**: 
  - JSON 格式的 Metadata
  - 符合 FAIR-DS 的结构
  - 字段必须包含: `evidence`, `confidence`, `origin`, `package_source`
  - **不生成** RDF/RO-Crate
  
- **当前实现**:
  - ❌ 生成 JSON Schema + YAML
  - ❌ 生成 RDF (Turtle/JSON-LD)
  - ❌ 生成 RO-Crate
  - ❌ 字段结构不符合 FAIR-DS 要求
  
- **需要修改**:
  ```python
  # 当前字段结构 (models.py)
  class MetadataField:
      name: str
      description: str
      data_type: str
      required: bool
      example_value: Optional[str]
      ontology_term: Optional[str]
      confidence: float
      evidence_text: Optional[str]
  
  # 需要改为 FAIR-DS 结构
  {
    "field_name": "project_name",
    "value": "Soil Metagenomics Study",
    "evidence": "Extracted from document title...",
    "confidence": 0.95,
    "origin": "document_parser",
    "package_source": "MIMAG",
    "status": "confirmed"  # or "provisional"
  }
  ```

#### 2. **本地 Provisional 扩展** ❌
- **要求**: 支持本地 provisional 扩展（与 FAIR-DS 同结构，source=local、status=provisional）
- **当前实现**: ❌ 未实现本地扩展机制
- **需要添加**: 本地 provisional terms/packages 管理

#### 3. **无服务端** ⚠️ **部分符合**
- **要求**: 不做 FastAPI/Auth；只做 CLI 工具和一个简单界面
- **当前实现**:
  - ❌ 包含 FastAPI 服务器 (`fairifier/apps/api/`)
  - ❌ 包含 Streamlit UI (`fairifier/apps/ui/`)
  - ✅ 有 CLI 工具
- **需要修改**: 删除或标记为可选的 API/UI 组件

#### 4. **日志格式** ❌
- **要求**: 最简 stdout（行式 JSON）
- **当前实现**: 
  - ❌ 使用标准 Python logging
  - ❌ 格式为文本而非 JSON
- **需要修改**: 
  ```python
  # 当前 (cli.py)
  logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
  
  # 需要改为
  import json
  import sys
  
  def log_json(event, **kwargs):
      log_entry = {"event": event, "timestamp": datetime.now().isoformat(), **kwargs}
      print(json.dumps(log_entry), file=sys.stdout)
  ```

---

## 🔧 需要的修改清单

### 高优先级 (必须修改)

1. **修改输出格式为纯 JSON**
   - [ ] 移除 RDF 生成 (`rdf_builder.py`)
   - [ ] 移除 RO-Crate 生成
   - [ ] 修改 MetadataField 模型符合 FAIR-DS 结构
   - [ ] 添加 `evidence`, `origin`, `package_source` 字段
   - [ ] 输出单个 JSON 文件而非多个格式

2. **实现本地 Provisional 扩展**
   - [ ] 创建本地 terms/packages 存储
   - [ ] 支持 `source=local`, `status=provisional`
   - [ ] 与 FAIR-DS 结构保持一致

3. **简化为纯 JSON 输出**
   - [ ] 移除 YAML 模板生成
   - [ ] 移除 JSON Schema 生成
   - [ ] 只输出符合 FAIR-DS 的 JSON

4. **修改日志为 JSON 格式**
   - [ ] 实现 JSON 行式日志
   - [ ] 输出到 stdout
   - [ ] 包含时间戳、事件类型、详细信息

### 中优先级 (建议修改)

5. **移除服务端组件**
   - [ ] 删除或标记 FastAPI 为可选
   - [ ] 删除或标记 Streamlit UI 为可选
   - [ ] 保持纯 CLI 模式

6. **添加多模型支持**
   - [ ] 添加 OpenAI 支持
   - [ ] 添加 Anthropic 支持
   - [ ] 实现模型切换逻辑

7. **增强 FAIR-DS 集成**
   - [ ] 优先使用 FAIR-DS packages
   - [ ] 完整的 terms 映射
   - [ ] 缓存优化

### 低优先级 (可选优化)

8. **RAG 比较功能**
   - [ ] 实现传统 RAG 模式
   - [ ] 添加 Agentic vs Traditional 比较
   - [ ] 性能和质量对比

9. **文档和示例**
   - [ ] 更新 README 反映最小化需求
   - [ ] 添加 JSON 输出示例
   - [ ] 更新使用说明

---

## 📊 符合度评分

| 需求项 | 符合度 | 说明 |
|--------|--------|------|
| 输入支持 | ✅ 100% | 完全符合 |
| 输出格式 | ❌ 20% | 需要重大修改 |
| Domain Context | ✅ 80% | 基础已实现，需增强 |
| Agentic RAG | ✅ 90% | 已实现，需添加比较 |
| 模型选择 | ⚠️ 60% | 需添加多模型支持 |
| CLI 工具 | ✅ 100% | 完全符合 |
| 无服务端 | ⚠️ 40% | 需移除 API/UI |
| 日志格式 | ❌ 30% | 需改为 JSON |
| LangSmith | ✅ 100% | 完全符合 |
| **总体符合度** | **⚠️ 69%** | **需要重大调整** |

---

## 🎯 建议的实施路径

### 阶段 1: 核心输出格式调整 (1-2天)
1. 修改 `models.py` 中的数据模型
2. 调整 `template_generator.py` 输出纯 JSON
3. 移除 RDF 和 RO-Crate 生成
4. 实现 FAIR-DS 兼容的 JSON 结构

### 阶段 2: 简化架构 (1天)
1. 移除或标记 API/UI 为可选
2. 修改日志为 JSON 格式
3. 清理不需要的依赖

### 阶段 3: 增强功能 (2-3天)
1. 实现本地 provisional 扩展
2. 添加多模型支持
3. 增强 FAIR-DS 集成
4. 实现 RAG 比较功能

### 阶段 4: 测试和文档 (1天)
1. 更新测试用例
2. 更新文档
3. 创建示例
4. 验证符合度

---

## 📝 结论

当前项目**基本符合**最小化需求的**69%**，但在以下关键方面需要重大调整：

1. **输出格式** - 需要从多格式改为纯 JSON (FAIR-DS 结构)
2. **架构简化** - 需要移除服务端组件
3. **日志格式** - 需要改为 JSON 行式日志

建议优先完成**阶段 1**的核心输出格式调整，这是最关键的不符合项。其他修改可以逐步进行。

预计完成所有调整需要 **5-7 个工作日**。

