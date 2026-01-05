# FAIR Data Station API Reference

This document describes the FAIR Data Station (FAIR-DS) API structure and usage for FAIRiAgent integration.

> **API Version:** FAIR-DS JAR (January 2026)  
> **Base URL:** `http://localhost:8083`

---

## Endpoints Overview

| Endpoint | Method | Status | Description |
|----------|--------|--------|-------------|
| `/api/packages` | GET | Available | Returns all metadata fields grouped by ISA sheet |
| `/api/upload` | POST | Available | Validates metadata Excel file |
| `/api/terms` | GET | Deprecated | Now returns HTML; use `/api/packages` instead |

---

## GET `/api/packages`

Returns all metadata fields organized by ISA (Investigation-Study-Assay) hierarchy.

### Request

```bash
curl http://localhost:8083/api/packages
```

### Response Structure

```json
{
  "total": 5,
  "totalMetadataItems": 2689,
  "metadata": {
    "<sheet_name>": {
      "name": "string",
      "displayName": "string",
      "description": "string",
      "hierarchyOrder": "number",
      "metadata": [<field>, ...]
    }
  }
}
```

### ISA Sheets

| Sheet | Display Name | Hierarchy | Field Count | Description |
|-------|--------------|-----------|-------------|-------------|
| `investigation` | Investigation | 1 | 17 | Project-level metadata |
| `study` | Study | 2 | 25 | Study-level metadata |
| `observationunit` | Observation Unit | 3 | 137 | Entity being observed |
| `sample` | Sample | 4 | 2411 | Physical specimen metadata |
| `assay` | Assay | 5 | 99 | Experiment/measurement metadata |

### Field Structure

Each field in `metadata[sheet].metadata[]` has the following structure:

```json
{
  "label": "investigation identifier",
  "definition": "Identifier corresponding to the investigation",
  "sheetName": "Investigation",
  "packageName": "default",
  "requirement": "MANDATORY",
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

### Field Properties

| Property | Type | Description |
|----------|------|-------------|
| `label` | string | Field name |
| `definition` | string | Field description |
| `sheetName` | string | ISA sheet this field belongs to |
| `packageName` | string | Package this field belongs to |
| `requirement` | string | `MANDATORY`, `OPTIONAL`, or `RECOMMENDED` |
| `term.syntax` | string | Syntax pattern for validation |
| `term.example` | string | Example value |
| `term.regex` | string | Regular expression for validation |
| `term.url` | string | Ontology URI |
| `term.file` | boolean | Whether field expects a file |
| `term.date` | boolean | Whether field expects a date |
| `term.dateTime` | boolean | Whether field expects a datetime |

---

## Available Packages

The API includes 59 packages. Fields are associated with packages via the `packageName` property.

### Core Packages

| Package | Description |
|---------|-------------|
| `default` | Base package with core ISA fields |
| `miappe` | Minimum Information About Plant Phenotyping Experiments |
| `unlock` | UNLOCK project specific fields |

### Environmental Packages

`air`, `water`, `soil`, `sediment`, `built environment`, `wastewater sludge`, `microbial mat biolfilm`, `miscellaneous natural or artificial environment`, `plant associated`

### Host-Associated Packages

`host associated`, `human associated`, `human gut`, `human oral`, `human skin`, `human vaginal`, `pig`, `pig_blood`, `pig_faeces`, `pig_health`, `pig_histology`, `person`

### Sequencing Technology Packages

`Illumina`, `Nanopore`, `PacBio`, `LS454`, `Amplicon demultiplexed`, `Amplicon library`, `Genome`

### ENA Checklists

`ENA default sample checklist`, `ENA prokaryotic pathogen minimal sample checklist`, `ENA virus pathogen reporting standard checklist`, `ENA binned metagenome`, `ENA Marine Microalgae Checklist`, `ENA Shellfish Checklist`, `ENA Tara Oceans`, `ENA Micro B3`, `ENA sewage checklist`, `ENA parasite sample checklist`, `ENA mutagenesis by carcinogen treatment checklist`, `ENA Influenza virus reporting standard checklist`, `ENA Global Microbial Identifier reporting standard checklist GMI_MDM:1.1`

### GSC Standards

| Package | Description |
|---------|-------------|
| `GSC MIMAGS` | Metagenome-Assembled Genomes |
| `GSC MISAGS` | Single Amplified Genomes |
| `GSC MIUVIGS` | Uncultivated Virus Genomes |

### Other Packages

`COMPARE-ECDC-EFSA pilot food-associated reporting standard`, `COMPARE-ECDC-EFSA pilot human-associated reporting standard`, `Crop Plant sample enhanced annotation checklist`, `Plant Sample Checklist`, `Tree of Life Checklist`, `HoloFood Checklist`, `PDX Checklist`, `UniEuk_EukBank`, `MIFE`, `Metabolomics`, `Proteomics`

---

## Code Examples

### Fetching All Packages

```python
import requests

response = requests.get("http://localhost:8083/api/packages")
data = response.json()

total_fields = data["totalMetadataItems"]  # 2689
```

### Iterating Over ISA Sheets

```python
for sheet_name, sheet_info in data["metadata"].items():
    print(f"{sheet_info['displayName']}: {len(sheet_info['metadata'])} fields")
    
    for field in sheet_info["metadata"]:
        print(f"  - {field['label']} ({field['requirement']})")
```

### Filtering Fields by Package

```python
def get_fields_by_package(data, package_name):
    """Extract all fields belonging to a specific package."""
    fields = []
    for sheet_name, sheet_info in data["metadata"].items():
        for field in sheet_info["metadata"]:
            if field["packageName"] == package_name:
                field["isaSheet"] = sheet_name
                fields.append(field)
    return fields

miappe_fields = get_fields_by_package(data, "miappe")
```

### Filtering Mandatory Fields

```python
def get_mandatory_fields(data):
    """Extract all mandatory fields."""
    fields = []
    for sheet_name, sheet_info in data["metadata"].items():
        for field in sheet_info["metadata"]:
            if field["requirement"] == "MANDATORY":
                fields.append(field)
    return fields
```

---

## Migration from Previous API Version

If upgrading from an older FAIR-DS version, note the following changes:

| Aspect | Previous | Current |
|--------|----------|---------|
| Top-level key | `packages` | `metadata` |
| Sheet structure | `[field, ...]` | `{name, displayName, description, hierarchyOrder, metadata: [...]}` |
| Fields location | `data["packages"]["investigation"]` | `data["metadata"]["investigation"]["metadata"]` |
| `/api/terms` | Returns JSON | Returns HTML (deprecated) |

---

## Related Resources

- [FAIR-DS Official Documentation](https://docs.fairbydesign.nl/docs/fairdatastation/tutorials/api.html)
- [FAIRDS_API_ENHANCEMENT_PROPOSAL.md](./FAIRDS_API_ENHANCEMENT_PROPOSAL.md) — Proposed API improvements
