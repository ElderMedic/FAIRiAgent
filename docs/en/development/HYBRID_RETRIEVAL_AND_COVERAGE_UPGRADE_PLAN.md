# Hybrid Retrieval, Evidence Store, and Deterministic Coverage — Upgrade Plan

> **Status: PROPOSED (v1.5.0 candidate)**
> This document supersedes the "no vector RAG" guardrail in
> [SOURCE_GROUNDING_ARCHITECTURE.md](SOURCE_GROUNDING_ARCHITECTURE.md) for the
> scope described here. It complements — and does not replace —
> [UPSTREAM_CANDIDATE_MERGING.md](UPSTREAM_CANDIDATE_MERGING.md), which stays
> the consensus/reconciliation layer that all new candidate sources feed into.

---

## 1. Problem statement

Three compounding gaps in the current (v1.4.0) pipeline can cause **missed
information**, not just occasional wrong values:

1. **Context truncation** — `extract_document_info()` and
   `generate_complete_metadata()` bound input text to conservative character
   budgets (`max_doc_context_markdown=200000`, `max_doc_context_text=120000`,
   per-field budgets in `_prepare_metadata_document_context`). Middle sections
   of long documents can be dropped entirely.
2. **Lexical-only retrieval** — `grep_sources()` / `search_table()` are exact,
   case-insensitive substring matches (`re.escape(query)`). Paraphrases,
   synonyms, and field-name mismatches produce **zero hits**, and a field with
   no hits gets no evidence at all.
3. **Model-judgment-dependent coverage** — the only "read more" mechanism
   today is the optional DeepAgent inner loop (`DocumentParser`,
   `KnowledgeRetriever`, `ISAValueMapper`), which is capped at
   `react_loop_max_iterations=6` / `react_loop_max_tool_calls=18`, is skipped
   entirely for long Qwen inputs, and delegates to its `section-analyst`
   subagent **only when the model decides to**. There is no guarantee that
   every section of a long or multi-file document is ever inspected.

None of this is a bug — it is a deliberate v1.4.0 trade-off (see guardrail:
*"Do not add vector RAG for this path unless explicitly requested"*). This
plan implements the requested next step: hybrid (lexical + semantic)
retrieval, a redesigned evidence substrate, deterministic section coverage,
and a token-budget policy that is safe to relax because coverage no longer
depends on one large call succeeding.

---

## 2. Design principles (carried over from existing guardrails)

- **Backward-compatible provenance.** Every new candidate — grep, semantic,
  or map-reduce — must still resolve to a `source_id:char_start-char_end`
  citation compatible with `SOURCE_REF_PATTERN`
  (`fairifier/utils/grounding.py`). No parallel citation format.
- **Feed the existing reconciliation layer, don't replace it.** New candidate
  sources plug into `FieldCandidate` / `_upstream_reconcile_candidates()`
  (`UPSTREAM_CANDIDATE_MERGING.md`) as additional inputs, not a competing
  pipeline.
- **Deterministic coverage over model-judgment coverage.** Per LangGraph and
  LangChain deep-agents guidance: *"coverage guaranteed by code, not model
  judgment"* — the fix for omission is a code-level loop over sections
  (`Send()` map-reduce), with agentic/DeepAgent delegation used for
  judgment-heavy tasks (package selection, skill matching), not for
  guaranteeing that text was read.
- **Everything is config-gated and falls back to v1.4.0 behavior.** Each
  workstream ships behind a flag, defaults to *off* until validated on the
  existing evaluation datasets (earthworm, Haarika+Bhamidipati, BIOREM), and
  degrades gracefully (semantic index build failure → grep-only; map-reduce
  timeout → existing single-call path).
- **Reuse existing infra.** `sentence-transformers` and `qdrant-client` are
  already dependencies (via `mem0_service.py`). No new vector DB or embedding
  provider is introduced.

---

## 3. Architecture overview

```mermaid
flowchart TD
    subgraph INGEST["Ingestion (existing)"]
        A[PDF/text/zip] --> B[MinerU/PyMuPDF]
        B --> SW[source_workspace/*]
    end

    subgraph NEW_INDEX["NEW: Chunk + Semantic Index"]
        SW --> CH[chunker.py section-aware chunks]
        CH --> EMB[semantic_index.py embeddings]
        EMB --> QD[(Qdrant per-run collection\nor local fallback)]
        CH --> MAN[chunk_manifest.jsonl]
    end

    subgraph NEW_MAPREDUCE["NEW: Deterministic Section Map-Reduce"]
        CH --> PLAN[plan_sections node]
        PLAN -->|Send x N| WORK[extract_section worker\n(parallel, bounded)]
        WORK --> RED[reduce_candidates node]
    end

    subgraph NEW_EVIDENCE["NEW: Evidence Store"]
        RED --> ES[(EvidenceStore\nqueryable, embedded)]
        DP[DocumentParser] --> ES
        JG_HYBRID[hybrid_search_sources] --> ES
    end

    subgraph EXISTING["Existing (unchanged contracts)"]
        ES --> UCM[_upstream_reconcile_candidates]
        UCM --> GEN[generate_complete_metadata]
        GEN --> PC[post-check / SOURCE_REF_PATTERN]
        PC --> OUT[metadata.json]
    end

    QD --> JG_HYBRID
    SW --> JG_HYBRID
```

Four new workstreams (A–D) plug into the existing pipeline without changing
its public contracts; two adjustment workstreams (E–F) tune existing
DeepAgent/budget behavior once A–D exist; one workstream (G) updates docs and
adds the metric needed to prove the fix works.

---

## 4. Workstream A — Section-aware chunking + semantic index

**New files:** `fairifier/services/chunking.py`, `fairifier/services/semantic_index.py`

### Chunking

- Split each preserved source (`source_workspace/sources/source_*.md`) using
  a heading-aware strategy first (MinerU output preserves `#`/`##` structure),
  falling back to a fixed token window (~450 tokens, ~15% overlap) for
  headerless text.
- Every chunk keeps **exact character offsets into the original source file**
  so its citation is `source_NNN:char_start-char_end` — identical format to
  existing `grep_sources()` output. This is the key compatibility constraint:
  the grounding regex and `_postcheck_source_grounding()` need zero changes.
- Persist a manifest parallel to the existing `tables/*.jsonl` convention:
  `source_workspace/chunks/chunk_manifest.jsonl` — one JSON line per chunk
  (`chunk_id`, `source_id`, `char_start`, `char_end`, `section_heading`,
  `source_role`, `token_count`).

```python
@dataclass
class SourceChunk:
    chunk_id: str
    source_id: str
    char_start: int
    char_end: int
    text: str
    section_heading: Optional[str]
    source_role: str
```

### Semantic index

- Embed chunks with `sentence-transformers` (reuse the model already
  configured for `mem0` via `MEM0_EMBEDDING_MODEL`, default
  `all-MiniLM-L6-v2`; allow override via
  `FAIRIFIER_SEMANTIC_EMBEDDING_MODEL`).
- Store vectors in a **per-run Qdrant collection** (`run_{session_id}_chunks`,
  TTL-cleaned like mem0's session scope) when Qdrant is reachable; fall back
  to an in-process numpy cosine-similarity index
  (`source_workspace/chunks/vectors.npy` + `chunk_ids.json`) when it is not —
  mirroring `mem0_service.py`'s existing health-check/fallback pattern so no
  new hard infra dependency is introduced.
- Index build happens once per run, right after `source_workspace`
  materialization, in `ReadFileNode` (or a new lightweight node immediately
  after it) — not lazily inside JSONGenerator, so both DocumentParser and the
  map-reduce workers (Workstream C) can use it.

**Config:** `FAIRIFIER_SEMANTIC_INDEX_ENABLED` (default `false` until
validated), `FAIRIFIER_SEMANTIC_CHUNK_SIZE_TOKENS`,
`FAIRIFIER_SEMANTIC_CHUNK_OVERLAP_TOKENS`, `FAIRIFIER_SEMANTIC_EMBEDDING_MODEL`,
`FAIRIFIER_SEMANTIC_TOP_K`.

---

## 5. Workstream B — Hybrid retrieval (grep + semantic + RRF + optional rerank)

**New function:** `hybrid_search_sources()` in `fairifier/services/source_workspace.py`
(same module as `grep_sources`, so it is a drop-in sibling, not a parallel
service).

```python
def hybrid_search_sources(
    workspace: SourceWorkspace,
    field_name: str,
    description: str,
    aliases: list[str],
    *,
    top_k: int = 8,
) -> List[FieldCandidate]:
    lexical_hits = []
    for q in build_field_search_queries(field_name, description, aliases):
        lexical_hits.extend(grep_sources(workspace, q))          # existing, unchanged

    semantic_hits = []
    if config.semantic_index_enabled:
        query_text = f"{field_name}: {description}"
        semantic_hits = semantic_search_chunks(workspace, query_text, top_k=top_k * 3)

    fused = reciprocal_rank_fusion([lexical_hits, semantic_hits], k=60)  # RRF, no score calibration needed

    if config.rerank_enabled and fused:
        fused = cross_encoder_rerank(query_text, fused, top_k=top_k)     # optional, CPU cross-encoder

    return [to_field_candidate(hit, retrieval_method=hit.method) for hit in fused[:top_k]]
```

- **Reciprocal Rank Fusion (RRF)** is used to combine lexical and semantic
  rankings because it needs no score normalization between BM25-like grep
  hits and cosine similarities — standard practice in 2026 hybrid-RAG
  pipelines (BM25 + dense + RRF, then optional cross-encoder rerank on the
  fused top-K).
- **Cross-encoder rerank** (`cross-encoder/ms-marco-MiniLM-L-6-v2` via
  `sentence-transformers`, CPU-friendly) is optional and config-gated
  (`FAIRIFIER_RERANK_ENABLED`) — adds precision for ambiguous fields at the
  cost of extra latency; default off, enable per-deployment.
- `FieldCandidate` gains one new observability field:
  `retrieval_method: Literal["grep", "semantic", "hybrid"]` — used for
  telemetry and for the evaluation metric in Workstream G, not for grounding
  logic (grounding still only cares about the `source_id:start-end`
  citation).
- **Call sites to update:** `JSONGeneratorAgent._build_field_source_evidence_context()`,
  `DocumentParserAgent`'s `focused_field_extraction` tool, and
  `ISAValueMapperAgent`'s grep usage — one shared utility, three integration
  points, so a synonym missed by grep in one agent doesn't need a separate
  fix in another.
- **Fallback:** if `config.semantic_index_enabled` is `false` or index build
  failed for this run, `hybrid_search_sources()` degrades to exactly today's
  `grep_sources()` behavior — zero risk to existing deployments.

**Config:** `FAIRIFIER_HYBRID_RETRIEVAL_ENABLED`, `FAIRIFIER_RERANK_ENABLED`,
`FAIRIFIER_RERANK_MODEL`, `FAIRIFIER_RRF_K` (default 60).

---

## 6. Workstream C — Evidence Store (replaces the static evidence-packet model)

**New file:** `fairifier/services/evidence_store.py`

### Problem with today's design

`evidence_packets` are built **once**, statically, by `DocumentParser` via
`build_evidence_packets()` / `build_evidence_context()`, capped at N
packets/chars, and passed downstream as an opaque text blob
(`fairifier/services/evidence_packets.py`). `source_workspace` is a static
manifest plus on-demand grep. Neither is queryable, incrementally
extendable, or shared across agents/subagents — each agent that wants "more
context" can only re-grep raw text.

### Redesign

```python
@dataclass
class EvidenceItem:
    id: str
    text: str
    source_id: str
    char_start: int
    char_end: int
    field_hints: list[str]        # which field names this likely supports
    produced_by: str              # "DocumentParser" | "SectionMapReduce" | "hybrid_search" | ...
    confidence: float
    embedding_id: Optional[str]   # points into the Workstream A index

class EvidenceStore:
    def add(self, items: list[EvidenceItem]) -> None: ...
    def query(self, text: str, top_k: int = 8, field_hint: str | None = None) -> list[EvidenceItem]: ...
    def export_context(self, max_chars: int) -> str: ...   # backward-compatible flat text for prompts
```

- Backed by the **same semantic index** as Workstream A — every evidence
  item any agent produces (DocumentParser's packets, map-reduce workers'
  spans, hybrid-search hits, JSONGenerator's reconciled candidates) becomes
  queryable by any other agent, instead of disjoint per-agent structures.
  This is the in-run analogue of what `mem0` already does across runs — the
  gap `mem0_service.py` explicitly leaves open ("not document RAG") is now
  filled for the *current* document.
- `EvidenceStore.export_context()` reimplements today's
  `build_evidence_context()` output shape exactly, so existing prompts in
  `llm_helper.py` need no changes — this is purely an internal upgrade of
  how the text is assembled, not a new prompt contract.
- `source_workspace.md`'s inventory gains a **section outline**, produced by
  promoting DocumentParser's existing (optional, tool-gated)
  `analyze_document_outline` to a **deterministic step run once during
  ingestion**, so section boundaries exist before any agent runs and can
  drive Workstream D's fan-out.

**Config:** `FAIRIFIER_EVIDENCE_STORE_ENABLED` (defaults to mirroring
`FAIRIFIER_SEMANTIC_INDEX_ENABLED`; store still works — as a plain list — when
the semantic index is off, just without similarity queries).

---

## 7. Workstream D — Deterministic section-level map-reduce (the actual fix for omissions)

This is the workstream that directly addresses "遗漏信息" (missed
information): coverage becomes a property of **code**, not of whether a
DeepAgent decided to call `section-analyst`.

### Why LangGraph `Send()` instead of DeepAgent dynamic subagents

Both are valid per current LangChain/LangGraph guidance:

| Approach | Coverage guarantee | Fits this repo's guardrail culture |
|---|---|---|
| **LangGraph `Send()` map-reduce** | Deterministic — a `for section in sections` router always fans out one `Send` per section | Yes — testable, budgeted, same style as existing `apply_budget_guardrails`, explicit fallback semantics |
| **DeepAgents dynamic subagents** (`CodeInterpreterMiddleware` + `task()`, triggered by phrasing a request as a "workflow") | Model-authored orchestration code — usually complete, but still one more model decision away from guaranteed | Complementary for judgment-heavy steps (see Workstream E), riskier as the *sole* coverage mechanism |

**Recommendation:** use `Send()`-based map-reduce as the primary, guaranteed
coverage mechanism (this workstream); keep DeepAgent subagents for
judgment tasks (package/skill selection) as today, optionally upgraded with
dynamic subagents later (Workstream E) as a complementary flexibility layer,
not a replacement.

### Graph shape

New subgraph inserted after `ReadFileNode`, before `OrchestrateNode` (or as
its own graph node `SectionExtractNode` that `OrchestrateNode` awaits before
`DocumentParser`):

```python
def plan_sections(state: FAIRifierState) -> dict:
    chunks = state["source_chunks"]                    # from Workstream A
    sections = merge_small_chunks_into_sections(
        chunks, max_sections=config.mapreduce_max_sections
    )
    return {"pending_sections": sections}

def route_to_workers(state: FAIRifierState) -> list[Send]:
    return [
        Send("extract_section", {"section": s, "fairds_field_catalog_summary": state["field_catalog_summary"]})
        for s in state["pending_sections"]
    ]

async def extract_section(payload: dict) -> dict:
    # Small, focused LLM call: ONE section + a compact FAIR-DS field catalog summary.
    # No document-wide context needed here — this is what keeps per-call cost bounded
    # even as global budgets (Workstream F) are relaxed.
    candidates = await llm_helper.extract_section_candidates(
        payload["section"], payload["fairds_field_catalog_summary"]
    )
    return {"section_candidates": candidates}           # reducer key uses Annotated[list, operator.add]

def reduce_candidates(state: FAIRifierState) -> dict:
    evidence_store.add(state["section_candidates"])      # -> Workstream C
    return {}

graph.add_node("plan_sections", plan_sections)
graph.add_node("extract_section", extract_section)
graph.add_node("reduce_candidates", reduce_candidates)
graph.add_conditional_edges("plan_sections", route_to_workers, ["extract_section"])
graph.add_edge("extract_section", "reduce_candidates")
```

- `state["section_candidates"]` uses LangGraph's standard map-reduce
  accumulator pattern (`Annotated[list, operator.add]`) so parallel worker
  outputs merge safely without manual locking.
- Each `extract_section` candidate still carries `source_id:char_start-char_end`
  (known exactly from the chunker), so it plugs directly into
  `_upstream_reconcile_candidates()` as a "Layer 0" candidate — no changes
  needed to the existing consensus-scoring logic in
  `UPSTREAM_CANDIDATE_MERGING.md`.
- **Bounded concurrency + graceful partial failure:** cap parallel workers
  (reuse the same 5-worker pattern already used in
  `evaluation/scripts/run_batch_evaluation.py`), and treat a failed/timed-out
  section worker as "zero candidates from that section" rather than failing
  the whole run — consistent with the existing Critic
  ESCALATE-but-continue philosophy.
- **Cost control / applicability gate:** skip this subgraph entirely for
  short documents that already fit comfortably in the existing single-call
  budget (`len(document_text) <= config.mapreduce_min_doc_chars`), since
  map-reduce trades higher total token cost for guaranteed coverage — only
  worth it once truncation risk is real.

**Config:** `FAIRIFIER_MAPREDUCE_ENABLED` (default `false` until validated),
`FAIRIFIER_MAPREDUCE_MIN_DOC_CHARS` (skip below this size),
`FAIRIFIER_MAPREDUCE_MAX_SECTIONS`, `FAIRIFIER_MAPREDUCE_MAX_PARALLEL_WORKERS`,
`FAIRIFIER_MAPREDUCE_WORKER_TIMEOUT_S`.

---

## 8. Workstream E — Deeper subagent integration (judgment tasks, not coverage)

Once Workstreams A–D exist, extend the *existing* DeepAgent inner loops
rather than introduce a second orchestration system:

1. **Raise inner-loop budgets.** `react_loop_max_iterations` /
   `react_loop_max_tool_calls` are currently hard-clamped in
   `apply_budget_guardrails()` (`config.py`) to 6 / 18 regardless of
   configured value. Replace the fixed clamp with a **document-size-aware**
   ceiling (e.g., scale with estimated section count from Workstream A, up to
   a higher hard ceiling) — see Workstream F for the paired budget policy.
2. **Give existing subagents (`section-analyst`, `package-selector`,
   `field-selector`) read/write access to the Evidence Store** (Workstream
   C) instead of returning results only into the parent DeepAgent's turn
   context. This means a retry that rebuilds the parent loop does not lose
   evidence a subagent already found — it persists in the store.
3. **Optional (higher risk, Phase 2): adopt dynamic/programmatic
   subagents.** LangChain's `CodeInterpreterMiddleware` lets a deep agent
   dispatch `section-analyst` over a full outline from a short orchestration
   script (loops/branches/parallel batches) instead of one `task` tool call
   at a time, when the request is phrased as a "workflow". This is
   complementary flexibility for DocumentParser/KnowledgeRetriever's
   judgment calls (e.g., "which sections need bio tools"), not a
   replacement for Workstream D's deterministic guarantee — the
   `for section in sections: Send(...)` graph-level loop is still what
   proves every section was visited, because it does not depend on the
   model choosing to write correct orchestration code.
4. **Keep `ISAValueMapper`'s cardinality-gate fallback.** Its
   `_CARDINALITY_CAP` deterministic-heuristic fallback for high-entity-count
   documents remains a valid safety net; it should read from the (now
   richer) Evidence Store so the heuristic path also benefits from
   Workstream D's coverage.

---

## 9. Workstream F — Token budget relaxation (paired with, not independent of, D)

Relaxing budgets *before* Workstream D exists just reproduces today's
truncation risk at higher cost. Sequenced correctly:

- Replace hardcoded conservative constants
  (`max_doc_context_markdown=200000`, `max_doc_context_text=120000`) with a
  **model-context-aware budget**: `resolve_doc_context_budget(is_structured_markdown)`
  computed from the configured LLM's context window minus reserved output
  tokens, instead of a fixed constant sized for "worst-case cheap model".
- Remove/raise the artificial ceiling in `apply_budget_guardrails()`
  (`config_instance.max_doc_context_markdown = min(config_instance.max_doc_context_markdown, 200000)`)
  **conditionally on `FAIRIFIER_MAPREDUCE_ENABLED=true`** — i.e., only allow
  larger single-call budgets once the deterministic coverage safety net
  exists to catch what a still-truncated single call misses.
- Same conditional relaxation for `metadata_max_context_chars_per_field` and
  the `react_loop_max_iterations` / `react_loop_max_tool_calls` clamps
  (Workstream E item 1).
- **Add telemetry**, not just higher numbers: extend
  `workflow_report.json` / Critic feedback with per-phase token/cost/latency
  and the new section-coverage metric (Workstream G) so budget relaxation is
  validated empirically per model/provider before becoming a default,
  matching the existing "Verified outcome on the earthworm dataset..." style
  already used in `SOURCE_GROUNDING_ARCHITECTURE.md`.

**Config:** `FAIRIFIER_DOC_CONTEXT_BUDGET_MODE` (`fixed` | `model_aware`,
default `fixed` until Workstream D ships), reuse existing
`MAX_DOC_CONTEXT_MARKDOWN` / `MAX_DOC_CONTEXT_TEXT` /
`REACT_LOOP_MAX_ITERATIONS` / `REACT_LOOP_MAX_TOOL_CALLS` as override escape
hatches.

---

## 10. Workstream G — Guardrail, evaluation, and doc updates

1. **Update `SOURCE_GROUNDING_ARCHITECTURE.md`.** Replace *"Do not add vector
   RAG for this path unless explicitly requested"* with a scoped statement:
   semantic retrieval is now allowed **only** as an additional ranking signal
   inside `hybrid_search_sources()`, fused via RRF with existing lexical
   grep, and only for field-evidence discovery — FAIR-DS schema retrieval and
   full-table scans stay deterministic/API-backed as before.
2. **New evaluation metric: section-coverage recall.** Today's metrics
   (`docs/en/EVALUATION_METHODOLOGY.md`) measure field presence/precision,
   not whether the source text supporting a ground-truth field was ever
   inspected. Add a metric that checks, per ground-truth field, whether *any*
   candidate (from grep, semantic search, or map-reduce) cites a source span
   overlapping the annotated evidence location — this is the metric that
   actually proves Workstream D reduces omissions, as opposed to only
   changing field-presence counts.
3. **A/B rollout on existing datasets** (earthworm, Haarika+Bhamidipati,
   BIOREM holdout) comparing: field coverage, section-coverage recall,
   hallucination rate (Critic faithfulness + `ungrounded_high_confidence_fields`),
   token cost, and latency — before flipping any default flag to `true`.

---

## 11. Rollout sequencing (technical dependencies, not calendar estimates)

```
Phase 1 (additive, default OFF, no behavior change when disabled)
  A. chunking.py + semantic_index.py
  B. hybrid_search_sources() wired into JSONGenerator/DocumentParser/ISAValueMapper
     — grep-only fallback if semantic index unavailable
  Tests: chunk offset correctness, RRF fusion determinism, FieldCandidate
  shape unchanged, grounding regex still matches new citations.

Phase 2 (backward-compatible internal refactor)
  C. EvidenceStore replacing internals of build_evidence_context/build_evidence_packets
     — export_context() output byte-for-byte compatible with today's prompts.
  Tests: store round-trip, existing prompt/evidence tests unchanged.

Phase 3 (the coverage fix — still default OFF)
  D. Send()-based section map-reduce subgraph, gated by document-length threshold.
  G.2 section-coverage recall metric.
  A/B evaluation on earthworm / Haarika+Bhamidipati / BIOREM before enabling by default.

Phase 4 (gated on Phase 3 evaluation results)
  E. Raise DeepAgent budgets + shared Evidence Store access for subagents;
     optional dynamic/programmatic subagents for judgment tasks.
  F. Model-context-aware budget relaxation, conditional on MAPREDUCE_ENABLED.
  G.1 Guardrail doc update to reflect the new default posture.
```

Each phase ships independently reviewable and testable; Phase 1–2 carry no
runtime-behavior risk (flags default off, fallback paths identical to
v1.4.0); Phase 3 is where the actual omission-reduction claim gets measured;
Phase 4 only relaxes cost/latency-sensitive knobs once Phase 3 data justifies
it.

---

## 12. Open questions / explicit non-goals

- **Not replacing FAIR-DS schema retrieval or full-table scans** with vector
  search — both already work deterministically and are out of scope.
- **Not introducing a new vector database.** Reuses the Qdrant instance and
  `sentence-transformers` dependency already present for `mem0_service.py`.
- **Not making map-reduce mandatory.** It is a cost/coverage trade-off gated
  by document length; short, well-structured documents should continue to
  use the existing single-call path unchanged.
- **Open for follow-up design:** exact section-merging heuristic (how small
  chunks get grouped into "sections" for Workstream D so section count stays
  bounded for very fragmented MinerU output), and whether
  `extract_section` candidates should be typed identically to
  `FieldCandidate` or need a lighter-weight intermediate type before
  reconciliation.
