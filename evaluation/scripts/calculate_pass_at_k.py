#!/usr/bin/env python3
"""
Calculate pass@k metrics for FAIRiAgent evaluation.

Similar to SWE-agent benchmark, this script calculates:
- pass@1: Probability of success in a single attempt
- pass@k: Probability of at least one success in k attempts

Success is defined based on configurable criteria:
- Basic: Run completed successfully
- Output: Produced minimum number of fields
- Quality: Meets minimum quality thresholds (completeness, F1, confidence)
"""

import json
import argparse
import math
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import numpy as np


@dataclass
class SuccessCriteria:
    """Configurable success criteria for pass@k calculation."""
    
    # Basic criteria (always required)
    require_run_success: bool = True
    
    # Output criteria
    min_fields_extracted: int = 5
    min_packages_used: int = 1  # Minimum number of packages in output
    
    # Completeness criteria
    min_overall_completeness: float = 0.0  # 0-1
    min_required_completeness: float = 0.3  # At least 30% of required fields
    min_recommended_completeness: float = 0.0
    
    # Correctness criteria
    min_f1_score: float = 0.0
    min_precision: float = 0.0
    min_recall: float = 0.0
    
    # Confidence criteria
    min_overall_confidence: float = 0.0
    
    # Combination mode: 'all' (AND) or 'any' (OR)
    combination_mode: str = 'all'
    
    def __str__(self):
        parts = []
        if self.require_run_success:
            parts.append("run_success")
        if self.min_fields_extracted > 0:
            parts.append(f"fields≥{self.min_fields_extracted}")
        if self.min_required_completeness > 0:
            parts.append(f"req_comp≥{self.min_required_completeness:.0%}")
        if self.min_f1_score > 0:
            parts.append(f"f1≥{self.min_f1_score:.2f}")
        return f"Success({', '.join(parts)})"


# Predefined success criteria levels
CRITERIA_PRESETS = {
    'basic': SuccessCriteria(
        require_run_success=True,
        min_fields_extracted=1,
        min_required_completeness=0.0,
        min_f1_score=0.0,
    ),
    'lenient': SuccessCriteria(
        require_run_success=True,
        min_fields_extracted=5,
        min_required_completeness=0.2,
        min_f1_score=0.0,
    ),
    'moderate': SuccessCriteria(
        require_run_success=True,
        min_fields_extracted=10,
        min_required_completeness=0.5,
        min_f1_score=0.3,
    ),
    'strict': SuccessCriteria(
        require_run_success=True,
        min_fields_extracted=15,
        min_required_completeness=0.7,
        min_f1_score=0.5,
        min_overall_confidence=0.6,
    ),
    'very_strict': SuccessCriteria(
        require_run_success=True,
        min_fields_extracted=20,
        min_required_completeness=0.8,
        min_f1_score=0.6,
        min_overall_confidence=0.7,
    ),
}


def is_successful(eval_result: Dict[str, Any], criteria: SuccessCriteria) -> Tuple[bool, List[str]]:
    """
    Check if an evaluation result meets the success criteria.
    
    Returns:
        Tuple of (success, list of reasons for failure)
    """
    failures = []
    
    # Basic: Run success
    if criteria.require_run_success:
        if not eval_result.get('success', False):
            failures.append("run_failed")
            return False, failures
    
    # Output: Fields extracted
    n_fields = eval_result.get('n_fields_extracted', 0)
    if n_fields < criteria.min_fields_extracted:
        failures.append(f"fields={n_fields}<{criteria.min_fields_extracted}")
    
    # Completeness metrics
    completeness = eval_result.get('completeness', {})
    
    overall_comp = completeness.get('overall_completeness', 0.0)
    if overall_comp < criteria.min_overall_completeness:
        failures.append(f"overall_comp={overall_comp:.2f}<{criteria.min_overall_completeness:.2f}")
    
    req_comp = completeness.get('required_completeness', 0.0)
    if req_comp < criteria.min_required_completeness:
        failures.append(f"req_comp={req_comp:.2f}<{criteria.min_required_completeness:.2f}")
    
    rec_comp = completeness.get('recommended_completeness', 0.0)
    if rec_comp < criteria.min_recommended_completeness:
        failures.append(f"rec_comp={rec_comp:.2f}<{criteria.min_recommended_completeness:.2f}")
    
    # Correctness metrics
    correctness = eval_result.get('correctness', {})
    
    f1 = correctness.get('f1_score', 0.0)
    if f1 < criteria.min_f1_score:
        failures.append(f"f1={f1:.2f}<{criteria.min_f1_score:.2f}")
    
    precision = correctness.get('precision', 0.0)
    if precision < criteria.min_precision:
        failures.append(f"precision={precision:.2f}<{criteria.min_precision:.2f}")
    
    recall = correctness.get('recall', 0.0)
    if recall < criteria.min_recall:
        failures.append(f"recall={recall:.2f}<{criteria.min_recall:.2f}")
    
    # Confidence metrics
    internal = eval_result.get('internal_metrics', {})
    confidence = internal.get('overall_confidence', 0.0)
    if confidence < criteria.min_overall_confidence:
        failures.append(f"confidence={confidence:.2f}<{criteria.min_overall_confidence:.2f}")
    
    # Determine success based on combination mode
    if criteria.combination_mode == 'all':
        return len(failures) == 0, failures
    else:  # 'any' - at least basic criteria met
        basic_ok = eval_result.get('success', False) and n_fields >= criteria.min_fields_extracted
        return basic_ok, failures


def calculate_pass_at_k(n: int, c: int, k: int) -> float:
    """
    Calculate pass@k using the unbiased estimator.
    
    pass@k = 1 - C(n-c, k) / C(n, k)
           = 1 - ∏(i=0 to k-1) [(n-c-i)/(n-i)]
    
    Args:
        n: Total number of samples
        c: Number of successful samples
        k: k value for pass@k
        
    Returns:
        pass@k value between 0 and 1
    """
    if n == 0:
        return 0.0
    if c == 0:
        return 0.0
    if k > n:
        k = n
    if c >= n:
        return 1.0
    
    # Use log to avoid numerical overflow for large numbers
    # pass@k = 1 - exp(log(C(n-c, k)) - log(C(n, k)))
    # log(C(n-c, k)) - log(C(n, k)) = sum(log(n-c-i) - log(n-i)) for i in 0..k-1
    
    log_ratio = 0.0
    for i in range(k):
        if n - c - i <= 0:
            # Not enough failures to fill k slots, so pass@k = 1
            return 1.0
        log_ratio += math.log(n - c - i) - math.log(n - i)
    
    return 1.0 - math.exp(log_ratio)


def load_eval_results(runs_dir: Path, exclude_models: List[str] = None, exclude_docs: List[str] = None) -> Dict[str, Dict[str, List[Dict]]]:
    """
    Load all eval_result.json files from the runs directory.
    
    Returns:
        Nested dict: {model_name: {document_id: [eval_results]}}
    """
    results = defaultdict(lambda: defaultdict(list))
    exclude_models = exclude_models or []
    exclude_docs = exclude_docs or []
    
    # Find all eval_result.json files
    for eval_file in runs_dir.rglob('eval_result.json'):
        try:
            with open(eval_file, 'r') as f:
                data = json.load(f)
            
            model = data.get('config_name', 'unknown')
            doc_id = data.get('document_id', 'unknown')
            
            # Skip excluded
            if model in exclude_models or doc_id in exclude_docs:
                continue
            
            # Add file path for reference
            data['_eval_file'] = str(eval_file)
            
            results[model][doc_id].append(data)
            
        except Exception as e:
            print(f"Warning: Failed to load {eval_file}: {e}")
    
    return dict(results)


def calculate_pass_at_k_for_model(
    model_results: Dict[str, List[Dict]], 
    criteria: SuccessCriteria,
    k_values: List[int] = [1, 3, 5, 10]
) -> Dict[str, Any]:
    """
    Calculate pass@k metrics for a single model across all documents.
    
    Returns:
        Dict with pass@k values and detailed breakdown
    """
    results = {
        'k_values': k_values,
        'pass_at_k': {},
        'by_document': {},
        'aggregate': {
            'total_runs': 0,
            'successful_runs': 0,
            'total_documents': 0,
            'documents_with_success': 0,
        }
    }
    
    all_n = []  # Total runs per document
    all_c = []  # Successful runs per document
    
    for doc_id, runs in model_results.items():
        n = len(runs)
        c = sum(1 for r in runs if is_successful(r, criteria)[0])
        
        all_n.append(n)
        all_c.append(c)
        
        results['aggregate']['total_runs'] += n
        results['aggregate']['successful_runs'] += c
        results['aggregate']['total_documents'] += 1
        if c > 0:
            results['aggregate']['documents_with_success'] += 1
        
        # Per-document pass@k
        doc_pass_at_k = {}
        for k in k_values:
            doc_pass_at_k[f'pass@{k}'] = calculate_pass_at_k(n, c, k)
        
        results['by_document'][doc_id] = {
            'n': n,
            'c': c,
            'success_rate': c / n if n > 0 else 0.0,
            **doc_pass_at_k
        }
    
    # Aggregate pass@k (average across documents)
    for k in k_values:
        pass_k_values = [calculate_pass_at_k(n, c, k) for n, c in zip(all_n, all_c)]
        results['pass_at_k'][f'pass@{k}'] = np.mean(pass_k_values) if pass_k_values else 0.0
        results['pass_at_k'][f'pass@{k}_std'] = np.std(pass_k_values) if pass_k_values else 0.0
    
    # Overall success rate
    total_n = results['aggregate']['total_runs']
    total_c = results['aggregate']['successful_runs']
    results['aggregate']['overall_success_rate'] = total_c / total_n if total_n > 0 else 0.0
    
    return results


def generate_report(
    all_results: Dict[str, Dict[str, List[Dict]]],
    criteria: SuccessCriteria,
    k_values: List[int] = [1, 3, 5, 10],
    output_format: str = 'markdown'
) -> str:
    """Generate a pass@k report for all models."""
    
    lines = []
    
    if output_format == 'markdown':
        lines.append("# FAIRiAgent pass@k Evaluation Report\n")
        lines.append(f"**Success Criteria:** {criteria}\n")
        lines.append("")
        
        # Summary table
        lines.append("## Summary (pass@k averaged across documents)\n")
        header = "| Model | Runs | Success Rate | " + " | ".join([f"pass@{k}" for k in k_values]) + " |"
        separator = "|-------|------|--------------|" + "|".join(["-------" for _ in k_values]) + "|"
        lines.append(header)
        lines.append(separator)
        
        model_metrics = {}
        for model, doc_results in sorted(all_results.items()):
            metrics = calculate_pass_at_k_for_model(doc_results, criteria, k_values)
            model_metrics[model] = metrics
            
            agg = metrics['aggregate']
            pass_k = metrics['pass_at_k']
            
            row = f"| {model} | {agg['total_runs']} | {agg['overall_success_rate']:.1%} | "
            row += " | ".join([f"{pass_k[f'pass@{k}']:.3f}" for k in k_values])
            row += " |"
            lines.append(row)
        
        lines.append("")
        
        # Detailed breakdown by document
        lines.append("## Detailed Results by Document\n")
        
        for model, metrics in model_metrics.items():
            lines.append(f"### {model}\n")
            lines.append("| Document | n | c | Success Rate | " + " | ".join([f"pass@{k}" for k in k_values]) + " |")
            lines.append("|----------|---|---|--------------|" + "|".join(["-------" for _ in k_values]) + "|")
            
            for doc_id, doc_metrics in metrics['by_document'].items():
                row = f"| {doc_id} | {doc_metrics['n']} | {doc_metrics['c']} | {doc_metrics['success_rate']:.1%} | "
                row += " | ".join([f"{doc_metrics[f'pass@{k}']:.3f}" for k in k_values])
                row += " |"
                lines.append(row)
            
            lines.append("")
        
        # Criteria explanation
        lines.append("## Success Criteria Details\n")
        lines.append("```")
        lines.append(f"require_run_success: {criteria.require_run_success}")
        lines.append(f"min_fields_extracted: {criteria.min_fields_extracted}")
        lines.append(f"min_required_completeness: {criteria.min_required_completeness:.0%}")
        lines.append(f"min_recommended_completeness: {criteria.min_recommended_completeness:.0%}")
        lines.append(f"min_f1_score: {criteria.min_f1_score:.2f}")
        lines.append(f"min_overall_confidence: {criteria.min_overall_confidence:.2f}")
        lines.append("```")
        
    elif output_format == 'json':
        output = {
            'criteria': {
                'require_run_success': criteria.require_run_success,
                'min_fields_extracted': criteria.min_fields_extracted,
                'min_required_completeness': criteria.min_required_completeness,
                'min_f1_score': criteria.min_f1_score,
            },
            'k_values': k_values,
            'models': {}
        }
        
        for model, doc_results in all_results.items():
            output['models'][model] = calculate_pass_at_k_for_model(doc_results, criteria, k_values)
        
        return json.dumps(output, indent=2)
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Calculate pass@k metrics for FAIRiAgent evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Success Criteria Presets:
  basic       - Run succeeds, ≥1 field extracted
  lenient     - Run succeeds, ≥5 fields, ≥20% required completeness
  moderate    - Run succeeds, ≥10 fields, ≥50% required completeness, ≥0.3 F1
  strict      - Run succeeds, ≥15 fields, ≥70% required completeness, ≥0.5 F1
  very_strict - Run succeeds, ≥20 fields, ≥80% required completeness, ≥0.6 F1

Examples:
  python calculate_pass_at_k.py --runs-dir evaluation/runs --preset moderate
  python calculate_pass_at_k.py --runs-dir evaluation/runs --min-fields 10 --min-f1 0.4
        """
    )
    
    parser.add_argument("--runs-dir", type=Path, required=True,
                       help="Directory containing evaluation runs")
    parser.add_argument("--output", type=Path, default=None,
                       help="Output file (default: stdout)")
    parser.add_argument("--format", choices=['markdown', 'json'], default='markdown',
                       help="Output format")
    
    # Criteria presets
    parser.add_argument("--preset", choices=list(CRITERIA_PRESETS.keys()), default=None,
                       help="Use predefined success criteria preset")
    
    # Custom criteria
    parser.add_argument("--min-fields", type=int, default=None,
                       help="Minimum fields extracted for success")
    parser.add_argument("--min-req-comp", type=float, default=None,
                       help="Minimum required completeness (0-1)")
    parser.add_argument("--min-f1", type=float, default=None,
                       help="Minimum F1 score")
    parser.add_argument("--min-confidence", type=float, default=None,
                       help="Minimum overall confidence")
    
    # k values
    parser.add_argument("--k-values", type=int, nargs='+', default=[1, 3, 5, 10],
                       help="k values to calculate pass@k for")
    
    # Filtering
    parser.add_argument("--exclude-models", nargs='+', default=[],
                       help="Models to exclude from analysis")
    parser.add_argument("--exclude-docs", nargs='+', default=[],
                       help="Documents to exclude from analysis")
    
    args = parser.parse_args()
    
    # Build criteria
    if args.preset:
        criteria = CRITERIA_PRESETS[args.preset]
    else:
        criteria = SuccessCriteria()
    
    # Override with custom values if provided
    if args.min_fields is not None:
        criteria.min_fields_extracted = args.min_fields
    if args.min_req_comp is not None:
        criteria.min_required_completeness = args.min_req_comp
    if args.min_f1 is not None:
        criteria.min_f1_score = args.min_f1
    if args.min_confidence is not None:
        criteria.min_overall_confidence = args.min_confidence
    
    # Load results
    print(f"Loading results from {args.runs_dir}...")
    all_results = load_eval_results(args.runs_dir, args.exclude_models, args.exclude_docs)
    
    total_models = len(all_results)
    total_runs = sum(len(runs) for doc_results in all_results.values() for runs in doc_results.values())
    print(f"Loaded {total_runs} runs from {total_models} models")
    
    # Generate report
    report = generate_report(all_results, criteria, args.k_values, args.format)
    
    # Output
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"Report saved to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
