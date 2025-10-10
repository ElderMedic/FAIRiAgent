# FAIRifier Simple - PoC Version

一个极简的FAIR元数据生成工具，专为科研概念验证设计。

## 🚀 快速开始

### 1. 安装依赖（可选）
```bash
pip install PyYAML PyMuPDF rdflib
```

### 2. 运行
```bash
# 处理文本文档
python fairifier_simple.py test_document.txt

# 处理PDF文档（需要PyMuPDF）
python fairifier_simple.py paper.pdf

# 指定输出目录
python fairifier_simple.py document.pdf -o results/

# 只显示结果，不保存文件
python fairifier_simple.py document.txt --no-save
```

## 📁 输出文件

- `schema.json` - JSON Schema元数据模板
- `template.yaml` - YAML填写模板  
- `metadata.ttl` - RDF Turtle格式
- `summary.json` - 处理摘要

## 🧠 工作原理

1. **文档解析**: 使用正则表达式提取标题、摘要、作者、关键词
2. **领域识别**: 基于关键词匹配识别研究领域
3. **字段生成**: 根据MIxS标准生成相关元数据字段
4. **格式输出**: 生成JSON Schema、YAML模板和RDF图谱

## 🔧 自定义

所有配置都在代码中，可以直接修改：

- `MIXS_FIELDS`: 元数据字段定义
- `RESEARCH_DOMAINS`: 研究领域关键词
- 提取规则在各个函数中

## 📊 特点

- **单文件**: 所有逻辑在一个文件中
- **最小依赖**: 核心功能无需外部库
- **易修改**: 清晰的函数结构，便于定制
- **快速**: 无复杂框架，直接处理

## 🎯 适用场景

- 科研概念验证
- 快速原型开发
- 教学演示
- 个人研究项目

总代码量: ~300行
核心依赖: 0个（可选依赖3个）
