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
