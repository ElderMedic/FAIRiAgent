# FAIRiAgent 测试策略

本文档定义了 FAIRiAgent 项目的核心单元测试策略，旨在确保代码可靠性，同时保持测试的简洁性和可维护性。

## 测试原则

1. **测试业务逻辑，而非框架代码**：重点测试核心业务逻辑，避免测试 LangGraph、LangChain 等框架本身
2. **纯函数优先**：优先测试无副作用的纯函数（解析、转换、计算）
3. **Mock 外部依赖**：外部 API、LLM 调用使用 mock，避免真实网络请求
4. **边界情况覆盖**：测试空值、异常、边界条件
5. **保持简洁**：避免过度测试，每个测试应有明确目的

## 必须的单元测试

### 1. 数据解析和转换层 ✅ 高优先级

#### 1.1 FAIR-DS API 解析器 (`fairds_api_parser.py`)
**为什么重要**：这是与外部 API 交互的关键，解析逻辑错误会导致整个工作流失败

```python
# tests/test_fairds_api_parser.py
- test_parse_terms_response() - 解析 terms API 响应
- test_parse_package_response() - 解析 package API 响应
- test_extract_field_info() - 提取字段信息
- test_extract_term_info() - 提取术语信息
- test_parse_empty_response() - 空响应处理
- test_parse_malformed_response() - 格式错误处理
```

#### 1.2 JSON 解析工具 (`llm_helper.py`, `critic.py`)
**为什么重要**：LLM 返回的 JSON 格式多变，解析失败会导致工作流中断

```python
# tests/test_critic_utils.py ✅ 已有
- test_safe_json_parse_handles_code_fence() ✅
- test_safe_json_parse_handles_generic_code_fence() ✅
- ... (已有 7 个测试)

# tests/test_llm_helper_utils.py (新增)
- test_extract_json_from_markdown() - 从 markdown 提取 JSON
- test_parse_json_with_fallback() - JSON 解析回退策略
- test_parse_json_with_nested_objects() - 嵌套对象处理
- test_parse_json_with_unicode() - Unicode 字符处理
```

### 2. 数据模型和验证层 ✅ 高优先级

#### 2.1 状态验证 (`models.py`)
**为什么重要**：状态结构错误会导致工作流崩溃，需要在早期发现

```python
# tests/test_models.py (新增)
- test_metadata_field_creation() - MetadataField 创建和验证
- test_metadata_field_required_fields() - 必需字段检查
- test_fairifier_state_structure() - FAIRifierState 结构验证
- test_state_serialization() - 状态序列化/反序列化
- test_validation_result_creation() - ValidationResult 创建
```

#### 2.2 配置验证 (`config.py`)
**为什么重要**：配置错误会导致运行时失败，应该在启动时发现

```python
# tests/test_config.py (新增)
- test_config_default_values() - 默认值验证
- test_config_env_overrides() - 环境变量覆盖
- test_config_validation() - 配置值验证（范围、类型）
- test_config_path_resolution() - 路径解析
- test_config_missing_required() - 缺失必需配置处理
```

### 3. 核心业务逻辑层 ✅ 高优先级

#### 3.1 置信度聚合 (`confidence_aggregator.py`)
**为什么重要**：置信度计算错误会导致错误的决策

```python
# tests/test_confidence_aggregator.py ✅ 已有
- test_aggregate_confidence_combines_components() ✅
- test_aggregate_confidence_empty_state() ✅
- test_aggregate_confidence_with_validation_errors() ✅

# 建议补充
- test_confidence_weights_application() - 权重应用
- test_confidence_edge_cases() - 边界情况（全0、全1等）
```

#### 3.2 Critic 决策逻辑 (`critic.py`)
**为什么重要**：决策逻辑是工作流的核心，错误会导致无限重试或错误接受

```python
# tests/test_critic_decision.py (新增)
- test_critic_decision_accept_threshold() - ACCEPT 决策
- test_critic_decision_retry_threshold() - RETRY 决策
- test_critic_decision_escalate_threshold() - ESCALATE 决策
- test_critic_decision_with_retry_count() - 重试次数影响
- test_critic_feedback_format() - 反馈格式验证
- test_critic_evaluation_empty_output() - 空输出处理
```

#### 3.3 字段置信度计算 (`json_generator.py`, `document_parser.py`)
**为什么重要**：字段置信度影响最终质量评估

```python
# tests/test_confidence_calculation.py (新增)
- test_calculate_field_confidence() - 字段置信度计算
- test_calculate_llm_confidence() - LLM 提取置信度
- test_confidence_with_evidence() - 有证据的置信度
- test_confidence_without_evidence() - 无证据的置信度
```

### 4. 工具函数层 ✅ 中优先级

#### 4.1 本地知识库 (`local_knowledge.py`)
**为什么重要**：本地知识库是 FAIR-DS API 的备用，需要确保正确加载和查询

```python
# tests/test_local_knowledge.py (新增)
- test_load_local_terms() - 加载本地术语
- test_load_local_packages() - 加载本地包
- test_search_local_terms() - 搜索本地术语
- test_fallback_to_local() - API 失败时的回退
```

#### 4.2 配置保存器 (`config_saver.py`)
**为什么重要**：运行时配置保存用于调试和复现

```python
# tests/test_config_saver.py ✅ 已完成
- test_collect_runtime_config_basic() - 基本配置收集
- test_collect_runtime_config_runtime_info() - 运行时信息收集
- test_collect_runtime_config_includes_config() - 配置对象包含
- test_collect_runtime_config_masks_sensitive_data() - 敏感数据掩码
- test_save_runtime_config_creates_file() - 创建配置文件
- test_save_runtime_config_valid_json() - JSON 格式验证
- test_save_runtime_config_complete_structure() - 完整结构验证
- test_save_runtime_config_handles_missing_output_dir() - 目录创建
- test_save_runtime_config_preserves_all_data() - 数据完整性
```

### 5. 服务集成层 ⚠️ 中优先级（使用 Mock）

#### 5.1 FAIR-DS 客户端 (`fair_data_station.py`)
**为什么重要**：API 客户端错误会导致知识检索失败。使用真实 API 测试确保能连接到数据库。

```python
# tests/test_fair_data_station.py ✅ 已完成（真实 API 集成测试）
- test_api_is_available() - API 可用性检查
- test_get_all_terms() - 获取所有术语（真实数据库）
- test_search_terms_by_label() - 按标签搜索（真实数据库）
- test_search_terms_by_definition() - 按定义搜索（真实数据库）
- test_get_available_packages() - 获取可用包列表（真实数据库）
- test_get_package_by_name() - 获取特定包（真实数据库）
- test_package_contains_valid_fields() - 验证包数据结构
- test_terms_have_required_fields() - 验证术语数据结构
- test_invalid_url_handling() - 错误 URL 处理
- test_timeout_handling() - 超时处理
```

#### 5.2 MinerU 客户端 (`mineru_client.py`)
**为什么重要**：文档转换失败会导致整个工作流失败

```python
# tests/test_mineru_client.py ✅ 已有
- 已有完整的测试覆盖
```

### 6. Agent 核心逻辑 ⚠️ 低优先级（部分测试）

**注意**：Agent 的 `execute()` 方法主要调用 LLM，应该：
- **不测试**：LLM 调用本身（这是外部依赖）
- **测试**：Agent 的状态转换逻辑、错误处理、边界情况

```python
# tests/test_agent_state_transitions.py (新增，使用 mock LLM)
- test_document_parser_state_update() - 状态更新逻辑（mock LLM）
- test_knowledge_retriever_state_update() - 状态更新逻辑（mock LLM）
- test_json_generator_state_update() - 状态更新逻辑（mock LLM）
- test_agent_error_handling() - 错误处理
- test_agent_empty_input_handling() - 空输入处理
```

## 不需要测试的内容

1. **LangGraph 工作流编排**：这是框架功能，不需要测试
2. **LLM API 调用**：使用 mock，不测试真实 API
3. **CLI 界面**：端到端测试，不属于单元测试
4. **UI 组件**：Streamlit/Gradio 界面，属于集成测试
5. **日志记录**：工具功能，不需要测试

## 测试组织结构

```
tests/
├── README.md
├── TESTING_STRATEGY.md            # 测试策略文档
├── conftest.py                    # 共享 fixtures
├── test_confidence_aggregator.py ✅ (3 tests)
├── test_critic_utils.py          ✅ (7 tests)
├── test_critic_decision.py       ✅ (9 tests)
├── test_fairds_api_parser.py     ✅ (9 tests)
├── test_fair_data_station.py     ✅ (13 tests, 真实 API 集成)
├── test_config_saver.py           ✅ (13 tests)
├── test_mineru_client.py         ✅ (13 tests)
├── test_llm_helper_utils.py      ⚠️ 新增
├── test_models.py                 ⚠️ 新增
├── test_config.py                 ⚠️ 新增
├── test_confidence_calculation.py ⚠️ 新增
├── test_local_knowledge.py       ⚠️ 新增
└── test_agent_state_transitions.py ⚠️ 新增（mock）
```

## 测试优先级

### P0 - 必须立即实现
1. ✅ `test_confidence_aggregator.py` - 已完成
2. ✅ `test_critic_utils.py` - 已完成
3. ✅ `test_mineru_client.py` - 已完成
4. ✅ `test_fairds_api_parser.py` - 已完成
5. ✅ `test_critic_decision.py` - 已完成
6. ✅ `test_fair_data_station.py` - 已完成（真实 API 集成测试）
7. ✅ `test_config_saver.py` - 已完成
8. ⚠️ `test_llm_helper_utils.py` - **高优先级**

### P1 - 近期实现
9. ⚠️ `test_models.py`
10. ⚠️ `test_config.py`
11. ⚠️ `test_confidence_calculation.py`

### P2 - 有时间再实现
12. ⚠️ `test_local_knowledge.py`
13. ⚠️ `test_agent_state_transitions.py` (mock)

## Mock 策略

### LLM Helper Mock
```python
# conftest.py
@pytest.fixture
def mock_llm_helper():
    """Mock LLM helper that returns predictable responses."""
    # 返回预定义的 JSON 响应，不调用真实 LLM
```

### FAIR-DS API Mock
```python
# conftest.py
@pytest.fixture
def mock_fair_ds_client():
    """Mock FAIR-DS API client."""
    # 使用 responses 库或 unittest.mock
```

## 测试覆盖率目标

- **核心业务逻辑**：> 80%
- **工具函数**：> 90%
- **数据解析**：> 85%
- **整体项目**：> 70%

## 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行快速测试（排除集成测试）
pytest tests/ -v -m "not integration and not slow"

# 运行特定优先级
pytest tests/test_fairds_api_parser.py tests/test_llm_helper_utils.py tests/test_critic_decision.py -v

# 生成覆盖率报告
pytest tests/ --cov=fairifier --cov-report=html
```

## 持续集成建议

1. **快速测试套件**：每次提交运行 P0 测试（< 30 秒）
2. **完整测试套件**：PR 时运行所有测试（< 5 分钟）
3. **覆盖率检查**：PR 时检查覆盖率不低于目标

## 总结

重点测试：
- ✅ 数据解析和转换（已有部分）
- ⚠️ 核心业务逻辑（Critic 决策、置信度计算）
- ⚠️ 数据模型验证
- ⚠️ 错误处理和边界情况

避免过度测试：
- ❌ 框架代码
- ❌ 外部 API（使用 mock）
- ❌ UI 组件
- ❌ 日志功能

保持测试简洁、快速、可维护，确保核心功能可靠性。
