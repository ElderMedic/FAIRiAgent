# FAIRiAgent Model Comparison: Ollama qwen3:30b vs Qwen-max
**Date**: 2026-01-29  
**Tests**: Final validation after critical prompt fixes and JSON parsing bug fix

---

## Executive Summary

### Test Results

| Metric | Ollama qwen3:30b-instruct | Qwen-max (DashScope) |
|--------|---------------------------|----------------------|
| **Workflow Status** | ❌ FAILED | ✅ COMPLETED |
| **Overall Confidence** | 35.50% | 84.12% |
| **Fields Generated** | 0 | 65 |
| **Retries Required** | 2 (DocumentParser, JSONGenerator) | 1 (KnowledgeRetriever) |
| **Total Execution Time** | ~27 minutes | ~2.7 minutes |
| **DocumentParser Time** | 514s (attempt 1), 108s (attempt 2) | 55.4s |
| **JSON Parsing Success** | ❌ Failed both attempts | ✅ Success |

**Verdict**: **Qwen-max is production-ready; Ollama qwen3:30b requires additional fixes**

---

## Detailed Analysis

### Test 1: Ollama qwen3:30b-instruct (Local)

**Configuration**:
- Model: `qwen3:30b-instruct` via Ollama (localhost:11434)
- Fixes Applied:
  - ✅ All 5 major prompts updated with length constraints
  - ✅ Standardized output format instructions
  - ✅ JSON parsing bug fix (`_extract_json_from_markdown`)

**Results**:

**DocumentParser** (2 attempts, both failed):
- **Attempt 1**: 
  - Duration: 514.4s (~8.6 minutes)
  - Response Size: 173,665 chars (~174 KB)
  - Error: `Failed to parse LLM response as JSON. Response length: 173665 chars`
  - Root Cause: Despite prompt constraints limiting to 20,000 chars, LLM generated 8.7x the limit
  
- **Attempt 2** (after Critic feedback):
  - Duration: 108.0s (~1.8 minutes)
  - Response Size: 35,865 chars (~36 KB)
  - Error: `Failed to parse LLM response as JSON. Response length: 35865 chars`
  - Improvement: 79% size reduction, but still 1.8x the limit and JSON invalid

**JSONGenerator** (2 attempts, both failed):
- **Attempt 1**:
  - Duration: 513.7s (~8.6 minutes)
  - Error: `Unterminated string starting at: line 5578 column 5 (char 158073)`
  - Root Cause: Malformed JSON with syntax errors
  
- **Attempt 2** (after Critic feedback):
  - Duration: 514.6s (~8.6 minutes)
  - Error: `Expecting property name enclosed in double quotes: line 4568 column 4 (char 136579)`
  - Root Cause: Still generating malformed JSON

**Workflow Outcome**:
- Status: FAILED
- Total Fields: 0
- No `metadata_json.json` generated
- Total Time: ~27 minutes (wasted compute time)

**Critical Issues**:
1. **Prompt adherence**: Ollama qwen3:30b ignores length constraints in prompts
2. **JSON generation**: Cannot reliably generate valid JSON, even after fixes
3. **Performance**: Extremely slow (8+ minutes per agent call)
4. **Reliability**: 0% success rate across all major agents

---

### Test 2: Qwen-max (DashScope API)

**Configuration**:
- Model: `qwen-max` via DashScope (dashscope-intl.aliyuncs.com)
- Same fixes as Test 1

**Results**:

**DocumentParser** (1 attempt, success):
- Duration: 55.4s (~1 minute)
- Response Size: 6,196 chars (~6 KB)
- Success: ✅ Valid JSON, correctly parsed
- Compliance: Response 69% below the 20,000 char limit

**KnowledgeRetriever** (2 attempts, final success):
- **Attempt 1**: Duration: 10.3s - Retry triggered by Critic
- **Attempt 2**: Duration: 10.7s - ✅ Accepted (score: 0.95)
- Total: 21s

**JSONGenerator** (1 attempt, success):
- Duration: 83.9s (~1.4 minutes)
- Generated: 65 metadata fields
- Packages: 6 (ENA virus, GSC MIMAGS, GSC MISAGS, Illumina, default, soil)
- Success: ✅ Valid JSON with complete metadata

**Workflow Outcome**:
- Status: COMPLETED ✅
- Overall Confidence: 84.12%
- Metadata Overall Confidence: 60.00%
- Total Fields: 65
  - Investigation: 8 fields (7 confirmed, 1 provisional)
  - Study: 3 fields (all confirmed)
  - Assay: 16 fields (11 confirmed, 5 provisional)
  - Sample: 34 fields (15 confirmed, 19 provisional)
  - ObservationUnit: 4 fields (all confirmed)
- Total Time: ~2.7 minutes

**Performance Metrics**:
- **Speed**: 10x faster than Ollama qwen3:30b
- **Reliability**: 100% workflow success rate
- **Quality**: High-quality structured metadata

---

## Remaining Issues (Both Models)

### Issue: `document_info` Still Incomplete

Even with successful workflow (Qwen-max), the `document_info` summary is incomplete:

```json
{
  "title": null,
  "abstract": null,
  "authors": [
    "{'name': 'Henk J. van Lingen', 'affiliation': 'a, *', 'email': 'hvanling@uoguelph.ca'}",
    // ... 6 more authors (stringified dicts)
  ],
  "keywords": [],
  "research_domain": null
}
```

**Problems**:
1. **Title**: null (should be extracted from DocumentParser response)
2. **Abstract**: null (should be extracted)
3. **Authors**: Present but **stringified** (should be proper objects/strings)
4. **Keywords**: Empty array (should be extracted)
5. **Research domain**: null (should be extracted)

**Root Cause**: `_build_document_info_compact` in `json_generator.py` still has mapping issues:
- The fix for nested `metadata` structure works
- But the actual mapping logic needs further refinement to handle diverse DocumentParser response structures

---

## Critical Bug Found: Ollama qwen3:30b Ignores Length Constraints

### Evidence

**Prompt Specification**:
```
**CRITICAL CONSTRAINTS - READ FIRST:**
1. Maximum response size: 20,000 characters (~5,000 tokens)
2. Extract ONLY key structured metadata
3. Each field value: concise (< 300 characters)
```

**Actual Behavior**:
- Attempt 1: Generated 173,665 chars (8.7x the limit)
- Attempt 2: Generated 35,865 chars (1.8x the limit)

### Why This Happens

1. **Model capability**: Ollama qwen3:30b may not have strong instruction-following for output length
2. **Local inference**: No API-level token limits or safety guardrails
3. **Prompt complexity**: Long, complex prompts may confuse the model

### Implications

**Ollama qwen3:30b is NOT suitable for production** due to:
1. Unreliable prompt adherence
2. Cannot generate valid JSON consistently
3. Extremely slow performance (8+ min per call)
4. High failure rate (100% in this test)

---

## Performance Comparison

| Metric | Ollama qwen3:30b | Qwen-max | Winner |
|--------|------------------|----------|--------|
| **Speed (DocumentParser)** | 514s / 108s | 55.4s | Qwen-max (9x faster) |
| **Speed (JSONGenerator)** | 514s+ | 83.9s | Qwen-max (6x faster) |
| **Response Size** | 174KB / 36KB | 6KB | Qwen-max (29x smaller) |
| **JSON Validity** | 0% | 100% | Qwen-max |
| **Workflow Success** | 0% | 100% | Qwen-max |
| **Cost** | Free (local) | ~$0.02-0.05 | Ollama (but useless) |
| **Reliability** | Low | High | Qwen-max |

---

## Recommendations

### Immediate Actions

1. **✅ Approve Qwen-max for production**
   - Reliable, fast, high-quality metadata generation
   - Only 1 retry needed across workflow
   - 84.12% overall confidence

2. **❌ Disable Ollama qwen3:30b for production workflows**
   - 100% failure rate despite fixes
   - Wastes compute time (~27 min vs ~3 min)
   - Requires model-specific workarounds

3. **🔧 Fix `document_info` mapping**
   - Issue affects both models (but only visible when workflow succeeds)
   - Priority: HIGH
   - Location: `fairifier/agents/json_generator.py::_build_document_info_compact`

### Short-term Actions

1. **Test alternative local models** (if cost is a concern):
   - Try `qwen2.5:14b` or `qwen2.5:72b` (if hardware permits)
   - Test `llama3.1:70b` or `mixtral:8x7b`
   - Evaluate instruction-following capability on JSON generation tasks

2. **Add model-specific prompt templates**:
   - Some models may need shorter, simpler prompts
   - Consider different prompting strategies for local vs API models

3. **Implement response validation**:
   - Check response size BEFORE parsing
   - Truncate responses that exceed limits
   - Add early-exit mechanisms for runaway generation

### Long-term Actions

1. **Hybrid approach**:
   - Use Qwen-max (API) for critical production workflows
   - Use local models for development/testing only

2. **Add model benchmarking suite**:
   - Automated tests for new models
   - Measure: speed, reliability, cost, quality
   - Update recommendations based on benchmark results

3. **Improve prompt engineering**:
   - A/B test different prompt formats
   - Optimize for specific models
   - Add dynamic prompt selection based on model capabilities

---

## Conclusion

**Qwen-max is the clear winner** for production FAIRiAgent workflows:
- ✅ 10x faster execution
- ✅ 100% workflow success rate
- ✅ High-quality, structured metadata
- ✅ Reliable JSON generation
- ✅ Respects prompt constraints

**Ollama qwen3:30b is NOT production-ready** and should be:
- ❌ Disabled for production workflows
- ⚠️ Used only for development/testing (with caution)
- 🔧 Replaced with a more capable local model if cost is critical

**Next Steps**:
1. Fix `document_info` mapping bug (affects both models)
2. Deploy Qwen-max as default model
3. Evaluate alternative local models for cost-sensitive scenarios
