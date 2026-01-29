# Prompt Engineering Guide for FAIRiAgent

**Version**: 1.0  
**Date**: 2026-01-29  
**Status**: Active Development Guidelines

---

## Overview

This document provides guidelines for writing, reviewing, and maintaining LLM prompts in FAIRiAgent. It's based on the comprehensive audit conducted in January 2026 (see [PROMPTS_AUDIT_REPORT.md](../../PROMPTS_AUDIT_REPORT.md)).

---

## Prompt Design Principles

### 1. Always Specify Output Length Limits ⭐

**Why**: Prevents oversized responses (e.g., 192KB instead of expected 20KB)

**How**:
```markdown
**CRITICAL CONSTRAINTS:**
- Maximum response size: 20,000 characters (~5,000 tokens)
- Each field value: < 500 characters
- Evidence/reasoning: < 200 characters
- If exceeds limit, MUST truncate and prioritize essential information
```

### 2. Use Consistent Format Instructions ⭐

**Problem**: Different prompts use contradictory format instructions

**Solution**: Standardize across all prompts

```markdown
**OUTPUT FORMAT - STANDARD v1.0:**
Wrap your JSON response in markdown code blocks:

```json
{
  "your": "content here"
}
```

REQUIREMENTS:
- Line 1: ```json (alone)
- Lines 2-N: Valid JSON only
- Line N+1: ``` (alone)
- NO text before the opening ```json
- NO text after the closing ```
- NO comments in JSON (// not allowed)
```

### 3. Define Clear Boundaries (Not "Extract ALL")

**Problem**: "Extract ALL relevant information" leads to verbose outputs

**Solution**: Use bounded extraction

```markdown
**Your task:**
Extract ONLY the essential metadata for this document type.

**DO Extract:**
- Key identifiers (titles, IDs, names)
- Structured data (dates, numbers, categories)
- Relationships (authors, affiliations, samples)
- Critical context (1-2 sentence summaries)

**DO NOT Extract:**
- Full paragraphs or sections
- Detailed explanations
- Background information
- Literature reviews
```

### 4. Add Model-Specific Instructions

**Why**: Different models have different strengths/weaknesses

**Implementation**:
```python
def get_model_specific_constraints(model_name: str) -> str:
    """Return model-specific prompt additions."""
    if "qwen" in model_name.lower():
        return """
**IMPORTANT FOR YOUR MODEL:**
- You tend to be verbose. Keep this response SHORT.
- Maximum: 20,000 characters
- NO academic essay writing
- NO explanatory paragraphs
- ONLY structured data extraction
"""
    elif "gpt" in model_name.lower():
        return """
**OUTPUT FORMAT:**
Return only valid JSON. No markdown blocks needed.
"""
    # ... other models
```

### 5. Provide Negative Examples

**Why**: Shows what NOT to do

**Example**:
```markdown
**INVALID OUTPUTS - DO NOT DO THIS:**
❌ "value": "According to the methods section..."  (explanation, not value)
❌ "evidence": "The researchers conducted a comprehensive analysis spanning multiple sites over 18 months..." (too long)
❌ Response includes: "Here are my findings: ```json..." (extra text)

**VALID OUTPUTS:**
✅ "value": "Soil microbiome diversity"
✅ "evidence": "Methods section, paragraph 2"
✅ Response is: "```json\n{...}\n```" (nothing else)
```

---

## Prompt Template

Use this template for all new prompts:

```python
def create_prompt(task_description: str, input_data: dict) -> str:
    """
    Standard prompt template for FAIRiAgent.
    
    Args:
        task_description: What the LLM should do
        input_data: Input data for the task
    """
    
    prompt = f"""You are an expert at {task_description}.

**CRITICAL CONSTRAINTS - READ FIRST:**
1. Maximum response size: 20,000 characters (~5,000 tokens)
2. [Add specific constraints for this task]
3. Use concise language
4. Prioritize essential information

**Your task:**
[Clear, bounded task description]

**DO:**
- [Specific action 1]
- [Specific action 2]
- [Specific action 3]

**DO NOT:**
- [Specific thing to avoid 1]
- [Specific thing to avoid 2]

**Input:**
{json.dumps(input_data, indent=2)}

**OUTPUT FORMAT - STANDARD v1.0:**
Wrap your JSON response in markdown code blocks:

```json
{{
  "your": "content"
}}
```

REQUIREMENTS:
- Line 1: ```json (alone)
- Lines 2-N: Valid JSON only
- Line N+1: ``` (alone)
- NO text before/after block
- NO comments in JSON

**INVALID OUTPUTS - DO NOT DO THIS:**
❌ [Example of what NOT to do]

**VALID OUTPUTS:**
✅ [Example of correct output]
"""
    
    return prompt
```

---

## Prompt Review Checklist

Before deploying a new prompt, verify:

### Format & Structure
- [ ] Has maximum output length constraint
- [ ] Uses standardized format instructions
- [ ] No contradictory instructions (e.g., "no markdown" then "use markdown")
- [ ] Has clear start/end markers for expected output

### Task Definition
- [ ] Uses bounded extraction (NOT "extract ALL")
- [ ] Clear DO/DO NOT sections
- [ ] Specific, actionable instructions
- [ ] Appropriate for task complexity

### Examples & Validation
- [ ] Provides positive examples
- [ ] Provides negative examples
- [ ] Shows expected output format
- [ ] Explains edge cases

### Model Considerations
- [ ] Has model-specific instructions (if needed)
- [ ] Tested with target model(s)
- [ ] Accounts for model verbosity/terseness
- [ ] Appropriate context window usage

### Error Handling
- [ ] Handles missing information gracefully
- [ ] Specifies fallback behavior
- [ ] Clear confidence scoring guidance

---

## Current Prompt Locations

| Prompt | File | Function | Status |
|--------|------|----------|--------|
| **DocumentParser** | `fairifier/utils/llm_helper.py` | `extract_document_info()` | ⚠️ Needs fixes |
| **PackageSelection** | `fairifier/agents/knowledge_retriever_llm_methods.py` | `llm_select_relevant_packages()` | ⚠️ Needs fixes |
| **FieldSelection** | `fairifier/agents/knowledge_retriever_llm_methods.py` | `llm_select_fields_from_package()` | ⚠️ Needs fixes |
| **JSONGenerator** | `fairifier/utils/llm_helper.py` | `generate_complete_metadata()` | ⚠️ Needs fixes |
| **Critic** | `fairifier/agents/critic.py` | `_judge_with_rubric()` | ⚠️ Needs fixes |

---

## Known Issues & Fixes

### Issue 1: Oversized Responses (CRITICAL)

**Problem**: qwen3:30b generates 192KB responses (expected: <20KB)

**Root Cause**: No output length constraints in prompts

**Fix**: Add to ALL prompts:
```markdown
**CRITICAL CONSTRAINT - READ CAREFULLY:**
- Maximum response size: 20,000 characters
- If your response exceeds this, you MUST truncate
```

**Status**: ⏳ Pending implementation

### Issue 2: Format Inconsistency (CRITICAL)

**Problem**: Different format instructions across prompts cause parsing failures

**Root Cause**: No standardized format instruction

**Fix**: Use `OUTPUT FORMAT - STANDARD v1.0` everywhere

**Status**: ⏳ Pending implementation

### Issue 3: Verbose Extraction (HIGH)

**Problem**: "Extract ALL" leads to including everything

**Root Cause**: Ambiguous boundaries

**Fix**: Replace with bounded extraction (DO/DO NOT lists)

**Status**: ⏳ Pending implementation

---

## Testing Prompts

### Unit Testing

```python
def test_prompt_length_control():
    """Test that prompts enforce length limits."""
    result = await extract_document_info(long_document)
    assert len(json.dumps(result)) < 25000, "Response exceeds 25KB limit"

def test_prompt_format_consistency():
    """Test that all prompts use consistent format instructions."""
    prompts = get_all_prompts()
    format_sections = [extract_format_section(p) for p in prompts]
    assert all(f == format_sections[0] for f in format_sections)
```

### Integration Testing

```python
@pytest.mark.parametrize("model", ["qwen3:30b", "gpt-4", "llama3"])
def test_model_compatibility(model):
    """Test prompts work with different models."""
    result = run_workflow_with_model(model, test_document)
    assert result["success"]
    assert len(result["response"]) < 30000
```

---

## Prompt Versioning

### Version Format
`PROMPT_NAME_v{major}.{minor}_{date}`

Example: `DOCUMENT_PARSER_v1.0_20260129`

### When to Increment
- **Major**: Breaking changes (output format, required fields)
- **Minor**: Improvements (wording, examples, constraints)

### Version Tracking
```python
PROMPT_VERSIONS = {
    "document_parser": "v1.0_20260129",
    "package_selection": "v1.0_20260129",
    "field_selection": "v1.0_20260129",
    "json_generator": "v1.0_20260129",
    "critic": "v1.0_20260129"
}
```

---

## Model-Specific Considerations

### Qwen Models (qwen2, qwen3)
- **Strength**: Fast, knowledgeable
- **Weakness**: Verbose, may ignore "JSON-only" instructions
- **Prompt Strategy**:
  - Emphasize output length limits
  - Add "NO explanatory text" repeatedly
  - Use strict format with markdown blocks
  - Provide negative examples of verbosity

### GPT-4 / GPT-4-turbo
- **Strength**: Follows instructions precisely
- **Weakness**: Expensive, slower
- **Prompt Strategy**:
  - Can use more concise instructions
  - Raw JSON output works well
  - Complex reasoning tasks suitable

### Llama 3 / Llama 3.1
- **Strength**: Good JSON formatting
- **Weakness**: Less knowledgeable, may hallucinate
- **Prompt Strategy**:
  - Emphasize "use document only"
  - Provide clear examples
  - Simpler tasks preferred

### Claude (Anthropic)
- **Strength**: Excellent at following boundaries
- **Weakness**: Different API, prompt format
- **Prompt Strategy**:
  - Use XML tags for structure
  - Clear sections work well
  - Long contexts supported

---

## Best Practices Summary

### ✅ DO
1. Always specify maximum output length
2. Use standardized format instructions
3. Provide DO/DO NOT lists
4. Include positive and negative examples
5. Add model-specific instructions when needed
6. Test with target models before deployment
7. Use bounded extraction (not "extract ALL")
8. Version your prompts

### ❌ DON'T
1. Use "extract ALL" without boundaries
2. Mix contradictory format instructions
3. Skip output length constraints
4. Forget to test with actual models
5. Use vague task descriptions
6. Omit examples
7. Assume all models behave the same

---

## Resources

- [PROMPTS_AUDIT_REPORT.md](../../PROMPTS_AUDIT_REPORT.md) - Comprehensive audit (Jan 2026)
- [LLM_INTEGRATION_GUIDE.md](../LLM_INTEGRATION_GUIDE.md) - Model integration guide
- [Critic Rubric](critic_rubric.yaml) - Evaluation criteria

---

## Changelog

### v1.0 - 2026-01-29
- Initial version based on comprehensive prompts audit
- Identified 3 critical issues causing workflow failures
- Established standardized prompt template
- Created review checklist and testing guidelines

---

**Maintained by**: FAIRiAgent Development Team  
**Next Review**: 2026-03-01 (or after major model updates)
