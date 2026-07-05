# Hybrid Retrieval & Phase 4 — Handover Document

**Last updated:** 2026-07-05  
**Branch:** `cursor/hybrid-retrieval-agentic-upgrade-plan-d719`  
**Author session:** Cursor agent (hybrid-retrieval upgrade plan execution)  
**Prior conversation transcript:** `.cursor/projects/.../agent-transcripts/63c70f9b-2be3-4f37-a30e-5630ad9d872e.jsonl` (search keywords: `phase4`, `adaptive lexical`, `dim mismatch`, `shadow_dimfix`)

---

## 中文摘要（接手必读）

本分支实现 **Hybrid Retrieval + Phase 4** 架构升级。核心结论：

1. **Phase 4 质量门（completeness）已通过**：在修复 Qdrant 向量维度错配后，3-doc A/B 显示 Phase4 adaptive mean **87.8%** ≥ shadow **85.5%**。
2. **仍有未提交代码**（见 §2）— 接手后应先 review、跑测试、commit，再 push。
3. **MinerU 端口为 `:30000`**（`MINERU_SERVER_URL=http://localhost:30000`）。此前 agent 文档误写 `:30001`，**从未经许可**；eval env 已改回 30000。服务不可用时停跑并报告，**不要改端口**。
4. **下一步**：8-doc expanded A/B（`ground_truth_phase4_ab.json`）、LangGraph `Send()` map-reduce（Plan §8）、收紧 semantic-fallback 的 `extra_fields`。

---

## 1. Purpose & scope

This handover covers work on the **Hybrid Retrieval & Coverage Upgrade Plan**:

| Document | Role |
|---|---|
| [HYBRID_RETRIEVAL_AND_COVERAGE_UPGRADE_PLAN.md](./HYBRID_RETRIEVAL_AND_COVERAGE_UPGRADE_PLAN.md) | Master plan (§10 = evaluation gates) |
| [SCIENTIFIC_DOCUMENT_CHUNKING_DESIGN.md](./SCIENTIFIC_DOCUMENT_CHUNKING_DESIGN.md) | Chunking / section design |
| This file | **Operational handover** for humans and agents |

**Goal:** Make hybrid retrieval the default evidence path **without regressing** metadata completeness vs lexical-only (shadow) baseline.

---

## 2. Git & workspace state (critical)

### Branch

```text
cursor/hybrid-retrieval-agentic-upgrade-plan-d719
  ↑ ahead of origin by ~18 commits (not pushed at handover time)
```

### Recent committed work (newest first, abbreviated)

| Commit | Summary |
|---|---|
| `932e1e7` | Embedder cache fix — do not cache failed client; lexical fallback |
| `ab6468a` | Section workers → `FieldCandidate` for JSONGenerator |
| `a8d43c4` | `_blend_lexical_first_hybrid_output()` |
| `244929a` | Eval env load order fix; Plan §10.4 |
| `9dd2f15` | Embedding upgrade to snowflake-arctic (later partially reverted in uncommitted defaults) |

### **Uncommitted changes at handover** (must be committed before merge)

```text
 M docs/en/development/HYBRID_RETRIEVAL_AND_COVERAGE_UPGRADE_PLAN.md  (+§10.5)
 M fairifier/agents/json_generator.py          # pre-reconcile semantic gate
 M fairifier/config.py                          # adaptive lexical + bge-small defaults
 M fairifier/services/semantic_index.py         # embedder dim probe + Qdrant recreate
 M fairifier/services/source_workspace.py       # adaptive prompt policy + prompt_mode telemetry
 M fairifier/utils/report_generator.py          # prompt_mode in field_retrieval_stats
 M tests/test_hybrid_retrieval.py
 M tests/test_semantic_embedder.py
```

**Suggested commit message:**

```text
fix(retrieval): adaptive lexical prompt, Qdrant dim probe, pre-reconcile gate

Phase4 uses lexical snippets when available; hybrid only on lexical miss.
Probe embedder vector width and recreate per-run Qdrant collections on mismatch.
Skip semantic-only pre-reconcile when lexical candidates exist.
```

Run before commit:

```bash
mamba run -n FAIRiAgent python -m pytest tests/test_hybrid_retrieval.py tests/test_semantic_embedder.py -q
```

---

## 3. Architecture changes (what shipped / pending commit)

### 3.1 Adaptive lexical prompt (Phase 4 default behaviour)

**Problem:** Full hybrid-in-prompt injected semantic-only snippets even when lexical hits existed → LLM over-extraction (`extra_fields` ↑), missed recommended fields.

**Fix:** `retrieval_prompt_adaptive_lexical=true` (default in `fairifier/config.py`).

| `prompt_mode` (telemetry) | When | Prompt content |
|---|---|---|
| `shadow_lexical` | `retrieval_shadow_mode=true` | Lexical only (A/B control) |
| `lexical_preferred` | Adaptive + lexical hits exist | Lexical only (matches shadow) |
| `semantic_fallback` | Adaptive + no lexical hits | Reranked hybrid output |

**Code:** `fairifier/services/source_workspace.py` → `hybrid_search_sources()`  
**Env:** `FAIRIFIER_RETRIEVAL_PROMPT_ADAPTIVE_LEXICAL` (bool)

### 3.2 Pre-reconcile injection gate

**Problem:** Semantic-only reconciled values injected as “High Confidence” even when grep/lexical evidence existed.

**Fix:** `JSONGeneratorAgent._should_inject_pre_reconciled_value()` — skip semantic primary when field pool has grep/lexical candidates.

**Code:** `fairifier/agents/json_generator.py`

### 3.3 Qdrant vector dimension probe

**Problem:** Qdrant collections created with `FAIRIFIER_RETRIEVAL_EMBEDDING_DIMS=384` (code default) while eval Ollama embedder (`nomic-embed-text-v2-moe`) returns **768-d** vectors → `Vector dimension error: expected dim: 384, got 768` → semantic index dead (`hybrid_fields=0`).

**Fix:**

- `_resolve_embedding_vector_size()` — probe live embedder, warn if config ≠ actual
- `_collection_vector_size()` — read existing collection dim
- On mismatch: **delete & recreate** per-run collection (safe; session-scoped names)

**Code:** `fairifier/services/semantic_index.py`

### 3.4 Other retrieval pieces (already on branch)

| Component | File | Status |
|---|---|---|
| Chunking + sections | `fairifier/services/chunking.py` | ✅ |
| Semantic index | `fairifier/services/semantic_index.py` | ✅ (+ dim fix uncommitted) |
| Hybrid search + RRF + rerank | `fairifier/services/source_workspace.py` | ✅ |
| Section → FieldCandidate | `fairifier/services/section_field_candidates.py` | ✅ |
| Evidence store | `fairifier/services/evidence_store.py` | ✅ |
| Map-reduce nodes (partial) | `fairifier/graph/retrieval_nodes.py` | ⏳ P2 — full LangGraph `Send()` not done |
| Eval harness env order | `evaluation/scripts/run_batch_evaluation.py` | ✅ model config first, then env file |

### 3.5 Config defaults (after uncommitted changes)

| Setting | Default | Eval override (`phase4_tuned`) |
|---|---|---|
| `retrieval_shadow_mode` | `false` | `false` (phase4) / `true` (shadow) |
| `retrieval_prompt_adaptive_lexical` | `true` | `true` |
| `retrieval_embedding_model` | `BAAI/bge-small-en-v1.5` | `nomic-embed-text-v2-moe` (Ollama) |
| `retrieval_embedding_dims` | `384` | `768` (overridden at runtime by probe) |
| `retrieval_embedding_backend` | `auto` | `ollama` + `http://localhost:11434` |
| `retrieval_final_snippets` | `8` | `5` (tuned) |

---

## 4. Infrastructure & ports (do not change)

| Service | URL / port | Handover status | Notes |
|---|---|---|---|
| FAIR-DS API | `http://localhost:8090` | ✅ OK | **Do not use 8083** (local Cursor conflict) |
| Qdrant (mem0 + semantic index) | `localhost:6335` | ✅ OK | Per-run collections `run_<session>` |
| Ollama (embeddings) | `http://localhost:11434` | Required for eval | Model: `nomic-embed-text-v2-moe` |
| MinerU | `http://localhost:30000` | Verify at run time | Canonical per `config.py` / `env.example`; PDFs may use local `mineru_*` cache |

**Policy from project owner:** If a fixed-port service is unavailable, **stop and report** — do not change ports or work around API outages.

### MinerU cache locations (when server down)

| Document | Cache path |
|---|---|
| earthworm | `evaluation/datasets/raw/earthworm/mineru_earthworm_4n_paper_bioRxiv/` |
| PETase papers | `evaluation/datasets/raw/petase_enzyme_engineering/papers/*/mineru_paper/` |
| biorem | Uses `.md` directly — no MinerU required |

---

## 5. Evaluation methodology

### 5.1 Ground truth files

| File | Docs | In git? | Use |
|---|---|:---:|---|
| `evaluation/datasets/annotated/ground_truth_shadow_gate.json` | 3 | ✅ | Phase 3/4 gate (earthworm + 2 PETase) |
| `evaluation/datasets/annotated/ground_truth_phase4_ab.json` | 8 | ❌ gitignored | Expanded A/B |
| `evaluation/datasets/annotated/ground_truth_biorem.local.json` | 1 | ❌ gitignored | biorem local GT |

**8-doc IDs:** `earthworm`, `petase_10_1002_anie_202218390`, `petase_10_1038_s41586-020-2149-4`, `biorem`, `biosensor`, `pea_cold_stress`, `sea_cucumber_gut_metagenome`, `human_gut_microbiome_temporal`

### 5.2 Eval env files (contain secrets — gitignored or local)

| Env file | `FAIRIFIER_RETRIEVAL_SHADOW_MODE` | Purpose |
|---|---|---|
| `evaluation/config/env.evaluation.shadow_tuned` | `true` | Shadow / lexical control |
| `evaluation/config/env.evaluation.phase4_tuned` | `false` + adaptive lexical | Phase 4 production path |

**Model config (shared):**  
`evaluation/config/model_configs/deepseek_v4-flash_v1.4.0_fairds8090_localpkg_phase4_tuned.env`

**Load order (important):** `run_batch_evaluation.py` loads **model config first**, then env file — so shadow flag is controlled by env, not model config.

### 5.3 Batch run command template

```bash
mamba run -n FAIRiAgent python evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation.phase4_tuned \
  --model-configs evaluation/config/model_configs/deepseek_v4-flash_v1.4.0_fairds8090_localpkg_phase4_tuned.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_shadow_gate.json \
  --output-dir evaluation/runs/<RUN_ID>/workflow_phase4_dimfix \
  --repeats 1 --workers 1 --timeout 3600
```

Swap env file for shadow arm. Use `--include-documents earthworm` for smoke tests.

Results land under `<output-dir>/results/evaluation_results.json` and per-run `workflow_report.json`.

### 5.4 Quality gates (Plan §10)

| Gate | Criterion | Status (2026-07-05) |
|---|---|---|
| Phase 3 shadow | Hybrid telemetry active, no crash | ✅ Passed (2026-07-03) |
| Phase 4 completeness | Phase4 mean ≥ shadow on same slice | ✅ **Passed** dim-fix 3-doc (87.8% vs 85.5%) |
| Phase 4 aggregate | Multi-layer aggregate ≥ shadow | ⚠️ Not passed (0.665 vs 0.676) — PETase Angew `extra_fields` |
| Expanded 8-doc | Re-run after embedder + dim fix | ❌ Not run |
| Default switch | `retrieval_shadow_mode=false` in prod | ✅ Default in code; keep shadow in regression envs until 8-doc OK |

### 5.5 How to verify semantic index is actually working

In `workflow_report.json` → `retrieval_metrics`:

```json
{
  "semantic_index_available": true,
  "indexed_chunk_count": 43,
  "hybrid_fields": 35,
  "qdrant_fallback_used": false,
  "semantic_index_status": "ready"
}
```

**Invalid run signature (ignore for hybrid A/B):**

```text
Vector dimension error: expected dim: 384, got 768
hybrid_fields: 0
qdrant_fallback_used: true
```

---

## 6. Evaluation results & provenance

All under: `evaluation/runs/phase4_adaptive_20260705/`

### 6.1 Invalid A/B — semantic index dead (dim mismatch)

**Do not use for hybrid conclusions.**

| Run dir | Mean completeness | Aggregate | Issue |
|---|---:|---:|---|
| `workflow_shadow_tuned/` | 83.1% | 0.677 | Qdrant 384 vs Ollama 768 |
| `workflow_phase4_tuned/` | 75.6% | 0.655 | Same + LLM variance |

### 6.2 Valid A/B — dim-fix, semantic active (authoritative)

| Run dir | Arm | Mean completeness | Aggregate |
|---|---|---:|---:|
| `workflow_shadow_dimfix/` | Shadow | 85.5% | 0.676 |
| `workflow_phase4_dimfix/` | Phase4 adaptive | **87.8%** | 0.665 |
| `workflow_phase4_dimfix_smoke/` | Phase4 earthworm only | 64.3% | 0.612 |

**Per-document (dim-fix, both arms):**

| Document | Shadow | Phase4 | Δ completeness | Shadow extra | Phase4 extra |
|---|---:|---:|---:|---:|---:|
| earthworm | 81.0% | 81.0% | 0 | 29 | 27 |
| petase_10_1002_anie_202218390 | 83.9% | 93.5% | +9.6% | 53 | 131 |
| petase_10_1038_s41586-020-2149-4 | 91.7% | 88.9% | −2.8% | 117 | 101 |

**Interpretation:**

- Adaptive lexical + working semantic **helps recall** on PETase Angew (+9.6%) but **inflates extra_fields** when semantic fallback fires heavily.
- earthworm: prompt-equivalent to shadow for lexical-rich fields; parity as expected.
- Aggregate score penalizes extra_fields — tune semantic-fallback policy before declaring full Phase 4 win.

### 6.3 Historical runs (earlier sessions)

| Run dir | Date | Notes |
|---|---|---|
| `evaluation/runs/shadow_gate_20260703/` | 2026-07-03 | Phase 3 gate + early Phase 4 A/B |
| `evaluation/runs/phase4_ab_20260703/` | 2026-07-03 | 8-doc batch **0/8 metadata.json** — embedder cache bug (fixed `932e1e7`) |

### 6.4 Key artifact paths per run

```text
<output-dir>/
  deepseek_v4-flash_v1.4.0_fairds8090_localpkg_phase4_tuned/
    <document_id>/run_1/
      metadata.json
      workflow_report.json      ← retrieval_metrics, critic scores
      full_output.log
      runtime_config.json       ← env snapshot (secrets masked)
      source_workspace/         ← chunks, evidence_store.jsonl
  results/evaluation_results.json
  run_metadata.json
```

---

## 7. Bugs found & fixes (provenance)

| ID | Symptom | Root cause | Fix | Commit / state |
|---|---|---|---|---|
| B1 | JSONGenerator ~0.03s fail, no metadata | Cached broken embedder client | Don't cache failed `_EMBEDDER` | `932e1e7` |
| B2 | `retrieval_telemetry` lost in state | Top-level reassignment | Dict merge in JSONGenerator | earlier on branch |
| B3 | Field key mismatch KR ↔ JSONGen | `term` vs `name` | Normalized lookup keys | earlier |
| B4 | FAIRDS parser crash on null syntax | `_infer_data_type` | Null guard | earlier |
| B5 | Eval shadow flag ignored | Env load order | Model config first | `244929a` |
| B6 | Phase4 metric drop vs shadow | Semantic noise in prompt | Adaptive lexical prompt | **uncommitted** |
| B7 | Semantic index always dead in eval | Qdrant dim 384 vs embedder 768 | Dim probe + recreate | **uncommitted** |
| B8 | Spurious pre-reconcile | Semantic wins over lexical | `_should_inject_pre_reconciled_value` | **uncommitted** |

---

## 8. Remaining work (prioritized)

### P0 — Immediate (next agent)

1. **Commit uncommitted retrieval fixes** (§2) + run fast tests.
2. **Re-run 8-doc expanded A/B** with dim-fix code:
   - GT: `evaluation/datasets/annotated/ground_truth_phase4_ab.json`
   - Output: e.g. `evaluation/runs/phase4_ab_<date>/workflow_{shadow,phase4}_dimfix/`
   - Confirm MinerU or caches per doc before starting.
3. **Update Plan §10.5** with 8-doc results when available.

### P1 — Architecture (Plan §8–§9)

| Task | Plan ref | Notes |
|---|---|---|
| LangGraph `Send()` section map-reduce | §8.2 | Partial code in `retrieval_nodes.py` |
| ISAValueMapper reads EvidenceStore | §4.1 | Not started |
| Tighten semantic-fallback extra_fields | §10.5 | e.g. cap snippets, score threshold, skip low rerank |
| Field-catalog precomputed embeddings | §9.1 | Performance |
| Ontology-driven query expansion | §9.3 | Replace hardcoded alias maps |

### P2 — Default switch & cleanup

- Set `FAIRIFIER_RETRIEVAL_SHADOW_MODE=false` in production `.env` after 8-doc gate.
- Keep `shadow_tuned` env in CI/regression until expanded slice stable.
- Deprecate duplicate grep loop per Plan §11 migration table.

### Explicit non-goals

See Plan §13 — do not replace FAIR-DS schema retrieval, add second vector DB, or run map-reduce on every tiny document.

---

## 9. Tests & local verification

```bash
# Fast retrieval regression (~15s)
mamba run -n FAIRiAgent python -m pytest \
  tests/test_hybrid_retrieval.py \
  tests/test_semantic_embedder.py \
  tests/test_section_field_candidates.py \
  tests/test_fairds_api_parser.py -q

# Full fast suite
mamba run -n FAIRiAgent python run_tests.py fast

# Single-doc smoke (phase4 path, ~10 min)
mamba run -n FAIRiAgent python evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation.phase4_tuned \
  --model-configs evaluation/config/model_configs/deepseek_v4-flash_v1.4.0_fairds8090_localpkg_phase4_tuned.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_shadow_gate.json \
  --output-dir evaluation/runs/smoke_$(date +%Y%m%d) \
  --include-documents earthworm \
  --repeats 1 --workers 1 --timeout 3600
```

**Shadow pilot (retrieval-only, no full workflow):**

```bash
mamba run -n FAIRiAgent python evaluation/scripts/run_retrieval_shadow_pilot.py --help
```

---

## 10. Key source files (quick index)

| Area | Path |
|---|---|
| Config | `fairifier/config.py` |
| Hybrid search | `fairifier/services/source_workspace.py` |
| Semantic index / embedder | `fairifier/services/semantic_index.py` |
| JSONGenerator evidence | `fairifier/agents/json_generator.py` |
| Section map-reduce | `fairifier/graph/retrieval_nodes.py` |
| Section FieldCandidates | `fairifier/services/section_field_candidates.py` |
| Workflow report metrics | `fairifier/utils/report_generator.py` |
| Batch eval | `evaluation/scripts/run_batch_evaluation.py` |
| Eval orchestrator | `evaluation/scripts/evaluate_outputs.py` |

---

## 11. Decision log (for future agents)

| Date | Decision | Rationale |
|---|---|---|
| 2026-07-03 | Keep `retrieval_shadow_mode=true` in regression envs | Phase 4 hybrid-in-prompt regressed before tuning |
| 2026-07-03 | Tuned snippet budget (5 snippets, 3 per field) | Reduce prompt noise |
| 2026-07-05 | Adaptive lexical default ON | Match shadow on ~76% of fields; hybrid only on lexical miss |
| 2026-07-05 | Probe embedder dim, recreate Qdrant collection | Fix silent semantic index failure |
| 2026-07-05 | Revert code default embedder to bge-small 384 | Stability; eval uses Ollama via env |
| 2026-07-05 | Do **not** change service ports | Owner policy |
| 2026-07-05 | Completeness gate passed on 3-doc dim-fix | Mean +2.3 pp; aggregate still −0.011 |

---

## 12. Contact & escalation

- **Plan owner / reviewer:** check PR on branch `cursor/hybrid-retrieval-agentic-upgrade-plan-d719`
- **Blocked on infra:** MinerU `:30000`, FAIR-DS `:8090`, Qdrant `:6335`, Ollama `:11434` — report to owner, do not patch ports
- **LangSmith projects:** `fairifier-evaluation-shadow-tuned`, `fairifier-evaluation-phase4-tuned` (see env files)

---

## 13. Related links

- [Hybrid Retrieval & Coverage Upgrade Plan §10](./HYBRID_RETRIEVAL_AND_COVERAGE_UPGRADE_PLAN.md#10-evaluation-rollout-and-guardrail-updates)
- [Evaluation README](../../../evaluation/README.md)
- [AGENTS.md repository guidelines](../../../AGENTS.md)
