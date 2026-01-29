# Baseline Design Plan for FAIRiAgent Performance Comparison

**Date**: January 29, 2026  
**Version**: 1.0  
**Purpose**: Comprehensive baseline design for evaluating FAIRiAgent's agentic workflow performance

---

## Executive Summary

This document outlines a multi-tier baseline strategy to rigorously evaluate FAIRiAgent's performance against conventional and alternative approaches. We propose **5 baseline types** spanning simple single-prompt methods to sophisticated multi-step pipelines, using the same evaluation metrics and datasets as the main agentic workflow.

---

## 1. Evaluation Framework Overview

### 1.1 Core Metrics (from existing evaluation system)

| Category | Metrics | Description |
|----------|---------|-------------|
| **Completeness** | Overall, Required, Recommended | Field coverage vs. ground truth |
| **Correctness** | Precision, Recall, F1-Score | Field presence accuracy |
| **Quality** | Adjusted Precision, Adjusted F1 | Confidence-aware metrics |
| **Reliability** | Success Rate, Retry Rate | Workflow robustness |
| **Efficiency** | Runtime, Token Usage, Cost | Resource consumption |
| **Pass@k** | Pass@1, Pass@5, Pass@10 | Success probability in k attempts |

### 1.2 Evaluation Datasets

Using existing ground truth:
- **Earthworm**: Genomics/metagenomics dataset
- **Haarika+Bhamidipati**: Control dataset
- **BIOREM**: Bioremediation holdout dataset

Each with:
- Ground truth annotations (`ground_truth_filtered.json`)
- Required/recommended/optional field classifications
- ISA-Tab structure expectations
- Package-specific requirements

### 1.3 Experimental Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Runs per document** | N=10 | Statistical significance |
| **Workers** | 5 | Parallel execution efficiency |
| **Timeout** | 600s | Reasonable upper bound |
| **Temperature** | 0.2 (generation), 0.0 (evaluation) | Reproducibility |

---

## 2. Proposed Baseline Types

### Baseline 1: Single-Prompt (Naive)

**Status**: ✅ Already implemented (`baseline_single_prompt.py`)

**Description**: One-shot LLM call with comprehensive prompt containing all instructions and schema requirements.

**Characteristics**:
- ❌ No iterative refinement
- ❌ No validation loops
- ❌ No critic feedback
- ❌ No confidence scoring
- ✅ Fast (15-30s per document)
- ✅ Simple implementation

**Models to Test**:
- GPT-4o (primary baseline)
- Claude 3.5 Sonnet
- GPT-4.1
- Qwen-Max

**Expected Performance**:
- Completeness: 35-50%
- F1-Score: 0.45-0.60
- Success Rate: 80-100%
- Runtime: 15-30s

**Implementation**:
```bash
python evaluation/scripts/run_baseline_batch.py \
  --config-file evaluation/config/model_configs/openai_gpt4o.env \
  --config-name baseline_gpt4o \
  --ground-truth evaluation/datasets/annotated/ground_truth_filtered.json \
  --output-dir evaluation/runs/baseline_single_prompt \
  --workers 5 \
  --n-runs 10
```

---

### Baseline 2: Few-Shot Prompting

**Status**: 🆕 New baseline (needs implementation)

**Description**: Single-prompt approach enhanced with few-shot examples from annotated documents.

**Characteristics**:
- ✅ Example-guided extraction
- ✅ Shows desired output structure
- ✅ Demonstrates field-level detail
- ❌ Still no iteration or validation
- ⚠️ Longer context (2-3 examples)

**Prompt Structure**:
```
System: You are a metadata extraction expert...

Example 1:
Input: [Document excerpt from earthworm paper]
Output: [Corresponding ground truth fields]

Example 2:
Input: [Document excerpt from biosensor paper]
Output: [Corresponding ground truth fields]

Now extract from:
Input: [Target document]
Output: ?
```

**Expected Performance**:
- Completeness: 45-60% (+10-15% vs Baseline 1)
- F1-Score: 0.50-0.65 (+0.05-0.10 vs Baseline 1)
- Runtime: 20-40s (longer context)

**Implementation Plan**:
1. Create `baseline_few_shot.py` (copy from `baseline_single_prompt.py`)
2. Add example selection logic (use 2 documents as examples, test on 3rd)
3. Format examples from ground truth annotations
4. Test with cross-validation (rotate examples)

---

### Baseline 3: Chain-of-Thought Reasoning

**Status**: 🆕 New baseline (needs implementation)

**Description**: Use models with built-in reasoning capabilities (O1, O3) or explicit CoT prompting.

**Characteristics**:
- ✅ Step-by-step reasoning
- ✅ Self-explanation of extraction logic
- ✅ Better handling of complex fields
- ❌ No external validation
- ⚠️ Much longer runtime (O1/O3 models)

**Approach A: O1/O3 Models (Native Reasoning)**
```python
# Use OpenAI O1/O3 directly
model = "o1-preview"  # or "o3"
temperature = 1.0  # Required for O1/O3
```

**Approach B: Explicit CoT Prompting**
```
Prompt: "Think step-by-step:
1. First, identify the study design section...
2. Then, extract the sample collection details...
3. Next, find sequencing methodology...
4. Finally, compile all fields into JSON..."
```

**Expected Performance**:
- Completeness: 50-65% (better reasoning)
- F1-Score: 0.55-0.70
- Runtime: 60-120s (O1/O3 are slower)

**Implementation Plan**:
1. Create `baseline_cot.py`
2. Add CoT prompt template
3. Test with O1-preview, O3
4. Compare explicit CoT prompting vs native reasoning

---

### Baseline 4: Two-Stage (Generation + Validation)

**Status**: 🆕 New baseline (needs implementation)

**Description**: Separate generation and validation steps, but no iterative refinement.

**Characteristics**:
- ✅ Stage 1: Extract metadata (like Baseline 1)
- ✅ Stage 2: Validate against schema (separate LLM call)
- ✅ Basic quality check
- ❌ No retry with feedback (validation is pass/fail only)
- ⚠️ 2× LLM calls

**Workflow**:
```
Step 1: Generation
Input: Document + Schema → LLM → Metadata JSON

Step 2: Validation
Input: Metadata JSON + Schema Rules → LLM → Validation Report

Output: Original JSON + Validation Flag
```

**Validation Prompt**:
```
You are a metadata validator. Check if this JSON:
1. Follows the schema structure
2. Has reasonable field values
3. Contains required fields

Output: {"valid": true/false, "issues": [...]}
```

**Expected Performance**:
- Completeness: 40-55% (same as Baseline 1)
- F1-Score: 0.50-0.65 (+0.05 vs Baseline 1 due to schema validation)
- Runtime: 25-50s (2× LLM calls)

**Implementation Plan**:
1. Create `baseline_two_stage.py`
2. Reuse generation from Baseline 1
3. Add validation stage
4. Track validation issues (for analysis)

---

### Baseline 5: RAG-Enhanced Single-Prompt

**Status**: 🆕 New baseline (needs implementation)

**Description**: Single-prompt with retrieved context (ontology terms, schema definitions) similar to agentic workflow's knowledge retrieval, but no iteration.

**Characteristics**:
- ✅ Retrieves relevant ontology terms (ENVO, NCBI Taxonomy)
- ✅ Retrieves schema field definitions
- ✅ Context-aware extraction
- ❌ No iteration or refinement
- ⚠️ RAG overhead (retrieval step)

**Workflow**:
```
Step 1: Context Retrieval
- Extract key concepts from document
- Retrieve ontology terms (ENVO, etc.)
- Retrieve relevant schema fields

Step 2: Enhanced Generation
- Single LLM call with document + retrieved context
- Output: Metadata JSON
```

**Expected Performance**:
- Completeness: 55-70% (better with context)
- F1-Score: 0.60-0.75 (+0.10-0.15 vs Baseline 1)
- Runtime: 30-60s (retrieval overhead)

**Implementation Plan**:
1. Create `baseline_rag.py`
2. Reuse knowledge retrieval from `fairifier/services/local_knowledge.py`
3. Format retrieved context into prompt
4. Single LLM call (no iteration)

---

## 3. Comparison Matrix

| Baseline Type | Complexity | Expected Completeness | Expected F1 | Runtime | Implementation |
|---------------|------------|----------------------|-------------|---------|----------------|
| **1. Single-Prompt** | ⭐ | 35-50% | 0.45-0.60 | 15-30s | ✅ Done |
| **2. Few-Shot** | ⭐⭐ | 45-60% | 0.50-0.65 | 20-40s | 🆕 New |
| **3. CoT Reasoning** | ⭐⭐ | 50-65% | 0.55-0.70 | 60-120s | 🆕 New |
| **4. Two-Stage** | ⭐⭐⭐ | 40-55% | 0.50-0.65 | 25-50s | 🆕 New |
| **5. RAG-Enhanced** | ⭐⭐⭐⭐ | 55-70% | 0.60-0.75 | 30-60s | 🆕 New |
| **FAIRiAgent (Agentic)** | ⭐⭐⭐⭐⭐ | 70-85% | 0.75-0.85 | 400-600s | ✅ Main System |

---

## 4. Evaluation Metrics & Analysis Plan

### 4.1 Primary Metrics (Per Baseline)

For each baseline type, compute:

**A. Completeness Metrics**
- Overall completeness (all fields)
- Required field completeness
- Recommended field completeness
- Optional field completeness
- By ISA-sheet breakdown (investigation, study, sample, assay)

**B. Correctness Metrics**
- Precision: TP / (TP + FP)
- Recall: TP / (TP + FN)
- F1-Score: 2 × (P × R) / (P + R)
- Adjusted Precision (confidence-aware)
- Adjusted F1 (confidence-aware)

**C. Reliability Metrics**
- Success rate (% of runs that complete)
- Failure rate
- Timeout rate
- Average runtime
- Runtime variance

**D. Pass@k Metrics**
- Pass@1, Pass@5, Pass@10 (for each success criterion)
- Success criteria presets: lenient, moderate, strict, very_strict

### 4.2 Comparative Analysis

**Statistical Tests**:
1. **Paired t-test**: Compare each baseline vs FAIRiAgent
2. **ANOVA**: Compare all baselines simultaneously
3. **Effect size**: Cohen's d for each comparison
4. **Confidence intervals**: 95% CI for all metrics

**Visualization**:
1. **Heatmaps**: Completeness by baseline × document
2. **Box plots**: F1-score distribution per baseline
3. **Runtime comparison**: Bar chart with error bars
4. **Radar charts**: Multi-metric comparison
5. **Pass@k curves**: Success probability vs k attempts

### 4.3 Analysis Scripts

**Existing tools** (can be reused):
- `evaluation/analysis/run_analysis.py`: Main analysis orchestrator
- `evaluation/analysis/visualizations/baseline_comparison.py`: Baseline-specific plots
- `evaluation/scripts/calculate_pass_at_k.py`: Pass@k calculation

**New scripts needed**:
- `evaluation/analysis/multi_baseline_comparison.py`: Compare all 5 baselines
- `evaluation/analysis/statistical_tests.py`: Significance testing
- `evaluation/analysis/ablation_study.py`: Component-level analysis

---

## 5. Implementation Roadmap

### Phase 1: Setup (Week 1)

**Tasks**:
1. ✅ Review existing baseline implementation
2. 🔲 Create baseline scripts directory structure:
   ```
   evaluation/baselines/
   ├── baseline_1_single_prompt.py     (✅ exists)
   ├── baseline_2_few_shot.py          (new)
   ├── baseline_3_cot.py               (new)
   ├── baseline_4_two_stage.py         (new)
   ├── baseline_5_rag.py               (new)
   └── run_all_baselines.py            (orchestrator)
   ```
3. 🔲 Configure model settings for each baseline
4. 🔲 Test single-run execution for each baseline

### Phase 2: Batch Execution (Week 2)

**Tasks**:
1. 🔲 Run Baseline 1 (already done, verify)
2. 🔲 Run Baseline 2 (few-shot)
3. 🔲 Run Baseline 3 (CoT)
4. 🔲 Run Baseline 4 (two-stage)
5. 🔲 Run Baseline 5 (RAG-enhanced)
6. 🔲 Each: 10 runs × 3 documents × 1-2 models = 30-60 runs per baseline

### Phase 3: Evaluation & Analysis (Week 3)

**Tasks**:
1. 🔲 Run existing evaluators on all baseline outputs
2. 🔲 Compute completeness, correctness, reliability metrics
3. 🔲 Calculate Pass@k for all baselines
4. 🔲 Generate comparison visualizations
5. 🔲 Run statistical significance tests
6. 🔲 Create summary tables (LaTeX-ready for paper)

### Phase 4: Documentation & Reporting (Week 4)

**Tasks**:
1. 🔲 Write comprehensive comparison report
2. 🔲 Create manuscript-ready figures and tables
3. 🔲 Document insights and key findings
4. 🔲 Prepare supplementary materials

---

## 6. Expected Outcomes & Hypotheses

### H1: Completeness Improvement

**Hypothesis**: FAIRiAgent achieves **+20-35% higher completeness** than best baseline (RAG-enhanced).

**Expected Results**:
- Single-Prompt: 35-50%
- RAG-Enhanced: 55-70%
- **FAIRiAgent: 70-85% ← Target**

**Significance**: Demonstrates value of iterative refinement and multi-agent collaboration.

### H2: Correctness Improvement

**Hypothesis**: FAIRiAgent achieves **+0.10-0.20 higher F1-score** than best baseline.

**Expected Results**:
- Single-Prompt: 0.45-0.60
- RAG-Enhanced: 0.60-0.75
- **FAIRiAgent: 0.75-0.85 ← Target**

**Significance**: Shows importance of critic feedback and validation loops.

### H3: Reliability Improvement

**Hypothesis**: FAIRiAgent has **higher success rate** (>85%) than baselines despite complexity.

**Expected Results**:
- Baselines: 80-95% (simpler, fewer failure points)
- **FAIRiAgent: >85%** (robust error handling)

**Significance**: Complex workflows can still be reliable with proper design.

### H4: Quality-Time Trade-off

**Hypothesis**: FAIRiAgent's **10-20× longer runtime** is justified by quality gains.

**Expected Results**:
- Baselines: 15-120s
- FAIRiAgent: 400-600s
- **But**: +20-35% completeness, +0.10-0.20 F1

**Significance**: For publication-quality metadata, the overhead is acceptable.

### H5: Component Value Analysis

**Hypothesis**: Each component adds incremental value:
- Few-shot: +5-10% completeness
- CoT: +10-15% completeness
- RAG: +15-20% completeness
- Iteration: +15-20% completeness (agentic vs RAG baseline)

**Significance**: Ablation study shows which components matter most.

---

## 7. Model Selection for Baselines

### Primary Models (All Baselines)

| Model | Provider | Use Case | Cost |
|-------|----------|----------|------|
| **GPT-4o** | OpenAI | Primary baseline (representative) | $$ |
| **Claude 3.5 Sonnet** | Anthropic | High-quality alternative | $$$ |

### Specialized Models (Selected Baselines)

| Model | Provider | Baseline Type | Reason |
|-------|----------|---------------|---------|
| **O1-preview** | OpenAI | Baseline 3 (CoT) | Native reasoning |
| **O3** | OpenAI | Baseline 3 (CoT) | Advanced reasoning |
| **GPT-4.1** | OpenAI | All baselines | High performance |

### Model Configuration

```bash
# GPT-4o
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0.2

# Claude 3.5 Sonnet
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-5-20250929
LLM_TEMPERATURE=0.2

# O1-preview (for CoT baseline)
LLM_PROVIDER=openai
LLM_MODEL=o1-preview
LLM_TEMPERATURE=1.0
```

---

## 8. Output Structure

All baselines produce outputs in the same format as agentic workflow:

```
evaluation/runs/baseline_comparison_20260129/
├── baseline_1_single_prompt/
│   ├── gpt4o/
│   │   ├── earthworm/
│   │   │   ├── run_1/
│   │   │   │   ├── metadata_json.json
│   │   │   │   ├── eval_result.json
│   │   │   │   ├── llm_responses.json
│   │   │   │   └── cli_output.txt
│   │   │   └── run_2..10/
│   │   ├── biosensor/
│   │   └── biorem/
│   └── sonnet/
├── baseline_2_few_shot/
├── baseline_3_cot/
├── baseline_4_two_stage/
├── baseline_5_rag/
└── comparison_results/
    ├── completeness_comparison.csv
    ├── correctness_comparison.csv
    ├── runtime_comparison.csv
    ├── pass_at_k_comparison.csv
    └── figures/
        ├── completeness_heatmap.png
        ├── f1_boxplot.png
        ├── runtime_comparison.png
        └── pass_at_k_curves.png
```

---

## 9. Key Advantages of This Design

### 9.1 Comprehensive Coverage

✅ **Simple to Complex**: From single-prompt to RAG-enhanced  
✅ **Multiple Techniques**: Few-shot, CoT, two-stage, RAG  
✅ **Fair Comparison**: Same data, metrics, evaluation process  
✅ **Ablation Study**: Can isolate component contributions  

### 9.2 Reproducibility

✅ **Same Infrastructure**: Reuse existing evaluation pipeline  
✅ **Same Metrics**: CompletenessEvaluator, CorrectnessEvaluator, etc.  
✅ **Same Ground Truth**: Consistent annotations  
✅ **Version Control**: All baselines in git  

### 9.3 Publication-Ready

✅ **Rigorous**: Multiple baselines, statistical tests  
✅ **Transparent**: Clear methodology, open source  
✅ **Visualizations**: Publication-quality figures  
✅ **Tables**: LaTeX-ready comparative tables  

---

## 10. Risk Mitigation

### Risk 1: Baselines Perform Better Than Expected

**Mitigation**:
- Still demonstrates iterative refinement value
- Highlight confidence scoring and FAIR compliance
- Focus on quality-guided human review capabilities

### Risk 2: Runtime Overhead Too High

**Mitigation**:
- Optimize agentic workflow (parallel agents)
- Show cost-benefit analysis (quality vs time)
- Demonstrate selective use cases (critical metadata only)

### Risk 3: Baseline Implementation Complexity

**Mitigation**:
- Start with simple baselines (1-2)
- Add complex baselines iteratively
- Document all assumptions and design choices

---

## 11. Success Criteria

This baseline comparison will be considered **successful** if:

1. ✅ **All 5 baselines implemented and tested** on 3 documents × 10 runs
2. ✅ **FAIRiAgent outperforms all baselines** on primary metrics (completeness, F1)
3. ✅ **Statistical significance achieved** (p < 0.05) for key comparisons
4. ✅ **Ablation insights obtained**: Which components contribute most
5. ✅ **Publication-ready results**: Figures, tables, and text ready for manuscript

---

## 12. Next Steps

### Immediate Actions

1. **Review and approve this plan** with research team
2. **Create baseline implementation scripts** (Baselines 2-5)
3. **Test single runs** for each baseline
4. **Launch batch evaluation** (estimated 2-3 days compute time)
5. **Analyze results** and iterate if needed

### Timeline

| Week | Tasks | Deliverables |
|------|-------|--------------|
| **Week 1** | Implement baselines 2-5, test | Working baseline scripts |
| **Week 2** | Run batch evaluations | Raw baseline outputs |
| **Week 3** | Evaluate & analyze results | Metrics, figures, tables |
| **Week 4** | Write comparison report | Manuscript-ready materials |

---

## 13. References

### Existing Documentation
- `evaluation/README.md`: Evaluation framework overview
- `docs/en/EVALUATION_METHODOLOGY.md`: Metrics and workflow
- `evaluation/archive/docs/BASELINE_VS_AGENTIC_COMPARISON.md`: Baseline 1 results
- `evaluation/archive/docs/BASELINE_EVALUATION.md`: Baseline methodology

### Key Scripts
- `evaluation/scripts/baseline_single_prompt.py`: Baseline 1 implementation
- `evaluation/scripts/run_baseline_batch.py`: Batch runner
- `evaluation/evaluators/*.py`: Evaluation metrics
- `evaluation/analysis/run_analysis.py`: Main analysis pipeline

---

**Document Status**: 📝 Draft v1.0  
**Review Status**: Pending team review  
**Implementation Status**: Baseline 1 ✅ | Baselines 2-5 🔲

---

*For questions or suggestions, contact the research team.*
