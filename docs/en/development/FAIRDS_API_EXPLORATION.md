# 🔍 FAIR-DS API Exploration Results

> **Last Updated**: January 2026 (FAIR-DS JAR latest version)

## 📊 Current API Structure

### Available Endpoints

| Endpoint | Status | Returns |
|----------|--------|---------|
| `GET /api/packages` | ✅ Working | JSON |
| `GET /api/terms` | ❌ Removed | HTML (Vaadin app) |
| `POST /api/upload` | ✅ Working | Validation result |

### GET `/api/packages` - All Metadata (Primary Endpoint)

```bash
curl http://localhost:8083/api/packages
```

**Return Structure (Updated):**
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

**Key Changes from Previous Version:**
- `packages` key renamed to `metadata`
- Each ISA sheet now includes: `name`, `displayName`, `description`, `hierarchyOrder`
- Fields array moved from `metadata[sheet]` to `metadata[sheet]["metadata"]`
- Added `totalMetadataItems` at top level

**Structure of Fields within Each ISA Sheet:**
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

### GET `/api/terms` - ⚠️ No Longer Available

The `/api/terms` endpoint now returns HTML (Vaadin web app) instead of JSON. All term information must be retrieved via `/api/packages`.

---

## 📋 Data Statistics

| ISA Sheet | Display Name | Hierarchy Order | Field Count |
|-----------|--------------|-----------------|-------------|
| **investigation** | Investigation | 1 | 17 |
| **study** | Study | 2 | 25 |
| **observationunit** | Observation Unit | 3 | 137 |
| **sample** | Sample | 4 | 2411 |
| **assay** | Assay | 5 | 99 |

**Total:** 2689 fields across 5 ISA sheets

---

## 📦 Available Packages (59 total)

The API now includes 59 unique package names:

### Core Packages
- `default` - Base package with core fields
- `miappe` - Minimum Information About Plant Phenotyping Experiments
- `unlock` - UNLOCK project specific

### Environmental Packages
- `air`, `water`, `soil`, `sediment`
- `built environment`
- `wastewater sludge`
- `microbial mat biolfilm`
- `miscellaneous natural or artificial environment`
- `plant associated`

### Host-Associated Packages
- `host associated`
- `human associated`, `human gut`, `human oral`, `human skin`, `human vaginal`
- `pig`, `pig_blood`, `pig_faeces`, `pig_health`, `pig_histology`
- `person`

### Sequencing Technology Packages
- `Illumina`, `Nanopore`, `PacBio`, `LS454`
- `Amplicon demultiplexed`, `Amplicon library`
- `Genome`

### ENA Checklists
- `ENA default sample checklist`
- `ENA prokaryotic pathogen minimal sample checklist`
- `ENA virus pathogen reporting standard checklist`
- `ENA binned metagenome`
- `ENA Marine Microalgae Checklist`
- `ENA Shellfish Checklist`
- `ENA Tara Oceans`
- `ENA Micro B3`
- `ENA sewage checklist`
- `ENA parasite sample checklist`
- `ENA mutagenesis by carcinogen treatment checklist`
- `ENA Influenza virus reporting standard checklist`
- `ENA Global Microbial Identifier reporting standard checklist GMI_MDM:1.1`
- `2 ENA Global Microbial Identifier Proficiency Test (GMI PT) checklist`

### GSC (Genomic Standards Consortium) Packages
- `GSC MIMAGS` - Metagenome-Assembled Genomes
- `GSC MISAGS` - Single Amplified Genomes
- `GSC MIUVIGS` - Uncultivated Virus Genomes

### Specialized Checklists
- `COMPARE-ECDC-EFSA pilot food-associated reporting standard`
- `COMPARE-ECDC-EFSA pilot human-associated reporting standard`
- `Crop Plant sample enhanced annotation checklist`
- `Plant Sample Checklist`
- `Tree of Life Checklist`
- `HoloFood Checklist`
- `PDX Checklist`
- `UniEuk_EukBank`
- `MIFE`

### Omics Packages
- `Metabolomics`
- `Proteomics`

---

## 🎯 Key Findings

### 1. ISA Model with Hierarchy
The API uses the ISA (Investigation-Study-Assay) model with clear hierarchy:
1. **Investigation** (hierarchyOrder: 1) - Project-level metadata
2. **Study** (hierarchyOrder: 2) - Study-level metadata
3. **ObservationUnit** (hierarchyOrder: 3) - Entity being observed
4. **Sample** (hierarchyOrder: 4) - Physical specimen metadata
5. **Assay** (hierarchyOrder: 5) - Experiment/measurement metadata

### 2. Requirement Levels
Fields have three requirement levels:
- **MANDATORY**: Required fields
- **OPTIONAL**: Optional fields
- **RECOMMENDED**: Recommended fields

### 3. Validation Rules
Each field includes validation rules in the `term` object:
- `regex`: Regular expression validation
- `syntax`: Syntax pattern
- `example`: Example value
- `file/date/dateTime`: Data type markers

---

## 🔧 Code Integration

### Parsing the New API Structure

```python
import requests

response = requests.get("http://localhost:8083/api/packages")
data = response.json()

# Access top-level info
total_sheets = data["total"]  # 5
total_fields = data["totalMetadataItems"]  # 2689

# Access ISA sheet info
for sheet_name, sheet_info in data["metadata"].items():
    print(f"Sheet: {sheet_info['displayName']}")
    print(f"  Description: {sheet_info['description']}")
    print(f"  Hierarchy Order: {sheet_info['hierarchyOrder']}")
    print(f"  Field Count: {len(sheet_info['metadata'])}")
    
    # Access fields
    for field in sheet_info["metadata"]:
        print(f"    - {field['label']} ({field['requirement']})")
        print(f"      Package: {field['packageName']}")
        print(f"      Regex: {field['term']['regex']}")
```

### Extracting Fields by Package Name

```python
def get_fields_by_package(data, package_name):
    """Extract all fields belonging to a specific package."""
    fields = []
    for sheet_name, sheet_info in data["metadata"].items():
        for field in sheet_info["metadata"]:
            if field["packageName"] == package_name:
                field["isaSheet"] = sheet_name  # Add ISA sheet info
                fields.append(field)
    return fields

# Example: Get all 'miappe' fields
miappe_fields = get_fields_by_package(data, "miappe")
```

---

## 📝 Migration Notes

### From Old API to New API

**Old Structure:**
```python
# Old: packages[sheet] is a list of fields
fields = data["packages"]["investigation"]
```

**New Structure:**
```python
# New: metadata[sheet]["metadata"] is a list of fields
fields = data["metadata"]["investigation"]["metadata"]
```

### Key Differences

| Aspect | Old API | New API |
|--------|---------|---------|
| Top-level key | `packages` | `metadata` |
| Sheet structure | List of fields | Object with `name`, `displayName`, `description`, `hierarchyOrder`, `metadata` |
| Fields location | `packages[sheet]` | `metadata[sheet]["metadata"]` |
| `/api/terms` | Returns JSON | Returns HTML (removed) |
| Total items key | N/A | `totalMetadataItems` |
