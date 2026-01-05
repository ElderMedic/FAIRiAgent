# Feature Request: Additional API Endpoints for Programmatic Access

## Summary

We are developing [FAIRiAgent](https://github.com/your-repo/FAIRiAgent), an AI-powered tool that helps researchers automatically generate FAIR-compliant metadata from scientific documents. Our tool integrates with FAIR Data Station's API to retrieve metadata schemas and validate generated values.

We would like to propose **two new API endpoints** that would significantly improve the efficiency of programmatic integrations like ours.

---

## Current API Usage

We currently use these endpoints:
- `GET /api/packages` - Retrieve all metadata fields (works well ✅)
- `POST /api/upload` - Validate Excel files (works well ✅)
- `GET /api/terms` - ⚠️ Now returns HTML instead of JSON

### Challenge

The `/api/packages` endpoint returns **all 2,689 fields** across all 59 packages in a single response (~500KB). For our use case, we typically only need 100-200 fields from 1-3 specific packages.

**Current workflow:**
```python
# Must fetch everything (2,689 fields)
response = requests.get("http://localhost:8083/api/packages")
all_data = response.json()

# Then filter client-side
miappe_fields = [f for f in all_fields if f["packageName"] == "miappe"]
```

This results in:
- **~93% unnecessary data transfer** when we only need one package
- **No search capability** for discovering relevant terms
- **Higher memory usage** on client side

---

## Proposed Enhancements

### 1. `GET /api/packages/{package_name}` — Get Specific Package

**Use case:** Retrieve all fields belonging to a specific package (e.g., `miappe`, `soil`, `default`).

**Request:**
```bash
curl http://localhost:8083/api/packages/miappe
```

**Suggested response:**
```json
{
  "packageName": "miappe",
  "description": "Minimum Information About Plant Phenotyping Experiments",
  "totalFields": 103,
  "mandatoryFields": 7,
  "optionalFields": 96,
  "isaSheets": ["investigation", "study", "sample", "observationunit"],
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
    }
    // ... remaining 102 fields
  ]
}
```

**Benefits:**
- Reduces data transfer by ~90% for typical use cases
- Allows clients to fetch packages on-demand
- Maintains backward compatibility (existing `/api/packages` still works)

**Implementation note:** This could be a simple filter on the existing data structure.

---

### 2. `GET /api/search/terms?q={query}` — Search Terms

**Use case:** Discover relevant metadata terms by searching labels and definitions.

**Request:**
```bash
curl "http://localhost:8083/api/search/terms?q=temperature"
```

**Suggested response:**
```json
{
  "query": "temperature",
  "total": 5,
  "results": [
    {
      "label": "temperature",
      "definition": "The temperature at the time of sampling",
      "packages": ["soil", "water", "air"],
      "isaSheet": "sample",
      "requirement": "OPTIONAL"
    },
    {
      "label": "air temperature",
      "definition": "Temperature of the air at sampling time",
      "packages": ["air"],
      "isaSheet": "sample",
      "requirement": "OPTIONAL"
    }
  ]
}
```

**Optional query parameters:**
- `package` — Filter by package name
- `sheet` — Filter by ISA sheet
- `requirement` — Filter by requirement level (MANDATORY/OPTIONAL)
- `limit` — Maximum results (default: 50)

**Benefits:**
- Enables term discovery without loading all data
- Replaces the removed `/api/terms` JSON functionality
- Helps users find the right metadata fields for their data

---

## Priority

| Priority | Endpoint | Impact |
|----------|----------|--------|
| 🔴 High | `GET /api/packages/{package_name}` | ~90% reduction in data transfer |
| 🟡 Medium | `GET /api/search/terms?q={query}` | Enables term discovery |

We believe `GET /api/packages/{package_name}` would provide the most immediate value and should be relatively straightforward to implement.

---

## Implementation Suggestions

1. **URL encoding:** Term/package names with spaces should use URL encoding (e.g., `study%20title`)
2. **Case insensitivity:** Package and term names should match case-insensitively
3. **Error handling:** Return 404 with helpful message if package/term not found
4. **Search:** Simple substring matching would be sufficient; fuzzy matching is nice-to-have

---

## About Our Project

FAIRiAgent is an open-source tool that uses LLMs to automatically extract metadata from scientific publications and format it according to FAIR Data Station's schema. The tool:

1. Analyzes research documents (PDFs, text)
2. Queries FAIR-DS API to get relevant metadata schemas
3. Uses AI to extract and map information to metadata fields
4. Validates the output against FAIR-DS validation rules

These API enhancements would help us build a more efficient and responsive tool for the research community.


We're happy to discuss further or contribute to the implementation if helpful.

Thank you for building FAIR Data Station! 🙏
