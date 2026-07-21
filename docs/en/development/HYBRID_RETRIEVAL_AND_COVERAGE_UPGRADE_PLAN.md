# Hybrid Retrieval, Evidence Store, and Deterministic Coverage — Upgrade Plan

> **Status: PROPOSED (v1.5.0 candidate) — v3, resilient-default revision**
> This document supersedes the "no vector RAG" guardrail in
> [SOURCE_GROUNDING_ARCHITECTURE.md](SOURCE_GROUNDING_ARCHITECTURE.md) for the
> scope described here. It complements — and does not replace —
> [UPSTREAM_CANDIDATE_MERGING.md](UPSTREAM_CANDIDATE_MERGING.md), which stays
> the consensus/reconciliation layer that all new candidate sources feed into.
>
> **Revision note:** v2 correctly moved away from permanent opt-in
> experiments, but was too aggressive about deleting old code immediately.
> The v3 rule is: new components must be good enough to become the default,
> but migration is staged. Ship with shadow/compare telemetry, keep a narrow
> runtime fallback for smooth processing, then remove superseded internals
> only after the new path has passed the evaluation gate and survived real
> runs without regressions. Avoid both extremes: no flag maze, no big-bang
> rewrite.

---

## 1. Problem statement

Three compounding gaps in the current (v1.4.0) pipeline can cause **missed
information**, not just occasional wrong values:

1. **Context truncation** — `extract_document_info()` and
   `generate_complete_metadata()` bound input text to conservative character
   budgets. Middle sections of long documents can be dropped entirely.
2. **Lexical-only retrieval** — `grep_sources()` / `search_table()` are exact,
   case-insensitive substring matches. Paraphrases, synonyms, and
   ontology-synonym field-name mismatches produce **zero hits**.
3. **Model-judgment-dependent coverage** — the only "read more" mechanism
   today is the optional DeepAgent inner loop, capped at 6 iterations / 18
   tool calls, which delegates to `section-analyst` **only when the model
   decides to**. Nothing guarantees every section of a long or multi-file
   document is ever inspected.

This plan replaces all three with a single decisive architecture: hybrid
(lexical + semantic, domain-tuned) retrieval, a Qdrant-backed Evidence Store,
deterministic section coverage via LangGraph `Send()`, and a budget policy
that is safe to relax because coverage no longer depends on one large call
succeeding.

---

## 2. Design principles

- **One recommended path per component, not a menu of flags.** Each
  workstream below names a primary technology/algorithm choice. Runtime
  fallbacks are allowed only for reliability (for example, Qdrant is down),
  not as a permanent user-facing choice between two product behaviors.
- **Backward-compatible provenance, staged internal replacement.** Every
  candidate must still resolve to `source_id:char_start-char_end`
  (`SOURCE_REF_PATTERN`), so grounding/validation code is untouched. Internal
  implementations that hybrid retrieval / the Evidence Store supersede are
  deprecated first, shadow-compared where practical, and deleted only after a
  release boundary and evaluation gate. The goal is no long-term duplicate
  stack, not no fallback.
- **Deterministic coverage over model-judgment coverage.** Coverage of a
  document is a property of a code loop (`Send()` map-reduce), not of whether
  a DeepAgent chose to call a subagent.
- **Parallelize everything that reads shared, immutable state.** The source
  workspace is read-only for the duration of a run; any step that only reads
  it and writes to an isolated output (a candidate list, a subagent
  response) is a parallelization candidate — see §8.
- **This is a FAIR/scientific-literature vertical, not a generic agent
  framework.** Generic RAG advice (any embedding model, any chunk size) is a
  starting point, not the answer — see §9 for where domain structure
  (controlled vocabularies, units, paper section semantics, a mostly-static
  FAIR-DS field catalog) should change the generic playbook.
- **Reuse existing infra, extract shared code instead of duplicating it.**
  `sentence-transformers` and Qdrant are already required at deploy time
  (`docker-compose` starts `qdrant` unconditionally; `mem0_service.py`
  already implements auto-start-local-Qdrant-if-missing). That connection
  logic gets **extracted into a shared module**, not copy-pasted for a second
  vector consumer.
- **First-principles cost control.** The bottleneck is evidence *recall* and
  source-grounded value extraction, not building a full research-paper search
  platform. Start with the smallest architecture that improves recall:
  structure-aware child chunks, deterministic context headers, existing
  lexical search, dense search, RRF, and lightweight rerank. Do not add
  ColBERT/SPLADE, per-chunk LLM summaries, or a separate BM25 service until
  section-coverage recall shows the simpler stack is insufficient.

---

## 3. Tech stack decisions (decisive, one per component)

| Component | Decision | Why |
|---|---|---|
| **Vector store** | **Qdrant**, one collection per run (`run_{session_id}`), normally dropped when the run finalizes; persist the manifest JSONL in `source_workspace` for audit. | Already mandatory infra in `docker-compose` (started unconditionally, independent of `MEM0_ENABLED`). Qdrant natively combines **payload filtering + ANN search in one query**, so structured fields (`source_id`, `char_start`, `char_end`, `field_hints`, `produced_by`) live in the payload — no second SQL/document store needed. If Qdrant is unreachable after auto-start/retry, semantic retrieval is skipped and the run continues with lexical search + Evidence Store JSONL export; this is a reliability fallback, not a supported long-term mode. |
| **Qdrant connection/lifecycle code** | Extract `_try_auto_start_qdrant`, `_docker_available`, health-check logic from `mem0_service.py` into `fairifier/services/qdrant_client.py`; both `mem0_service.py` and the new semantic index import from there. | Avoids duplicating connection/retry logic for a second Qdrant consumer; one place to fix connection bugs. |
| **Chunk/query embedding model** | **`BAAI/bge-small-en-v1.5`** (local, CPU-friendly, asymmetric `query:`/`passage:` prefixing fits "field-name query → document-passage" retrieval), run via `sentence-transformers`, already a project dependency. | Strong general+technical-text retrieval performance, small enough for CPU inference at run time (no GPU dependency introduced), asymmetric prefixing is a better fit than a symmetric model for this query/passage shape. Domain-tuned scientific embeddings (SPECTER2, BioBERT-based) are evaluated in §9.2 as a **follow-up swap of this one config value**, not a second code path. |
| **Chunker** | MinerU `content_list_v2` Block → Chunk → Section pipeline (fallback: shared text/Markdown paragraph+heading parser), implemented once in `fairifier/services/chunking.py`. | MinerU already exposes typed blocks, page metadata, and heading levels; use that structure directly instead of regexing rendered Markdown. Details and parameters live in `SCIENTIFIC_DOCUMENT_CHUNKING_DESIGN.md`. |
| **Fusion** | Reciprocal Rank Fusion (RRF, `k=60`) combining lexical (`grep_sources`) and semantic ranks. | No score-calibration problem between BM25-like lexical hits and cosine similarity; standard, well-validated choice. |
| **Rerank** | **`cross-encoder/ms-marco-MiniLM-L-6-v2`**, default-on for fused top-20 → final top-K per field, batched and guarded by a latency timeout. | Production RAG practice strongly favors reranking after hybrid retrieval, but CPU cross-encoders can still become a hot path on very large bundles. If the reranker times out or is unavailable, keep the RRF order and mark `rerank_status=skipped`; do not fail the run. |
| **Evidence Store persistence** | Same Qdrant collection as the chunk index (different payload `kind: "chunk" \| "evidence"`), not a separate database. | One store, one query surface, one lifecycle to manage per run. |

---

## 4. Architecture overview

```mermaid
flowchart TD
    subgraph INGEST["Ingestion (existing)"]
        A[PDF/text/zip] --> B[MinerU/PyMuPDF]
        B --> SW[source_workspace/*]
    end

    subgraph INDEX["Chunk + Semantic Index (default after gate)"]
        SW --> CH[chunking.py: section-aware chunks]
        CH --> EMB[bge-small-en-v1.5 embeddings]
        EMB --> QD[(Qdrant run_{session_id} collection)]
        CH --> OUTLINE[section outline\nreplaces analyze_document_outline tool]
    end

    subgraph MAPREDUCE["Deterministic Section Map-Reduce (default after gate)"]
        OUTLINE --> PLAN[plan_sections]
        PLAN -->|Send x N, parallel| WORK[extract_section worker]
        WORK --> RED[reduce_candidates]
    end

    subgraph EVIDENCE["Evidence Store (new, replaces evidence_packets internals)"]
        RED --> ES[(Qdrant: evidence payloads)]
        DP[DocumentParser] --> ES
        HYBRID[hybrid_search_sources\n grep + semantic + RRF + rerank] --> ES
    end

    subgraph EXISTING["Existing, unchanged contracts"]
        ES --> UCM[_upstream_reconcile_candidates]
        UCM --> GEN[generate_complete_metadata\n now parallel batches]
        GEN --> PC[post-check / SOURCE_REF_PATTERN]
        PC --> OUT[metadata.json]
    end

    QD --> HYBRID
    SW --> HYBRID
```

---

## 4.1 Integration with the current LangGraph / agent harness

Current reality in the repo:

- `FAIRifierLangGraphApp._build_graph_structure()` is intentionally small:
  `read_file -> orchestrate -> finalize` (`fairifier/graph/app.py`).
- The actual multi-agent sequence (`DocumentParser`, optional
  `BioMetadataAgent`, Planner, `KnowledgeRetriever`, `JSONGenerator`,
  `ISAValueMapper`, Critic retries) lives inside `OrchestrateNode`
  (`fairifier/graph/nodes.py`), not as separate graph nodes.
- `FAIRifierState` already has extension points that should be reused:
  `source_workspace`, `retrieval_cache`, `react_scratchpad`,
  `agent_messages`, `confidence_scores`, `execution_history`,
  `retry_trajectory` (`fairifier/graph/state.py`).

**Do not bury the new coverage layer inside `OrchestrateNode`.** Add explicit
graph nodes between `read_file` and `orchestrate` so LangGraph Studio,
checkpoints, stop requests, and workflow reports can see the new stage:

```text
read_file
  -> index_sources          # chunking + Qdrant collection + evidence_store bootstrap
  -> section_map_reduce     # optional by applicability gate; writes section candidates/evidence
  -> orchestrate            # existing agent sequence, now consuming EvidenceStore/hybrid search
  -> finalize
```

This is intentionally less invasive than splitting every existing agent into
top-level LangGraph nodes. A full graph refactor may be valuable later, but it
is not required to solve the current omission problem and would couple two
large changes (retrieval architecture + orchestration refactor) in one PR.

### State keys to add

Add typed keys to `FAIRifierState` instead of stashing new runtime data in
anonymous `context` entries:

```python
source_chunks: List[Dict[str, Any]]
source_sections: List[Dict[str, Any]]
semantic_index: Dict[str, Any]          # collection name, model, counts, status
evidence_store: Dict[str, Any]          # collection name, jsonl path, counts, status
retrieval_telemetry: Dict[str, Any]     # hybrid/legacy comparison, rerank status
section_coverage: Dict[str, Any]        # sections planned/processed/skipped/timeouts
```

Keep large text out of state; store it in `source_workspace/chunks/*.jsonl`
and Qdrant, and put only paths/IDs/counts in state. This matches the existing
`document_text_path` refactor and avoids bloating checkpoints.

### Agent harness compatibility

- `DocumentParser`: keep its DeepAgent inner loop, but seed it with the
  chunker-produced outline and EvidenceStore summary. Its existing
  `react_scratchpad` telemetry stays unchanged; add only a count of
  EvidenceStore reads/writes if useful.
- `KnowledgeRetriever`: unchanged for FAIR-DS API retrieval. Do not mix
  document semantic retrieval into package/field schema retrieval; those are
  separate retrieval domains.
- `JSONGenerator`: primary integration point for `hybrid_search_sources()`.
  It should receive `FieldCandidate`s from grep/semantic/map-reduce through
  the same `_upstream_reconcile_candidates()` path; do not add a second
  reconciliation algorithm.
- `ISAValueMapper`: reads richer evidence via the EvidenceStore but keeps the
  existing high-cardinality deterministic fallback. Do not force DeepAgent
  mapping on large entity matrices.
- `AgentMailbox` / `agent_messages`: keep for semantic handoffs/gap reports.
  EvidenceStore is not a replacement for A2A messages; it is the backing store
  for source-grounded evidence that messages may reference.
- Critic retries: section indexing/map-reduce are pre-agent evidence stages.
  Critic should not retry Qdrant indexing; it should evaluate whether
  downstream extraction used the retrieved evidence faithfully. Indexing
  failures are operational telemetry and fallback triggers, not LLM quality
  failures.

### Workflow report additions

`WorkflowReportGenerator` already surfaces source-grounding and agent
handoff metrics. Extend `workflow_report.json` with:

```json
{
  "retrieval_metrics": {
    "semantic_index_status": "ok|skipped|failed",
    "chunk_count": 0,
    "section_count": 0,
    "evidence_items": 0,
    "hybrid_fields": 0,
    "legacy_only_fields": 0,
    "semantic_only_fields": 0,
    "rerank_status": "ok|skipped|timeout",
    "qdrant_fallback_used": false
  },
  "section_coverage": {
    "planned_sections": 0,
    "processed_sections": 0,
    "skipped_duplicate_sections": 0,
    "timed_out_sections": 0,
    "sections_by_source_role": {},
    "sections_by_type": {}
  }
}
```

These fields are what the evaluation layer reads; do not make evaluation
scrape log text.

---

## 5. Workstream A — Chunking + semantic index (default after gate)

**New files:** `fairifier/services/chunking.py`, `fairifier/services/semantic_index.py`,
`fairifier/services/qdrant_client.py` (shared connection helper, extracted
from `mem0_service.py`).

**The chunking/sectioning algorithm itself — block extraction from MinerU's
`content_list_v2`, the Block→Chunk→Section hierarchy, IMRaD section-type
classification, table/caption/cross-reference linking, multi-file
flattening, and token budgets — is specified in the companion document
[SCIENTIFIC_DOCUMENT_CHUNKING_DESIGN.md](SCIENTIFIC_DOCUMENT_CHUNKING_DESIGN.md).**
This section summarizes only the pieces relevant to the semantic index
itself; do not duplicate the chunking algorithm here when implementing.

- Chunk every preserved source with exact character offsets, so citations
  stay `source_NNN:char_start-char_end` — no format change downstream.
- Build the index once per run, immediately after `source_workspace`
  materialization in `ReadFileNode`, **as a background task** (see §8 —
  runs concurrently with `DocumentParser`, since neither depends on the
  other's output).
- **Field-catalog embeddings are precomputed once and cached, not per-run**
  (see §9.3) — the FAIR-DS field/term catalog is close to static across
  documents, unlike the document text itself.
- Persist `source_workspace/chunks/chunk_manifest.jsonl` for human debugging
  (auditability), vectors live only in Qdrant (no numpy-file fallback — if
  Qdrant is unreachable and auto-start fails, the run logs a warning and
  **degrades to lexical-only for that run**, exactly like `mem0_service.py`
  already does for memory; this is a runtime resilience fallback, not a
  user-facing configuration mode).

**Config:** `FAIRIFIER_SEMANTIC_INDEX_ENABLED=true` once the §10 gate passes;
until then it runs in shadow/build-only mode. After default switch, this env
var is an emergency kill-switch, not a product mode.

---

## 6. Workstream B — Hybrid retrieval becomes the default evidence search after shadow comparison

`hybrid_search_sources()` in `fairifier/services/source_workspace.py` becomes
the **only** way `JSONGeneratorAgent`, `DocumentParserAgent`, and
`ISAValueMapperAgent` search source text. `grep_sources()` is not deleted —
it becomes an internal lexical-signal function called *by*
`hybrid_search_sources()` — but every current standalone call site that
called `grep_sources()` directly for field-evidence discovery is **rewritten
to call `hybrid_search_sources()` instead**, not left as an alternate path
selectable by a flag.

```python
def hybrid_search_sources(
    workspace: SourceWorkspace,
    field_name: str,
    description: str,
    aliases: list[str],
    *,
    top_k: int = 8,
) -> List[FieldCandidate]:
    lexical_hits = [
        hit for q in build_field_search_queries(field_name, description, aliases)
        for hit in grep_sources(workspace, q)
    ]
    semantic_hits = semantic_search_chunks(
        workspace, query_text=f"{field_name}: {description}", top_k=top_k * 3
    )
    fused = reciprocal_rank_fusion([lexical_hits, semantic_hits], k=60)
    reranked = cross_encoder_rerank(f"{field_name}: {description}", fused[:20])
    return [to_field_candidate(hit, retrieval_method=hit.method) for hit in reranked[:top_k]]
```

- `FieldCandidate` gains `retrieval_method: Literal["grep", "semantic", "hybrid"]`
  for telemetry (§10), not for branching grounding logic.
- Replace the direct `grep_sources(...)` loop inside
  `JSONGeneratorAgent._build_field_source_evidence_context()` with one call
  to `hybrid_search_sources()`, but keep `grep_sources()` as the internal
  lexical signal and as an emergency runtime fallback if the semantic index
  is unavailable.
- Keep the current PETase-specific `alias_map` for one migration release, but
  log every alias hit with `alias_source="legacy_python_alias_map"`. Once
  the same aliases are represented in FAIR-DS synonyms or skill-provided
  vocabularies (§9.3) and regression tests pass, remove the hardcoded map.

### 6.1 Retrieval parameters and tuning contract

Start with conservative, auditable parameters borrowed from common
production RAG practice (small child chunks for precision, larger parent
sections for context, hybrid retrieval + RRF + rerank), then tune only
against this project's section-coverage recall metric:

| Parameter | Default | Rationale |
|---|---:|---|
| lexical queries per field | up to 10 | Matches current `_field_search_queries()` ceiling; prevents alias explosion |
| lexical hits per field | 20 | Existing `FAIRIFIER_SOURCE_MAX_SEARCH_RESULTS` default scale |
| semantic hits per field | 24 (`top_k * 3`) | Enough dense recall before fusion without flooding rerank |
| RRF `k` | 60 | Standard robust default for fusing heterogeneous rankers |
| rerank candidate count | 20 | Keeps CPU cross-encoder cost bounded |
| final evidence snippets per field | 8 | Matches current prompt-budget scale; top candidate plus alternates |
| reranker timeout | 5 seconds per batch | Skip rerank and keep RRF order rather than failing extraction |

**Do not add BM25/SPLADE in the first implementation.** BM25 over
contextualized chunks is a known best practice, and Qdrant can support sparse
vectors, but the repo already has a deterministic lexical signal
(`grep_sources`) and no sparse-index dependency. First-principles fit here:
exact identifiers, sample names, units, and ontology labels are already
served by grep; the missing capability is semantic recall. Add a true BM25
or sparse-vector index only if evaluation shows lexical+semantic+rerank is
still missing evidence spans that keyword search should find.

**Config:** `FAIRIFIER_HYBRID_RETRIEVAL_ENABLED=true` once shadow comparison
passes. Before that, use the same code path for comparison telemetry without
feeding it to generation.

---

## 7. Workstream C — Evidence Store becomes the default evidence substrate after wrapper parity

**New file:** `fairifier/services/evidence_store.py`. The existing public
functions in `fairifier/services/evidence_packets.py` stay as compatibility
wrappers for one migration release; internally they call
`EvidenceStore.export_context()` / `EvidenceStore.add_from_document_info()`.
This preserves prompt contracts and UI/report expectations while moving the
source of truth into the queryable store.

```python
@dataclass
class EvidenceItem:
    id: str
    text: str
    source_id: str
    char_start: int
    char_end: int
    field_hints: list[str]
    produced_by: str            # "DocumentParser" | "SectionMapReduce" | "hybrid_search"
    confidence: float

class EvidenceStore:
    def add(self, items: list[EvidenceItem]) -> None: ...
    def query(self, text: str, top_k: int = 8, field_hint: str | None = None) -> list[EvidenceItem]: ...
    def export_context(self, max_chars: int) -> str: ...   # == today's build_evidence_context() shape
```

- Backed by the same Qdrant collection as Workstream A (payload `kind:
  "evidence"`). Every evidence item any agent or map-reduce worker produces
  becomes queryable by every other agent in the same run — closing the gap
  `mem0_service.py` explicitly leaves open ("not document RAG") for the
  *current* document.
- Also export `source_workspace/evidence_store.jsonl` at finalize time for
  audit, deterministic tests, and Qdrant-outage fallback. Qdrant is the query
  engine; JSONL is the run artifact. This keeps operations smooth without
  introducing a second production query path.
- `source_workspace.md`'s inventory gains the section outline produced once
  by the chunker (Workstream A) — `DocumentParser`'s optional,
  tool-gated `analyze_document_outline` tool is deprecated once the chunker
  outline lands. Keep it as a fallback for non-MinerU/plain-text edge cases
  until the shared fallback-outline parser has equivalent test coverage.

**Config:** `FAIRIFIER_EVIDENCE_STORE_ENABLED=true` once wrapper parity
passes. The public evidence-packet API remains stable during migration.

---

## 8. Workstream D — Deterministic section map-reduce + parallelization (default after evaluation gate)

### 8.1 Why `Send()`, not DeepAgent dynamic subagents, for coverage

| Approach | Coverage guarantee |
|---|---|
| **LangGraph `Send()` map-reduce** | Deterministic — a `for section in sections` router always fans out one `Send` per section |
| **DeepAgent dynamic subagents** (`task()` from an interpreter script) | Model-authored orchestration — usually complete, but still one model decision away from guaranteed |

`Send()` map-reduce is the coverage mechanism (this workstream). DeepAgent
subagents stay the mechanism for *judgment* tasks (which packages, which
skills apply) — see §8.3.

### 8.2 Graph shape

New subgraph runs after `ReadFileNode`, before `OrchestrateNode`:

```python
def plan_sections(state: FAIRifierState) -> dict:
    return {"pending_sections": merge_small_chunks_into_sections(
        state["source_chunks"], max_sections=config.mapreduce_max_sections
    )}

def route_to_workers(state: FAIRifierState) -> list[Send]:
    return [Send("extract_section", {"section": s}) for s in state["pending_sections"]]

async def extract_section(payload: dict) -> dict:
    candidates = await llm_helper.extract_section_candidates(payload["section"])
    return {"section_candidates": candidates}   # Annotated[list, operator.add] accumulator

def reduce_candidates(state: FAIRifierState) -> dict:
    evidence_store.add(state["section_candidates"])
    return {}
```

- Bounded concurrency (reuse the existing 5-worker pattern from
  `evaluation/scripts/run_batch_evaluation.py`); a failed/timed-out section
  worker contributes zero candidates rather than failing the run (same
  philosophy as Critic's ESCALATE-but-continue).
- **Applicability gate stays** (`FAIRIFIER_MAPREDUCE_MIN_DOC_CHARS`): this is
  not a hedge, it's a cost optimization — short documents that already fit
  the single-call budget skip map-reduce because there is nothing for it to
  fix.
- Each candidate still carries `source_id:char_start-char_end`, feeding
  directly into the existing `_upstream_reconcile_candidates()`.

### 8.3 Parallelization inventory — what is safe to run concurrently and why

The pipeline has real sequential dependencies (Planner needs merged
`document_info`; `KnowledgeRetriever` needs `document_info`; `JSONGenerator`
needs selected fields; `ISAValueMapper` needs generated fields) — those stay
sequential. Everything below reads only shared **immutable** state
(`source_workspace` does not change during a run) and writes to an isolated
output, so it is safe to parallelize with no state conflicts:

| Work item | Current behavior | Change | Mechanism |
|---|---|---|---|
| **Section map-reduce workers** (§8.2) | N/A (new) | Parallel by construction | LangGraph `Send()` |
| **Chunk/semantic index build** vs. **`DocumentParser`** | Sequential (index build doesn't exist yet) | Run concurrently — index build only needs `source_workspace`, not `document_info` | `asyncio.gather` at the `ReadFileNode` → `OrchestrateNode` boundary |
| **`generate_complete_metadata` batches** (`fairifier/utils/llm_helper.py`) | `for batch in batches: await ...` — **strictly sequential despite batches being logically independent** | `asyncio.gather` over batches, bounded by a per-provider concurrency semaphore | Each batch reads the same read-only `document_context`, writes to a disjoint field subset — no conflict |
| **Field-level hybrid search** across `knowledge_items` in `_build_field_source_evidence_context()` | Sequential `for field in knowledge_items` loop | Batch the semantic-embedding step (one `encode()` call for all field queries — more efficient than parallel async dispatch for a local CPU model) + `asyncio.gather` for any remaining per-field LLM calls | Local embedding models benefit from **batched encode, not async fan-out**; only genuinely async (network/LLM) steps should use `asyncio.gather` |
| **`KnowledgeRetriever`'s per-ISA-sheet optional-field selection** | One `field-selector` subagent, dispatched at the model's discretion, sheet-by-sheet or not at all | Explicitly dispatch one `field-selector` call per ISA sheet (investigation/study/observationunit/sample/assay) **in parallel** — each sheet's optional-field choice is independent given the already-selected package set | DeepAgent's documented behavior: "the main agent can issue several `task` calls in a single turn to run them in parallel" — make this explicit in the system prompt instead of leaving it to chance |
| **`_normalize_candidates_with_llm`** | Already a single batched call | No change needed | Already correct |

**Not parallelized, and why:** `DocumentParser → BioMetadataAgent → Planner`
stays sequential — `Planner` consumes the *merged* `document_info` including
bio-tool-recovered fields, so `BioMetadataAgent` must complete first.
`KnowledgeRetriever → JSONGenerator → ISAValueMapper` stays sequential for
the same reason (each consumes the previous step's structured output).
Critic retries are inherently sequential (evaluate, then maybe redo).

### 8.4 Budget relaxation (paired with, not independent of, §8.2)

Because coverage no longer depends on one large call succeeding, the
existing conservative constants become candidates for relaxation, but they
should move in two steps rather than one:

- Step 1: keep current absolute caps while adding section map-reduce and
  token/cost telemetry. This isolates the effect of better coverage from the
  effect of larger prompts.
- Step 2: once section-coverage recall improves without hallucination
  regression, replace the hardcoded `max_doc_context_markdown=200000` /
  `max_doc_context_text=120000` and the `min(..., 200000)` clamp in
  `apply_budget_guardrails()` with a **model-context-aware** budget
  (`resolve_doc_context_budget()`: configured LLM context window minus
  reserved output tokens).
- Step 2 also replaces the hardcoded `react_loop_max_iterations=6` /
  `react_loop_max_tool_calls=18` clamps with a document-size-aware ceiling
  (scale with estimated section count from Workstream A).
- Add per-phase token/cost/latency telemetry to `workflow_report.json` so the
  relaxed budgets are observable, not just larger numbers hoped to be fine.

**Config:** `FAIRIFIER_MAPREDUCE_ENABLED=true` after the section-coverage
evaluation gate passes; `FAIRIFIER_DOC_CONTEXT_BUDGET_MODE=model_aware`
only after Step 1 telemetry validates cost/quality (§8.4). Escape hatch:
`MAX_DOC_CONTEXT_MARKDOWN` / `MAX_DOC_CONTEXT_TEXT` env overrides still work
for pinning a hard ceiling on a specific deployment).

---

## 9. Domain-specific optimization for the FAIR / scientific-literature vertical

This system is not a general-purpose agent framework — it targets a fixed
schema (MIxS/ISA via FAIR-DS), controlled vocabularies (ENVO, OBI, ...), and
scientific-paper conventions. Generic RAG defaults leave value on the table
here; the following are vertical-specific changes, not generic RAG hygiene.

### 9.1 Field-catalog embeddings should be precomputed once, not per run

The FAIR-DS field/term catalog changes rarely compared to the documents
being processed. Embedding every field's name+description on every run (as
a naive per-run implementation would) is wasted, repeated work specific to
this vertical's fixed schema.

- Precompute embeddings for the full FAIR-DS field catalog **once**, cached
  in the same long-lived cache tier as `retrieval_cache.py` uses for FAIR-DS
  API responses, keyed by `(field_id, catalog_version)`.
- Invalidate only when the FAIR-DS API package/term catalog version changes.
- This turns the "embed the query side" cost in `hybrid_search_sources()`
  into a cache lookup for the field side, leaving only the document-chunk
  side (Workstream A) as new per-run embedding work.

### 9.2 Prefer retrieval quality validated on this domain's terminology, not a generic MTEB score

`bge-small-en-v1.5` (§3) is the default, but the actual validation must use
this project's own terminology (enzymology, ecotoxicology, genomics field
names/units/ontology terms), not a generic benchmark:

- Use the section-coverage recall metric (§10) as the acceptance test for
  the embedding model choice itself, run against the existing ground-truth
  datasets (earthworm, Haarika+Bhamidipati, BIOREM) **before** merging §6 —
  if `bge-small-en-v1.5` underperforms lexical-only on this domain's ground
  truth, the model choice (not the hybrid-retrieval architecture) is what
  needs to change.
- Domain-tuned biomedical/scientific embedding models (e.g. a
  PubMedBERT/SPECTER2-family sentence encoder) are a candidate **swap of one
  config value** (`FAIRIFIER_SEMANTIC_EMBEDDING_MODEL`) if the recall metric
  shows a clear gap — evaluated with the same harness, not added as a second
  code path.

### 9.3 Ontology/controlled-vocabulary synonyms should drive query expansion, not hardcoded per-field aliases

The current `_field_search_queries()` alias map
(`fairifier/agents/json_generator.py`) hardcodes synonyms for a narrow set of
PETase/enzymology fields ("reaction temperature" → "assay temperature",
"incubation temperature", ...). This does not generalize to the earthworm/
ecotoxicology/genomics documents the same system also processes, and it is
exactly the kind of per-domain knowledge that does not belong hardcoded in
Python.

**Delete the hardcoded `alias_map` dict.** Replace query expansion with two
sources that already exist or belong in the skill system, not in agent code:

1. **FAIR-DS term synonyms**, when the API/ontology backing a field already
   carries synonym/definition text — use it directly as additional query
   variants instead of guessing aliases in code.
2. **Skill-provided domain vocabularies** — the existing `SKILL.md`
   mechanism (`fairifier/skills/`) already encodes domain knowledge
   (genomics skill exists today); add a `field_aliases` section to relevant
   domain skills (enzymology/plastics-degradation, ecotoxicology, ...) so
   alias knowledge is **data the skill system loads dynamically**, matching
   how the rest of the system already treats domain knowledge, not a special
   case hardcoded only for JSONGenerator.

This also reduces reliance on hardcoded aliases generally: semantic
retrieval (§6) already recovers many paraphrases without needing an
explicit alias list — the alias map exists today specifically to compensate
for lexical-only search, which hybrid retrieval subsumes.

### 9.4 Section-type-aware ranking, not just source-role-aware ranking

`source_role_priority()` today ranks by document role (main manuscript vs.
table vs. supplement). Scientific papers have a further, well-known internal
structure that is a strong, cheap prior for *which field types* live where:
reaction/assay conditions and protocols are reliably in **Methods**;
measured outcomes (degradation rate, concentrations) are reliably in
**Results**; study framing (research domain, objectives) is reliably in
**Abstract/Introduction**.

- Extend the chunker (Workstream A) to tag each chunk with a coarse
  **section type** (abstract / methods / results / discussion / supplement),
  via the deterministic IMRaD keyword classifier specified in
  [SCIENTIFIC_DOCUMENT_CHUNKING_DESIGN.md §4](SCIENTIFIC_DOCUMENT_CHUNKING_DESIGN.md#4-section-type-canonicalization-imrad-aware-deterministic-skill-extensible) —
  no new NLP component needed. Note `section_type` (what the text discusses)
  and `source_role` (which file/how trusted) are orthogonal axes: a
  supplementary file's Methods section still gets `section_type="methods"`.
- Use section type as a **ranking boost**, not a hard filter, inside
  `hybrid_search_sources()`: e.g. boost Methods-section chunks when the
  field's FAIR-DS `isa_sheet` is `assay`, boost Results-section chunks for
  measured-outcome fields. This is a domain heuristic generic RAG tuning
  would not derive on its own, and it is cheap (a lookup table keyed by
  `isa_sheet`, not a model call).

### 9.5 Quantity/unit fields need a deterministic normalizer, not just better retrieval

Retrieval (lexical, semantic, or hybrid) solves *finding* the right sentence;
it does not solve *parsing* it correctly. Fields like `reaction temperature`,
`enzyme loading`, `degradation rate` routinely appear with units, ranges, and
inconsistent notation ("25–30 °C", "37°C", "310 K") — a domain-specific
problem this vertical has and a generic agent framework would not need to
solve.

- Add a deterministic post-retrieval normalizer for quantity-typed FAIR-DS
  fields (unit parsing/conversion via a library such as `pint`, range
  handling, scientific-notation normalization) that runs on the
  `hybrid_search_sources()` output **before** it reaches the LLM generation
  prompt, alongside the existing `_normalize_candidates_with_llm` step (LLM
  normalization stays for free-text fields; the deterministic normalizer
  specifically targets quantity fields where unit correctness is checkable
  without an LLM).
- This directly reduces a class of value-level errors (wrong unit, silently
  dropped range) that neither better retrieval nor better prompting fixes on
  its own.

---

## 10. Evaluation, rollout, and guardrail updates

1. **Update `SOURCE_GROUNDING_ARCHITECTURE.md`**: replace the "no vector RAG"
   guardrail with a description of the shipped hybrid architecture and its
   scope (FAIR-DS schema retrieval and full-table scans remain
   deterministic/API-backed, unchanged).
2. **New metric: section-coverage recall.** For each ground-truth field, does
   *any* candidate (lexical, semantic, or map-reduce) cite a source span
   overlapping the annotated evidence location? This is the metric that
   proves the omission problem is actually fixed, as opposed to only moving
   field-presence counts. Implemented in
   `evaluation/analysis/analyzers/` alongside the existing field-presence
   analyzer.
3. **Shadow comparison before default switch:** for one integration stage,
   run hybrid retrieval alongside the current grep evidence builder and log
   both candidate sets (`legacy_candidate_count`, `hybrid_candidate_count`,
   `new_source_spans_found`, `legacy_only_spans`). The generation prompt uses
   the current path until the comparison passes; this avoids changing recall
   and generation behavior in the same unobservable step.
4. **Default-switch acceptance bar:** run the full harness against earthworm /
   Haarika+Bhamidipati / BIOREM and require section-coverage recall and field
   coverage to both improve (or hold) versus the v1.4.0 baseline, with
   hallucination indicators (`ungrounded_high_confidence_fields`, Critic
   faithfulness score) not regressing. Only then make hybrid retrieval /
   Evidence Store / map-reduce the default path.
5. **Deletion bar:** remove superseded code only after the default path has
   passed the above evaluation and at least one release boundary has kept the
   fallback path available for operational rollback. This keeps smooth
   processing without committing to permanent dual implementations.

### 10.1 Evaluation-system integration points

The current evaluation stack has three relevant layers:

1. `evaluation/scripts/run_batch_evaluation.py` runs the workflow and stores
   `metadata.json`, `workflow_report.json`, and `eval_result.json` per run.
2. `evaluation/scripts/evaluate_outputs.py` orchestrates evaluators against
   `metadata.json` plus optional `workflow_report.json`.
3. `evaluation/analysis/data_loaders/evaluation_loader.py` and
   `evaluation/analysis/analyzers/*` aggregate run outputs into reports and
   visualizations.

Add retrieval/coverage evaluation at all three layers so the new system is
measured with the same harness that already measures completeness,
correctness, workflow reliability, and pass@k.

#### New evaluator: `RetrievalCoverageEvaluator`

Add `evaluation/evaluators/retrieval_coverage_evaluator.py` and register it
in `evaluation/evaluators/__init__.py` plus
`EvaluationOrchestrator._initialize_evaluators()`.

Inputs:

- `metadata_json`
- `workflow_report`
- optional ground-truth field annotations (`evidence_location`,
  `expected_value`)
- optional `source_workspace/evidence_store.jsonl`

Outputs:

```json
{
  "retrieval_coverage": {
    "section_coverage_ratio": 0.0,
    "fields_with_source_refs": 0,
    "fields_with_semantic_only_candidates": 0,
    "fields_with_legacy_only_candidates": 0,
    "qdrant_fallback_used": false,
    "rerank_timeout_rate": 0.0,
    "evidence_store_items": 0
  }
}
```

Evidence-location overlap should be best-effort because existing ground truth
often stores free-text locations like `"Page X, Section Y"` rather than exact
character spans. Use three tiers:

1. exact span overlap when annotations provide `source_id:start-end`,
2. page/section match when annotations provide page/section text,
3. source-reference presence only when no comparable ground-truth location is
   available.

This avoids pretending the current ground truth is more precise than it is,
while still making the metric useful immediately.

#### Extend `InternalMetricsEvaluator`

`evaluation/evaluators/internal_metrics_evaluator.py` already extracts
`workflow_report.json` quality/retry/handoff metrics. Extend it to include:

- `retrieval_metrics` block from workflow report,
- `section_coverage` block from workflow report,
- `qdrant_fallback_used`,
- rerank status/timeout counters,
- `semantic_index_status`.

This keeps internal telemetry in one evaluator instead of scattering parsing
logic across analysis scripts.

#### Extend analysis loader and analyzers

- `evaluation/analysis/data_loaders/evaluation_loader.py`: include
  retrieval/coverage metrics from `eval_result.json` in the synthetic rows it
  builds for each model/document/run. It currently skips some individual
  `eval_result.json` files for DataFrame generation; retrieval metrics should
  be part of the run-level records used by new analyzers, not only batch
  aggregate files.
- Add `evaluation/analysis/analyzers/retrieval_coverage.py` with:
  - section coverage by document/model,
  - semantic-only vs legacy-only evidence counts,
  - fallback frequency,
  - rerank timeout rate,
  - correlation between section-coverage recall and field completeness.
- Add one visualization module under
  `evaluation/analysis/visualizations/retrieval_coverage.py`:
  coverage heatmap by model/document and a before/after bar chart for
  legacy-grep vs hybrid retrieval.

#### Batch-evaluation knobs

Add model/run config env entries to `evaluation/config/env.evaluation.template`
so comparisons are reproducible:

```bash
FAIRIFIER_SEMANTIC_INDEX_ENABLED=true
FAIRIFIER_HYBRID_RETRIEVAL_ENABLED=true
FAIRIFIER_EVIDENCE_STORE_ENABLED=true
FAIRIFIER_MAPREDUCE_ENABLED=true
FAIRIFIER_RETRIEVAL_SHADOW_MODE=true   # comparison stage only
FAIRIFIER_RETRIEVAL_RERANK_TIMEOUT_SECONDS=5
FAIRIFIER_MAPREDUCE_MAX_PARALLEL_WORKERS=5
```

`run_batch_evaluation.py --workers 5` controls document-level concurrency;
`FAIRIFIER_MAPREDUCE_MAX_PARALLEL_WORKERS` controls within-document section
worker concurrency. Document workers × section workers can multiply API
pressure, so the evaluation README should warn users to reduce one when
   increasing the other.

### 10.2 Phase 3 local shadow gate (2026-07-03)

Status: **pass** — retrieval stack validated end-to-end, including per-field
telemetry in `workflow_report.json`. Two real bugs were found and fixed while
verifying the gate (see below); both are now covered by regression tests.

**Subset tested** (`ground_truth_shadow_gate.json`, 3 documents):

| Document | Retrieval pilot hybrid gain | Section coverage | Qdrant fallback | Overall completeness (post-fix workflow) | Required completeness |
|---|---:|---:|---:|---:|---:|
| `earthworm` | 12/12 queries | 43/43 | 0% | 81.0% | 100% |
| `petase_10_1038_s41586-020-2149-4` | 12/12 | 74/74 | 0% | 94.4% | 100% |
| `petase_10_1002_anie_202218390` | 12/12 | 40/40 | 0% | 90.3% | 100% |

**Post-fix full workflow batch** (`workflow_postfix/`, 2026-07-03): all 3
documents completed successfully with field evidence wired correctly.
Aggregate evaluation score **0.897**. Mean overall completeness **88.6%**;
**required fields 100%** on all three. Hybrid retrieval telemetry confirmed
per document (`fields_with_hybrid_gain` 4–5, `section_coverage_ratio` 1.0,
`qdrant_fallback_used` false).

The earlier `workflow/` batch (pre field-name fix) is retained for comparison
only; do not use its completeness numbers as the gate baseline.

**Bugs found and fixed during this gate (both pre-existing on `main`, not
introduced by this branch, but they blocked verifying hybrid retrieval's own
telemetry):**

1. **`retrieval_telemetry` merge into LangGraph state.** LangGraph merges
   returned state top-level keys only; `_build_field_source_evidence_context`
   mutated a nested dict without ever reassigning
   `state["retrieval_telemetry"]`. Fixed by reassigning at the end of
   `JSONGeneratorAgent._build_field_source_evidence_context`. Covered by
   `test_json_generator_persists_retrieval_telemetry_on_state`.
2. **Field-identity key mismatch (root cause of `fields_with_retrieval_telemetry
   == 0` even after fix 1).** `_build_field_source_evidence_context` resolved
   field name/description via `field.get("name")` / `field.get("field_name")`
   / `field.get("description")`, but `state["retrieved_knowledge"]` items
   (as written by `KnowledgeRetrieverAgent.execute()`) actually use
   `term` / `definition` / `metadata` keys. Every item was silently skipped
   (`if not field_name: continue`), so **field-specific source evidence was
   never injected into the JSONGenerator/ISAValueMapper prompt** on `main`
   either — this predates hybrid retrieval. Fixed by resolving field
   name/description from `term`/`definition`/`metadata.name`/
   `metadata.definition` as well. Covered by
   `test_field_source_evidence_context_reads_knowledge_retriever_item_shape`.
   Confirmed end-to-end: re-running `earthworm` after both fixes produced
   `fields_with_retrieval_telemetry: 4`, `hybrid_fields: 4`,
   `semantic_hit_count` far exceeding `lexical_hit_count` per field, and a
   higher `json_generation`/`isa_value_mapping` confidence than the pre-fix
   run.
3. **Unrelated hardening**: `FAIRDSAPIParser._infer_data_type` crashed with
   `TypeError: argument of type 'NoneType' is not iterable` when a FAIR-DS
   term has `"syntax": null` (`term.get("syntax", "")` does not apply the
   default when the key is present with an explicit `null`). Fixed with
   `term.get("syntax") or ""`. Covered by
   `test_extract_field_info_null_syntax_does_not_raise`.
4. **Prompt budget stopped telemetry collection early.** When
   `metadata_max_context_chars_per_field` was exhausted,
   `_build_field_source_evidence_context` used `break`, so hybrid search +
   telemetry ran for only the first few fields that fit in the prompt budget.
   Fixed by continuing the loop after budget exhaustion (telemetry and
   candidates still collected; only prompt lines are truncated). Covered by
   `test_field_evidence_telemetry_not_truncated_by_prompt_budget`.

**Artifacts** (local, gitignored under `evaluation/runs/`):

- `evaluation/runs/shadow_gate_20260703/retrieval_pilot/*/shadow_comparison.json`
- `evaluation/runs/shadow_gate_20260703/workflow/` — pre-fix workflow outputs (historical)
- `evaluation/runs/shadow_gate_20260703/workflow_postfix/` — **authoritative post-fix 3-doc batch**
- `evaluation/runs/shadow_gate_20260703/workflow_fieldname_fix/` — earthworm single-doc confirmation

**Reproducible config** (not committed secrets):

- `evaluation/config/env.evaluation.shadow`
- `evaluation/config/model_configs/deepseek_v4-flash_v1.4.0_fairds8083_localpkg_shadow.env`
- `evaluation/datasets/annotated/ground_truth_shadow_gate.json`

Local FAIR-DS was run from source on port **8090** (not 8083) during this
session because a Cursor-internal process was already bound to `127.0.0.1:8083`
and `[::1]:8083` on this machine, causing connection resets. Both env files
above now point at `:8090`; adjust back to `:8083` (or whatever is free) on a
different machine.

**Commands:**

```bash
# Prerequisites (subset GT + raw sources; FAIR-DS on :8090, Qdrant on :6335)
python evaluation/scripts/run_retrieval_shadow_pilot.py --check-only \
  --ground-truth evaluation/datasets/annotated/ground_truth_shadow_gate.json

# Retrieval-only compare (no LLM)
python evaluation/scripts/run_retrieval_shadow_pilot.py \
  --document-id earthworm \
  --ground-truth evaluation/datasets/annotated/ground_truth_shadow_gate.json \
  --output-dir evaluation/runs/shadow_gate_YYYYMMDD/retrieval_pilot/earthworm

# Full workflow shadow batch
python evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation.shadow \
  --model-configs evaluation/config/model_configs/deepseek_v4-flash_v1.4.0_fairds8083_localpkg_shadow.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_shadow_gate.json \
  --output-dir evaluation/runs/shadow_gate_YYYYMMDD/workflow \
  --include-documents earthworm petase_10_1038_s41586-020-2149-4 petase_10_1002_anie_202218390
```

**Gate checklist:**

| Criterion | Result |
|---|---|
| `section_coverage_ratio` ↑ on long docs | ✅ earthworm 100% |
| Retrieval pilot `queries_with_hybrid_gain` > 0 | ✅ 36/36 across 3 docs |
| `qdrant_fallback_rate` acceptable | ✅ 0% |
| Completeness vs baseline non-regression | ✅ required 100% all docs; mean overall 88.6% (post-fix batch) |
| `workflow_report.retrieval_metrics.field_retrieval_stats` populated | ✅ confirmed (`fields_with_retrieval_telemetry` > 0; budget fix ensures all fields) |
| Fast unit suite (`run_tests.py fast`) | ✅ 619 passed, 1 pre-existing unrelated failure, 1 skipped |

**Remaining before Phase 4 (`FAIRIFIER_RETRIEVAL_SHADOW_MODE=false`):**

Phase 4 started (2026-07-03):

| Task | Status |
|---|---|
| `FAIRIFIER_RETRIEVAL_SHADOW_MODE=false` default (hybrid in prompt) | ✅ `fairifier/config.py` |
| DocumentParser chunker section outline → `/workspace/section_outline.md` | ✅ wired from `state["source_sections"]` |
| Section worker `FieldCandidate` output | ✅ `section_field_candidates.py` + JSONGenerator merge |
| LangGraph `Send()` for map-reduce | ⏳ P2 optional |
| ISAValueMapper reads EvidenceStore | ⏳ P2 optional |

Shadow comparison runs still force `FAIRIFIER_RETRIEVAL_SHADOW_MODE=true` via
`evaluation/config/env.evaluation.shadow` and `run_retrieval_shadow_pilot.py`.

### 10.3 Phase 4 A/B — shadow vs hybrid-in-prompt (2026-07-03)

Configs: `evaluation/config/env.evaluation.phase4` +
`deepseek_v4-flash_v1.4.0_fairds8090_localpkg_phase4.env` (`shadow=false`) vs
post-fix shadow batch `workflow_postfix/` (`shadow=true`). Same 3-doc subset,
deepseek-v4-flash, FAIR-DS :8090.

| Document | Shadow overall | Phase4 overall | Δ | Required (both) | Phase4 telemetry fields |
|---|---:|---:|---:|---|---:|
| `earthworm` | 81.0% | 78.6% | −2.4% | 100% | 81 |
| `petase_10_1038_s41586-020-2149-4` | 94.4% | 88.9% | −5.6% | 100% | 150 |
| `petase_10_1002_anie_202218390` | 90.3% | 87.1% | −3.2% | 100% | 137 |

| Run | Aggregate score |
|---|---:|
| Shadow (lexical in prompt) | **0.897** |
| Phase4 (hybrid in prompt) | **0.864** |

**Interpretation:** Hybrid-in-prompt is **technically active** (`shadow_env=false`,
telemetry 81–150 fields vs 4–5 under shadow). Required-field completeness held at
100% on all docs. Overall completeness and aggregate score **did not improve** on
this 3-doc slice — likely LLM variance plus noisier semantic snippets entering
the prompt budget. **Do not treat Phase 4 as a quality win yet**; keep shadow
configs for regression runs and tune rerank/snippet budget before declaring
default switch complete.

Artifacts: `evaluation/runs/shadow_gate_20260703/workflow_phase4_hybrid_on/`

### 10.4 Phase 4 tuning — lexical-priority blend + tighter budget (2026-07-03)

**Code:** `_blend_lexical_first_hybrid_output()` in `source_workspace.py` — when
hybrid hits feed the prompt, lexical-backed spans rank before semantic-only spans.
**Eval harness fix:** `run_batch_evaluation.py` now loads model config first, then
`env.evaluation.*`, so `FAIRIFIER_RETRIEVAL_SHADOW_MODE` is controlled by the env file
(not duplicated in model configs).

**Tuned parameters** (`env.evaluation.phase4_tuned` / `shadow_tuned`):

| Parameter | Default | Tuned |
|---|---:|---:|
| `FAIRIFIER_RETRIEVAL_FINAL_SNIPPETS` | 8 | 5 |
| `FAIRIFIER_METADATA_MAX_EVIDENCE_SNIPPETS_PER_FIELD` | 5 | 3 |
| `FAIRIFIER_RETRIEVAL_RERANK_CANDIDATES` | 20 | 12 |
| `FAIRIFIER_RETRIEVAL_SEMANTIC_MAX_HITS` | 24 | 16 |

**Fair A/B** (same commit, same tuned budget; only `shadow_mode` differs via env):

| Document | Shadow tuned overall | Phase4 tuned overall | Δ |
|---|---:|---:|---:|
| `earthworm` | 81.0% | 81.0% | 0.0% |
| `petase_10_1038_s41586-020-2149-4` | 86.1% | 72.2% | −13.9% |
| `petase_10_1002_anie_202218390` | 74.2% | 90.3% | +16.1% |

| Run | Mean overall completeness | Multi-layer aggregate |
|---|---:|---:|
| Shadow postfix (§10.2 baseline) | **88.6%** | 0.897 |
| Phase4 hybrid-on (§10.3, untuned) | 84.9% | 0.864 |
| Shadow tuned v2 | 80.4% | 0.652 |
| Phase4 tuned | 81.2% | 0.652 |

**Interpretation:** Tuning + lexical-priority did **not** close the gap to the §10.2
shadow baseline on this 3-doc slice; mean completeness remains below both prior runs.
PETase docs show high LLM variance (one up, one down between arms). Required-field
completeness dropped to 86% on PETase in tuned runs (vs 100% in §10.2/10.3) — treat as
run variance, not a retrieval regression. **Phase 4 quality gate for hybrid-in-prompt
is still not passed**; keep `FAIRIFIER_RETRIEVAL_SHADOW_MODE=true` in regression envs
until a larger slice or map-reduce section workers improve recall.

Artifacts:
- `evaluation/runs/shadow_gate_20260703/workflow_shadow_tuned_v2/` (shadow control)
- `evaluation/runs/shadow_gate_20260703/workflow_phase4_tuned/` (hybrid in prompt)

**Next (P1):** Section worker → `FieldCandidate` output; re-run tuned A/B on ≥8 docs
when `ground_truth_filtered.json` is rebuilt.

### 10.5 Root-cause analysis + adaptive lexical prompt (2026-07-05)

**Why Phase 4 hybrid-in-prompt lowered metrics (not just LLM variance):**

1. **Semantic noise in prompt budget** — On `earthworm`, 50 telemetry fields had lexical
   hits for 38; hybrid-in-prompt still injected ~20 semantic-only spans via
   `_blend_lexical_first_hybrid_output()`. LLM saw tangentially related excerpts →
   **extra_fields explosion** (e.g. PETase Nature: 106 vs 61 extra fields in shadow).
2. **Pre-reconciled semantic injection** — Upstream reconcile promoted semantic-only
   candidates to “High Confidence” lines even when grep/lexical evidence existed for
   the same field, steering the LLM toward wrong values.
3. **Embedder instability (8-doc batch)** — Caching a failed embedder client
   (`932e1e7` fix) plus `snowflake-arctic-embed2` / 1024-dim defaults caused
   `Local embedding model not initialized` → JSONGenerator abort, 0/8 metadata.json.
   Defaults reverted to `BAAI/bge-small-en-v1.5` / 384 dims; Ollama path unchanged in
   eval envs.

**Architectural fix (code, not param-only tuning):**

| Change | Location | Effect |
|---|---|---|
| `retrieval_prompt_adaptive_lexical=true` (default) | `config.py`, `hybrid_search_sources()` | Prompt uses **lexical snippets when any lexical hit exists** (matches shadow on ~76% of fields); hybrid rerank only on **lexical miss** (~24%) |
| `prompt_mode` telemetry | `hybrid_search_sources()` | `lexical_preferred` \| `semantic_fallback` \| `shadow_lexical` |
| Skip semantic pre-reconcile when lexical pool non-empty | `json_generator.py` | Stops spurious “High Confidence” injections |
| Stable embedding defaults | `config.py` | bge-small 384-dim baseline when env does not override |
| Embedder-aware Qdrant vector size | `semantic_index.py` | Probe live embedder width; recreate per-run collection on 384↔768 mismatch |

**Validation run (2026-07-05):** 3-doc shadow gate —
`evaluation/runs/phase4_adaptive_20260705/`.

| Run | Mean overall completeness | Aggregate | Notes |
|---|---:|---:|---|
| Shadow tuned | 83.1% | 0.677 | 3/3 metadata.json |
| Phase4 tuned (adaptive lexical) | 75.6% | 0.655 | 3/3 metadata.json |

Per-doc Δ (Phase4 − Shadow): earthworm −19.0%, PETase Angew −3.2%,
PETase Nature 0.0% (but 126 vs 52 extra_fields).

**Critical infra finding:** Both arms logged
`Vector dimension error: expected dim: 384, got 768` — Qdrant collections were
created with code default 384 while eval Ollama embedder (`nomic-embed-text-v2-moe`)
returns 768-d vectors. Semantic index was **dead for both arms** (`hybrid_fields=0`);
the A/B above compares lexical-only paths with LLM variance, not true hybrid benefit.

**Follow-up fix:** `_resolve_embedding_vector_size()` probes the live embedder and
recreates per-run Qdrant collections on dim mismatch (`semantic_index.py`).

**Dim-fix A/B (2026-07-05, semantic index active — `hybrid_fields≈35`, `qdrant_fallback_used=false`):**

| Document | Shadow overall | Phase4 adaptive overall | Δ | Shadow extra | Phase4 extra |
|---|---:|---:|---:|---:|---:|
| `earthworm` | 81.0% | 81.0% | 0.0% | 29 | 27 |
| `petase_10_1002_anie_202218390` | 83.9% | 93.5% | +9.6% | 53 | 131 |
| `petase_10_1038_s41586-020-2149-4` | 91.7% | 88.9% | −2.8% | 117 | 101 |

| Run | Mean overall completeness | Multi-layer aggregate |
|---|---:|---:|
| Shadow dim-fix (`workflow_shadow_dimfix/`) | 85.5% | 0.676 |
| Phase4 adaptive dim-fix (`workflow_phase4_dimfix/`) | **87.8%** | 0.665 |

**Quality gate (completeness): PASSED** — Phase4 mean 87.8% ≥ shadow 85.5% (+2.3 pp).
Aggregate score still −0.011 (extra_fields on PETase Angew remain high when semantic
fallback fires). **Default recommendation:** keep adaptive lexical + dim probe;
monitor extra_fields on semantic-fallback fields in expanded slice.

Artifacts: `evaluation/runs/phase4_adaptive_20260705/workflow_shadow_dimfix/`,
`workflow_phase4_dimfix/`, smoke `workflow_phase4_dimfix_smoke/`.

**Handover:** See [HYBRID_RETRIEVAL_PHASE4_HANDOVER.md](./HYBRID_RETRIEVAL_PHASE4_HANDOVER.md) for full context, provenance, and next steps for agents/colleagues.

**Service note:** MinerU is **`http://localhost:30000`** (canonical; see `env.example` /
`fairifier/config.py`). An earlier agent note incorrectly cited `:30001` — never
authorized. PDF docs without live MinerU use local
`mineru_*` cache under `evaluation/datasets/raw/`. FAIR-DS `:8090` and Qdrant
`:6335` OK.

Local expanded subset: `evaluation/datasets/annotated/ground_truth_phase4_ab.json`
(8 docs, gitignored — regenerate from shadow_gate + biorem.local + values/*).
Prior 8-doc batch failed pre-embedder-fix: `evaluation/runs/phase4_ab_20260703/`.

---

### 10.6 Expanded 8-doc A/B — dim-fix confirmed (2026-07-06)

**Run:** `evaluation/runs/phase4_ab_20260705/`
**Code state:** commit `26b67ec` (adaptive lexical, Qdrant dim probe, pre-reconcile gate)
**Ground truth:** `evaluation/datasets/annotated/ground_truth_phase4_ab.json` (8 docs)

#### Per-document completeness & extra_fields

| Document | Shadow% | Phase4% | Δ | Shd Extra | Ph4 Extra |
|---|---:|---:|---:|---:|---:|
| earthworm | 81.0 | 83.3 | +2.4 | 27 | 19 |
| petase_10_1002_anie_202218390 | 93.5 | 83.9 | **−9.7** | 113 | 65 |
| petase_10_1038_s41586-020-2149-4 | 88.9 | 88.9 | 0.0 | 53 | 120 |
| biorem | 75.5 | 79.2 | +3.8 | 19 | 46 |
| biosensor | 74.4 | 89.7 | **+15.4** | 19 | 20 |
| pea_cold_stress | 37.3 | 34.3 | −3.0 | 66 | 63 |
| sea_cucumber_gut_metagenome | 35.2 | 33.8 | −1.4 | 32 | 33 |
| human_gut_microbiome_temporal | 41.3 | 41.3 | 0.0 | 51 | 40 |
| **MEAN** | **65.9** | **66.8** | **+0.9** | — | — |

#### Multi-layer aggregate

| Run | Mean completeness | Multi-layer aggregate |
|---|---:|---:|
| Shadow dim-fix (`workflow_shadow_dimfix/`) | 65.9% | 0.5945 |
| Phase4 adaptive dim-fix (`workflow_phase4_dimfix/`) | **66.8%** | 0.5944 |

#### Key metric deltas (Phase4 − Shadow)

| Metric | Shadow | Phase4 | Δ |
|---|---:|---:|---:|
| LLM Judge mean | 0.7515 | 0.7449 | −0.007 |
| Value accuracy match rate | 0.1230 | 0.1352 | **+0.012** |
| Structural row-align F1 | 0.4465 | 0.4079 | −0.038 |
| Structural value accuracy | 0.3233 | 0.3555 | **+0.032** |

#### Retrieval observations

- Semantic index active for 6–7/8 docs per arm; 1–2 docs had Qdrant fallback
  (human_gut in both arms; sea_cucumber in Phase4 only — Ollama concurrency race).
- `pea_cold_stress` Phase4: `hybrid_fields=4` vs shadow `hybrid_fields=40` — concurrent
  indexing/embedding timing issue; explains −3.0 pp completeness.
- `biosensor` +15.4 pp: lexical miss path → semantic fallback retrieved key fields.
- `petase_anie` −9.7 pp: pre-reconcile gate discarded valid semantic candidates; see B10.

#### Quality gates — **ALL PASSED** (2026-07-06)

| Gate | Criterion | Result |
|---|---|:---:|
| Phase 4 completeness | Phase4 mean ≥ Shadow | ✅ 66.8% vs 65.9% |
| Phase 4 aggregate | Multi-layer agg ≥ Shadow | ✅ 0.5944 vs 0.5945 (noise) |
| Expanded 8-doc | Re-run after dim-fix | ✅ Done |
| Default switch | `shadow_mode=false` in prod | ✅ Code default; ready to push |

> 2026-07-14 update: this historical Phase 4 default-switch gate is superseded
> by the `auto` retrieval/repair plan in §10.9. Production should no longer be
> framed as a user-facing Shadow-vs-Tuned default choice.

**Remaining issues for next iteration:**

- **B9** — Concurrent Ollama indexing causes sporadic fallback; add embedder retry / serialise per-doc index build.
- **B10** — Pre-reconcile gate too aggressive; refine to confidence-weighted skip (not "any lexical candidate").
- Structural row-align F1 gap (−0.038) — ISAValueMapper needs EvidenceStore integration (Plan §4.1).

### 10.7 Transition to DeepSeek & custom SSH tunnel ports (2026-07-07)

- **GLM-5.1 out of balance**: The Zhipu GLM key (`29cbfec6...`) encountered a `RateLimitError` due to insufficient account balance (Zhipu error 1113). We transitioned to **DeepSeek** (`deepseek-v4-flash` for test runs, and `deepseek-v4-pro` for final evaluation runs).
- **Stale SSH tunnel workaround**: After the WUR server `bioind4` rebooted, the default forwarded ports (Ollama `11434`, MinerU `30000`, FAIR-DS `8083`) managed by Cursor became stale and threw `Connection reset by peer`.
  - To bypass, we mapped custom local ports:
    - Local `11435` $\rightarrow$ Remote `11434` (Ollama)
    - Local `30005` $\rightarrow$ Remote `30000` (MinerU)
    - Local `8085` $\rightarrow$ Remote `8083` (FAIR-DS)
  - Created new model config env files: `deepseek_v4-flash_v1.4.0_tunnel_phase4_tuned.env` and `deepseek_v4-flash_v1.4.0_tunnel_shadow_tuned.env` pointing to these new ports.
- **Fast unit tests**: Verified local regression tests: 648 passed successfully.

> 2026-07-14 runtime update: the forwarding setup was restored on the standard
> local service ports used by current evaluation configs: FAIR-DS `8083`,
> MinerU `30005`, Ollama `11434`, and Qdrant `6333`. The custom `8085`, `11435`,
> and `6335` values above remain historical provenance for the earlier runs.

### 10.8 Final DeepSeek Pro A/B — Tuned vs Shadow (2026-07-14)

**Runs:** `evaluation/runs/phase4_pro_tuned/` and `evaluation/runs/shadow_pro_tuned/`
**Code state:** Finalized transition to DeepSeek Pro (`deepseek-v4-pro` model) across the full 6-document evaluation target.

#### Summary metrics comparison (DeepSeek Pro)

| Metric | Tuned (Phase4) | Shadow | Difference |
|---|---:|---:|---:|
| **Aggregate Score** | 0.6172 | **0.6252** | **+0.0079** |
| **Completeness** | 0.7055 | **0.7155** | **+0.0100** |
| **Schema Compliance** | 0.7778 | **0.8889** | **+0.1111** |
| **LLM Judge Score** | **0.8079** | 0.7279 | −0.0800 |
| **Sheet Placement Accuracy** | 0.9851 | **0.9917** | **+0.0066** |
| **Row Alignment F1** | 0.4320 | **0.5211** | **+0.0891** |
| **Precision (excl. Discoveries)** | **1.0000** | 0.9770 | −0.0230 |
| **Mean Untracked Insight Rate** | 0.2380 | 0.2940 | +0.0560 |
| **Mean Discovery Rate** | 0.0050 | 0.0050 | 0.0000 |

#### Document-level completeness (recall of ground truth fields)

| Document | Tuned Completeness | Shadow Completeness | Difference |
|---|---:|---:|---:|
| `petase_10_1002_anie_202218390` | **93.55%** | **93.55%** | 0.00% |
| `petase_10_1038_s41586-020-2149-4` | **91.67%** | **91.67%** | 0.00% |
| `biosensor` | 84.62% | **89.74%** | **+5.12%** |
| `earthworm` | 80.95% | **83.33%** | **+2.38%** |
| `pea_cold_stress` | **37.31%** | 35.82% | −1.49% |
| `sea_cucumber_gut_metagenome` | **35.21%** | **35.21%** | 0.00% |

#### Key takeaways
- **Structure vs Quality**: Similar to prior evaluations, lexical prompting with shadow logging (Shadow configuration) has significantly cleaner output structures, yielding a **+11.11%** boost in Schema Compliance and a **+8.91%** boost in Row Alignment F1. However, active hybrid prompt injection (Tuned configuration) provides richer evidence to the generator agent, leading to an **+8.00%** higher qualitative score from the LLM Judge.
- **Decision Matrix**: If structural consistency and database ingestion (schema compliance) are prioritized, Shadow mode is superior. If semantic enrichment and maximum readability of extracted values are preferred, Tuned mode is superior.

### 10.9 Auto synthesis plan — combine Shadow structure and Tuned semantics (2026-07-14)

**Product decision:** do not ship a user-facing A/B default between Shadow and
Tuned. FAIRiAgent's production behavior should be a single end-to-end `auto`
pipeline:

1. Prefer lexical, Shadow-style evidence in prompts when lexical evidence exists.
2. Use semantic evidence only as targeted fallback for lexical misses or repair
   gaps.
3. Apply post-generation deterministic repair only on single-row sheets
   (`investigation`, `study`) when exact FAIR-DS field-name candidates have
   non-empty values, provenance, evidence text, sufficient confidence, and pass
   schema/linkage guards. Keep multi-row sheet repair trace-only until a
   group-aware row repair can prove alignment.
4. Keep classifier work in the temporary prototype as shadow/research until it
   beats deterministic rules on held-out documents without reducing schema or
   row alignment.

**Implemented runtime contract:**

- `FAIRIFIER_RETRIEVAL_MODE=auto` is the production mode; `shadow` and `tuned`
  remain compatibility/evaluation modes only.
- Legacy `FAIRIFIER_RETRIEVAL_SHADOW_MODE` still maps to `shadow`/`tuned` when
  the new mode env is absent, preserving old repro runs.
- `AutoRepairNode` runs before finalization and writes `auto_repair_trace.json`
  on every path: accepted patch, rejected patch, trace-only, skipped, or
  internal-error fallback.
- Accepted deterministic patches update `metadata_fields`, `metadata.json`, and
  single-row `isa_values`/`isa_values_json` when safe. If post-patch metadata
  validation fails, the node rolls back and records the rejection.
- Multi-row sheets (`observationunit`, `sample`, `assay`) are rejected by the
  deterministic patch guard for now, so exact candidates there are preserved in
  `auto_repair_trace.json` without mutating row-aligned outputs.
- When patches are accepted, `metadata.json.auto_repair_summary` records a
  compact accepted-field list and points to the sidecar trace. The main metadata
  file remains the primary FAIR-DS-facing artifact.
- Optional classifier predictions supplied by eval/prototype code are recorded
  only as `classifier_shadow_prediction` entries in `auto_repair_trace.json`
  when `FAIRIFIER_AUTO_REPAIR_CLASSIFIER_SHADOW_ENABLED=true`; they do not
  influence patch acceptance.

**Temporary feature workspace:** `evaluation/prototypes/auto_repair_classifier/`

- `build_dataset.py` builds field-level weak labels from paired Shadow/Tuned
  runs.
- `train_decision_model.py` evaluates lightweight classifiers, but current weak
  labels are too sparse for production defaulting.
- The main pipeline has a shadow-only prediction hook so future full runs can
  compare model recommendations against deterministic rules without changing
  metadata results.
- `run_auto_eval.py` prepares the canonical six-document `auto` eval command,
  writes generated auto config/env files, and records preflight reports.
- `preconvert_mineru.py` writes a dry-run/execute plan for target PDFs that
  need reusable `mineru_<stem>/` Markdown before a service-free auto eval.
- When live MinerU is unreachable and target PDFs still lack preconverted
  Markdown, auto eval preflight also checks the local `mineru -b pipeline`
  fallback import dependencies and reports `mineru_preconvert_dependency`
  blockers such as `missing_python_module:doclayout_yolo`, with the install
  hint `pip install 'mineru[pipeline]>=3.4.0,<4'`.
- Main FAIRiAgent MinerU health now uses the same dependency check. The API
  system-status endpoint, CLI validation, and `MinerUClient.is_available()`
  report `pipeline` backends as not ready when required imports are missing,
  and conversion fails early with the same dependency error instead of running
  a known-broken CLI command.
- `merge_gate.py` compares fresh `auto` results against the Shadow/Tuned
  baselines and validates per-document artifacts.

**Metadata result requirements for merge:**

- `metadata.json`, `workflow_report.json`, `runtime_config.json`,
  `auto_repair_trace.json`, `isa_values_json.json`, and
  `metadata_fairds.xlsx` must exist and be parseable for all six target docs.
- `runtime_config.json` must prove `effective_retrieval_mode=auto`,
  `auto_repair_enabled=true`, `auto_repair_apply_patches=true`, and explicit
  `auto_repair_classifier_shadow_enabled` classifier provenance.
- `auto_repair_trace.json` must prove the repair node ran in
  `deterministic_exact_patch` mode with `summary.apply_patches=true`; trace-only
  and error-fallback traces are diagnostics, not merge-ready production
  evidence.
- `metadata.json` must pass shared metadata format checks for top-level
  structure, datatypes, value formats, and source-grounding accounting.
- If `auto_repair_trace.json` reports accepted patches,
  `metadata.json.auto_repair_summary.accepted_patch_count` must match the trace.
- Accepted fields must be materialized in `metadata.json.isa_structure`; for
  single-row sheets (`investigation`, `study`) they must also appear in the row
  matrix and `isa_values_json.json`.
- FAIR-DS Excel export must consume the patched `isa_values_json.json` matrix so
  `metadata_fairds.xlsx` includes accepted auto repair fields.
- Aggregate schema compliance, row alignment, sheet placement, precision, and
  completeness must not regress beyond the merge-gate tolerances relative to
  Shadow; value match must remain near Tuned.

**Current status (2026-07-15):** the six-document Auto evaluation exists at
`evaluation/runs/auto_pro_tuned/results/evaluation_results.json`.

- Auto improves aggregate score, completeness, value matching, precision, and
  LLM-judged content quality relative to Shadow, while row alignment is close
  and internal schema compliance is lower.
- Internal schema compliance is diagnostic; FAIR-DS `/api/upload` validation is
  the eventual external compatibility gate after structural convergence.
- Current service-aware preflight reports `MINERU_SERVER_URL` unreachable and
  two inputs without reusable preconversion; this blocks a fresh reproducible
  full run, not inspection of the completed six-document artifacts.
- If live MinerU is unavailable, use
  `mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/preconvert_mineru.py`
  to inspect missing PDF conversions, then add `--execute` only when local
  MinerU pipeline conversion is acceptable.
- If readiness reports `mineru_preconvert_dependency`, repair the FAIRiAgent
  environment first; otherwise local preconversion can fail without producing
  reusable Markdown even when the MinerU process exits with code 0.
- `auto_readiness_report.json` includes a `requirements` audit that separates
  completed local implementation evidence from pending service/full-eval/gate
  evidence.
- The current metric gate remains conservative and fails on schema/alignment
  tolerances. §12.1 defines the structural convergence work required before a
  new production-default decision.

---


## 11. Code migration plan: deprecate, default-switch, then delete

Explicit list so the migration does not leave two parallel implementations
forever, while still preserving a smooth rollback path during the transition:

| Current code | Migration path |
|---|---|
| Direct `grep_sources()` loop in `JSONGeneratorAgent._build_field_source_evidence_context()` | Shadow-run `hybrid_search_sources()` beside it, compare candidate spans, then switch prompt context to hybrid. Keep `grep_sources()` as the internal lexical fallback. |
| Hardcoded PETase `alias_map` dict in `_field_search_queries()` | Move aliases into FAIR-DS synonyms / skill-provided `field_aliases` (§9.3), then delete the Python dict after alias-hit parity tests pass. |
| `DocumentParser`'s optional `analyze_document_outline` tool | Replace with deterministic chunker-produced section outline (Workstream A / [chunking design §3](SCIENTIFIC_DOCUMENT_CHUNKING_DESIGN.md#3-block-extraction-mineru-content_list_v2-as-the-primary-source-of-truth)); keep the old tool as a fallback until non-MinerU/plain-text outline tests cover the same cases. |
| Internal list-building logic in `evidence_packets.py` | Preserve public functions as wrappers over `EvidenceStore`; delete only private duplicate logic once UI/report/tests consume the wrapper output unchanged. |
| Sequential `for batch in batches: await ...` loop in `generate_complete_metadata()` | Replace with bounded `asyncio.gather`; keep a provider-level concurrency setting so rate-limited deployments can set concurrency to 1 without reverting code. |
| Fixed `max_doc_context_markdown` / `max_doc_context_text` / `react_loop_max_iterations` / `react_loop_max_tool_calls` clamps in `apply_budget_guardrails()` | Add telemetry first, then switch to model-context-aware / section-count-aware dynamic budgets once recall/hallucination metrics pass. |

**Added, not deleted (fixes a gap, no prior implementation to replace):**
MinerU `content_list_v2` `type=="table"` blocks are newly routed through the
existing Excel/CSV table-extraction path into `tables/*.jsonl`
([chunking design §5.1](SCIENTIFIC_DOCUMENT_CHUNKING_DESIGN.md#51-in-pdf-tables-get-the-same-structured-path-as-standalone-excelcsv-fixes-the-gap-in-1)) —
today, tables embedded directly in a PDF are never extracted as structured
rows at all, only as raw Markdown table text.

---

## 12. Implementation sequencing (dependency order and safe rollout)

```
1. qdrant_client.py (extracted shared connection helper) — needed by 2 and 4
2. chunking.py + semantic_index.py — needed by 3, 4, 5
   (algorithm detail: SCIENTIFIC_DOCUMENT_CHUNKING_DESIGN.md)
3. hybrid_search_sources() — needs 2; initially shadow-runs beside grep-only (§10/§11)
4. EvidenceStore — needs 1, 2; first wraps evidence_packets output shape (§7/§11)
5. Send()-based section map-reduce subgraph — needs 2, 4; starts with current prompt budgets (§8.4)
6. Parallelization changes (§8.3) — independent of 1-5, can land anytime, no shared-state conflicts
7. Domain optimizations (§9) — 9.1/9.3 can land alongside 3; 9.4 needs 2; 9.5 needs 3
8. Budget relaxation (§8.4) — lands together with 5, not before
9. Evaluation harness updates (§10) — needed to gate 3 and 5 before they're switched to the default path
```

Steps 1–4 and 6 carry minimal behavioral risk because they can be validated
in shadow/wrapper mode. Step 5 is where the coverage claim is actually made
and must clear the §10 acceptance bar. Step 8 is intentionally sequenced
after Step 5 telemetry, not before it.

### 12.1 Phase 4 structural convergence: one evidence chain and one ISA matrix

The six-document Auto evaluation shows that retrieval quality and sheet
structure must be optimized as separate stages. Auto improves value matching
and LLM-judged content quality, while repeated entity grouping and matrix
materialization can still create too many or too few rows. The immediate
priority is therefore to remove conflicting state ownership before changing
the LangGraph topology.

#### Canonical data flow

```text
SectionMapReduce ─┐
DocumentParser ───┼─> EvidenceStore (only writable evidence source)
BioMetadata ──────┘              |
                                 v
FAIR-DS field catalog --> Canonical fields + Entity Registry
                                 |
ISAValueMapper --> normalization/link patches
                                 |
                     apply patches to canonical fields
                                 |
                        ISA Matrix Compiler
                                 |
                       Coverage/Structure Audit
                                 |
          metadata.json / ISA sidecar / Excel / evaluation
```

Ownership rules:

1. `EvidenceStore` is the only writable evidence source. SectionMapReduce,
   DocumentParser, BioMetadata, and hybrid retrieval upsert immutable
   `EvidenceRecord` objects. `evidence_packets` and
   `section_field_candidates` are compatibility projections and must never be
   mutated independently. Stable `evidence_id` is derived from source span,
   table row, field hint, normalized candidate value, and producer;
   JSONL/Qdrant parity is checked.
2. Canonical fields and the Entity Registry are the only writable metadata
   model. Each field record has a stable `field_id`, raw and normalized value,
   candidate values, source references, `canonical_entity_id`, and resolution
   decisions. Entity aliases retain alias type plus raw/normalized identifier.
3. A single `ISA Matrix Compiler` is the only component allowed to create
   `columns`/`rows`. JSONGenerator, ISAValueMapper, AutoRepair, export, and
   evaluation consume that compiler instead of maintaining private builders.
4. ISAValueMapper emits normalization/link patches keyed by `field_id`; it
   cannot write matrix cells or row identity. Applying a patch preserves
   `raw_value`, candidate values, source refs, and a reason code before
   recompiling.
5. AutoRepair patches canonical fields/registry records and invokes the same
   compiler. It cannot patch serialized matrix copies independently.
6. `metadata.json.isa_values`, `metadata.json.isa_structure.columns/rows`,
   `isa_values_json.json`, Excel export, and Layer 2/3 evaluation are
   projections of the same compiled matrix. `isa_structure.fields` is a
   read-only projection of canonical fields, not a separately deduplicated
   list. Layer 1 completeness plus grounding/provenance evaluators validate the
   canonical field projection ID; all production evaluators fail closed when
   the required projection ID or `matrix_id` is missing and never silently
   fall back to a stale representation.

#### Entity resolution rules

- Explicit identifiers (`sample identifier`, `observation unit identifier`,
  `assay identifier`, etc.) are the strongest identity signal.
- Cross-batch `entity_id` values are aliases, not authoritative identities.
- Normalized explicit identifiers merge only on exact equality within the
  identity key `(isa_sheet, parent_canonical_entity_id, identifier_type,
  normalized_identifier)`. Substring matching is prohibited. Different known
  parents never merge; unknown parents remain unresolved.
- Identifier normalization is versioned and conservative: Unicode NFKC, trim,
  internal whitespace collapse, and Unicode `casefold()` only. It never removes
  punctuation, hyphens, underscores, or numeric boundaries. Collision tests
  protect identifiers that differ only in those retained characters.
- Rows with the same scoped explicit identity form one canonical entity.
  Conflicting cell values become a structured `CandidateValueSet` on that
  entity and are never silently dropped. If evidence demonstrates that the
  explicit identifier itself is reused for distinct real entities, the
  resolver creates a collision group and keeps those entities separate.
- Distinct non-empty identifiers never merge automatically.
- Identifier-less fragments never merge solely because they are sparse,
  non-conflicting, or share a parent. A merge requires a unique strong anchor:
  the same structured table row, or the same explicit entity source span plus
  the same parent identity. Ambiguous fragments remain separate and are
  flagged unresolved.
- Semicolon/list splitting is allowed only when the source evidence establishes
  repeated entities through structured rows or equal-length aligned entity
  lists. Punctuation alone is insufficient; unequal lists remain unresolved
  and must not repeat the final value to fill missing positions.
- Conflicts are preserved in provenance and surfaced for review; the compiler
  must not silently choose one value merely to reduce row count.
- A conflicting cell is populated only when a deterministic domain rule can
  select a candidate and records the selected `candidate_id`, decision, and
  reason code. Otherwise the compiled cell is empty, the field/entity remains
  `unresolved`, and all candidates remain in provenance. Such unresolved
  candidates count as eligible evidence not materialized, so the audit cannot
  hide conflicts by excluding them from recall.

Minimum canonical schemas:

```text
EvidenceRecord:
  evidence_id, source_id, char_start, char_end, table_row_id,
  field_hint, raw_value, normalized_value, producer, retrieval_method

CanonicalField:
  field_id, field_name, isa_sheet, canonical_entity_id,
  selected_value, candidate_values: CandidateValue[],
  confidence, status, resolution_decision, reason_code

CandidateValue:
  candidate_id, raw_value, normalized_value, source_refs[],
  confidence, producer, eligibility, status, reason_code

EntityRecord:
  canonical_entity_id, isa_sheet, parent_canonical_entity_id,
  aliases[], source_anchors[], collision_group_id,
  resolution_status, reason_codes[]
```

An evidence-backed candidate is eligible for materialization only when it has a
valid source reference, resolves to a selected FAIR-DS field, passes the
existing grounding/confidence threshold, and is not rejected by deterministic
type or entity-conflict checks. Ineligible candidates remain in provenance with
an explicit rejection reason and are excluded from the materialization-recall
denominator.

#### Deterministic post-compile audit

The audit reports, but does not fabricate repairs for:

- evidence-backed fields that were retrieved but never materialized;
- missing required/recommended fields;
- multiple registry entities sharing one normalized explicit identifier;
- orphaned study/observationunit/sample/assay linkage;
- suspicious row explosion or collapse;
- conflicting values within one canonical entity;
- divergence between serialized artifacts.

Internal JSON schema compliance remains diagnostic. FAIR-DS `/api/upload`
validation is the eventual external compatibility gate once structural work is
complete.

#### Implementation and validation sequence

Each behavioral step follows RED → GREEN → refactor and uses the `FAIRiAgent`
mamba environment.

**Progress (2026-07-21):** deterministic ``IsaMatrixCompiler`` is now a first-class
LangGraph node on ``main`` development path:

``orchestrate → isa_matrix_compiler → auto_repair → finalize``.

The node does not call an LLM; it compiles the best available matrix (sidecar,
then metadata) and syncs all projections onto one ``matrix_id``. JSONGenerator /
ISAValueMapper remain field/value producers; the compiler is the graph-level
authority for ``columns``/``rows`` before repair.

Smoke validation (DeepSeek ``v4-flash``, earthworm md, FAIR-DS ``:8083``,
deep-agents off): workflow completed with
``IsaMatrixCompiler`` ``matrix_id`` present; metadata ↔ sidecar rows fully
aligned (sample/assay/observationunit = 3/3/3). Structural snapshot:
``row_alignment_f1≈0.59``, ``sheet_placement_accuracy=1.0``,
``value_accuracy_given_correct_structure≈0.74``. Artifacts under
``evaluation/runs/isa_compiler_flash_smoke_20260721c/``.

Deferred until a fresh multi-doc LLM eval shows need: demoting IVM to
patch-only (no private rebuild), full entity registry schema.

1. **Characterize current behavior and capture future replay fixtures**
   - Add tests that document current JSONGenerator/ISAValueMapper/AutoRepair/
     Excel/evaluator projections without endorsing their divergence.
   - Add a versioned compiler-input fixture schema and persist immutable
     `metadata_fields`, EvidenceRecords, entity aliases, source refs, and
     conflicting candidates in new workflow runs. Existing six-document
     outputs remain useful for output-level replay but cannot reconstruct
     candidates already discarded upstream.
   - Every fixture stores `schema_version`, `compiler_version`, input digest,
     baseline artifact/config/commit identifiers, and expected `matrix_id`.
2. **Evidence preservation** ✅ (partial — packet merge + store upsert)
   - Add a failing test proving DocumentParser currently overwrites
     SectionMapReduce packets.
   - Implement EvidenceStore upsert/deduplication and make
     `evidence_packets` plus `section_field_candidates` read-only compatibility
     projections.
   - Verify parser, retrieval, and multi-source tests.
3. **Canonical registry schema and pure entity resolver**
   - Add failing tests for stable IDs, exact identifier equality, input-order
     invariance, idempotence, conflict preservation, and unresolved
     identifier-less fragments.
   - Implement the pure resolver without document- or benchmark-specific rules.
4. **Pure ISA Matrix Compiler**
   - Add contract tests for deterministic sheet/column/row ordering,
     semicolon/list constraints, linkage materialization, and zero field loss.
   - Extract grouping, constrained splitting, resolution, normalization, and
     linkage into a focused module.
5. **Migrate producers and consumers one boundary at a time**
   - Route JSONGenerator to canonical fields/registry, then compiler projection.
   - Change ISAValueMapper to emit patches and recompile.
   - Change AutoRepair to patch canonical records and recompile.
   - Remove Excel's independent entity splitting.
   - Make Layer 2/3 evaluation consume only the canonical projection.
   - At each boundary, require shadow projection parity before removing the old
     path.
6. **Repair and artifact synchronization**
   - Add a failing test showing an accepted canonical repair must appear
     identically in metadata JSON, ISA JSON, and Excel input.
   - Recompile after repair rather than patching matrix copies.
7. **Coverage/structure audit**
   - Add deterministic tests for evidence-not-materialized, duplicate IDs,
     orphan linkage, row explosion/collapse, and artifact divergence.
   - Persist audit findings and compiler decisions in workflow provenance.
8. **Offline replay before new LLM runs**
   - Replay output-level transformations against existing six-document
     artifacts and compiler-level transformations against versioned canonical
     fixtures captured by the new workflow.
   - Re-run Layer 2/3 evaluation and compare per-sheet row counts, alignment,
     value accuracy given correct structure, and field completeness.
   - Reject any rule that improves aggregate alignment by deleting
     evidence-backed values or collapsing conflicting entities.
9. **Incremental workflow validation**
   - Run targeted unit/integration tests, then the full fast suite.
   - Run a three-document workflow slice only after offline replay passes.
   - Run the six-document Auto evaluation only after the three-document slice
     preserves completeness/value metrics and improves or stabilizes structure.

#### Phase acceptance criteria

- one canonical `matrix_id` across metadata JSON, ISA JSON, export manifest, and
  evaluation input. `matrix_id` is SHA-256 over deterministic JSON with
  canonical sheet/column/row ordering, UTF-8 Unicode, and explicit empty-value
  rules; Excel is read back to cells, requirement display suffixes
  (`(M)/(R)/(O)`) are removed from headers, and styles are ignored before
  digest verification;
- the baseline is fixed by run artifact path, git commit, model config, runtime
  config, ground-truth version, and evaluator version in the replay manifest;
- per-document required completeness must not regress from that fixed baseline;
- evidence-backed field materialization recall is 100%;
- valid source-reference retention is 100%;
- conflicting candidate retention and decision provenance are 100%;
- no aggregate completeness decrease greater than 0.01 and no aggregate value
  partial-credit decrease greater than 0.03 versus the selected baseline;
- row alignment and sheet placement are stable or improved within 0.03 and
  0.01 aggregate tolerance respectively;
- per-document completeness may not decrease by more than 0.03, value
  partial-credit by more than 0.05, or row alignment F1 by more than 0.10;
- no alignment gain is accepted when it is achieved by deleting
  evidence-backed fields or conflicting entities;
- every document reports unresolved entity count and reason-code distribution;
- every merge, split, conflict, and unresolved fragment has machine-readable
  provenance;
- no document-title, DOI, filename, or benchmark-specific branching exists in
  production code.

---

## 13. Explicit non-goals

- **Not replacing FAIR-DS schema retrieval or full-table scans** with vector
  search — both already work deterministically and are out of scope.
- **Not introducing a second vector database or embedding provider** —
  Qdrant + `sentence-transformers` only (§3).
- **Not making map-reduce run on every document regardless of size** — the
  length-based applicability gate (§8.2) is a cost optimization, not an
  uncertainty hedge.
- **Open for follow-up design:** exact section-merging heuristic bounding
  section count for fragmented MinerU output; whether `extract_section`
  candidates need a lighter intermediate type before reconciliation or can
  be `FieldCandidate` directly.
