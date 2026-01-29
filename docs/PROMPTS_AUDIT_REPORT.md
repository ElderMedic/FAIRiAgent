# FAIRiAgent Prompts Audit Report

**Date**: 2026-01-29  
**Auditor**: FAIRiAgent Development Team  
**Scope**: All LLM prompts in the project

---

## Executive Summary

### Overall Status: ⚠️ **NEEDS IMPROVEMENT**

| Aspect | Rating | Status |
|--------|--------|--------|
| **Format Specification** | 🟡 Medium | Partially specified, inconsistencies observed |
| **Boundary Definition** | 🟢 Good | Clear task boundaries in most prompts |
| **Input/Output Clarity** | 🟡 Medium | Mixed - some excellent, some vague |
| **Model Adaptation** | 🔴 Poor | Not optimized for specific model capabilities |
| **Error Handling** | 🟢 Good | Robust fallback strategies |
| **Consistency** | 🟡 Medium | Format instructions inconsistent across prompts |

**Key Finding**: The primary issue causing workflow failures (192KB responses with embedded essays) is **lack of strict output length control and format enforcement** in prompts, especially for models like qwen3:30b-instruct that don't follow JSON-only instructions well.

---

## 1. DocumentParser Prompts

### Location
- `fairifier/utils/llm_helper.py` → `extract_document_info()` (lines 1050-1300)

### Prompt Analysis

#### ✅ Strengths
1. **Excellent Adaptability**
   - Detects document type automatically (research paper, proposal, DMP, SOP)
   - Different extraction strategies per type
   - Flexible schema that adapts to content

2. **Clear Task Definition**
   ```markdown
   **Your task:** 
   1. FIRST identify what type of document this is
   2. THEN extract ALL relevant information
   3. DO NOT force a paper structure if it doesn't fit
   ```

3. **Format Examples Provided**
   - Multiple examples for different document types
   - Shows expected JSON structure

#### ⚠️ Issues

**CRITICAL: No Output Length Control**
```python
# Missing constraints:
- No "Maximum response length: 20KB"
- No "Extract ONLY key information, not full text"
- No "Limit each field to 200 characters"
```

**CRITICAL: Ambiguous "Extract ALL"**
```markdown
**Your task:**
THEN extract ALL relevant information appropriate for that document type
```
↓ Result: LLM includes EVERYTHING (192KB response)

**Inconsistent Format Instructions**
```markdown
# Version 1 (Structured Markdown):
**OUTPUT FORMAT - CRITICAL:**
You MUST wrap your JSON response in markdown code blocks with ```json prefix

# Version 2 (Plain Text):
Return a JSON object with clear, descriptive field names.
```

#### 🔴 Critical Problems Causing Failure

**Problem 1: No Length Limits**
- Prompt says "extract ALL" without boundaries
- Model interprets as "include everything"
- Result: 192KB response (179KB extraneous content)

**Problem 2: Encourages Verbosity**
```markdown
**Best practices:**
- Extract numerical data with units preserved
- Capture hierarchical relationships naturally present
- Include both human-readable descriptions AND structured identifiers
```
↓ Interpreted as: "Be as comprehensive as possible"

**Problem 3: No Output Size Warning**
```markdown
# Should add:
**CRITICAL CONSTRAINT:**
- Maximum response size: 20,000 characters (~5,000 tokens)
- If document is long, extract ONLY the essential metadata
- DO NOT include full text, paragraphs, or detailed explanations
- Each field value should be concise (< 200 chars unless specific need)
```

---

## 2. KnowledgeRetriever Prompts

### Location
- `fairifier/agents/knowledge_retriever_llm_methods.py`
  - `llm_select_relevant_packages()` (lines 68-133)
  - `llm_select_fields_from_package()` (lines 259-375)

### Prompt 1: Package Selection

#### ✅ Strengths
1. **Clear Selection Criteria**
   ```markdown
   **Selection principles:**
   1. Match packages to research domain
   2. Select domain-specific packages
   3. Select method-specific packages
   4. Select at least 1 package
   5. There is no upper limit
   ```

2. **Step-by-Step Guidance**
   ```markdown
   **Think step by step:**
   1. What is the research domain?
   2. What type of samples?
   3. What methods are used?
   4. Which packages match?
   ```

3. **Explicit Format Specification**
   ```markdown
   **OUTPUT FORMAT - CRITICAL:**
   Return ONLY valid JSON. Do NOT include:
   - Markdown code blocks (no ```json or ```)
   - Explanatory text before or after
   - Comments or notes
   - Any other content
   ```

#### ⚠️ Issues

**CRITICAL: Contradictory Format Instructions**
```markdown
# System prompt says:
Return ONLY valid JSON. Do NOT include:
- Markdown code blocks (no ```json or ```)

# User prompt says:
- If you must use markdown, use ```json code blocks (but raw JSON is preferred)
```
↓ Result: Confusion for LLM, inconsistent outputs

**No Output Validation Examples**
```python
# Should add:
**VALID OUTPUT:**
{"selected_packages": ["soil", "GSC MIMAGS"], "reasoning": "..."}

**INVALID OUTPUT:**
Here are my thoughts... ```json {"selected_packages": [...]} ```
^ This will be rejected - no text before JSON
```

### Prompt 2: Field Selection

#### ✅ Strengths
1. **Excellent ISA Context**
   ```markdown
   **ISA Sheet Level:** {isa_sheet.upper()}
   **ISA Level Description:** {isa_description}
   ```

2. **Clear Search Capabilities**
   - Explains `/api/terms` search
   - Explains field search across packages
   - Shows when to use each

3. **Flexible Selection**
   ```markdown
   Select at least 5 fields. Choose as many as needed.
   There is no upper limit - use your judgment.
   ```

#### ⚠️ Issues

**Same Contradictory Format Issue**
- System: "No markdown blocks"
- User: "If you must use markdown..."

**No Examples of terms_to_search**
```python
# Should add:
**EXAMPLE:**
{
  "selected_fields": ["soil pH", "temperature"],
  "terms_to_search": ["soil moisture", "conductivity"],
  "reasoning": "Document mentions these but not in list"
}
```

---

## 3. JSONGenerator Prompts

### Location
- `fairifier/utils/llm_helper.py` → `generate_complete_metadata()` (lines 1620-1770)

### Prompt Analysis

#### ✅ Strengths
1. **Explicit Field Count Requirement**
   ```markdown
   **IMPORTANT:**
   - You MUST return a JSON array with exactly {len(selected_fields)} fields
   - Do NOT skip any fields
   ```

2. **ISA Level Guidance**
   ```markdown
   **CRITICAL REQUIREMENTS:**
   4. **Investigation-level fields** ({count} fields): Must generate values...
   5. **Study-level fields** ({count} fields): Must generate values...
   ```

3. **Clear Evidence Requirement**
   ```markdown
   **For each field, provide:**
   - field_name: MUST match exactly
   - value: The actual metadata value
   - evidence: Where/how you determined this
   - confidence: Float 0.0-1.0
   ```

#### ⚠️ Issues

**CRITICAL: No Output Length Control**
```python
# Missing:
**CRITICAL CONSTRAINT:**
- Maximum response size: 50,000 characters
- Each field value: < 500 characters
- Evidence: < 200 characters
- DO NOT include full paragraphs or quotes
```

**CRITICAL: "Extract or Generate" Ambiguity**
```markdown
**Your task:** For EACH field, extract or generate an appropriate value
```
↓ Result: LLM might generate verbose explanations

**Document Excerpt Too Small**
```python
document_text[:3000]  # Only 3KB context
```
↓ For 57KB document, misses critical information

#### 🔴 Critical Problems

**Problem: Encourages Long Values**
```markdown
**Principles:**
1. Extract values directly from document when possible
2. Generate appropriate values when information is implicit
3. Provide clear evidence/provenance for each value
```
↓ "Provide clear evidence" interpreted as "provide full quotes"

**Problem: No Negative Examples**
```python
# Should add:
**INVALID OUTPUTS - DO NOT DO THIS:**
❌ "evidence": "According to the methods section paragraph 3, the researchers conducted a comprehensive analysis of soil samples collected from multiple sites across the region over a period of 18 months, using standardized protocols..."  (TOO LONG)

✅ "evidence": "Methods section: soil samples from multiple sites, 18-month study"  (GOOD)
```

---

## 4. Critic Prompts

### Location
- `fairifier/agents/critic.py` → `_judge_with_rubric()` (lines 411-437)

### Prompt Analysis

#### ✅ Strengths
1. **Clear Rubric Structure**
   ```markdown
   # Node: {node_key}
   Goal: {description}
   
   ## Evaluation Context
   {evaluation_content}
   
   ## Rubric
   {rubric_block}
   ```

2. **JSON Schema Reference**
   ```markdown
   Use the JSON schema described in the system instructions.
   ```

3. **Score-Based Decision**
   - Thresholds clearly defined in rubric YAML
   - Code enforces thresholds (ignores LLM's decision field)

#### ⚠️ Issues

**No Format Specification in Prompt**
```markdown
# Current:
Use the JSON schema described in the system instructions.

# Should be explicit:
**OUTPUT FORMAT:**
Return ONLY a JSON object:
{
  "score": 0.0-1.0,
  "critique": "concise summary",
  "issues": ["issue1", "issue2"],
  "suggestions": ["suggestion1", "suggestion2"]
}
```

**No Output Size Limit**
```python
# Should add:
**CRITICAL CONSTRAINTS:**
- critique: < 200 characters
- Each issue: < 100 characters
- Each suggestion: < 150 characters
- Total response: < 2,000 characters
```

---

## 5. Cross-Cutting Issues

### Issue 1: Inconsistent Format Instructions ❌

**Problem**: Every prompt has different format instructions

| Prompt | Format Instruction |
|--------|-------------------|
| DocumentParser | "MUST wrap in ```json```" |
| PackageSelection | "Do NOT include ```json" THEN "If you must use markdown..." |
| FieldSelection | "Do NOT include ```json" THEN "If you must use markdown..." |
| JSONGenerator | "Prefer raw JSON without markdown" |

**Impact**: LLM receives contradictory signals

**Solution**: Standardize format instructions across ALL prompts

```markdown
**STANDARD FORMAT INSTRUCTION (Version A - Strict JSON):**

**OUTPUT FORMAT - CRITICAL:**
Return ONLY a valid JSON object/array. 
- DO NOT wrap in markdown code blocks (no ```json```)
- DO NOT include any text before or after the JSON
- DO NOT include comments (no // in JSON)
- Return the raw JSON content only

Example: {"key": "value"}
NOT: ```json\n{"key": "value"}\n```
```

OR

```markdown
**STANDARD FORMAT INSTRUCTION (Version B - Markdown JSON):**

**OUTPUT FORMAT - CRITICAL:**
Wrap your JSON in markdown code blocks:

```json
{
  "your": "content"
}
```

Requirements:
- Start with ```json on its own line
- End with ``` on its own line
- NO text before or after the code block
- NO comments inside JSON
```

### Issue 2: No Output Length Controls ❌

**Problem**: Not a single prompt specifies maximum output length

**Impact**: qwen3:30b generates 192KB responses (expected: <20KB)

**Solution**: Add length limits to EVERY prompt

```markdown
**CRITICAL CONSTRAINTS:**
- Maximum total response: 20,000 characters (~5,000 tokens)
- Each field value: < 500 characters
- Evidence/reasoning: < 200 characters
- If you need to truncate, prioritize essential information
```

### Issue 3: No Model-Specific Adaptations ❌

**Problem**: Same prompt for all models (GPT-4, qwen3:30b, llama3, Claude)

**Reality**: Different models have different strengths/weaknesses

| Model | Strength | Weakness |
|-------|----------|----------|
| GPT-4 | Follows instructions precisely | Expensive |
| qwen3:30b | Fast, knowledgeable | Verbose, ignores "JSON-only" |
| llama3 | Good JSON formatting | Less knowledgeable |
| Claude | Excellent at boundaries | Different API |

**Solution**: Add model-specific prompt variants

```python
def get_format_instruction(model_name: str) -> str:
    if "qwen" in model_name.lower():
        return """
**CRITICAL FOR YOUR MODEL:**
You tend to be verbose. For this task:
- Maximum response: 20KB
- NO explanatory essays
- NO academic writing
- ONLY JSON content
- Keep values concise
"""
    elif "gpt" in model_name.lower():
        return """
**OUTPUT FORMAT:**
Return only valid JSON. No markdown blocks needed.
"""
    # ... other models
```

### Issue 4: Ambiguous "Extract ALL" ❌

**Problem**: "Extract ALL relevant information" misinterpreted

**Example from DocumentParser**:
```markdown
**Your task:**
THEN extract ALL relevant information appropriate for that document type
```

**Impact**: LLM extracts EVERYTHING, including full paragraphs

**Solution**: Replace with bounded extraction

```markdown
**Your task:**
Extract the ESSENTIAL metadata for this document type.

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
- Methodology details beyond key parameters
```

---

## 6. Recommendations by Priority

### 🔴 Critical (Fix Immediately)

#### 1. Add Output Length Limits to ALL Prompts
```markdown
**CRITICAL CONSTRAINT - READ CAREFULLY:**
- Maximum response size: 20,000 characters
- If your response exceeds this, you MUST truncate
- Prioritize essential information over completeness
- Use concise language
```

**Impact**: Prevents 192KB responses  
**Effort**: Low (copy-paste to all prompts)  
**Urgency**: HIGH (causes workflow failures)

#### 2. Standardize Format Instructions
Choose ONE format (recommend: markdown with ```json) and use everywhere

```markdown
**OUTPUT FORMAT - STANDARD (v1.0):**
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

**Impact**: Consistent parsing, fewer errors  
**Effort**: Low (replace all format sections)  
**Urgency**: HIGH (improves reliability)

#### 3. Replace "Extract ALL" with Bounded Instructions
```markdown
# Before:
extract ALL relevant information

# After:
extract ONLY the essential metadata (identifiers, structured data, key relationships)
DO NOT extract full text, paragraphs, or detailed descriptions
```

**Impact**: Prevents verbose responses  
**Effort**: Low (find-replace + review)  
**Urgency**: HIGH (root cause of verbosity)

### 🟡 Important (Fix Soon)

#### 4. Add Field-Level Length Limits
```markdown
**Field Value Constraints:**
- Title: 10-200 characters
- Abstract/Summary: 100-500 characters
- Evidence: 50-200 characters
- Single value (ID, name): 5-100 characters
```

#### 5. Add Negative Examples
```markdown
**INVALID OUTPUTS - DO NOT DO THIS:**
❌ "value": "According to the methods section..."  (explanation, not value)
❌ "evidence": "The researchers conducted..." (too long)
❌ Response includes: "Here are my findings..." (extra text)

**VALID OUTPUTS:**
✅ "value": "Soil microbiome diversity"
✅ "evidence": "Methods section, paragraph 2"
```

#### 6. Add Model-Specific Instructions
```python
# In llm_helper.py
def _get_model_specific_constraints(self) -> str:
    """Return model-specific prompt additions."""
    provider = config.llm_provider.lower()
    model = config.fairifier_llm_model.lower()
    
    if "qwen" in model:
        return """
**IMPORTANT FOR YOUR MODEL:**
- You tend to generate long responses. Keep this one SHORT.
- Maximum: 20,000 characters
- NO academic essay writing
- NO explanatory paragraphs
- ONLY structured data extraction
"""
    # ... other models
```

### 🟢 Nice to Have (Future Improvement)

#### 7. Add Output Validation Examples
#### 8. Add Structured Output Mode (if supported by model)
#### 9. Add Progressive Truncation Strategy
#### 10. Add Prompt Version Tracking

---

## 7. Specific Fixes for Observed Failures

### Fix for 192KB DocumentParser Response

**Root Cause**: No length limit + "extract ALL" + verbose model

**Fix**:
```python
# In extract_document_info(), line ~1098
system_prompt = """You are an expert at extracting ESSENTIAL metadata from research documents.

**CRITICAL CONSTRAINTS - READ FIRST:**
1. Maximum response size: 20,000 characters (~5,000 tokens)
2. Extract ONLY key structured metadata
3. DO NOT include full text, paragraphs, or detailed explanations
4. Each field value: concise (< 200 chars unless specifically needed)
5. If document is long, extract SUMMARY information, not everything

**Document Format:** [... rest of prompt ...]
"""
```

### Fix for JSON Parse Errors

**Root Cause**: Contradictory format instructions + markdown blocks

**Fix**:
```python
# Standardize to ONE format across all prompts
STANDARD_FORMAT_INSTRUCTION = """
**OUTPUT FORMAT - MANDATORY:**

Wrap your JSON response in markdown code blocks EXACTLY like this:

```json
{
  "your": "content"
}
```

RULES:
- First line: ```json (nothing else on this line)
- Middle lines: Valid JSON only (no comments)
- Last line: ``` (nothing else on this line)
- NO explanatory text before or after the code block
- NO markdown, no prose, no commentary

INVALID:  "Here is the result: ```json..."
VALID:    "```json\n{...}\n```"
"""
```

---

## 8. Testing Recommendations

### Test 1: Length Control
```python
# Test that prompts enforce length limits
def test_prompt_length_limit():
    # Run with deliberately long document
    result = await extract_document_info(long_document)
    assert len(result) < 25000, "Response exceeds 25KB limit"
```

### Test 2: Format Consistency
```python
def test_format_consistency():
    # All prompts should have identical format sections
    prompts = [
        extract_document_info_prompt,
        package_selection_prompt,
        field_selection_prompt,
        metadata_generation_prompt
    ]
    format_instructions = [extract_format_section(p) for p in prompts]
    assert all(f == format_instructions[0] for f in format_instructions)
```

### Test 3: Model Compatibility
```python
# Test with different models
@pytest.mark.parametrize("model", ["qwen3:30b", "gpt-4", "llama3"])
def test_model_compatibility(model):
    result = run_workflow_with_model(model, test_document)
    assert result["success"]
    assert len(result["response"]) < 30000
```

---

## 9. Summary Scorecard

| Prompt | Format | Boundaries | I/O Clarity | Length Control | Model Adapt | Grade |
|--------|--------|------------|-------------|----------------|-------------|-------|
| **DocumentParser** | 🟡 | 🟢 | 🟢 | 🔴 | 🔴 | C |
| **PackageSelection** | 🟡 | 🟢 | 🟢 | 🔴 | 🔴 | C+ |
| **FieldSelection** | 🟡 | 🟢 | 🟢 | 🔴 | 🔴 | C+ |
| **JSONGenerator** | 🟡 | 🟢 | 🟢 | 🔴 | 🔴 | C |
| **Critic** | 🟡 | 🟢 | 🟡 | 🔴 | 🔴 | C |
| **Overall** | 🟡 | 🟢 | 🟢 | 🔴 | 🔴 | **C** |

**Legend**: 🟢 Good | 🟡 Needs Work | 🔴 Critical Issue

---

## 10. Implementation Checklist

### Immediate Actions (This Week)
- [ ] Add output length limits to all 5 main prompts
- [ ] Standardize format instructions (choose one variant)
- [ ] Replace "extract ALL" with bounded extraction
- [ ] Test with qwen3:30b to verify fixes

### Short-Term (Next 2 Weeks)
- [ ] Add field-level length constraints
- [ ] Add negative examples to all prompts
- [ ] Implement model-specific prompt variants
- [ ] Update prompt testing suite

### Long-Term (Next Month)
- [ ] Add structured output mode support
- [ ] Implement prompt versioning system
- [ ] Create prompt optimization guide
- [ ] Add comprehensive prompt test coverage

---

**Report Conclusion**: The prompts are well-structured with clear task definitions and good adaptability, BUT lack critical output controls (length limits, strict formatting) that cause failures with verbose models like qwen3:30b. Implementing the recommended fixes will significantly improve reliability and success rate.

**Priority**: 🔴 **HIGH** - Current prompts cause workflow failures with certain LLMs

**Estimated Fix Time**: 4-8 hours for all critical fixes

**Expected Impact**: 80%+ reduction in JSON parsing errors and oversized responses

---

**Generated**: 2026-01-29  
**Version**: 1.0  
**Pages**: 20  
**Reviewed Prompts**: 5 major prompts across 3 modules
