# FAIR Data Station API Reference

This document describes the FAIR Data Station (FAIR-DS) API structure and usage for FAIRiAgent integration.

> **API Version:** FAIR-DS JAR (Latest - January 2026)  
> **Base URL:** `http://localhost:8083`  
> **Swagger UI:** http://localhost:8083/swagger-ui/index.html

---

## Endpoints Overview

| Endpoint | Method | Status | Description |
|----------|--------|--------|-------------|
| `GET /api` | GET | Available | Get API overview and list available endpoints |
| `GET /api/terms` | GET | Available | Get all metadata terms or filter by label/definition |
| `GET /api/package` | GET | Available | Get all packages or a specific package by name |
| `POST /api/upload` | POST | Available | Validates metadata Excel file |
| `POST /api/isa` | POST | Available | Submit ISA JSON; receive generated metadata Excel (`.xlsx`) |

---

## GET `/api`

Returns overview of available API endpoints.

### Request

```bash
curl http://localhost:8083/api
```

### Response

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

Retrieves all metadata terms or filters by label and/or definition using case-insensitive pattern matching.

### Request

```bash
# Get all terms
curl http://localhost:8083/api/terms

# Filter by label
curl "http://localhost:8083/api/terms?label=temperature"

# Filter by definition
curl "http://localhost:8083/api/terms?definition=sampling"

# Combine filters
curl "http://localhost:8083/api/terms?label=temp&definition=temperature"
```

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `label` | string | No | Filter terms by label (supports pattern matching, case-insensitive) |
| `definition` | string | No | Filter terms by definition (supports pattern matching, case-insensitive) |

### Response Structure

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

### Filtered Response Example

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

**Key Points:**
- Returns 892 terms when called without filters
- Supports partial matching (e.g., `label=temp` matches "temperature")
- Case-insensitive pattern matching
- Can combine `label` and `definition` filters (AND logic)
- Filtered results significantly reduce response size

---

## GET `/api/package`

Retrieves all available metadata packages or a specific package by name.

### Request

```bash
# Get list of all packages
curl http://localhost:8083/api/package

# Get specific package
curl "http://localhost:8083/api/package?name=miappe"
```

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | No | Name of the metadata package to retrieve. If not provided, returns list of all available packages |

### Response (without name parameter)

```json
{
  "message": "No package name specified. Available packages listed below.",
  "packages": [
    "default",
    "miappe",
    "soil",
    "water",
    // ... 59 total packages
  ],
  "example": "/api/package?name=soil"
}
```

### Response (with name parameter)

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
    // ... remaining fields
  ]
}
```

**Key Points:**
- Returns only fields for the specified package (e.g., 63 fields for miappe vs 2689 total)
- Reduces data transfer by ~98% for single package queries
- Includes `itemCount` for quick reference
- `metadata` is an array of fields (not grouped by ISA sheet)

---

## POST `/api/isa`

Submits an ISA (Investigation, Study, Assay, …) structure as JSON and returns a **metadata Excel workbook** (binary `.xlsx`). See Swagger: [submitIsaStructure](https://fairds.fairbydesign.nl/swagger-ui/index.html#/FAIR%20Data%20Station%20API/submitIsaStructure).

### Request body

Top-level shape: `{"isa_structure": { ... }}`. The `isa_structure` object may include any of:

- `investigation`, `study`, `observationunit`, `sample`, `assay`

Each block is typically `{"description": string, "fields": [ ... ]}`. Each field follows the API `Field` model (e.g. `field_name`, `value`, optional `evidence`, `confidence`, `origin`, `status`, `package_source`). FAIRiAgent’s workflow JSON uses the same `isa_structure` tree under the root key `isa_structure`; pass that object (or the whole file’s `isa_structure` value) as the inner payload when calling the API.

### Sheets vs metadata packages

- The generated workbook uses **one worksheet per ISA level** that has at least one field, and usually a **`Help`** sheet. Levels correspond to the blocks above (e.g. `investigation`, `study`), not to MIxS/GSC **package names** (`soil`, `water`, `miappe`, …).
- **Multiple packages** in one dataset are represented **inside those ISA sheets**, e.g. via `package_source` on each field—not as separate tabs per package.

### Example

```bash
curl -sS -X POST "https://fairds.fairbydesign.nl/api/isa" \
  -H "Content-Type: application/json" \
  -H "Accept: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" \
  -d '{"isa_structure":{"study":{"description":"…","fields":[{"field_name":"study title","value":"My study"}]}}}' \
  -o metadata.xlsx
```

In Python, use `FAIRDataStationClient.generate_excel_from_isa_structure` in `fairifier.services.fair_data_station`.

After a successful workflow run, the CLI and Web API also write **`metadata_fairds.xlsx`** next to `metadata.json` when FAIR-DS is reachable and `isa_structure` contains at least one field (see `fairifier.services.fairds_excel_export`).

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

### Get All Terms

```python
import requests

response = requests.get("http://localhost:8083/api/terms")
data = response.json()

total_terms = data["total"]  # 892
```

### Search Terms by Label

```python
# Search for temperature-related terms
response = requests.get("http://localhost:8083/api/terms", params={"label": "temperature"})
data = response.json()

print(f"Found {data['total']} terms matching 'temperature'")
for term_name, term_info in data["terms"].items():
    print(f"  - {term_name}: {term_info['definition']}")
```

### Search Terms by Definition

```python
# Search for terms related to sampling
response = requests.get("http://localhost:8083/api/terms", params={"definition": "sampling"})
data = response.json()

print(f"Found {data['total']} terms related to sampling")
```

### Get List of All Packages

```python
response = requests.get("http://localhost:8083/api/package")
data = response.json()

packages = data["packages"]  # List of 59 package names
print(f"Available packages: {len(packages)}")
```

### Get Specific Package

```python
# Get miappe package fields
response = requests.get("http://localhost:8083/api/package", params={"name": "miappe"})
package_data = response.json()

print(f"Package: {package_data['packageName']}")
print(f"Fields: {package_data['itemCount']}")

for field in package_data["metadata"]:
    print(f"  - {field['label']} ({field['requirement']})")
    print(f"    Sheet: {field['sheetName']}")
```

### Filter Fields by Requirement Level

```python
def get_mandatory_fields(package_data):
    """Extract mandatory fields from a package response."""
    return [
        field for field in package_data["metadata"]
        if field["requirement"] == "MANDATORY"
    ]

# Get miappe package
response = requests.get("http://localhost:8083/api/package", params={"name": "miappe"})
package_data = response.json()

mandatory_fields = get_mandatory_fields(package_data)
print(f"Mandatory fields: {len(mandatory_fields)}")
```

### Group Fields by ISA Sheet

```python
def group_fields_by_sheet(package_data):
    """Group package fields by ISA sheet."""
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
    print(f"{sheet}: {len(fields)} fields")
```

---

## Migration Notes

### API Changes

| Aspect | Previous | Current |
|--------|----------|---------|
| `/api/terms` | Returned HTML | ✅ Returns JSON with filtering support |
| `/api/packages` | Returned all fields (2689) | ❌ Not available |
| `/api/package` | Not available | ✅ New - query specific packages |
| Package endpoint | N/A | Uses query parameter `?name={package}` |

### Best Practices

1. **Use `/api/package?name={name}`** instead of fetching all fields and filtering client-side
   - Reduces data transfer by ~98%
   - Faster response times

2. **Use `/api/terms?label={pattern}`** for term discovery
   - More efficient than fetching all 892 terms
   - Supports partial matching

3. **Combine filters** when possible
   - `/api/terms?label=temp&definition=temperature` for precise searches

---

## Related Resources

- [FAIR-DS Official Documentation](https://docs.fairbydesign.nl/docs/fairdatastation/tutorials/api.html)
- [Swagger UI](http://localhost:8083/swagger-ui/index.html) - Interactive API documentation
