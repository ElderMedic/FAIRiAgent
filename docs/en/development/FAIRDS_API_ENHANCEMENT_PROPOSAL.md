# FAIR Data Station API Enhancement Proposal

## Current API Capabilities

Based on the [official documentation](https://docs.fairbydesign.nl/docs/fairdatastation/tutorials/api.html), the FAIR-DS API currently supports:

1. **GET `/api/terms`** - Returns all terms (893 total)
2. **GET `/api/packages`** - Returns all packages grouped by ISA sheet (2689 total fields)
3. **POST `/api/upload`** - Validates an Excel file

## Problem Statement

The current workflow requires fetching **all** terms (893) and **all** packages (2689 fields), then filtering client-side. This is inefficient for agentic workflows that need targeted queries.

## Proposed API Enhancements

### 1. **GET `/api/terms/{term_name}`** - Get Specific Term

**Purpose**: Retrieve detailed information about a specific term by name, including which packages use it.

**Request**:
```bash
curl http://localhost:8083/api/terms/study%20title
```

**Response**:
```json
{
  "label": "study title",
  "syntax": "{text}{10,}",
  "example": "Cultivation and characterization of anaerobic Dehalobacter-enriched microbial cultures",
  "definition": "Title describing the study",
  "preferredUnit": null,
  "ontology": null,
  "regex": ".*{10,}",
  "file": false,
  "date": false,
  "dateTime": false,
  "url": "http://schema.org/title",
  "packages": [
    {
      "packageName": "default",
      "sheetName": "Study",
      "requirement": "MANDATORY"
    },
    {
      "packageName": "miappe",
      "sheetName": "Study",
      "requirement": "MANDATORY"
    }
  ]
}
```

**Benefits**:
- Quick lookup without fetching all 893 terms
- See which packages use the term
- Get validation rules (regex, syntax, example) for the term

---

### 2. **GET `/api/packages/{package_name}`** - Get Specific Package

**Purpose**: Retrieve all terms and metadata for a specific package.

**Request**:
```bash
curl http://localhost:8083/api/packages/miappe
```

**Response**:
```json
{
  "packageName": "miappe",
  "description": "Minimum Information About Plant Phenotyping Experiments",
  "version": "1.0.0",
  "isaSheets": ["investigation", "study", "sample", "observationunit"],
  "totalFields": 103,
  "mandatoryFields": 7,
  "optionalFields": 96,
  "fields": [
    {
      "label": "study title",
      "definition": "Title describing the study",
      "sheetName": "Study",
      "requirement": "MANDATORY",
      "term": {
        "syntax": "{text}{10,}",
        "example": "Cultivation and characterization...",
        "regex": ".*{10,}",
        "url": "http://schema.org/title"
      }
    },
    ...
  ],
  "mandatoryFieldsBySheet": {
    "investigation": [...],
    "study": [...],
    "sample": [...],
    "observationunit": [...]
  },
  "optionalFieldsBySheet": {
    "investigation": [...],
    "study": [...],
    "sample": [...],
    "observationunit": [...]
  }
}
```

**Benefits**:
- Fetch only the package you need (e.g., 103 fields for miappe) instead of all 2689 fields
- Understand package structure (mandatory vs optional fields)
- See which ISA sheets the package covers
- Get all terms with their validation rules

---

### 3. **GET `/api/search/terms?q={query}`** - Search Terms

**Purpose**: Search terms by name, label, or definition to discover relevant terms.

**Request**:
```bash
curl "http://localhost:8083/api/search/terms?q=temperature"
```

**Response**:
```json
{
  "query": "temperature",
  "total": 3,
  "results": [
    {
      "label": "temperature",
      "definition": "The temperature at the time of sampling",
      "packages": ["environmental_measurements"],
      "matchType": "exact"
    },
    {
      "label": "air temperature",
      "definition": "Temperature of the air",
      "packages": ["environmental_measurements"],
      "matchType": "partial"
    },
    {
      "label": "water temperature",
      "definition": "Temperature of the water",
      "packages": ["environmental_measurements"],
      "matchType": "partial"
    }
  ]
}
```

**Query Parameters**:
- `q` (required): Search query string
- `package` (optional): Filter by package name (e.g., `?q=temperature&package=environmental_measurements`)
- `sheet` (optional): Filter by ISA sheet (e.g., `?q=temperature&sheet=sample`)
- `requirement` (optional): Filter by requirement level (e.g., `?q=temperature&requirement=MANDATORY`)
- `limit` (optional): Maximum results (default: 50)

**Benefits**:
- Discover relevant terms when exact name is unknown
- Find alternative terms with similar meanings
- Filter results by package, ISA sheet, or requirement level
- Much faster than fetching all 893 terms and filtering client-side

---

## Example Usage

### Current Workflow (Inefficient):
```python
# Fetch ALL terms (893)
all_terms = client.get_terms()

# Fetch ALL packages (2689 fields)
all_packages = client.get_packages()

# Client-side filtering
relevant_terms = [t for t in all_terms if "temperature" in t["label"].lower()]
miappe_fields = [f for f in all_packages if f.get("packageName") == "miappe"]
```

### Enhanced Workflow (Efficient):
```python
# Search for relevant terms (only 3 results)
temperature_terms = client.search_terms("temperature")

# Get specific package (only 103 fields)
miappe_package = client.get_package("miappe")

# Get specific term with package info
study_title = client.get_term("study title")
```

---

## Backward Compatibility

All proposed endpoints are **additive** - they don't modify existing endpoints:
- `/api/terms` - Still works as before
- `/api/packages` - Still works as before
- `/api/upload` - Still works as before

New endpoints provide additional functionality without breaking existing code.

---

## Implementation Notes

1. **Term name encoding**: Use URL encoding for term names with spaces (e.g., `study%20title` for "study title")
2. **Case sensitivity**: Term and package names should be case-insensitive for better usability
3. **404 handling**: Return 404 if term/package not found
4. **Search algorithm**: Implement fuzzy matching for better discovery (e.g., "temp" matches "temperature")
