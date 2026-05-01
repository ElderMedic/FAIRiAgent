# Upstream Candidate Merging — Developer Guide

This document describes the **upstream candidate merging** architecture
introduced in v1.4.0.  It complements
[SOURCE_GROUNDING_ARCHITECTURE.md](SOURCE_GROUNDING_ARCHITECTURE.md)
and is aimed at developers modifying the `JSONGeneratorAgent` or the grounding
pipeline.

---

## Problem this solves

Prior to v1.4.0, the `JSONGeneratorAgent` received field evidence snippets from
multiple sources (PDF manuscript + Excel sheets) as raw text and passed them
directly into a long generation prompt.  The LLM then had to choose values
unassisted, often picking a low-quality or outlier snippet simply because it
appeared first in the context window.  After generation, a post-check attempted
to downgrade fields lacking a source citation — but the regex used for citation
recognition was duplicated in three places (`json_generator.py` ×2 and
`metadata_json_format.py`), and was too narrow, causing widespread false
provisional downgrades.

The combined effect: 0 / 55 fields were source-grounded in a real multi-file
run.

---

## Architecture

### 1. Shared grounding constants (`fairifier/utils/grounding.py`)

The regex patterns are now defined once:

```python
from fairifier.utils.grounding import SOURCE_REF_PATTERN, SOURCE_TABLE_PATTERN
```

- **`SOURCE_REF_PATTERN`**: matches any evidence string that contains a source
  citation — e.g. `source_001: title section`, `source_002 table row 1, column
  'orcid'`, `source_001:250-310 main.md: ...`.
- **`SOURCE_TABLE_PATTERN`**: narrower variant for tabular-specific provenance
  (matches when evidence references `table`, `sheet`, or `column`).

**Rule**: never define a local `re.compile(r"source_\\d+...")` for grounding
decisions.  Always import from this module.

### 2. Field candidates (`FieldCandidate`)

`FieldCandidate` (defined in `json_generator.py`) carries one evidence
candidate per source snippet or table row:

```python
@dataclass
class FieldCandidate:
    field_name: str
    value: str          # raw extracted value
    evidence: str       # "source_001:45-90 main.md: ..." or "source_002 table ..."
    source_id: str      # "source_001"
    source_role: str    # "main_manuscript" | "table" | "supplement"
    relevance_score: float
    confidence: float
    normalized_value: Optional[str] = None   # set by _normalize_candidates_with_llm
```

Candidates are collected during `_build_field_source_evidence_context()` by
searching the preserved source workspace.

### 3. Pre-generation normalization (`_normalize_candidates_with_llm`)

Before the main JSON generation call, all field candidates are batched and sent
to the LLM for normalization:

```
Input:  { "cid_1": "Gene expression profile dynamics of earthworms ...", ... }
Output: { "cid_1": "Gene expression profile dynamics ...", ... }  (concise)
```

This ensures that when two sources say the same thing in different words, they
receive the same `normalized_value` and can be grouped correctly in the next
step.

### 4. Consensus scoring (`_upstream_reconcile_candidates`)

Candidates are grouped by `normalized_value`.  Each group is scored:

```
score = source_role_priority(role)      # main_manuscript=3, table=2, supplement=1
      + agreement_count * 0.5           # more sources agreeing → higher weight
      + relevance_score * 0.3
```

The highest-scoring group provides the **primary candidate**.  All others become
secondary (used only for provenance metadata, not value selection).

### 5. Prompt injection

Pre-reconciled values are appended to the field evidence context before the LLM
call:

```
Pre-reconciled Source Fields (High Confidence):
Use these exact values for the corresponding fields as they represent cross-source consensus:
- study identifier: Diagonal
- investigation title: Gene expression profile dynamics of earthworms ...
```

The LLM is thereby guided to produce the consensus value rather than selecting
an arbitrary source.

### 6. Post-check and downgrade (`_postcheck_source_grounding`)

After generation, fields above `FAIRIFIER_METADATA_SOURCE_REF_MIN_CONFIDENCE`
that still lack a source citation are downgraded.  This is now the **fallback
safety net**, not the primary grounding mechanism.

Since the generation prompt already carries reconciled values with explicit
source IDs, most high-confidence fields naturally include a citation and are
not penalised.

---

## Data flow summary

```
source_workspace (PDF + Excel)
        │
        ▼
_build_field_source_evidence_context()
  → collects FieldCandidate list per field
        │
        ▼
_normalize_candidates_with_llm()      ← batched LLM, sets normalized_value
        │
        ▼
_upstream_reconcile_candidates()      ← groups by normalized_value, scores
        │
        ▼
consensus values injected into generation prompt
        │
        ▼
LLM generates metadata.json fields with source citations
        │
        ▼
_postcheck_source_grounding()         ← safety net for still-uncited fields
  uses SOURCE_REF_PATTERN (shared constant)
        │
        ▼
_compute_source_grounding_summary()   ← statistics block
  uses SOURCE_REF_PATTERN + SOURCE_TABLE_PATTERN (shared constants)
        │
        ▼
validate_source_grounding()           ← validation module, same shared constants
```

---

## Tests

| File | What it covers |
|---|---|
| `tests/test_source_ref_regex.py` | Positive/negative fixture tests for both shared patterns, importing the canonical constants (not a copy) |
| `tests/test_candidate_normalization.py` | Reconciliation determinism; main-manuscript consensus beats table outlier; tie-breaking by relevance |
| `tests/test_source_grounding_e2e.py` | E2E: workspace → field evidence context → grounding summary counters → JSON round-trip |
| `tests/test_field_candidates.py` | FieldCandidate sorting, `_reconcile_candidates`, `_postcheck_source_grounding` enrichment |

Run the targeted suite:

```bash
mamba run -n FAIRiAgent pytest \
  tests/test_source_ref_regex.py \
  tests/test_candidate_normalization.py \
  tests/test_source_grounding_e2e.py \
  tests/test_field_candidates.py \
  -q
```

---

## Guardrails

- **Never redefine the grounding regex locally.**  Any future site that needs to
  classify evidence citations must import from `fairifier.utils.grounding`.
- **Do not widen `SOURCE_REF_PATTERN` without adding negative fixture tests.**
  The pattern must not match vague strings like `"source_002: no sample IDs in
  preview"`.
- **Normalization is best-effort.**  If the LLM normalization call fails or
  returns partial results, the pipeline continues using raw `value` strings.
  Upstream reconciliation gracefully degrades to raw-value grouping.
- **Upstream merging operates on pre-generation context only.**  It does not
  modify the generated `metadata.json` post-hoc; it shapes what the LLM sees.

---

## Next phase: Identifier Completeness and ISA Structural Repair

This phase is **explicitly out of scope** for the current architecture.  Open
issues deferred:

1. `sample identifier` and `observation unit identifier` are absent when source
   documents do not provide FAIR-DS-compatible IDs.  Deterministic derivation
   (e.g., `{study_id}_sample_{row_index}`) is needed.
2. `collection date` may contain multiple semicolon-separated values, violating
   the FAIR-DS single-value constraint.
3. Low-confidence fields (0.1–0.6) for information genuinely absent from the
   paper are expected and correct — do not attempt to fill them by inference.
