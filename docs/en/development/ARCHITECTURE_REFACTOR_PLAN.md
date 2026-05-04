# FAIRiAgent Architecture Refactor Plan

> **Based on:** Anthropic "Building effective agents" (2024) + Anthropic "Effective Context Engineering" (2025) + Claude Code architecture analysis (arXiv:2604.14228) + JetBrains context management research (2025) + internal FAIRiAgent code audit  
> **Refactor date:** 2026-05-04  
> **Status:** Phase 1–4 COMPLETED · Phase P3 (LangGraph native routing) pending

---

## Refactor Results (2026-05-04)

Branch: `refactor/architecture-v2`, commit `ed5f44e`  
Test suite: **417 tests pass** (29.5 s), 82 new TDD tests added for refactor modules.

### E2E comparison (qwen3.5:9b, ollama, A100)

| Metric | Run 1 — earthworm (pre-fix) | Run 2 — biosensor (post-fix) |
|--------|---------------------------|------------------------------|
| Overall confidence | 74.60 % | **80.89 %** |
| ISAValueMapper result | 2× ESCALATE (score 0.00) → auto-accept | **ACCEPT (score 0.85)** |
| Global retries | 3 / 6 | **1 / 5** |
| Format-check warnings | 29 | **13** |
| `context_usage` events logged | ❌ CLI overwrote file | **✅ 5 events, all agents** |
| Duration | 266 s | 169 s |

### Context-usage profile (Run 2, biosensor)

| Agent | State tokens | Dominant field |
|-------|-------------|----------------|
| DocumentParser | 86 | context (setup) |
| KnowledgeRetriever | 2,669 | evidence_packets + plan_tasks |
| JSONGenerator | ~160,000 | **retrieval_cache = 144,566** |
| ISAValueMapper | ~163,000 | retrieval_cache (carried through) |

`retrieval_cache` is the single largest state field (144 K tokens) — it is the memoised FAIR-DS API response cache. Not trimmed (per architecture principle below), but now visible for operator monitoring.

---

## 0. Core Principle

**"Simple workflows + strict context hygiene > complex multi-agent frameworks"**

FAIRiAgent is fundamentally a **highly-structured workflow integrating one true Agent (BioMetadataAgent) and multiple LLM Workers**, driven by a Critic-based evaluator-optimizer loop.

**The information-passing rule:** every token carried across a stage boundary must be there because it measurably increases the probability of the next stage succeeding. Noise is not neutral — it actively degrades output quality ("attention dilution", "context rot").

**No trimming of domain content.** The multi-agent setup exists precisely so each agent has a sufficient context window for complete, correct metadata extraction. A discarded low-confidence evidence item may be the only source for a required FAIR-DS field. Structural removals (execution_history bloat, document_content by reference) are fine because they remove unambiguously redundant data — not domain content.

---

## 1. ✅ P0 — document_info fixed schema

**Problem:** `DocumentInfoResponse` used `extra="allow"`, forcing 15+ defensive fallback chains in `json_generator.py`.

**Fix (implemented):**
- `fairifier/utils/doc_info_canonical.py` — `canonicalize_doc_info()` maps all known LLM field aliases to canonical names at DocumentParser's output boundary.
- `DocumentInfoResponse`: `extra="ignore"`, stable downstream schema.
- `json_generator.py`: `_build_document_info_compact()` reduced from ~130 lines to ~15 lines (direct field access only).

**Tests:** `tests/test_doc_info_canonical.py` — 31 tests.

---

## 2. ✅ P0 — Retry context isolation (Echo Chamber fix)

**Problem:** On retry, the LLM saw its own failed output + verbose critique prose → anchoring effect.

**The counter-intuitive finding:** JetBrains (2025) research shows LLM-generated summaries smooth away failure signals, causing 13–15% more wasted steps. Correct approach: **observation masking** — keep raw structured `issues` list, discard verbose prose critique and the failed output itself.

**Fix (implemented):**
- `fairifier/utils/retry_context.py` — `clean_critic_feedback_for_prompt()` strips `critique` prose and `previous_attempt` before passing feedback to LLM on retry.
- `fairifier/agents/base.py` — `get_context_feedback()` always sets `previous_attempt=None`.
- `fairifier/agents/react_loop.py` — `_compose_task_message()` no longer includes critique prose.

**Tests:** `tests/test_retry_context_isolation.py` — 11 tests.

---

## 2.5. ✅ P0 — execution_history pruning

**Problem:** 3 complete failed JSON outputs + 3 full Critic evaluations after JSONGenerator retry ×3 → 50K+ tokens of accumulated failure evidence in live state.

**Fix (implemented):**
- `fairifier/utils/execution_history.py` — `compact_execution_record()` strips `critique`, full `issues` list, `improvement_ops`, `suggestions`; keeps `score`, `decision`, `issues_count`.
- `langgraph_app.py` — `compact_prior_attempts_for_agent()` called at retry start and loop exit.

**Tests:** `tests/test_execution_history_compact.py` — 16 tests.

---

## 3. ⚠️ P1 — Declarative Agent Input/Output Schemas (partial)

**Problem:** Every agent receives the full `FAIRifierState` TypedDict (~40+ fields). Each agent only needs 3–5.

**Status — partially implemented:**
- `PlannerTask` dataclass defined in `fairifier/models.py`.
- `plan_tasks` field added to `FAIRifierState`.
- Agents still receive `full_state` — narrowly-scoped `AgentInput`/`AgentOutput` dataclasses are the **next major architectural step**.

**Remaining work:**
```python
@dataclass
class KnowledgeRetrieverInput:
    document_info: DocumentInfo
    evidence_packets: List[EvidencePacket]
    planner_task: Optional[PlannerTask]
    context_feedback: Optional[ContextFeedback]
    # NOT: execution_history, bio_file_paths, source_workspace, react_scratchpad, etc.
```
Orchestrator constructs each agent's input from full state; merges output back. Agents cannot accidentally read irrelevant state fields.

---

## 4. ✅ P1 — Structured Planner output

**Problem:** Planner output was free-form `special_instructions` prose; KnowledgeRetriever used regex to extract package names.

**Fix (implemented):**
- `fairifier/utils/planner_tasks.py` — `PlannerTask` dataclass, `parse_plan_tasks_from_llm_output()`, `extract_plan_task()`.
- `langgraph_app.py` — Planner prompt extended with structured `plan_tasks` array format; output parsed and stored in `state["plan_tasks"]`.
- `knowledge_retriever.py` — Consumes `plan_tasks` directly; structured `priority_packages` and `search_terms` take front position in candidate lists.

**Tests:** `tests/test_planner_structured.py` — 13 tests.

---

## 5. ✅ P1 — Large text by reference

**Problem:** `document_content` (hundreds of KB) carried in live state through the entire pipeline.

**Fix (implemented):**
- `fairifier/utils/document_text.py` — `read_document_text(state)` prefers `document_text_path` (disk), falls back to `document_content`, then empty string.
- `_read_file_node` — sets `state["document_content"] = None` when `markdown_path` exists.
- `document_parser.py`, `json_generator.py` — use `read_document_text(state)` for all text access.

**Tests:** `tests/test_document_text_by_reference.py` — 7 tests.

---

## 6. ✅ P2 — Context usage observability (monitor only, NO trimming)

**Fix (implemented):**
- `fairifier/utils/context_observability.py` — `estimate_tokens()` (tiktoken cl100k_base, fallback chars/4), `estimate_state_usage()` (tracks 18 key state fields), `log_context_usage()` (writes JSONL at each agent boundary).
- `langgraph_app.py` — `log_context_usage()` called at start of each agent attempt.
- `cli.py` — preserves inline `context_usage` events when writing final `processing_log.jsonl` (bug fix: was overwriting with `'w'` mode).
- `evaluation/scripts/analyze_refactor_run.py` — summarises context_usage and Critic decisions post-hoc.

**Tests:** `tests/test_context_observability.py` — 11 tests.

**Key finding from profiling:** `retrieval_cache` is the dominant state cost (144 K tokens). This is the memoised FAIR-DS API response cache carried from KnowledgeRetriever through JSONGenerator and ISAValueMapper. Per the no-trim principle it is not removed; but it is now visible for operator monitoring and informs future optimization strategy (e.g., moving it to disk like `document_content`).

---

## 7. ⏳ P3 — Native LangGraph routing (pending)

**Problem:** The orchestrator is a hardcoded linear sequence inside one LangGraph node (`orchestrate`). LangGraph sees only `read_file → orchestrate → finalize`. All agent routing, retry, and rollback is procedural Python.

**Planned fix:**
- Each agent becomes a proper LangGraph node.
- Conditional edges replace `if result == "RETRY": continue` logic.
- `Send` API for parallel execution (BioMetadataAgent + Planner in parallel when bio files present).
- Subgraph checkpoints restore LangGraph's per-agent checkpoint/resume.

```
read_file
    ↓
document_parser ←─── retry (conditional edge)
    ↓ (ACCEPT)
[bio_metadata ‖ planner]  ← parallel via Send API
    ↓
knowledge_retriever ←── retry
    ↓ (ACCEPT)
json_generator ←─── retry
    ↓ (ACCEPT)
isa_value_mapper
    ↓
finalize
```

**Why deferred:** Phases 1–4 are prerequisites. This is a high-effort rewrite (3–5 days) that should be gated on Phase 1–4 being stable in production evaluations.

---

## 8. Bug fixes found during E2E evaluation (2026-05-04)

These bugs were latent before the refactor and discovered during the first E2E run:

| Bug | Root cause | Fix |
|-----|-----------|-----|
| ISAValueMapper always ESCALATE (score 0.00) | `Critic.node_key_map` had no entry for `ISAValueMapper`; `_fallback_evaluation()` returned score 0 immediately | Added `"ISAValueMapper": "isa_value_mapper"` to map + `isa_value_mapper` rubric section + `_build_isa_mapper_context()` |
| ISAValueMapper LLM call failed | `_get_llm()` called `LLMHelper(provider=..., model=...)` but `LLMHelper.__init__()` takes no args | Changed to use `get_llm_helper()` factory |
| `context_usage` events lost from `processing_log.jsonl` | `cli.py` opened log in `'w'` mode, overwriting events written inline during run | Changed to read existing `context_usage` events first, then write merged output |

---

## 9. What stays the same (proven effective)

| Component | Why keep |
|-----------|---------|
| Critic + hard-gate closed loop | Evaluator-optimizer is the right paradigm for metadata generation |
| KnowledgeRetriever 4-phase pipeline | Package → mandatory → optional → term search is clean |
| Memory R+W gating | Retrieve-before-execute + write-on-accept prevents noise accumulation |
| No-progress detection (same score ×2 → auto-accept) | Correct and matches Anthropic best practice for stopping runaway retry loops |
| MinerU + PyMuPDF fallback | Document parsing flexibility is essential |
| BioMetadataAgent ReAct loop | Only true Agent in the system — keep its autonomy |
| Full transcript to JSONL | Audit log stays; just don't carry it in live state |

---

## 10. Next step optimizations

### 10.1 Retrieval cache by reference (high impact, low risk)

`retrieval_cache` (144 K tokens in current profiling) is the memoised FAIR-DS API response. It is constructed by KnowledgeRetriever and carried in state through all downstream agents — but only JSONGenerator and ISAValueMapper actually read it.

Analogous to the `document_content → document_text_path` fix (Phase 5): write `retrieval_cache` to disk after KnowledgeRetriever completes, clear from state, and have downstream agents read on demand. This is the single highest-impact remaining context reduction that does not trim any domain content.

### 10.2 JSONGenerator accept threshold tuning

Both E2E runs showed JSONGenerator retrying with score 0.65 (accept threshold 0.70) → no-progress detection auto-accepted. Two possible interpretations:
1. The Critic's `accept_threshold: 0.70` is slightly too strict for qwen3.5:9b's output style on this task.
2. The JSONGenerator prompt needs improvement to consistently produce 0.70+ output.

Recommended: run 5–10 evaluations on the same dataset, track Critic score distribution per agent, and adjust thresholds based on observed model capability. The current threshold was set for larger models.

### 10.3 Agent I/O schema isolation (Phase 3a)

Agents still receive `full_state`. Implement narrowly-scoped `AgentInput`/`AgentOutput` dataclasses so that:
- Agents cannot accidentally read irrelevant state (implicit dependency elimination).
- The orchestrator explicitly controls what enters and leaves each agent boundary.
- Type checking at agent boundaries becomes possible.

### 10.4 Native LangGraph routing (Phase P3)

See §7 above. The main benefits: per-agent LangGraph checkpoint/resume, parallel BioMetadataAgent + Planner, clean separation of retry logic from agent logic.

### 10.5 Ground truth evaluation methodology

Current `compare_values_against_gt.py` scores (biosensor: 9%, earthworm: 21%) use substring matching. These are low partly because:
- GT has multi-row sample/assay tables (e.g., 6 observation units, 7 samples) that LLM consolidates into fewer rows.
- Exact value matching fails on numeric IDs (`ncbi taxonomy id: 4577`) that LLM formats differently.
- qwen3.5:9b is smaller than models used during ground truth annotation.

Better metric: semantic similarity (BERTScore or sentence-transformers) + field coverage (fraction of GT fields populated regardless of value accuracy).

---

## 11. Mental model

```
┌──────────────────────────────────────────────────────────────┐
│                      LangGraph Graph                          │
│                                                               │
│  read_file → [document_parser] ←──────────────────┐          │
│                    ↓ (ACCEPT)                      │ RETRY    │
│              [bio_meta ‖ planner] (parallel)       │          │
│                    ↓                      ┌────────┘          │
│           [knowledge_retriever] ←─────────┤                   │
│                    ↓ (ACCEPT)             │ RETRY             │
│             [json_generator] ←────────────┤                   │
│                    ↓ (ACCEPT)             │ RETRY             │
│             [isa_value_mapper]            │                   │
│                    ↓             [critic_node] ───────────────┘
│                finalize                                        │
│                    │                  ESCALATE → terminal     │
└──────────────────────────────────────────────────────────────┘

Per-agent contract (target state after Phase 3a):
  Worker.execute(AgentInput) → AgentOutput
  Orchestrator merges output into state, routes via Critic

Context at each boundary (current state):
  DocumentParser     ~86 tokens     (lean)
  KnowledgeRetriever ~2,700 tokens  (plan_tasks visible)
  JSONGenerator      ~160,000 tokens (retrieval_cache dominates — §10.1)
  ISAValueMapper     ~163,000 tokens (same)
```

- **Workers** (Parser, Retriever, Generator, ISAValueMapper): single LLM call, fixed input/output, no autonomy.
- **Agent** (BioMetadataAgent): LLM-driven action-observation loop, can call external tools.
- **Evaluator** (Critic): rubric-based quality assessment, structured `issues` + `suggestions` only on retry path.
- **Orchestrator** (LangGraph graph — target): native conditional edges + Send API, NOT a procedural Python loop.
