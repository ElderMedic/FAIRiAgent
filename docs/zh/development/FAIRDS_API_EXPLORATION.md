# 🔍 FAIR-DS API 探索结果

> **最后更新**: 2026年1月 (FAIR-DS JAR 最新版本)

## 📊 当前 API 结构

### 可用端点

| 端点 | 状态 | 返回 |
|------|------|------|
| `GET /api/packages` | ✅ 可用 | JSON |
| `GET /api/terms` | ❌ 已移除 | HTML (Vaadin app) |
| `POST /api/upload` | ✅ 可用 | 验证结果 |

### GET `/api/packages` - 所有元数据 (主要端点)

```bash
curl http://localhost:8083/api/packages
```

**返回结构 (已更新):**
```json
{
  "total": 5,
  "totalMetadataItems": 2689,
  "metadata": {
    "investigation": {
      "name": "investigation",
      "displayName": "Investigation",
      "description": "A research investigation representing an overarching research question or hypothesis",
      "hierarchyOrder": 1,
      "metadata": [...]
    },
    "study": {
      "name": "study",
      "displayName": "Study",
      "description": "A specific study within an investigation...",
      "hierarchyOrder": 2,
      "metadata": [...]
    },
    "observationunit": {
      "name": "observationunit",
      "displayName": "Observation Unit",
      "description": "The fundamental unit of observation in the study...",
      "hierarchyOrder": 3,
      "metadata": [...]
    },
    "sample": {
      "name": "sample",
      "displayName": "Sample",
      "description": "A physical specimen or material derived from an observation unit...",
      "hierarchyOrder": 4,
      "metadata": [...]
    },
    "assay": {
      "name": "assay",
      "displayName": "Assay",
      "description": "An analytical measurement or experimental procedure...",
      "hierarchyOrder": 5,
      "metadata": [...]
    }
  }
}
```

**与旧版本的主要变化:**
- `packages` 键更名为 `metadata`
- 每个 ISA sheet 现在包含: `name`, `displayName`, `description`, `hierarchyOrder`
- 字段数组从 `metadata[sheet]` 移动到 `metadata[sheet]["metadata"]`
- 顶层新增 `totalMetadataItems`

**每个 ISA Sheet 中的字段结构:**
```json
{
  "definition": "Identifier corresponding to the investigation",
  "sheetName": "Investigation",
  "packageName": "default",
  "requirement": "MANDATORY",
  "label": "investigation identifier",
  "term": {
    "label": "investigation identifier",
    "syntax": "{id}{5,25}$",
    "example": "BO3B",
    "preferredUnit": "",
    "definition": "Identifier corresponding to the investigation",
    "ontology": null,
    "regex": "^[a-zA-Z0-9-_.]*{5,25}$",
    "file": false,
    "date": false,
    "dateTime": false,
    "url": "http://schema.org/identifier"
  }
}
```

### GET `/api/terms` - ⚠️ 不再可用

`/api/terms` 端点现在返回 HTML (Vaadin 网页应用) 而不是 JSON。所有术语信息必须通过 `/api/packages` 获取。

---

## 📋 数据统计

| ISA Sheet | 显示名称 | 层级顺序 | 字段数量 |
|-----------|----------|----------|----------|
| **investigation** | Investigation | 1 | 17 |
| **study** | Study | 2 | 25 |
| **observationunit** | Observation Unit | 3 | 137 |
| **sample** | Sample | 4 | 2411 |
| **assay** | Assay | 5 | 99 |

**总计:** 2689 个字段，5 个 ISA sheets

---

## 📦 可用的 Packages (共 59 个)

API 现在包含 59 个唯一的 package 名称:

### 核心 Packages
- `default` - 包含核心字段的基础包
- `miappe` - Minimum Information About Plant Phenotyping Experiments
- `unlock` - UNLOCK 项目特定字段

### 环境 Packages
- `air`, `water`, `soil`, `sediment`
- `built environment`
- `wastewater sludge`
- `microbial mat biolfilm`
- `miscellaneous natural or artificial environment`
- `plant associated`

### 宿主相关 Packages
- `host associated`
- `human associated`, `human gut`, `human oral`, `human skin`, `human vaginal`
- `pig`, `pig_blood`, `pig_faeces`, `pig_health`, `pig_histology`
- `person`

### 测序技术 Packages
- `Illumina`, `Nanopore`, `PacBio`, `LS454`
- `Amplicon demultiplexed`, `Amplicon library`
- `Genome`

### ENA 检查表
- `ENA default sample checklist`
- `ENA prokaryotic pathogen minimal sample checklist`
- `ENA virus pathogen reporting standard checklist`
- `ENA binned metagenome`
- `ENA Marine Microalgae Checklist`
- `ENA Shellfish Checklist`
- `ENA Tara Oceans`
- `ENA Micro B3`
- 等等...

### GSC (基因组标准联盟) Packages
- `GSC MIMAGS` - 宏基因组组装基因组
- `GSC MISAGS` - 单细胞扩增基因组
- `GSC MIUVIGS` - 未培养病毒基因组

### 专业检查表
- `COMPARE-ECDC-EFSA pilot food-associated reporting standard`
- `Crop Plant sample enhanced annotation checklist`
- `Plant Sample Checklist`
- `Tree of Life Checklist`
- `HoloFood Checklist`
- `Metabolomics`, `Proteomics`
- 等等...

---

## 🎯 关键发现

### 1. 带层级的 ISA 模型
API 使用 ISA (Investigation-Study-Assay) 模型，具有清晰的层级结构:
1. **Investigation** (hierarchyOrder: 1) - 项目级别元数据
2. **Study** (hierarchyOrder: 2) - 研究级别元数据
3. **ObservationUnit** (hierarchyOrder: 3) - 被观察的实体
4. **Sample** (hierarchyOrder: 4) - 物理样本元数据
5. **Assay** (hierarchyOrder: 5) - 实验/测量元数据

### 2. 要求级别
字段有三种要求级别:
- **MANDATORY**: 必需字段
- **OPTIONAL**: 可选字段
- **RECOMMENDED**: 推荐字段

### 3. 验证规则
每个字段在 `term` 对象中包含验证规则:
- `regex`: 正则表达式验证
- `syntax`: 语法模式
- `example`: 示例值
- `file/date/dateTime`: 数据类型标记

---

## 🔧 代码集成

### 解析新 API 结构

```python
import requests

response = requests.get("http://localhost:8083/api/packages")
data = response.json()

# 访问顶层信息
total_sheets = data["total"]  # 5
total_fields = data["totalMetadataItems"]  # 2689

# 访问 ISA sheet 信息
for sheet_name, sheet_info in data["metadata"].items():
    print(f"Sheet: {sheet_info['displayName']}")
    print(f"  描述: {sheet_info['description']}")
    print(f"  层级顺序: {sheet_info['hierarchyOrder']}")
    print(f"  字段数量: {len(sheet_info['metadata'])}")
    
    # 访问字段
    for field in sheet_info["metadata"]:
        print(f"    - {field['label']} ({field['requirement']})")
        print(f"      Package: {field['packageName']}")
        print(f"      Regex: {field['term']['regex']}")
```

### 按 Package 名称提取字段

```python
def get_fields_by_package(data, package_name):
    """提取属于特定 package 的所有字段"""
    fields = []
    for sheet_name, sheet_info in data["metadata"].items():
        for field in sheet_info["metadata"]:
            if field["packageName"] == package_name:
                field["isaSheet"] = sheet_name  # 添加 ISA sheet 信息
                fields.append(field)
    return fields

# 示例: 获取所有 'miappe' 字段
miappe_fields = get_fields_by_package(data, "miappe")
```

---

## 📝 迁移说明

### 从旧 API 到新 API

**旧结构:**
```python
# 旧: packages[sheet] 是字段列表
fields = data["packages"]["investigation"]
```

**新结构:**
```python
# 新: metadata[sheet]["metadata"] 是字段列表
fields = data["metadata"]["investigation"]["metadata"]
```

### 主要区别

| 方面 | 旧 API | 新 API |
|------|--------|--------|
| 顶层键 | `packages` | `metadata` |
| Sheet 结构 | 字段列表 | 包含 `name`, `displayName`, `description`, `hierarchyOrder`, `metadata` 的对象 |
| 字段位置 | `packages[sheet]` | `metadata[sheet]["metadata"]` |
| `/api/terms` | 返回 JSON | 返回 HTML (已移除) |
| 总数键 | 无 | `totalMetadataItems` |
