# 🔍 FAIR-DS API Exploration Results

## 📊 Actual API Structure (Based on [FAIR-DS API Documentation](https://docs.fairbydesign.nl/docs/fairdatastation/tutorials/api.html))

### API Endpoints

#### 1. GET `/api/terms` - All Terms
```bash
curl http://localhost:8083/api/terms
```

**Return Structure:**
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

#### 2. GET `/api/packages` - Grouped Terms
```bash
curl http://localhost:8083/api/packages
```

**Return Structure:**
```json
{
  "total": 5,
  "packages": {
    "investigation": [...],  // 17 fields
    "study": [...],          // 25 fields
    "sample": [...],         // 2411 fields (Max!)
    "assay": [...],          // 99 fields
    "observationunit": [...]  // 137 fields
  }
}
```

**Structure of Fields within Each Package:**
```json
{
  "label": "investigation identifier",
  "definition": "Identifier corresponding to the investigation",
  "sheetName": "Investigation",
  "packageName": "default",
  "requirement": "MANDATORY",  // or OPTIONAL
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

## 📋 Data Statistics

| Package | Field Count | Purpose |
|---------|---------|------|
| **investigation** | 17 | Project-level metadata |
| **study** | 25 | Study-level metadata |
| **sample** | 2411 | Sample-level metadata (Most detailed) |
| **assay** | 99 | Experiment/Assay-level metadata |
| **observationunit** | 137 | Observation unit metadata |

**Total:** 2689 fields!

---

## 🎯 Key Findings

### 1. This is NOT the MIxS Standard
- ✅ This is FAIR Data Station's own metadata schema.
- ✅ Based on the **ISA (Investigation-Study-Assay)** model.
- ✅ Supports **MIAPPE** (Minimum Information About Plant Phenotyping Experiments).
- ✅ Has a hierarchical structure: Investigation → Study → Sample/ObservationUnit → Assay.

### 2. Fields Have Clear Requirement Levels
- **MANDATORY**: Required fields.
- **OPTIONAL**: Optional fields.
- **RECOMMENDED**: Recommended fields.

### 3. Each Field Has Validation Rules
- `regex`: Regular expression validation.
- `syntax`: Syntax pattern.
- `example`: Example value.
- `file/date/dateTime`: Data type markers.

---

## 🔄 Updated KnowledgeRetriever Strategy

Based on the actual API, we should:

### Current Issue:
```python
# Code assumes MIxS packages (MIMS, MIMAG etc.)
# But actual API returns ISA model (investigation, study, sample, assay)
```

### Correct Approach:
```python
# 1. Get packages
packages_data = fair_ds_client.get_packages()
# → {"total": 5, "packages": {investigation: [...], study: [...], ...}}

# 2. LLM analyzes document to decide which packages are needed
# "This is a research paper, needs investigation and study levels"
# "This is a sample description, needs sample and observationunit levels"

# 3. For each relevant package, LLM selects relevant fields
# Select 5-8 fields from investigation's 17
# Select 8-12 fields from study's 25
# Select 5-10 most relevant fields from sample's 2411

# 4. Prioritize MANDATORY fields
```

---

## 💡 Proposed Logic

### Phase 1: Determine Relevant Packages
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

### Phase 2: Select Fields for Each Package
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

### Phase 3: Generate Field Values
```python
# Generate values for selected fields
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

## 🔧 Code Changes Needed

### 1. `fairifier/services/fair_data_station.py`
Current code needs adjustment to correctly parse the API return structure.

### 2. `fairifier/agents/knowledge_retriever.py`
- Remove MIxS assumption.
- Use the actual 5 packages.
- LLM selects packages based on document type.
- LLM intelligently selects from 2411 sample fields.

### 3. Prompt Updates
- "MIxS packages" → "FAIR-DS packages"
- "MIMS, MIMAG" → "investigation, study, sample, assay, observationunit"
- Mention actual field counts.

---

## 📝 Example Mandatory Fields

### Investigation Level (Mandatory):
- investigation identifier
- investigation title
- investigation description
- firstname, lastname, email, organization

### Study Level (Mandatory):
- study identifier
- study title
- study description

---

## 🎯 Next Steps

I need to update the code to:
1. ✅ Correctly parse the actual FAIR-DS API return format.
2. ✅ Use real package names (investigation, study, sample, assay, observationunit).
3. ✅ Enable LLM to intelligently handle 2411 sample fields.
4. ✅ Prioritize MANDATORY fields.
5. ✅ Use regex and example for validation.

