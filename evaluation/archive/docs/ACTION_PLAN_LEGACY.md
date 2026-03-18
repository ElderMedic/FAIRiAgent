# FAIRiAgent Evaluation Report

**Version**: 2.0 (Confidence-Aware Evaluation)  
**Date**: 2026-01-16  
**Authors**: Changlin Ke

---

## Executive Summary

This report presents comprehensive evaluation results of FAIRiAgent, a multi-agent system for automated FAIR metadata extraction from scientific documents. We evaluated 8 LLM backends across 160 runs (8 models × 2 documents × 10 repetitions) and developed an improved **confidence-aware evaluation methodology** that distinguishes valuable metadata discoveries from erroneous extractions.

**Key Findings**:
- GPT-4.1 achieves best overall performance (adjusted score: 0.882)
- Claude Sonnet 4.5 shows highest discovery potential (discovery bonus: 0.748)
- Field-level confidence effectively identifies valuable excess extractions

---

## 1. Methodology

### 1.1 Evaluation Framework

| Metric | Definition | Range |
|--------|------------|-------|
| **Completeness** | Proportion of required fields successfully extracted | 0-1 |
| **Precision** | TP / (TP + FP) - original formulation | 0-1 |
| **Recall** | TP / (TP + FN) - fields from GT that were extracted | 0-1 |
| **F1 Score** | Harmonic mean of precision and recall | 0-1 |

### 1.2 Confidence-Aware Evaluation 

**Problem**: Original evaluation penalizes all excess fields equally, but many excess fields are high-quality metadata that annotators missed.

**Solution**: Leverage field-level confidence scores (0-1) assigned by the Critic agent to distinguish:
- **High-confidence excess** (≥0.8): Likely valid metadata, not penalized
- **Low-confidence excess** (<0.8): Uncertain extractions, penalized

**New Metrics**:

| Metric | Formula | Purpose |
|--------|---------|---------|
| **Adjusted Precision** | TP / (TP + low_conf_excess) | Only penalize low-quality excess |
| **Adjusted F1** | 2 × (adj_prec × recall) / (adj_prec + recall) | Balanced score |
| **Discovery Bonus** | high_conf_excess / GT_fields | Reward for finding valid extras |

### 1.3 Aggregate Score

```
Adjusted Aggregate = 0.4 × Completeness + 0.4 × Adjusted_F1 + 0.2 × Overall_Confidence
```

---

## 2. Results

### 2.1 Model Rankings (Confidence-Aware)

| Rank | Model | Adj Score | Orig Score | Δ | Completeness | Adj F1 | F1 | Discovery |
|------|-------|-----------|------------|---|--------------|--------|-----|-----------|
| 🥇 1 | **GPT-4.1** | **0.882** | 0.837 | +5% | 89.1% | 0.886 | 0.775 | 0.30 |
| 🥈 2 | Claude Sonnet 4.5 | 0.859 | 0.769 | +12% | 88.6% | 0.858 | 0.634 | 0.75 |
| 🥉 3 | GPT-5 | 0.841 | 0.771 | +9% | 89.2% | 0.795 | 0.620 | 0.74 |
| 4 | Claude Haiku 4.5 | 0.796 | 0.722 | +10% | 83.6% | 0.768 | 0.584 | 0.78 |
| 5 | Qwen Plus | 0.763 | 0.698 | +9% | 79.7% | 0.752 | 0.589 | 0.74 |
| 6 | Qwen Max | 0.746 | 0.705 | +6% | 75.8% | 0.683 | 0.581 | 0.41 |
| 7 | O3 | 0.740 | 0.719 | +3% | 77.6% | 0.731 | 0.678 | 0.15 |
| 8 | Qwen Flash | 0.700 | 0.643 | +9% | 77.9% | 0.633 | 0.492 | 1.18 |

### 2.2 Excess Fields Analysis

| Model | Fields Extracted | High Conf Excess | Low Conf Excess | % High Conf |
|-------|-----------------|------------------|-----------------|-------------|
| GPT-4.1 | 52.7 | 12.0 | 4.7 | **71.9%** |
| Claude Sonnet 4.5 | 73.5 | 30.4 | 7.3 | 80.6% |
| GPT-5 | 80.7 | 29.8 | 14.9 | 66.7% |
| Claude Haiku 4.5 | 79.8 | 31.9 | 14.1 | 69.3% |
| Qwen Plus | 76.5 | 30.1 | 14.3 | 67.8% |
| Qwen Max | 61.6 | 16.7 | 14.2 | 54.0% |
| O3 | 47.3 | 6.3 | 9.5 | 39.9% |
| Qwen Flash | 112.2 | 48.7 | 31.9 | **60.4%** |

### 2.3 Runtime Performance

| Model | Avg Runtime (s) | Std | Cost Efficiency |
|-------|-----------------|-----|-----------------|
| Qwen Max | 411 | ±85 | Fastest |
| Qwen Flash | 503 | ±120 | Fast |
| GPT-4.1 | 533 | ±95 | **Best value** |
| Claude Haiku 4.5 | 652 | ±110 | Medium |
| Qwen Plus | 664 | ±130 | Medium |
| Claude Sonnet 4.5 | 665 | ±105 | Medium |
| GPT-5 | 795 | ±150 | Slower |
| O3 | 994 | ±200 | Slowest |

---

## 3. Discussion

### 3.1 Why GPT-4.1 Ranks First

GPT-4.1 employs a **conservative extraction strategy**:
- Extracts fewest fields on average (52.7)
- Achieves highest original precision (0.688)
- **71.9% of excess fields are high-confidence** (indicating quality control)
- Balanced between completeness (89.1%) and precision

**Trade-off**: Lower discovery potential (0.30) compared to more exploratory models.

### 3.2 Why Claude Sonnet 4.5 Benefits Most from Adjusted Metrics

Claude Sonnet 4.5 showed the largest score improvement (+12%):
- **80.6% of excess fields are high-confidence** (highest rate)
- Many extracted fields are valid metadata that GT annotators missed
- Examples: strain names, host organisms, dataset accessions

**Implication**: Original evaluation unfairly penalized Claude's thoroughness.

### 3.3 O3's Ranking Drop

O3 dropped from 2nd (original) to 7th (adjusted):
- Very conservative: only 47.3 fields extracted
- Low discovery bonus (0.15) - misses valuable metadata
- High original precision reflects strict adherence to expected fields only

**Implication**: O3 may be over-fitted to exact field matching.

### 3.4 Qwen Flash: High Discovery, Low Quality

Qwen Flash has the highest discovery bonus (1.18) but ranks last:
- Extracts most fields (112.2 avg)
- 60.4% high-confidence excess (reasonable quality)
- But also highest low-confidence excess (31.9) - many hallucinations

**Implication**: Quantity without quality control is not beneficial.

### 3.5 Confidence Scores as LLM Judge Proxy

Our analysis validates that **field-level confidence scores effectively replace a separate LLM Judge**:
- High-confidence excess fields (≥0.8) correlate with valid metadata
- Low-confidence fields (<0.8) often have status="provisional"
- No additional API calls needed - confidence is computed during extraction

---

## 4. Limitations and Future Work

### 4.1 Current Limitations

1. **Ground Truth Coverage**: Only 2 documents with 89 fields - may not generalize
2. **Domain Specificity**: Biosensor and earthworm papers only
3. **No Value Correctness**: Current evaluation checks field presence, not value accuracy
4. **Static Context**: Each document processed independently, no cross-document learning

### 4.2 Identified Improvement Areas

| Area | Current State | Target State | Priority | Status |
|------|---------------|--------------|----------|--------|
| Context Retention | None (stateless) | Long-term memory (mem0) | P0 | Planned |
| Critic Agent | Single-pass with retry | ~~Multi-turn self-reflection~~ | ~~P1~~ | **Cancelled** |
| Agent Communication | Via state only | Direct inter-agent feedback | P2 | Planned |
| Dynamic Planning | One-shot at start | Adaptive re-planning | P3 | Planned |

> **Note on Multi-Turn Reflection (2026-01-16)**: After implementation and testing, multi-turn reflection was **removed** from the system. Analysis showed that:
> 1. Agents did not differentiate between reflection iterations and retry attempts - both executed identical logic
> 2. The reflection loop added complexity without providing meaningful iterative improvement
> 3. Critic feedback was not effectively integrated into agent behavior during reflections
> 4. The mechanism wasted tokens by repeating similar executions without progress
> 
> The current design uses a **simple retry mechanism** with Critic feedback, which proved more efficient and equally effective.

---

## 5. Current System Analysis and Improvement Plan

### 5.1 Current Architecture Review

```
┌─────────────────────────────────────────────────────────────────┐
│                    Current FAIRiAgent Workflow                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  read_file ──▶ orchestrate ──▶ finalize ──▶ END                │
│                    │                                            │
│                    ▼                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                 Orchestrator Node                        │   │
│  │                                                          │   │
│  │  DocumentParser → Critic → (retry with feedback?) →     │   │
│  │  Planner →                                               │   │
│  │  KnowledgeRetriever → Critic → (retry with feedback?) → │   │
│  │  JSONGenerator → Critic → (retry with feedback?) →      │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Key Features:                                                  │
│  - Critic provides feedback for each retry attempt              │
│  - API-aware evaluation for Knowledge Retriever                 │
│  - No-progress detection to avoid infinite retry loops          │
│  - Feedback deduplication to prevent token waste                │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Current System Strengths

| Feature | Description | Benefit |
|---------|-------------|---------|
| **Critic with Feedback** | Critic provides actionable feedback for retry attempts | Guides agent improvement |
| **API-Aware Evaluation** | Critic considers FAIR-DS API limitations | Realistic expectations |
| **No-Progress Detection** | Terminates retries when scores don't improve | Saves tokens |
| **Feedback Deduplication** | Limits historical guidance to 10 items | Prevents context overflow |

### 5.3 Remaining Issues

| Issue | Description | Impact |
|-------|-------------|--------|
| **Stateless Processing** | No memory between documents or sessions | Cannot learn from past extractions |
| **Linear Orchestration** | Fixed sequence, no dynamic adaptation | Cannot adjust strategy mid-workflow |
| **No Local KB** | Local knowledge base not yet integrated | Limited fallback options |

### 5.4 mem0 vs GraphRAG: Which to Use?

Based on research and our use case analysis:

| Dimension | mem0 | GraphRAG/A-MEM |
|-----------|------|----------------|
| **Efficiency** | Very high (91% latency reduction) | Moderate (graph maintenance overhead) |
| **Use Case** | Conversational memory, fact extraction | Complex relational reasoning |
| **Implementation** | Simple, well-documented | More complex (tagging, linking) |
| **Our Need** | ✅ Document context, extraction patterns | ❌ Not needed for FAIR metadata |

**Recommendation**: **mem0 is sufficient** for FAIRiAgent. GraphRAG adds complexity without proportional benefit for our use case. The key needs are:
- Remember document context during multi-agent interaction
- Store successful extraction patterns
- Retrieve similar past extractions

These are well-served by mem0's hybrid vector + optional graph store.

---

## 6. Priority Improvements

### 6.1 P0: mem0 + Vector Database Integration

**Goal**: Enable agents to retain and retrieve research context across multi-agent interactions.

**Architecture**:

```
┌─────────────────────────────────────────────────────────────────┐
│                      FAIRiAgent + mem0                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐    │
│  │ Document │──▶│ Planner  │──▶│Knowledge │──▶│  JSON    │    │
│  │  Parser  │   │          │   │Retriever │   │Generator │    │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘    │
│       │              │              │              │           │
│       ▼              ▼              ▼              ▼           │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                   mem0 Memory Layer                      │  │
│  ├─────────────────────────────────────────────────────────┤  │
│  │  • Document context (entities, structure, themes)       │  │
│  │  • Extraction patterns (field → evidence mappings)      │  │
│  │  • Entity knowledge (organisms, methods, datasets)      │  │
│  └────────────────────────┬────────────────────────────────┘  │
│                           │                                    │
│                           ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │         Qdrant Vector Database (Local)                   │  │
│  │         Embedding: all-MiniLM-L6-v2                      │  │
│  └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Technology Stack**:

| Component | Choice | Rationale |
|-----------|--------|-----------|
| **Memory Framework** | mem0 | LangChain integration, efficient, well-documented |
| **Vector Database** | Qdrant (local mode) | No server, fast, Python-native |
| **Embedding Model** | sentence-transformers/all-MiniLM-L6-v2 | Local, fast, 384-dim |

**Implementation**:

```python
# fairifier/memory/memory_manager.py

from mem0 import Memory

MEMORY_CONFIG = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "collection_name": "fairifier_memory",
            "path": "./data/qdrant_storage",
        }
    },
    "embedder": {
        "provider": "huggingface",
        "config": {
            "model": "sentence-transformers/all-MiniLM-L6-v2"
        }
    }
}

class FAIRifierMemory:
    def __init__(self):
        self.memory = Memory.from_config(MEMORY_CONFIG)
    
    def store_document_context(self, doc_id: str, context: dict):
        """Store parsed document context for retrieval during extraction."""
        self.memory.add(
            messages=[{"role": "system", "content": str(context)}],
            user_id="fairifier",
            metadata={"type": "document", "doc_id": doc_id}
        )
    
    def store_extraction_pattern(self, field: str, pattern: dict):
        """Store successful extraction for future reference."""
        self.memory.add(
            messages=[{"role": "assistant", "content": str(pattern)}],
            user_id="fairifier", 
            metadata={"type": "pattern", "field": field}
        )
    
    def search(self, query: str, limit: int = 5) -> list:
        """Retrieve relevant memories."""
        return self.memory.search(query=query, user_id="fairifier", limit=limit)
```

---

### 6.2 ~~P1: Multi-Turn Self-Reflection for Critic Agent~~ (CANCELLED)

> **Status: CANCELLED (2026-01-16)**
> 
> Multi-turn self-reflection was implemented and tested but subsequently **removed** from the codebase due to the following findings:
>
> **Problems Identified:**
> 1. **No Agent Differentiation**: Agents did not distinguish between reflection iterations and retry attempts - both executed identical code paths
> 2. **Ineffective Feedback Integration**: Critic feedback was stored in state but agents did not modify their behavior based on `is_revision` or `reflection_iter` context
> 3. **Token Waste**: The mechanism doubled execution costs without providing proportional quality improvement
> 4. **Complexity vs Benefit**: Added significant code complexity without measurable output quality gains
>
> **Current Implementation (Simplified):**
> - Single retry loop with Critic feedback between attempts
> - No-progress detection to avoid infinite retry loops
> - Feedback deduplication to prevent context overflow
> - API-aware evaluation for realistic constraints
>
> **Lessons Learned:**
> - Reflection mechanisms require agents to have **distinct revision behaviors** (e.g., different prompts, strategies)
> - Simple retry with feedback is often more effective than complex reflection patterns
> - Measure actual improvement before adding architectural complexity

---

### 6.3 P1: Pre-Action Reflection (Anticipatory Planning)

**Research Insight**: MIRROR framework shows **intra-reflection** (anticipate before acting) reduces downstream errors.

**Implementation**: Add a "think before acting" step to each agent.

```python
# fairifier/agents/base.py (enhanced)

class BaseAgent:
    async def pre_reflect(self, state: FAIRifierState) -> dict:
        """Anticipate potential issues before execution."""
        prompt = f"""Before executing {self.name}, analyze:
        1. What information is available?
        2. What could go wrong?
        3. What should I focus on?
        4. What questions remain unclear?
        
        Current context: {state.get('document_info', {})}
        """
        # Use lightweight LLM for pre-reflection
        reflection = await self.llm_helper.quick_call(prompt)
        return {"pre_reflection": reflection, "anticipated_issues": [...]}
    
    async def execute_with_reflection(self, state: FAIRifierState) -> FAIRifierState:
        """Execute with pre-action reflection."""
        # 1. Pre-reflect
        pre_reflection = await self.pre_reflect(state)
        state["context"]["pre_reflection"] = pre_reflection
        
        # 2. Execute main logic
        state = await self.execute(state)
        
        return state
```

---

### 6.4 Implementation Roadmap (Revised)

| Phase | Task | Duration | Dependencies | Status |
|-------|------|----------|--------------|--------|
| **Phase 1** | mem0 + Qdrant setup | 1 week | None | Planned |
| **Phase 1** | Memory integration in agents | 1 week | mem0 setup | Planned |
| ~~**Phase 2**~~ | ~~Multi-turn reflection subgraph~~ | ~~1 week~~ | ~~None~~ | **Cancelled** |
| ~~**Phase 2**~~ | ~~Integrate reflection into workflow~~ | ~~1 week~~ | ~~Subgraph~~ | **Cancelled** |
| **Phase 2** | Pre-action reflection | 1 week | None | Planned |
| **Testing** | End-to-end evaluation | 1 week | All above | Planned |

**Total estimated time**: 4 weeks for full implementation (reduced from 6 weeks)

---

## 7. Appendix

### 7.1 File Locations

- **Evaluation runs**: `evaluation/runs/`
- **Analysis output**: `evaluation/analysis/output/`
- **Ground truth**: `evaluation/datasets/annotated/ground_truth_filtered.json`
- **Figures**: `evaluation/analysis/output/figures/`

### 7.2 Key Scripts

```bash
# Re-run evaluation with confidence-aware metrics
python evaluation/scripts/add_evaluation_metrics.py \
  --runs-dir evaluation/runs \
  --ground-truth evaluation/datasets/annotated/ground_truth_filtered.json

# Generate analysis and figures
python evaluation/scripts/quick_analysis.py
```

### 7.3 Checklist

- [x] Ground truth dataset prepared (2 documents, 89 fields)
- [x] 160 evaluation runs completed (8 models × 2 docs × 10 reps)
- [x] Confidence-aware evaluation implemented
- [x] Analysis figures generated (10 visualizations)
- [x] Model rankings computed with adjusted metrics
- [x] Multi-turn reflection implemented and tested
- [x] Multi-turn reflection removed (decision: adds complexity without benefit)
- [x] API-aware Critic evaluation implemented
- [x] No-progress detection implemented
- [ ] mem0 integration (planned)
- [ ] Local Knowledge Base integration (planned)
- [ ] Production deployment (planned)

---

**Report generated**: 2026-01-16  
**Analysis timestamp**: 20260116_005441  
**Total runs analyzed**: 160
