# Evaluation Framework Changes

## Overview

The evaluation framework has been updated to focus on **field presence** rather than **value correctness**. This aligns with the goal of evaluating metadata extraction completeness, not the accuracy of extracted values.

## Changes Made

### 1. Ground Truth Format

**Before**: Ground truth included `expected_value` for each field
```json
{
  "field_name": "investigation title",
  "expected_value": "Differential gene expression...",
  "is_required": true,
  ...
}
```

**After**: Ground truth only includes field metadata (no values)
```json
{
  "field_name": "investigation title",
  "is_required": true,
  "isa_sheet": "investigation",
  "package_source": "default",
  ...
}
```

**Script**: `evaluation/scripts/clean_ground_truth.py`
- Removes all `expected_value` fields
- Preserves field metadata (is_required, isa_sheet, etc.)
- Creates cleaned version: `ground_truth_v2.json`

### 2. Correctness Evaluator

**Before**: Compared extracted values against expected values
- Exact match checking
- Semantic match using LLM judge
- Value-based precision/recall/F1

**After**: Only checks field presence
- Checks if fields were extracted (present/absent)
- Field presence rate
- Precision/Recall/F1 based on field presence only
- No value comparison

**Metrics**:
- `field_presence_rate`: Percentage of ground truth fields that were extracted
- `precision`: TP / (TP + FP) = correct extractions / total extractions
- `recall`: TP / (TP + FN) = correct extractions / total ground truth fields
- `f1_score`: Harmonic mean of precision and recall

### 3. Configuration Update

**File**: `evaluation/config/env.evaluation`
- Updated default ground truth path: `ground_truth_v2.json`

## Usage

### Clean Existing Ground Truth

```bash
python evaluation/scripts/clean_ground_truth.py \
  evaluation/datasets/annotated/ground_truth_v1.json \
  evaluation/datasets/annotated/ground_truth_v2.json
```

### Run Evaluation

```bash
python evaluation/scripts/evaluate_outputs.py \
  --run-dir evaluation/runs/your_run_dir \
  --ground-truth evaluation/datasets/annotated/ground_truth_v2.json \
  --env-file evaluation/config/env.evaluation
```

## Evaluation Metrics

### Completeness Evaluator
- **Purpose**: Field coverage analysis
- **Metrics**: Overall completeness, required/recommended/optional completeness
- **Breakdown**: By ISA sheet, by package

### Correctness Evaluator (Field Presence)
- **Purpose**: Field extraction accuracy
- **Metrics**: Field presence rate, Precision, Recall, F1
- **Focus**: Which fields were extracted (not their values)

### Schema Validator
- **Purpose**: JSON structure and schema compliance
- **Metrics**: Validation pass rate, compliance rate

### Ontology Evaluator
- **Purpose**: Ontology term usage
- **Metrics**: Ontology usage rate, validity rate

### LLM Judge Evaluator
- **Purpose**: Holistic quality assessment
- **Metrics**: Multi-dimensional scores (evidence quality, appropriateness, completeness, accuracy)

## Results Format

Field-level results now show:
```json
{
  "field_name": {
    "is_present": true,
    "status": "PRESENT" or "MISSING",
    "confidence": 0.7,
    "has_value": true,
    "has_evidence": true
  }
}
```

No value comparison is performed.

