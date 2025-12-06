# 🔍 FAIR-DS API 探索结果

## 📊 实际 API 结构（基于 [FAIR-DS API 文档](https://docs.fairbydesign.nl/docs/fairdatastation/tutorials/api.html)）

### API Endpoints

#### 1. GET `/api/terms` - 所有术语
```bash
curl http://localhost:8083/api/terms
```

**返回结构：**
```json
{
  "total": 892,
  "terms": {
    "study title": {
      "label": "study title",
      "syntax": "{text}{10,}",
      "example": "Cultivation and characterization...",
      "definition": "Title describing the study",
      "regex": ".*{10,}",
      "url": "http://schema.org/title",
      "file": false,
      "date": false,
      "dateTime": false
    },
    ...
  }
}
```

#### 2. GET `/api/packages` - 分组的术语
```bash
curl http://localhost:8083/api/packages
```

**返回结构：**
```json
{
  "total": 5,
  "packages": {
    "investigation": [...],  // 17 个字段
    "study": [...],          // 25 个字段
    "sample": [...],         // 2411 个字段（最多！）
    "assay": [...],          // 99 个字段
    "observationunit": [...]  // 137 个字段
  }
}
```

**每个 package 中的字段结构：**
```json
{
  "label": "investigation identifier",
  "definition": "Identifier corresponding to the investigation",
  "sheetName": "Investigation",
  "packageName": "default",
  "requirement": "MANDATORY",  // 或 OPTIONAL
  "sessionID": "no_session",
  "term": {
    "label": "investigation identifier",
    "syntax": "{id}{5,25}$",
    "example": "BO3B",
    "definition": "...",
    "regex": "^[a-zA-Z0-9-_.]*{5,25}$",
    "url": "http://schema.org/identifier"
  }
}
```

---

## 📋 实际数据统计

| Package | 字段数量 | 用途 |
|---------|---------|------|
| **investigation** | 17 | 研究项目级别元数据 |
| **study** | 25 | 研究级别元数据 |
| **sample** | 2411 | 样本级别元数据（最详细） |
| **assay** | 99 | 实验/分析级别元数据 |
| **observationunit** | 137 | 观察单元级别元数据 |

**总计：** 2689 个字段！

---

## 🎯 关键发现

### 1. 这不是 MIxS 标准
- ✅ 这是 FAIR Data Station 自己的元数据模式
- ✅ 基于 **ISA (Investigation-Study-Assay)** 模型
- ✅ 支持 **MIAPPE** (Minimum Information About Plant Phenotyping Experiments)
- ✅ 有层次结构：Investigation → Study → Sample/ObservationUnit → Assay

### 2. 字段有明确的要求级别
- **MANDATORY**: 必需字段
- **OPTIONAL**: 可选字段
- **RECOMMENDED**: 推荐字段（可能）

### 3. 每个字段都有验证规则
- `regex`: 正则表达式验证
- `syntax`: 语法模式
- `example`: 示例值
- `file/date/dateTime`: 数据类型标记

---

## 🔄 更新 KnowledgeRetriever 策略

根据实际 API，我们应该：

### 当前问题：
```python
# 代码假设了 MIxS packages（MIMS, MIMAG等）
# 但实际 API 返回的是 ISA 模型（investigation, study, sample, assay）
```

### 正确做法：
```python
# 1. 获取 packages
packages_data = fair_ds_client.get_packages()
# → {"total": 5, "packages": {investigation: [...], study: [...], ...}}

# 2. LLM 分析文档，决定需要哪些 packages
# "这是一个研究论文，需要 investigation 和 study 层级"
# "这是一个样本描述，需要 sample 和 observationunit 层级"

# 3. 对于每个相关 package，LLM 选择相关字段
# 从 investigation 的 17 个字段中选 5-8 个
# 从 study 的 25 个字段中选 8-12 个
# 从 sample 的 2411 个字段中选 5-10 个最相关的

# 4. 优先选择 MANDATORY 字段
```

---

## 💡 建议的新逻辑

### Phase 1: 确定相关的 Packages
```python
llm_prompt = f"""
Document type: {doc_type}
Research domain: {domain}

Available FAIR-DS packages:
- investigation (17 fields): Project-level metadata
- study (25 fields): Study-level metadata  
- sample (2411 fields): Sample-level metadata
- assay (99 fields): Assay/experiment-level metadata
- observationunit (137 fields): Observation unit metadata

Which packages are relevant for this document?
Return: ["investigation", "study", ...]
"""
```

### Phase 2: 对每个 Package 选择字段
```python
llm_prompt = f"""
Package: {package_name} ({field_count} fields available)

Mandatory fields: {mandatory_fields}
Optional fields (sample): {optional_fields[:20]}

Document context: {doc_info}

Select 5-15 most relevant fields for this document.
Prioritize MANDATORY fields.
"""
```

### Phase 3: 生成字段值
```python
# 为选定的字段生成值
for field in selected_fields:
    value = await llm.generate_value(
        field_name=field['label'],
        definition=field['definition'],
        example=field['term']['example'],
        regex=field['term']['regex'],
        document=doc_info
    )
```

---

## 🔧 需要修改的代码

### 1. `fairifier/services/fair_data_station.py`
当前代码可能需要调整以正确解析 API 返回的结构。

### 2. `fairifier/agents/knowledge_retriever.py`
- 移除 MIxS 假设
- 使用实际的 5 个 packages
- LLM 根据文档类型选择 packages
- LLM 从 2411 个 sample fields 中智能选择

### 3. Prompts 更新
- "MIxS packages" → "FAIR-DS packages"
- "MIMS, MIMAG" → "investigation, study, sample, assay, observationunit"
- 提到实际的字段数量

---

## 📝 示例 Mandatory 字段

### Investigation 层（必需）:
- investigation identifier
- investigation title
- investigation description
- firstname, lastname, email, organization

### Study 层（必需）:
- study identifier
- study title
- study description

---

## 🎯 下一步

我需要更新代码以：
1. ✅ 正确解析 FAIR-DS API 的实际返回格式
2. ✅ 使用真实的 package 名称（investigation, study, sample, assay, observationunit）
3. ✅ LLM 智能处理 2411 个 sample 字段
4. ✅ 优先选择 MANDATORY 字段
5. ✅ 使用字段的 regex 和 example 进行验证

准备好了让我更新代码吗？

