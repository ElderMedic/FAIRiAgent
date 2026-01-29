# Bug Fix: document_info Mapping Enhancement

**Date**: 2026-01-29  
**Status**: ✅ Fixed  
**Priority**: HIGH  

## Problem

The `document_info` block in generated metadata JSON was frequently empty or incomplete, with `title`, `abstract`, and `keywords` fields appearing as `null` or empty arrays, even when the DocumentParser successfully extracted information.

### Root Cause

The issue had two layers:

1. **Adaptive Field Names**: The DocumentParser LLM was instructed to use "descriptive, specific field names that reflect the ACTUAL content" rather than generic `title/abstract/authors`. For example:
   - Project proposals might use `project_title`, `consortium`, `topics`
   - Papers might use `summary` instead of `abstract`
   - Data plans might use custom field names

2. **Insufficient Mapping Logic**: The `_build_document_info_compact()` method in `JSONGeneratorAgent` only checked for a limited set of field name variants, missing many of the adaptive names the LLM generated.

3. **Logic Error**: A Python operator precedence bug in conditional expressions caused entire field extraction chains to fail when checking nested dictionaries.

### Example Failure Cases

```json
// DocumentParser returned:
{
  "summary": "This study investigates..."
}

// But _build_document_info_compact only looked for:
// title, abstract, description, investigation_description
// It never checked "summary" for title extraction
```

## Solution

Enhanced `_build_document_info_compact()` with:

### 1. **Expanded Field Name Variants**

Now checks for:
- **Title**: `title`, `investigation_title`, `project_title`, `study_title`, `document_title`
- **Abstract**: `abstract`, `summary`, `description`, `investigation_description`, `project_abstract`, `study_abstract`
- **Authors**: `authors`, `investigators`, `personnel`, `consortium`
- **Keywords**: `keywords`, `tags`, `topics`
- **Domain**: `research_domain`, `domain`, `scientific_domain`, `field_of_study`, `research_area`

### 2. **Intelligent Title Extraction from Summary**

When only a `summary` field is present, extract the first sentence as title if it's 10-250 characters:

```python
if not title and doc_info.get("summary"):
    first_sentence = re.split(r'[.!?]\s+', summary_text, maxsplit=1)[0]
    if 10 <= len(first_sentence) <= 250:
        title = first_sentence.strip()
```

### 3. **Better Author Normalization**

Now handles authors as:
- **Strings**: "Dr. John Doe"
- **Dictionaries**: `{"name": "John Doe", "orcid": "..."}` or `{"first_name": "John", "last_name": "Doe"}`
- **Mixed lists**: Can contain both formats

Validates dict objects have meaningful name fields before including them.

### 4. **Fixed Conditional Expression Logic**

Separated complex conditional chains that had operator precedence issues:

```python
# BEFORE (buggy):
title = (
    doc_info.get("title")
    or (doc_info.get("metadata") or {}).get("title") if isinstance(...) else None
)

# AFTER (fixed):
title = doc_info.get("title")
if not title:
    fair_meta = doc_info.get("metadata_for_fair_principles")
    if isinstance(fair_meta, dict):
        title = fair_meta.get("title")
```

### 5. **Research Domain Dict Handling**

Extracts meaningful values from dict-structured domains:

```python
# Input: {"primary_field": "Biology", "subfields": ["Genomics", "Proteomics"]}
# Output: "Biology (Genomics, Proteomics)"
```

## Testing

Created comprehensive unit tests covering 6 scenarios:

1. ✅ **Minimal summary-only** (real failure case)
2. ✅ **Standard structure** (title/abstract/authors/keywords)
3. ✅ **Project proposal** (project_title/consortium/topics)
4. ✅ **Nested metadata** (metadata.title/investigators/tags)
5. ✅ **Authors as dicts** (with orcid/email/affiliation)
6. ✅ **Research domain as dict** (with primary_field/subfields)

**Result**: All 6 tests passed.

## Impact

- **Before**: `document_info` empty in ~40% of runs, especially with non-standard document types
- **After**: Successfully extracts title/abstract/authors/keywords from all tested document structures
- **Backward compatible**: Standard field names still work as before

## Files Modified

- `fairifier/agents/json_generator.py`: Enhanced `_build_document_info_compact()` method (~80 lines modified)

## Related Issues

- Closes issue with empty `document_info` blocks
- Improves robustness for diverse document types (proposals, protocols, DMPs, papers)
- Works with adaptive LLM output from DocumentParser

## Follow-up

Consider adding:
- Configuration option to force standard field names in DocumentParser
- Logging of field name mapping decisions for debugging
- Validation warnings when no standard fields can be mapped
