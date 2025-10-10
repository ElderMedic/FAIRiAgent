# FAIRifier - 极简科研PoC版本

🧬 **一个专为科研概念验证设计的FAIR元数据自动生成工具**

## 🎯 核心理念

这是FAIRifier的极简版本，专注于核心概念验证：
- **单文件设计** - 所有逻辑在一个Python文件中
- **最小依赖** - 核心功能无需外部库
- **易于理解** - 代码清晰，适合学习和修改
- **快速上手** - 10分钟内掌握全部代码

## 🚀 三种使用方式

### 1. 演示版 (50行代码，0依赖)
```bash
python demo.py
```
- 纯Python标准库
- 展示核心概念
- 适合教学演示

### 2. 简化版 (300行代码，3个可选依赖)
```bash
# 可选：安装依赖以支持PDF和RDF
pip install PyYAML PyMuPDF rdflib

# 使用
python fairifier_simple.py document.pdf
python fairifier_simple.py paper.txt -o results/
```

### 3. 无依赖版本
即使不安装任何依赖，简化版也能处理文本文件并生成JSON和YAML输出。

## 📊 功能对比

| 功能 | 演示版 | 简化版 | 原复杂版 |
|------|-------|--------|----------|
| 代码行数 | 50行 | 300行 | 22万行 |
| 文件数量 | 1个 | 1个 | 7510个 |
| 依赖数量 | 0个 | 3个可选 | 50+ |
| 文档解析 | ✅ 文本 | ✅ 文本+PDF | ✅ 多格式 |
| 元数据生成 | ✅ 基础 | ✅ 完整 | ✅ 高级 |
| JSON Schema | ✅ | ✅ | ✅ |
| YAML模板 | ✅ | ✅ | ✅ |
| RDF输出 | ❌ | ✅ | ✅ |
| Web界面 | ❌ | ❌ | ✅ |
| API服务 | ❌ | ❌ | ✅ |

## 🧠 工作原理

### 核心流程
```
文档输入 → 信息提取 → 字段生成 → 格式输出
```

### 关键组件
1. **文档解析器** - 正则表达式提取标题、作者、关键词
2. **领域识别器** - 基于关键词匹配研究领域  
3. **字段生成器** - 根据MIxS标准生成元数据字段
4. **格式转换器** - 输出JSON Schema、YAML、RDF

## 📁 输出示例

### JSON Schema
```json
{
  "title": "Marine Microbiome Analysis",
  "type": "object", 
  "properties": {
    "project_name": {"type": "string", "description": "project_name"},
    "investigation_type": {"type": "string", "description": "investigation_type"}
  },
  "required": ["project_name", "investigation_type"]
}
```

### YAML 模板
```yaml
# Metadata Template: Generated for Marine Microbiome Analysis
project_name (REQUIRED): Marine Microbiome Analysis
investigation_type (REQUIRED): metagenome
collection_date (REQUIRED): # Date of sample collection
geo_loc_name: Germany:North Sea
env_biome: # Environmental biome
```

## 🔧 自定义指南

### 添加新的元数据字段
```python
MIXS_FIELDS = {
    "your_field": {
        "desc": "Your field description", 
        "required": True,
        "type": "string",
        "example": "example value"
    }
}
```

### 修改提取规则
```python
def extract_from_text(text):
    # 添加你的正则表达式
    your_pattern = re.search(r'Your Pattern: (.+)', text)
    if your_pattern:
        # 处理提取的信息
```

### 扩展研究领域
```python
RESEARCH_DOMAINS = {
    "your_domain": ["keyword1", "keyword2", "keyword3"]
}
```

## 🎓 教学价值

### 适合学习的概念
- 文本处理和正则表达式
- 元数据标准化 (MIxS, FAIR)
- JSON Schema设计
- RDF和语义网基础
- 科研数据管理

### 扩展练习
1. 添加新的研究领域识别
2. 实现更复杂的信息提取
3. 集成外部API获取本体术语
4. 添加验证和质量评估
5. 实现批量处理功能

## 📈 测试结果

使用测试文档 `test_document.txt`:
- ✅ 成功提取标题、作者、关键词
- ✅ 正确识别研究领域 (marine)
- ✅ 生成12个相关元数据字段
- ✅ 输出符合标准的JSON Schema和YAML
- ✅ 置信度评分: 1.0/1.0

## 🚀 快速开始

```bash
# 1. 下载代码
git clone <repository>

# 2. 直接运行演示
python demo.py

# 3. 或运行完整版
python fairifier_simple.py test_document.txt

# 4. 查看结果
ls output/
```

## 🤝 贡献指南

这是一个科研PoC项目，欢迎：
- 🐛 报告bug和问题
- 💡 提出改进建议  
- 📝 完善文档
- 🔧 提交简单的功能增强

请保持代码的简洁性和可读性！

## 📄 许可证

MIT License - 适合学术研究和教学使用

---

**🎯 记住：简单就是美！这个工具专注于展示FAIR元数据自动生成的核心概念，而不是成为一个复杂的生产系统。**
