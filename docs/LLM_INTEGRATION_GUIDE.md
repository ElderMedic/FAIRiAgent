# LLM集成使用指南

## 概述

FAIRifier项目现已集成大语言模型(LLM)支持，可以使用OpenAI GPT模型或Claude模型来增强各个agent的智能处理能力。

## 配置设置

### 1. 环境变量配置

在使用前，需要设置相应的API密钥：

```bash
# 使用OpenAI (推荐)
export OPENAI_API_KEY="your-openai-api-key"
export FAIRIFIER_LLM_PROVIDER="openai"
export FAIRIFIER_LLM_MODEL="gpt-4o-mini"  # 或 "gpt-4", "gpt-3.5-turbo"

# 或使用Claude
export CLAUDE_API_KEY="your-claude-api-key"
export FAIRIFIER_LLM_PROVIDER="claude"
export FAIRIFIER_LLM_MODEL="claude-3-haiku-20240307"  # 或其他Claude模型
```

### 2. 配置文件设置

也可以直接修改 `fairifier/config.py` 文件：

```python
# LLM Configuration
llm_provider: str = "openai"  # "openai", "claude", or "ollama"
llm_model: str = "gpt-4o-mini"  # 模型名称
openai_api_key: Optional[str] = "your-api-key"
claude_api_key: Optional[str] = "your-api-key"
```

## LLM增强功能

### 1. DocumentParserAgent
- **功能增强**: 使用LLM智能解析科学文档，提取结构化信息
- **改进点**: 
  - 更准确的标题、摘要、作者提取
  - 智能识别研究领域和方法论
  - 自动识别数据集、仪器和变量

### 2. KnowledgeRetrieverAgent
- **功能增强**: 使用LLM进行智能知识检索和匹配
- **改进点**:
  - 智能选择合适的MIxS包
  - 基于文档内容选择相关的可选字段
  - 识别相关的本体术语

### 3. TemplateGeneratorAgent
- **功能增强**: 使用LLM生成更智能、更准确的元数据模板
- **改进点**:
  - 生成基于研究内容的真实示例值
  - 智能推断字段的数据类型和必要性
  - 建议额外的FAIR数据相关字段

## 使用方法

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 设置API密钥

```bash
export OPENAI_API_KEY="your-openai-api-key"
```

### 3. 运行系统

```bash
python run_fairifier.py examples/inputs/test_document.txt
```

## 模型选择建议

### OpenAI模型
- **gpt-4o-mini**: 推荐，性价比高，处理速度快
- **gpt-4**: 最高质量，但成本较高
- **gpt-3.5-turbo**: 成本最低，但质量稍逊

### Claude模型
- **claude-3-haiku-20240307**: 快速且经济
- **claude-3-sonnet-20240229**: 平衡性能和成本
- **claude-3-opus-20240229**: 最高质量

## 错误处理

系统具有完善的错误处理机制：

1. **LLM调用失败**: 自动回退到基于规则的处理方法
2. **JSON解析失败**: 使用正则表达式作为备选方案
3. **API限制**: 自动重试和速率限制处理

## 性能优化

1. **批处理**: 将多个字段批量发送给LLM处理
2. **文本截断**: 长文档自动截断以避免token限制
3. **缓存**: 相同输入的结果会被缓存

## 成本控制

1. **使用gpt-4o-mini**: 推荐用于生产环境
2. **设置max_tokens限制**: 控制响应长度
3. **文本预处理**: 去除无关内容减少token使用

## 示例输出

使用LLM后，系统能够生成更准确的元数据：

```json
{
  "project_name": "Marine Microbiome Diversity Study",
  "investigation_type": "metagenome",
  "env_biome": "marine biome [ENVO:00000447]",
  "sample_collect_device": "CTD rosette",
  "depth": "150",
  "temp": "4.2",
  "collection_date": "2023-08-15"
}
```

## 故障排除

### 常见问题

1. **API密钥错误**: 检查环境变量设置
2. **模型不存在**: 确认模型名称正确
3. **网络连接问题**: 检查网络连接和防火墙设置
4. **Token限制**: 减少输入文本长度或增加max_tokens

### 日志查看

系统会记录详细的日志信息：

```bash
# 查看agent执行日志
tail -f fairifier.log
```

## 下一步

1. 考虑集成更多模型提供商（如Azure OpenAI）
2. 添加模型性能监控和评估
3. 实现更细粒度的提示工程优化
