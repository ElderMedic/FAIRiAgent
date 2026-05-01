# Source Workspace Developer Handoff

> **Last updated: v1.4.0 (2026-05-02)**
> For the upstream candidate merging architecture added in this version, see
> [UPSTREAM_CANDIDATE_MERGING.md](UPSTREAM_CANDIDATE_MERGING.md).

This note is for coding agents and developers continuing the source-workspace
and metadata-grounding work.  It summarizes the current implementation,
guardrails, tests, and recommended next steps.

---

## Current State (v1.4.0)

Source preservation is implemented in `fairifier/services/source_workspace.py`.
Runs materialize:

- `source_workspace/source_manifest.json`: source ids, paths, methods, roles,
  sizes, and table references.
- `source_workspace/source_workspace.md`: compact inventory for agents and
  reports.
- `source_workspace/sources/source_*.md`: full source text or MinerU markdown.
- `source_workspace/tables/*.jsonl`: full table rows for CSV/TSV/Excel inputs.

Single-file runs use the same structure with one source.  Directory and zip
inputs create one source per supported file.  Files starting with `mineru_` are
excluded to prevent recursive re-ingestion.

JSON metadata generation uses four layers of context (v1.4.0):

1. compact evidence packets,
2. source workspace inventory,
3. field-specific source evidence searched from source text and full table rows,
4. **pre-reconciled upstream candidate values** (new in v1.4.0).

After generation, high-confidence fields are post-checked using
`SOURCE_REF_PATTERN` from `fairifier/utils/grounding.py`.  If a field is above
`FAIRIFIER_METADATA_SOURCE_REF_MIN_CONFIDENCE` but lacks a source citation, it
is downgraded to `FAIRIFIER_METADATA_SOURCE_REF_DOWNGRADE_CONFIDENCE` and kept
provisional.

Verified outcome on the earthworm dataset (v1.4.0, qwen3.6:35b):
- `source_grounded_fields = 38`, `table_backed_fields = 15`,
  `ungrounded_high_confidence_fields = 0`, `confirmed_fields = 31`.

---

## Important Files

- `fairifier/utils/grounding.py` (**new in v1.4.0**): canonical
  `SOURCE_REF_PATTERN` and `SOURCE_TABLE_PATTERN`.  Import from here — never
  redefine locally.
- `fairifier/services/source_workspace.py`: workspace materialization, loading,
  text grep, source span reads, and table search.
- `fairifier/graph/langgraph_app.py`: file ingestion, bundle prioritization, and
  serialized workspace metadata attachment.
- `fairifier/agents/document_parser.py`: deep-agent seed files include workspace
  inventory and source files.
- `fairifier/agents/json_generator.py`: source inventory context, field-specific
  evidence search, upstream candidate merging, and grounding post-check.
- `fairifier/utils/llm_helper.py`: configurable metadata context budgets and
  prompt instructions for source references.
- `fairifier/validation/metadata_json_format.py`: post-generation format checks,
  `validate_source_grounding()` — uses shared grounding constants.
- `fairifier/config.py`: env-driven budgets and feature flags.

---

## Configuration Contract

All new behavior must remain env-configurable.  Use existing config names before
adding new ones.

Key knobs:

- `FAIRIFIER_SOURCE_WORKSPACE_ENABLED`
- `FAIRIFIER_SOURCE_WORKSPACE_DIR_NAME`
- `FAIRIFIER_SOURCE_MAX_SELECTED_INPUTS`
- `FAIRIFIER_SOURCE_INVENTORY_MAX_CHARS_PER_SOURCE`
- `FAIRIFIER_SOURCE_READ_MAX_CHARS`
- `FAIRIFIER_SOURCE_GREP_CONTEXT_CHARS`
- `FAIRIFIER_SOURCE_MAX_SEARCH_RESULTS`
- `FAIRIFIER_SOURCE_ROLE_DETECTION_ENABLED`
- `FAIRIFIER_SOURCE_MIN_RELEVANCE_SCORE`
- `FAIRIFIER_SOURCE_OUTLIER_POLICY`
- `FAIRIFIER_METADATA_CONTEXT_MODE`
- `FAIRIFIER_METADATA_FIELD_SEARCH_ENABLED`
- `FAIRIFIER_METADATA_MAX_EVIDENCE_SNIPPETS_PER_FIELD`
- `FAIRIFIER_METADATA_MAX_CONTEXT_CHARS_PER_FIELD`
- `FAIRIFIER_METADATA_SOURCE_REF_MIN_CONFIDENCE`
- `FAIRIFIER_METADATA_SOURCE_REF_DOWNGRADE_CONFIDENCE`
- `FAIRIFIER_TABLE_FULL_SCAN_ENABLED`
- `FAIRIFIER_TABLE_SEARCH_MAX_ROWS`
- `FAIRIFIER_TABLE_SEARCH_MAX_MATCHES`

When adding a setting, update `FAIRifierConfig`, `apply_env_overrides`,
`env.example`, and tests.

---

## Tests To Run

Use the `FAIRiAgent` mamba environment.

```bash
# Grounding and candidate merging suite
mamba run -n FAIRiAgent pytest \
  tests/test_source_ref_regex.py \
  tests/test_candidate_normalization.py \
  tests/test_source_grounding_e2e.py \
  tests/test_field_candidates.py \
  -q

# Source workspace integration
mamba run -n FAIRiAgent pytest \
  tests/test_source_workspace.py \
  tests/test_source_workspace_config.py \
  tests/test_metadata_context_budget.py \
  tests/test_multifile_ingestion.py \
  -q

# JSON generator inner loops
mamba run -n FAIRiAgent pytest \
  tests/test_deep_agents_inner_loops.py::test_json_generator_builds_source_workspace_context \
  tests/test_deep_agents_inner_loops.py::test_json_generator_builds_field_specific_source_evidence \
  tests/test_deep_agents_inner_loops.py::test_json_generator_field_source_evidence_searches_full_tables \
  tests/test_deep_agents_inner_loops.py::test_json_generator_postcheck_downgrades_high_confidence_without_source_reference \
  -q
```

Compile check:

```bash
mamba run -n FAIRiAgent python -m compileall -q \
  fairifier/utils/grounding.py \
  fairifier/services/source_workspace.py \
  fairifier/graph/langgraph_app.py \
  fairifier/agents/document_parser.py \
  fairifier/agents/json_generator.py \
  fairifier/validation/metadata_json_format.py \
  fairifier/utils/llm_helper.py \
  fairifier/config.py
```

---

## Implementation Status of Previous Next-Steps

Items from the v1.3.x handoff, now resolved:

| Item | Status |
|---|---|
| Surface downgraded fields in validation/report | ✅ Done — `source_grounding_summary` in `metadata.json` + `workflow_report.json` |
| Source-aware validation output (field counts) | ✅ Done — `validate_source_grounding()` + UI Provenance card |
| Prefer sources by role and relevance in ranking | ✅ Done — `_upstream_reconcile_candidates()` scoring |
| Replace shallow merge with field-level provenance | ✅ Done — upstream candidate merging architecture |
| Use source role / agreement count for primary value | ✅ Done — consensus scoring in `_upstream_reconcile_candidates()` |
| Add source-span evidence packets | 🔶 Partial — `source_id:char_start-char_end` citations present in generation prompt; full span objects not yet stored as structured metadata |
| Add integration fixture (multi-source directory) | ✅ Done — `tests/test_source_grounding_e2e.py::test_e2e_field_evidence_context_with_multi_source_workspace` |

---

## Next Phase: Identifier Completeness and ISA Structural Repair

Suggested scope for the next development phase:

1. **Deterministic identifier generation**: synthesize `sample identifier` and
   `observation unit identifier` when source documents don't supply them (e.g.
   `{study_id}_sample_{row_index}`), to eliminate the two standing FAIR/ISA
   format errors.
2. **Multi-value field normalisation**: `collection date` currently carries
   semicolon-separated values; enforce single-value constraint by selecting a
   representative date or restructuring into multiple sample rows.
3. **ISA structural repair**: investigate whether mandatory field coverage can
   reach 100% without hallucinating content.

---

## Guardrails

- **Never redefine the grounding regex locally.**  Import from
  `fairifier.utils.grounding`.
- Do not reintroduce hard `[:6000]` or `[:3000]` truncation for reasoning
  paths.  Prompt budgets are allowed; source workspace content must remain
  preserved.
- Do not add vector RAG for this path unless explicitly requested.  The current
  design is agentic source search over preserved files and external FAIR-DS
  tools.
- Keep single-file behavior compatible by treating it as a one-source workspace.
- Avoid broad refactors in `langgraph_app.py`; prefer focused helpers and tests.
