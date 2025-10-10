# FAIRifier Agentic Framework - 设计文档

## 核心设计原则
- **MVP优先**: 先实现核心功能，后续迭代优化
- **模块化**: 每个Agent职责单一，可独立测试
- **可追溯**: 所有决策和数据转换都有记录
- **人机协作**: 关键节点支持人工干预

## 系统架构（简化版）

```
输入文档 (PDF/Text) 
    ↓
[文档解析Agent] → 结构化内容
    ↓
[知识检索Agent] → 扩充背景信息
    ↓
[模板生成Agent] → Metadata模板
    ↓
[RDF构建Agent] → RDF/RO-Crate
    ↓
[验证Agent] → SHACL验证
    ↓
[HITL检查点] → 人工审核（可选）
    ↓
输出制品
```

## 核心组件设计

### 1. 状态管理 (LangGraph State)
```python
class FAIRifierState(TypedDict):
    # 输入
    document_path: str
    document_content: str
    
    # 中间状态
    parsed_entities: Dict[str, Any]
    retrieved_knowledge: List[Dict]
    metadata_template: Dict[str, Any]
    rdf_graph: str
    
    # 输出
    validation_results: Dict[str, Any]
    final_artifacts: Dict[str, str]
    
    # 控制流
    needs_human_review: bool
    confidence_scores: Dict[str, float]
```

### 2. 核心Agents

#### DocumentParserAgent
- 输入: PDF/文本文档
- 输出: 结构化研究信息（标题、摘要、方法、数据集等）
- 工具: 简单的文本解析 + LLM提取

#### KnowledgeRetrieverAgent  
- 输入: 解析的研究信息
- 输出: 相关的本体术语、标准字段
- 工具: 预置的FAIR标准知识库

#### TemplateGeneratorAgent
- 输入: 研究信息 + 知识
- 输出: JSON Schema模板 + YAML表单
- 工具: 规则引擎 + LLM生成

#### RDFBuilderAgent
- 输入: 填充的模板数据
- 输出: RDF图 + RO-Crate描述符
- 工具: RDFLib + 预定义本体

#### ValidationAgent
- 输入: 生成的RDF
- 输出: 验证报告 + 置信度评分
- 工具: SHACL验证器

### 3. 最小工具集
- **文档解析**: PyMuPDF (简单PDF文本提取)
- **LLM**: 本地Ollama模型 (避免API依赖)
- **知识库**: 静态JSON文件 (FAIR标准字段)
- **RDF处理**: RDFLib
- **验证**: pySHACL
- **存储**: 本地文件系统 (后续可扩展)

## 实施路线图

### Phase 1: 核心功能 (本次实现)
1. 基础项目结构
2. 核心数据模型
3. 5个核心Agent实现
4. LangGraph工作流编排
5. 简单CLI接口测试

### Phase 2: Web接口
1. FastAPI基础端点
2. 文件上传处理
3. 异步任务处理

### Phase 3: 人工干预
1. 置信度评分机制
2. HITL检查点
3. 简单Web UI

### Phase 4: 增强功能
1. 知识库扩展
2. 更复杂的解析
3. 外部API集成

## 成功标准
- [ ] 能处理简单的PDF研究文档
- [ ] 生成有效的JSON Schema模板
- [ ] 输出符合标准的RDF/RO-Crate
- [ ] 端到端执行时间 < 2分钟
- [ ] 核心字段覆盖率 > 80%
