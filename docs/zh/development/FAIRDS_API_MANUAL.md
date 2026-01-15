# FAIR Data Station API 参考文档

本文档描述 FAIR Data Station (FAIR-DS) API 结构和用法，用于 FAIRiAgent 集成。

> **API 版本:** FAIR-DS JAR (最新版本 - 2026年1月)  
> **基础 URL:** `http://localhost:8083`  
> **Swagger UI:** http://localhost:8083/swagger-ui/index.html

---

## 端点概览

| 端点 | 方法 | 状态 | 描述 |
|------|------|------|------|
| `GET /api` | GET | 可用 | 获取 API 概览和可用端点列表 |
| `GET /api/terms` | GET | 可用 | 获取所有元数据术语或按标签/定义过滤 |
| `GET /api/package` | GET | 可用 | 获取所有包或按名称获取特定包 |
| `POST /api/upload` | POST | 可用 | 验证元数据 Excel 文件 |

---

## GET `/api`

返回可用 API 端点的概览。

### 请求

```bash
curl http://localhost:8083/api
```

### 响应

```json
{
  "availableEndpoints": [
    "/api/upload",
    "/api/terms",
    "/api/package"
  ]
}
```

---

## GET `/api/terms`

检索所有元数据术语，或使用不区分大小写的模式匹配按标签和/或定义过滤。

### 请求

```bash
# 获取所有术语
curl http://localhost:8083/api/terms

# 按标签过滤
curl "http://localhost:8083/api/terms?label=temperature"

# 按定义过滤
curl "http://localhost:8083/api/terms?definition=sampling"

# 组合过滤
curl "http://localhost:8083/api/terms?label=temp&definition=temperature"
```

### 查询参数

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `label` | string | 否 | 按标签过滤术语（支持模式匹配，不区分大小写） |
| `definition` | string | 否 | 按定义过滤术语（支持模式匹配，不区分大小写） |

### 响应结构

```json
{
  "total": 892,
  "terms": {
    "term_name": {
      "label": "string",
      "syntax": "string",
      "example": "string",
      "preferredUnit": "string",
      "definition": "string",
      "ontology": null,
      "regex": "string",
      "file": false,
      "date": false,
      "dateTime": false,
      "url": "string"
    }
  }
}
```

### 过滤响应示例

```json
{
  "total": 12,
  "terms": {
    "temperature": {
      "label": "temperature",
      "syntax": "{number}",
      "example": "25 °C",
      "preferredUnit": "°C",
      "definition": "temperature of the sample at time of sampling",
      "regex": "(\\-|\\+)?(\\d+)(\\.\\d+)? ?(°C)",
      "url": "https://w3id.org/mixs/0000113"
    },
    "air temperature": { ... },
    "water temperature": { ... }
  }
}
```

**要点:**
- 无过滤器时返回 892 个术语
- 支持部分匹配（例如，`label=temp` 匹配 "temperature"）
- 不区分大小写的模式匹配
- 可组合 `label` 和 `definition` 过滤器（AND 逻辑）
- 过滤结果显著减少响应大小

---

## GET `/api/package`

检索所有可用的元数据包或按名称获取特定包。

### 请求

```bash
# 获取所有包的列表
curl http://localhost:8083/api/package

# 获取特定包
curl "http://localhost:8083/api/package?name=miappe"
```

### 查询参数

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `name` | string | 否 | 要检索的元数据包名称。如果未提供，返回所有可用包的列表 |

### 响应（无 name 参数）

```json
{
  "message": "No package name specified. Available packages listed below.",
  "packages": [
    "default",
    "miappe",
    "soil",
    "water",
    // ... 共 59 个包
  ],
  "example": "/api/package?name=soil"
}
```

### 响应（带 name 参数）

```json
{
  "packageName": "miappe",
  "itemCount": 63,
  "metadata": [
    {
      "definition": null,
      "sheetName": "Study",
      "packageName": "miappe",
      "requirement": "MANDATORY",
      "label": "start date of study",
      "term": {
        "label": "start date of study",
        "syntax": "{date}",
        "example": "2002-04-04 00:00:00",
        "preferredUnit": "",
        "definition": "Date and, if relevant, time when the experiment started",
        "ontology": null,
        "regex": "\\d{4}-\\d{2}-\\d{2}(?:[ T]00:00:00)?",
        "file": false,
        "date": true,
        "dateTime": false,
        "url": "http://fairbydesign.nl/ontology/start_date_of_study"
      }
    }
    // ... 其余字段
  ]
}
```

**要点:**
- 仅返回指定包的字段（例如，miappe 为 63 个字段，而非全部 2689 个）
- 单包查询可减少约 98% 的数据传输
- 包含 `itemCount` 用于快速参考
- `metadata` 是字段数组（未按 ISA sheet 分组）

---

## 可用包

API 包含 59 个包。字段通过 `packageName` 属性与包关联。

### 核心包

| 包 | 描述 |
|----|------|
| `default` | 包含核心 ISA 字段的基础包 |
| `miappe` | Minimum Information About Plant Phenotyping Experiments |
| `unlock` | UNLOCK 项目特定字段 |

### 环境包

`air`, `water`, `soil`, `sediment`, `built environment`, `wastewater sludge`, `microbial mat biolfilm`, `miscellaneous natural or artificial environment`, `plant associated`

### 宿主相关包

`host associated`, `human associated`, `human gut`, `human oral`, `human skin`, `human vaginal`, `pig`, `pig_blood`, `pig_faeces`, `pig_health`, `pig_histology`, `person`

### 测序技术包

`Illumina`, `Nanopore`, `PacBio`, `LS454`, `Amplicon demultiplexed`, `Amplicon library`, `Genome`

### ENA 检查表

`ENA default sample checklist`, `ENA prokaryotic pathogen minimal sample checklist`, `ENA virus pathogen reporting standard checklist`, `ENA binned metagenome`, `ENA Marine Microalgae Checklist`, `ENA Shellfish Checklist`, `ENA Tara Oceans`, `ENA Micro B3`, `ENA sewage checklist`, `ENA parasite sample checklist`, `ENA mutagenesis by carcinogen treatment checklist`, `ENA Influenza virus reporting standard checklist`, `ENA Global Microbial Identifier reporting standard checklist GMI_MDM:1.1`

### GSC 标准

| 包 | 描述 |
|----|------|
| `GSC MIMAGS` | 宏基因组组装基因组 |
| `GSC MISAGS` | 单细胞扩增基因组 |
| `GSC MIUVIGS` | 未培养病毒基因组 |

### 其他包

`COMPARE-ECDC-EFSA pilot food-associated reporting standard`, `COMPARE-ECDC-EFSA pilot human-associated reporting standard`, `Crop Plant sample enhanced annotation checklist`, `Plant Sample Checklist`, `Tree of Life Checklist`, `HoloFood Checklist`, `PDX Checklist`, `UniEuk_EukBank`, `MIFE`, `Metabolomics`, `Proteomics`

---

## 代码示例

### 获取所有术语

```python
import requests

response = requests.get("http://localhost:8083/api/terms")
data = response.json()

total_terms = data["total"]  # 892
```

### 按标签搜索术语

```python
# 搜索温度相关术语
response = requests.get("http://localhost:8083/api/terms", params={"label": "temperature"})
data = response.json()

print(f"找到 {data['total']} 个匹配 'temperature' 的术语")
for term_name, term_info in data["terms"].items():
    print(f"  - {term_name}: {term_info['definition']}")
```

### 按定义搜索术语

```python
# 搜索与采样相关的术语
response = requests.get("http://localhost:8083/api/terms", params={"definition": "sampling"})
data = response.json()

print(f"找到 {data['total']} 个与采样相关的术语")
```

### 获取所有包的列表

```python
response = requests.get("http://localhost:8083/api/package")
data = response.json()

packages = data["packages"]  # 59 个包名称的列表
print(f"可用包: {len(packages)}")
```

### 获取特定包

```python
# 获取 miappe 包字段
response = requests.get("http://localhost:8083/api/package", params={"name": "miappe"})
package_data = response.json()

print(f"包: {package_data['packageName']}")
print(f"字段: {package_data['itemCount']}")

for field in package_data["metadata"]:
    print(f"  - {field['label']} ({field['requirement']})")
    print(f"    Sheet: {field['sheetName']}")
```

### 按要求级别过滤字段

```python
def get_mandatory_fields(package_data):
    """从包响应中提取必需字段"""
    return [
        field for field in package_data["metadata"]
        if field["requirement"] == "MANDATORY"
    ]

# 获取 miappe 包
response = requests.get("http://localhost:8083/api/package", params={"name": "miappe"})
package_data = response.json()

mandatory_fields = get_mandatory_fields(package_data)
print(f"必需字段: {len(mandatory_fields)}")
```

### 按 ISA Sheet 分组字段

```python
def group_fields_by_sheet(package_data):
    """按 ISA sheet 分组包字段"""
    grouped = {}
    for field in package_data["metadata"]:
        sheet = field["sheetName"]
        if sheet not in grouped:
            grouped[sheet] = []
        grouped[sheet].append(field)
    return grouped

response = requests.get("http://localhost:8083/api/package", params={"name": "miappe"})
package_data = response.json()

fields_by_sheet = group_fields_by_sheet(package_data)
for sheet, fields in fields_by_sheet.items():
    print(f"{sheet}: {len(fields)} 个字段")
```

---

## 迁移说明

### API 变更

| 方面 | 之前 | 当前 |
|------|------|------|
| `/api/terms` | 返回 HTML | ✅ 返回 JSON 并支持过滤 |
| `/api/packages` | 返回所有字段 (2689) | ❌ 不可用 |
| `/api/package` | 不可用 | ✅ 新增 - 查询特定包 |
| 包端点 | N/A | 使用查询参数 `?name={package}` |

### 最佳实践

1. **使用 `/api/package?name={name}`** 而不是获取所有字段并在客户端过滤
   - 减少约 98% 的数据传输
   - 更快的响应时间

2. **使用 `/api/terms?label={pattern}`** 进行术语发现
   - 比获取所有 892 个术语更高效
   - 支持部分匹配

3. **尽可能组合过滤器**
   - `/api/terms?label=temp&definition=temperature` 用于精确搜索

---

## 相关资源

- [FAIR-DS 官方文档](https://docs.fairbydesign.nl/docs/fairdatastation/tutorials/api.html)
- [Swagger UI](http://localhost:8083/swagger-ui/index.html) - 交互式 API 文档
