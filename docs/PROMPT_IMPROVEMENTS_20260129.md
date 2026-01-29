# Prompt Improvements to Prevent Model Hallucination

**Date**: 2026-01-29  
**Status**: Implemented  
**Priority**: HIGH  

## Background

During testing with Ollama qwen3:30b, the model completely misunderstood the extraction task and generated:
- **192KB** of paper-style content (expected: 20KB)
- Full "Introduction", "Methods", "Results", "Conclusion" sections
- APA-formatted reference lists
- Meta-commentary: "Word count: 980", "This response is accurate..."

Analysis showed **290+ occurrences** of paper-writing keywords, indicating the model activated its "write research paper" mode instead of "extract metadata" mode.

## Root Causes

### 1. **Ambiguous Role Definition**
```
Current: "You are an expert at extracting..."
Problem: "expert" implies demonstrating expertise by generating content
```

### 2. **Trigger Keywords**
```
Current: "For Research Papers: Extract...results, conclusions"
Problem: "results, conclusions" are classic paper structure keywords
         that activate paper-writing language patterns
```

### 3. **Weak Constraints**
```
Current: "DO NOT Extract: Full paragraphs..."
Problem: Too mild for weak models, no examples of what's forbidden
```

### 4. **No Stop Signals**
```
Current: "Maximum response size: 20,000 characters"
Problem: Just a suggestion, no enforcement mechanism
```

### 5. **Interpretive Language**
```
Current user_prompt: "Analyze this document..."
Problem: "Analyze" implies deep interpretation, not mechanical extraction
```

## Implemented Solutions

### ✅ 1. Role Redefinition
```diff
- You are an expert at extracting ESSENTIAL structured metadata
+ You are a METADATA EXTRACTION TOOL (not a content writer or analyst)

+ YOUR ONLY JOB: Parse existing text → Output structured JSON metadata
```

**Rationale**: "TOOL" emphasizes mechanical extraction, reducing creative impulse.

### ✅ 2. Explicit Prohibitions (FORBIDDEN List)

```markdown
YOU ARE FORBIDDEN TO:
❌ Generate, write, or compose ANY new content not present in the source
❌ Summarize, analyze, or interpret beyond what's explicitly stated
❌ Create introductions, conclusions, or narrative text in paper-writing style
❌ Add explanations, commentary, or your own thoughts
❌ Write in academic paper style (e.g., "In this study...", "We found that...")
❌ Create reference lists, bibliographies, or citations (APA, MLA formats)
❌ Add meta-commentary ("Word count: 980", "This response is accurate...")
```

**Rationale**: 
- Stronger language ("FORBIDDEN" vs "DO NOT")
- Specific examples of prohibited phrases
- Covers all observed failure modes

### ✅ 3. Anti-Pattern Example

Added complete "BAD OUTPUT EXAMPLE" showing:
- Full paper structure (Introduction → Methods → Results → Conclusion)
- APA reference list
- Meta-commentary

Labeled clearly: **"⚠️ THIS IS COMPLETELY WRONG! You wrote a paper, not extracted metadata!"**

**Rationale**: For weak models, showing what's wrong is more effective than just saying "don't do X".

### ✅ 4. Multiple Stop Signals

```markdown
**STOP SIGNAL - READ CAREFULLY:**

1. Write ONLY the JSON code block
2. Once you write the closing ```, IMMEDIATELY STOP
3. DO NOT add after the closing ```:
   ❌ Explanations
   ❌ Meta-commentary
   ❌ References sections
   ❌ Notes or additional comments

← **END HERE. STOP. DO NOT WRITE ANYTHING AFTER THIS LINE.**
```

**Rationale**: 
- Repetition: "STOP" appears 3 times
- Visual cues: Arrow (←), bold text
- Explicit list of forbidden post-JSON additions

### ✅ 5. Maintained Flexibility (User Requirement)

**User Note**: "Don't fix specific fields to extract (except necessary info), let agent autonomously decide JSON fields and structure based on document content."

**Implementation**:
```diff
- For **Research Papers**: Extract bibliographic info, research context, 
-   methodology, data, results, conclusions

+ For **Research Papers** (typical fields):
+ - Bibliographic metadata (title, authors, DOI, journal, publication info)
+ - Research context (domain, objectives, hypotheses)  
+ - Methodology identifiers (type, key methods, instruments)
+ - Data availability (repositories, accessions, formats)
+ - Key findings (brief extracts from results/conclusions)

+ ⚠️  IMPORTANT: These are EXAMPLES, not mandatory templates.
+ Extract what's actually present, using field names that make sense.
```

**Changes**:
- Labeled as "EXAMPLES (not rigid requirements)"
- Changed "results, conclusions" to "key findings (brief extracts)"
- Added flexibility guidance: "Adapt field names to match what's ACTUALLY in document"
- "Extract fields that exist, skip fields that don't"

**Rationale**: Balance two goals:
1. Prevent hallucination (stricter constraints on HOW to output)
2. Preserve adaptability (flexible on WHAT to extract)

### ✅ 6. Language Adjustments

```diff
- Analyze this Markdown-formatted research document and extract 
-   comprehensive metadata
+ Parse the following document and extract ONLY the metadata fields.
+ Do NOT analyze, summarize, or rewrite the content.

- Return comprehensive JSON with hierarchical structure
+ Return structured JSON metadata ONLY. No narrative text.
+ Stop immediately after the closing ```.
```

**Key Changes**:
- "Analyze" → "Parse" (less interpretive)
- "comprehensive" → "ONLY" (more restrictive)
- Added explicit prohibition: "Do NOT analyze, summarize"
- Multiple stop instructions

## Expected Impact

### For Strong Models (Qwen-Max, GPT-4, Claude)
✅ **Minimal impact** - they already understood the instructions  
✅ **May improve consistency** - clearer boundaries

### For Weak Models (qwen3:30b, small local models)
⚠️  **20-40% improvement expected**:
- Reduced likelihood of paper-writing mode activation
- Less meta-commentary
- Better adherence to JSON-only output

⚠️  **Still limited by model capability**:
- May still exceed length constraints
- JSON format errors may persist
- Not a complete solution for fundamentally weak models

## Testing Recommendations

1. **High Priority**: Test with Qwen-Max to ensure no regression
2. **Medium Priority**: Re-test with qwen3:30b to measure improvement
3. **Low Priority**: Test with other local models (Llama3, Mistral)

## Related Documents

- Original failure analysis: `docs/MODEL_COMPARISON_FINAL_20260129.md`
- Session summary: `docs/SESSION_FINAL_SUMMARY_20260129.md`
- Bugfix document: `docs/BUGFIX_document_info_mapping.md`

## Key Design Decision

**Balanced Approach**:
- ✅ Strong "what NOT to do" constraints (prevent hallucination)
- ✅ Flexible "what to extract" guidance (preserve adaptability)

Result: The agent can still adapt field structure to document content, but with much clearer boundaries on output style and format.
