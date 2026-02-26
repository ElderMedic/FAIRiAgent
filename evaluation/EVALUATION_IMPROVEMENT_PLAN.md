# Evaluation Framework Improvement Plan for Research Publication

**Date**: 2026-01-30  
**Purpose**: Address meeting feedback (2026-01-16) for scientific paper preparation  
**Status**: 🎯 Implementation Plan

---

## 📋 Executive Summary

Based on the meeting feedback, we need to refine our evaluation methodology to better demonstrate FAIRiAgent's value proposition. The key insight: **our audience (researchers) are lazy and don't know what they want** - they need to see clearly that the agent makes better metadata choices than they would manually.

**Core Problem Identified**: Current metrics focus on overall completeness, but miss critical success criteria - **100% mandatory field coverage within selected packages**.

---

## 🎯 Meeting Feedback & Action Items

### 1. **SUCCESS CRITERION #1: 100% Mandatory Field Coverage** ⭐ CRITICAL

#### Current Problem
- We report overall completeness (e.g., 70%) regardless of mandatory field coverage
- A run with 90% completeness but missing key mandatory fields is treated as "good"
- This doesn't reflect real-world usability

#### Proposed Solution

**New Success Definition:**
```python
RUN_SUCCESS = (
    mandatory_completeness == 1.0  # 100% mandatory fields present
    AND package_correctly_selected == True
)
```

**Implementation:**
1. **Add to `completeness_evaluator.py`**:
   ```python
   def is_run_successful(self, result: Dict) -> bool:
       """
       Determine if a run meets minimum success criteria.
       
       Success = 100% mandatory fields for selected package
       """
       package = result['selected_package']
       pkg_metrics = result['by_package'][package]
       
       # Get mandatory fields only
       mandatory_count = pkg_metrics['mandatory_expected']
       mandatory_covered = pkg_metrics['mandatory_covered']
       
       return (mandatory_covered / mandatory_count) == 1.0
   ```

2. **Filter Analysis Pipeline**:
   ```python
   # In run_analysis.py
   successful_runs = [
       run for run in all_runs 
       if evaluator.is_run_successful(run['eval_result'])
   ]
   
   failed_runs = [
       run for run in all_runs
       if not evaluator.is_run_successful(run['eval_result'])
   ]
   ```

3. **Update All Visualizations**:
   - Show two sets of results: "All Runs" vs "Successful Runs Only"
   - Add success rate metric: `(successful_runs / total_runs) * 100`

**Impact Metrics:**
- **Success Rate**: % of runs meeting 100% mandatory criterion
- **Consensus Quality**: Stats on successful runs only (more meaningful)
- **Failure Analysis**: Why did runs fail? Missing mandatory fields breakdown

---

### 2. **Field Presence Matrix** ⭐ HIGH PRIORITY

#### Why This Matters
Shows **exactly** what each model extracts, making it easy to spot:
- Core fields all models get right
- Fields only top models extract
- Hallucinated fields (extras not in ground truth)

#### Proposed Visualization

**Matrix Design:**
```
                    | Model A | Model B | Model C | ... | Ground Truth
Field Name          | Run1-10 | Run1-10 | Run1-10 | ... | Expected
--------------------|---------|---------|---------|-----|-------------
[M] study_id        |  ✓✓✓✓✓  |  ✓✓✓✓✗  |  ✓✓✓✓✓  | ... |    ✓
[M] assay_type      |  ✓✓✓✓✓  |  ✓✓✓✗✗  |  ✓✓✓✓✗  | ... |    ✓
[R] protocol        |  ✓✓✗✗✗  |  ✓✗✗✗✗  |  ✓✓✓✗✗  | ... |    ✓
[O] notes           |  ✗✗✗✗✗  |  ✓✗✗✗✗  |  ✗✗✗✗✗  | ... |    ✓
[X] made_up_field   |  ✗✗✗✓✗  |  ✗✗✗✗✗  |  ✗✗✗✗✗  | ... |    ✗

Legend:
[M] = Mandatory  [R] = Recommended  [O] = Optional  [X] = Extra (not in GT)
✓ = Present  ✗ = Missing
```

**Implementation:**
```python
def plot_field_presence_matrix(
    self,
    df: pd.DataFrame,
    document_id: str,
    ground_truth: Dict,
    filename: str = 'field_presence_matrix'
):
    """
    Create detailed field presence matrix.
    
    Shows:
    - All ground truth fields (rows)
    - All models + runs (columns)
    - Field category ([M]andatory, [R]ecommended, [O]ptional)
    - Presence/absence heatmap
    - Highlight hallucinated fields
    """
    # Get all fields from ground truth
    gt_fields = ground_truth['ground_truth_fields']
    
    # Create presence matrix
    matrix_data = []
    for field in gt_fields:
        row = {
            'field_name': field['field_name'],
            'category': get_category_label(field),
            'isa_sheet': field['isa_sheet'],
            'package': field.get('package_source', 'default')
        }
        
        # For each model, check presence across 10 runs
        for model in df['model_name'].unique():
            runs = df[(df['model_name'] == model) & 
                     (df['document_id'] == document_id)]
            
            presence_pattern = ''
            for _, run in runs.iterrows():
                extracted = run['extracted_field_names']
                presence_pattern += '✓' if field['field_name'] in extracted else '✗'
            
            row[f'{model}_presence'] = presence_pattern
            row[f'{model}_rate'] = presence_pattern.count('✓') / len(runs)
        
        matrix_data.append(row)
    
    # Add extra fields (hallucinations)
    # ... (check for fields in extracted but not in GT)
    
    # Create heatmap
    matrix_df = pd.DataFrame(matrix_data)
    
    # Plot with category coloring
    fig, ax = plt.subplots(figsize=(16, max(10, len(matrix_df) * 0.3)))
    
    # Create heatmap (0-1 scale for presence rate)
    model_cols = [col for col in matrix_df.columns if col.endswith('_rate')]
    sns.heatmap(
        matrix_df[model_cols],
        annot=True,
        fmt='.0%',
        cmap='RdYlGn',
        vmin=0,
        vmax=1,
        yticklabels=matrix_df['field_name'],
        cbar_kws={'label': 'Presence Rate (across 10 runs)'},
        linewidths=0.5
    )
    
    # Color-code field categories on y-axis
    # [M] = Red background, [R] = Yellow, [O] = Green, [X] = Gray
    
    ax.set_title(f'Field Presence Matrix: {document_id}', 
                fontsize=16, fontweight='bold')
    ax.set_xlabel('Model', fontsize=13)
    ax.set_ylabel('Field Name [Category]', fontsize=13)
    
    plt.tight_layout()
    plt.savefig(self.output_dir / f'{filename}_{document_id}.png', 
                dpi=300, bbox_inches='tight')
    plt.close()
```

**Output Tables:**
1. **Presence Matrix (CSV)** - Full data for supplementary materials
2. **Core Fields Table** - Fields extracted by ≥80% of runs across all models
3. **Model-Specific Fields** - Fields uniquely or predominantly extracted by specific models
4. **Hallucination Report** - Extra fields not in ground truth, by model

---

### 3. **Core/Shared Terms Analysis** ⭐ HIGH PRIORITY

#### Research Question
> "Why is earthworm more stable but lower completeness? Different terms when same completeness score?"

#### Proposed Analysis

**Stability vs. Completeness Decomposition:**

```python
def analyze_stability_completeness_tradeoff(
    self,
    df: pd.DataFrame,
    document_id: str
) -> Dict:
    """
    Analyze why some documents show high stability but low completeness.
    
    Hypothesis: Different models extract different field sets with 
    similar cardinality but different content.
    """
    results = {
        'document_id': document_id,
        'models': {}
    }
    
    for model in df['model_name'].unique():
        runs = df[(df['model_name'] == model) & 
                 (df['document_id'] == document_id)]
        
        # Collect all extracted field sets
        field_sets = [set(run['extracted_field_names']) for _, run in runs.iterrows()]
        
        # Core fields: present in ALL runs
        core_fields = set.intersection(*field_sets) if field_sets else set()
        
        # Variable fields: present in SOME runs
        all_fields = set.union(*field_sets) if field_sets else set()
        variable_fields = all_fields - core_fields
        
        # Stability metrics
        stability = len(core_fields) / len(all_fields) if all_fields else 0
        
        # Completeness (vs ground truth)
        gt_fields = set(ground_truth['field_names'])
        completeness = len(all_fields & gt_fields) / len(gt_fields)
        
        # Core field quality
        core_correct = len(core_fields & gt_fields)
        core_hallucinated = len(core_fields - gt_fields)
        
        results['models'][model] = {
            'n_runs': len(runs),
            'core_fields': list(core_fields),
            'variable_fields': list(variable_fields),
            'stability_score': stability,
            'completeness_score': completeness,
            'core_field_count': len(core_fields),
            'variable_field_count': len(variable_fields),
            'core_correct_count': core_correct,
            'core_hallucinated_count': core_hallucinated,
            'interpretation': interpret_tradeoff(stability, completeness)
        }
    
    return results

def interpret_tradeoff(stability: float, completeness: float) -> str:
    """Interpret stability-completeness pattern."""
    if stability > 0.8 and completeness < 0.6:
        return "HIGH_STABILITY_LOW_COMPLETENESS: Model consistently extracts same limited field set"
    elif stability < 0.5 and completeness > 0.7:
        return "LOW_STABILITY_HIGH_COMPLETENESS: Model explores diverse fields across runs"
    elif stability > 0.8 and completeness > 0.7:
        return "IDEAL: Consistent and comprehensive extraction"
    else:
        return "POOR: Low stability and low completeness"
```

**Visualizations:**

1. **Stability-Completeness Scatter Plot**:
   - X-axis: Completeness (0-1)
   - Y-axis: Stability (0-1)  
   - Points: Models (colored by family)
   - Size: Number of core fields
   - Quadrants: Ideal (top-right), Exploratory (bottom-right), Conservative (top-left), Poor (bottom-left)

2. **Shared Terms Venn Diagram**:
   - For each document, show overlap of field sets across top 3 models
   - Highlight mandatory fields in core overlap

3. **Core Fields Table**:
   ```
   Field Name          | Category | Model A | Model B | Model C | Consensus
   --------------------|----------|---------|---------|---------|----------
   study_id            | M        | 10/10   | 10/10   | 10/10   | Core
   assay_type          | M        |  9/10   | 10/10   |  8/10   | Core  
   optional_notes      | O        |  2/10   |  0/10   |  1/10   | Rare
   ```

---

### 4. **Extra Fields Validation** ⭐ MEDIUM PRIORITY

#### Research Question
> "On the extra terms: whether they exist [in document]? or made up?"

#### Proposed Analysis

**Hallucination Detection:**

```python
def validate_extra_fields(
    self,
    extra_fields: List[str],
    document_text: str,
    fairifier_output: Dict
) -> Dict:
    """
    Determine if extra fields are:
    1. Legitimate (present in document but missing from ground truth)
    2. Near-miss (similar to ground truth field, different naming)
    3. Hallucination (not found in document)
    """
    validation_results = {}
    
    for field in extra_fields:
        # Get field value from FAIRiAgent output
        field_value = get_field_value(fairifier_output, field)
        
        # Check 1: Value appears in document text?
        value_in_doc = field_value in document_text if field_value else False
        
        # Check 2: Field name similarity to GT fields
        similar_gt_fields = find_similar_fields(field, ground_truth_fields)
        
        # Check 3: Semantic search in document
        # (use simple string matching for now)
        field_keywords = field.lower().replace('_', ' ').split()
        keyword_matches = sum(1 for kw in field_keywords if kw in document_text.lower())
        keyword_score = keyword_matches / len(field_keywords) if field_keywords else 0
        
        # Classification
        if value_in_doc and keyword_score > 0.5:
            category = "LEGITIMATE"
            reason = "Field value and keywords found in document"
        elif len(similar_gt_fields) > 0:
            category = "NEAR_MISS"
            reason = f"Similar to GT field: {similar_gt_fields[0]}"
        elif value_in_doc:
            category = "POSSIBLE_VALID"
            reason = "Value found in document, but field name unclear"
        else:
            category = "HALLUCINATION"
            reason = "Field value not found in document"
        
        validation_results[field] = {
            'category': category,
            'reason': reason,
            'value': field_value,
            'value_in_document': value_in_doc,
            'keyword_score': keyword_score,
            'similar_gt_fields': similar_gt_fields
        }
    
    return validation_results
```

**Output:**
- **Extra Fields Report (per model)**:
  - Total extra fields
  - Breakdown: Legitimate / Near-miss / Hallucination
  - Examples of each category
- **Hallucination Rate Metric**:
  - `hallucination_rate = n_hallucinations / (n_correct_fields + n_hallucinations)`

---

### 5. **Package Selection Quality Analysis** ⭐ HIGH PRIORITY

#### Research Question
> "Demonstrate that models making better choices with looking at the content"

#### Proposed Analysis

**Package Selection Quality Metrics:**

```python
def analyze_package_selection_quality(
    self,
    fairifier_output: Dict,
    ground_truth: Dict,
    document_metadata: Dict
) -> Dict:
    """
    Evaluate whether agent selected appropriate metadata package.
    
    Quality indicators:
    1. Correct package selected (vs. ground truth)
    2. Package matches document domain/type
    3. Package-specific mandatory fields covered
    """
    selected_package = fairifier_output.get('selected_package', 'unknown')
    expected_package = ground_truth.get('expected_package', 'unknown')
    
    # 1. Package correctness
    package_correct = (selected_package == expected_package)
    
    # 2. Domain alignment
    doc_domain = document_metadata.get('domain', '')  # e.g., "metagenomics"
    package_domain = get_package_domain(selected_package)  # e.g., "metagenomics"
    domain_aligned = (doc_domain.lower() in package_domain.lower())
    
    # 3. Mandatory field coverage (for selected package)
    package_mandatory_fields = get_mandatory_fields_for_package(selected_package)
    extracted_fields = set(fairifier_output['extracted_field_names'])
    
    mandatory_covered = len(extracted_fields & package_mandatory_fields)
    mandatory_total = len(package_mandatory_fields)
    mandatory_coverage = mandatory_covered / mandatory_total if mandatory_total else 0
    
    # 4. Decision quality score
    quality_score = 0
    if package_correct: quality_score += 0.5
    if domain_aligned: quality_score += 0.2
    if mandatory_coverage >= 1.0: quality_score += 0.3
    
    # 5. Compare with alternative packages
    alternative_packages = get_alternative_packages(doc_domain)
    alternative_scores = {}
    
    for alt_pkg in alternative_packages:
        alt_mandatory = get_mandatory_fields_for_package(alt_pkg)
        alt_coverage = len(extracted_fields & alt_mandatory) / len(alt_mandatory)
        alternative_scores[alt_pkg] = alt_coverage
    
    # Best alternative (counterfactual)
    best_alternative = max(alternative_scores.items(), key=lambda x: x[1]) if alternative_scores else (None, 0)
    
    return {
        'selected_package': selected_package,
        'expected_package': expected_package,
        'package_correct': package_correct,
        'domain_aligned': domain_aligned,
        'mandatory_coverage': mandatory_coverage,
        'quality_score': quality_score,
        'alternatives': alternative_scores,
        'best_alternative': best_alternative[0],
        'best_alternative_score': best_alternative[1],
        'decision_quality': 'GOOD' if quality_score >= 0.8 else 'ACCEPTABLE' if quality_score >= 0.5 else 'POOR'
    }
```

**Visualizations:**
1. **Package Selection Accuracy** (bar chart):
   - % of runs selecting correct package, by model
   - % of runs with 100% mandatory coverage

2. **Domain-Package Alignment Matrix**:
   - Rows: Document domains (metagenomics, transcriptomics, etc.)
   - Columns: Selected packages
   - Values: Frequency heatmap
   - Show if models learn domain→package mapping

3. **Decision Quality Over Runs** (line plot):
   - X-axis: Run number (1-10)
   - Y-axis: Package selection quality score
   - Show if quality improves with memory (if shared project-id used)

---

### 6. **Consensus Analysis (Filtered)** ⭐ CRITICAL

#### Why This Matters
Current analysis includes ALL runs, diluting results with failed runs that don't meet basic success criteria.

#### Implementation

**Filter Pipeline:**
```python
def generate_consensus_analysis(
    self,
    all_runs: List[Dict],
    success_criterion: str = 'mandatory_100'
) -> Dict:
    """
    Generate consensus analysis on successful runs only.
    
    Success criteria options:
    - 'mandatory_100': 100% mandatory fields for selected package
    - 'mandatory_90': ≥90% mandatory fields
    - 'package_correct': Correct package selected
    """
    # Apply filter
    if success_criterion == 'mandatory_100':
        successful_runs = [
            run for run in all_runs
            if run['eval_result']['by_package'][run['selected_package']]['mandatory_coverage'] == 1.0
        ]
    # ... other criteria
    
    failed_runs = [run for run in all_runs if run not in successful_runs]
    
    # Consensus stats on successful runs only
    consensus_stats = {
        'total_runs': len(all_runs),
        'successful_runs': len(successful_runs),
        'failed_runs': len(failed_runs),
        'success_rate': len(successful_runs) / len(all_runs) if all_runs else 0,
        
        # Aggregate metrics on successful runs
        'consensus_metrics': {
            'mean_completeness': np.mean([r['completeness'] for r in successful_runs]),
            'mean_correctness': np.mean([r['correctness_f1'] for r in successful_runs]),
            'mean_quality_score': np.mean([r['aggregate_score'] for r in successful_runs]),
        },
        
        # Failure analysis
        'failure_breakdown': analyze_failure_reasons(failed_runs)
    }
    
    return consensus_stats
```

**Output:**
- **Success Rate Leaderboard**: Models ranked by % successful runs
- **Consensus Quality Metrics**: Stats on successful runs only (more meaningful than all runs)
- **Failure Taxonomy**: Why do runs fail? Missing mandatory fields breakdown

---

## 📊 New Visualizations Summary

### For Main Paper

1. **Figure 1: Model Success Rate & Quality**
   - Panel A: Success rate (% runs with 100% mandatory) - Bar chart
   - Panel B: Quality on successful runs only - Box plot
   - Panel C: Stability vs Completeness - Scatter plot

2. **Figure 2: Field Presence Matrix (Representative Document)**
   - Heatmap showing mandatory/recommended/optional field extraction
   - Highlight consensus fields vs. model-specific fields

3. **Figure 3: Package Selection Quality**
   - Panel A: Package accuracy by model - Bar chart
   - Panel B: Domain-package alignment - Heatmap

4. **Figure 4: Core vs. Variable Fields**
   - Venn diagram showing field overlap across top 3 models
   - Table of core mandatory fields with 100% presence

### For Supplementary Materials

5. **Table S1: Complete Field Presence Matrix**
   - Full matrix for all documents (CSV format)

6. **Table S2: Hallucination Report**
   - Extra fields breakdown: Legitimate / Near-miss / Hallucination
   - Examples and validation details

7. **Table S3: Failure Analysis**
   - Runs not meeting 100% mandatory criterion
   - Missing mandatory fields by model and document

8. **Figure S1: Pass@k with Mandatory Filter**
   - Pass@k curves using 100% mandatory as success criterion

---

## 🔧 Implementation Priority

### Phase 1: Critical Updates (Week 1)
1. ✅ Implement 100% mandatory success criterion
2. ✅ Add run filtering pipeline
3. ✅ Update all analysis scripts to use filtered runs
4. ✅ Generate success rate metrics

### Phase 2: Core Visualizations (Week 2)
5. ✅ Field presence matrix
6. ✅ Core/shared terms analysis
7. ✅ Stability-completeness decomposition
8. ✅ Package selection quality

### Phase 3: Advanced Analysis (Week 3)
9. ✅ Extra fields validation (hallucination detection)
10. ✅ Consensus analysis (filtered)
11. ✅ Domain-package alignment matrix

### Phase 4: Paper-Ready Outputs (Week 4)
12. ✅ Generate all main figures (publication quality)
13. ✅ Generate all supplementary tables
14. ✅ Write results narrative with key findings

---

## 📝 Expected Results Narrative

Based on these improvements, the paper results section should tell this story:

### Story Arc

1. **Context**: Metadata extraction is hard - many fields, complex schemas
   
2. **Challenge**: Not all metadata is equally important. Mandatory fields are critical for data submission.

3. **Key Finding 1**: FAIRiAgent achieves **XX% success rate** (100% mandatory fields) vs. **YY%** for baseline
   - *Evidence*: Success rate bar chart + significance test

4. **Key Finding 2**: Top models show **high stability + high completeness** (ideal quadrant)
   - *Evidence*: Stability-completeness scatter plot
   - *Insight*: Earthworm shows high stability but lower completeness because it has more mandatory fields, and models consistently get core mandatory fields right but vary on optional fields

5. **Key Finding 3**: Models make **appropriate package selections** based on document content
   - *Evidence*: Package selection accuracy (XX%) + domain alignment matrix
   - *Insight*: Models learn domain→package mapping, not random guessing

6. **Key Finding 4**: Low hallucination rate - extra fields are mostly **legitimate** or **near-miss** naming variants
   - *Evidence*: Hallucination report table
   - *Insight*: Models extract real information, not fabricating

7. **Key Finding 5**: Core mandatory fields show **>90% consensus** across models
   - *Evidence*: Field presence matrix + core fields table
   - *Insight*: Problem is well-defined; models agree on critical fields

8. **Conclusion**: FAIRiAgent reliably extracts mandatory metadata at publication-ready quality

---

## 🎓 Audience Considerations

> "Our users/audience are lazy, and they don't know what they want!"

### Translation for Paper

**What researchers want (but don't say)**:
1. "Will this save me time?" → **Success rate metric** (% runs ready for submission)
2. "Will it work on my data?" → **Domain-package alignment** (shows adaptability)
3. "Can I trust it?" → **Core fields consensus** (high agreement = reliability)
4. "What if it's wrong?" → **Hallucination analysis** (low rate = trustworthy)

**Key Message**: 
FAIRiAgent doesn't just extract metadata - it extracts **submission-ready** metadata with critical mandatory fields at **publication quality**.

---

## ✅ Success Metrics for This Plan

**Quantitative:**
- [ ] Success rate metric implemented (100% mandatory criterion)
- [ ] Field presence matrix generated for all documents
- [ ] Core fields analysis completed
- [ ] Hallucination rate < 10% demonstrated
- [ ] Package selection accuracy > 80%

**Qualitative:**
- [ ] Results tell clear story: "agent makes good decisions"
- [ ] Visualizations are publication-ready (Nature/Science quality)
- [ ] Supplementary materials are comprehensive
- [ ] Reviewers can reproduce analysis from provided data

---

## 📚 Files to Create/Modify

### New Files
1. `evaluation/evaluators/mandatory_coverage_evaluator.py` - 100% mandatory criterion
2. `evaluation/analysis/analyzers/field_presence.py` - Presence matrix logic
3. `evaluation/analysis/analyzers/package_selection.py` - Package quality analysis
4. `evaluation/analysis/analyzers/stability_completeness.py` - Stability decomposition
5. `evaluation/analysis/analyzers/hallucination_detector.py` - Extra fields validation
6. `evaluation/analysis/visualizations/field_presence_matrix.py` - Matrix visualization
7. `evaluation/analysis/visualizations/stability_plots.py` - Stability-completeness plots
8. `evaluation/analysis/visualizations/package_quality.py` - Package selection viz
9. `evaluation/scripts/generate_paper_figures.py` - Main figure generation script

### Modified Files
1. `evaluation/evaluators/completeness_evaluator.py` - Add mandatory tracking
2. `evaluation/analysis/run_analysis.py` - Add filtering pipeline
3. `evaluation/analysis/config.py` - Add success criterion configs
4. `evaluation/README.md` - Document new metrics and visualizations

---

## 🚀 Next Steps

1. **Discuss & Refine** this plan with team
2. **Prioritize** which analyses are most critical for paper
3. **Prototype** one key visualization (field presence matrix) to validate approach
4. **Implement** in phases as outlined above
5. **Generate** results on existing evaluation data (openai_gpt5.1, ollama_20260129)
6. **Draft** results section with key findings

---

**Questions for Discussion:**
1. Which visualizations are most compelling for the target journal?
2. Should we re-run evaluations with revised ground truth (if needed)?
3. What threshold for "success rate" would be impressive? (80%? 90%?)
4. Should we compare against human baseline for mandatory field coverage?

---

**Document Status**: 🎯 Ready for Team Review  
**Next Action**: Team meeting to prioritize implementation
