"""
Pass@k Analyzer

Calculates pass@k metrics similar to SWE-agent benchmark for evaluating
the probability of successful metadata extraction.
"""

import math
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict
import json


@dataclass
class SuccessCriteria:
    """Configurable success criteria for pass@k calculation."""
    
    # Basic criteria (always required)
    require_run_success: bool = True
    
    # Output criteria
    min_fields_extracted: int = 5
    
    # Completeness criteria
    min_overall_completeness: float = 0.0
    min_required_completeness: float = 0.3
    min_recommended_completeness: float = 0.0
    
    # Correctness criteria
    min_f1_score: float = 0.0
    min_precision: float = 0.0
    min_recall: float = 0.0
    
    # Confidence criteria
    min_overall_confidence: float = 0.0
    
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
    
    def to_dict(self) -> dict:
        return {
            'require_run_success': self.require_run_success,
            'min_fields_extracted': self.min_fields_extracted,
            'min_overall_completeness': self.min_overall_completeness,
            'min_required_completeness': self.min_required_completeness,
            'min_recommended_completeness': self.min_recommended_completeness,
            'min_f1_score': self.min_f1_score,
            'min_precision': self.min_precision,
            'min_recall': self.min_recall,
            'min_overall_confidence': self.min_overall_confidence,
        }


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


class PassAtKAnalyzer:
    """
    Analyze pass@k metrics for FAIRiAgent evaluation runs.
    
    Similar to SWE-agent benchmark, calculates the probability of
    at least one successful run in k attempts.
    """
    
    def __init__(
        self,
        runs_dir: Path,
        criteria: Optional[SuccessCriteria] = None,
        k_values: List[int] = [1, 3, 5, 10]
    ):
        """
        Initialize pass@k analyzer.
        
        Args:
            runs_dir: Path to evaluation runs directory
            criteria: Success criteria (default: moderate preset)
            k_values: List of k values to calculate pass@k for
        """
        self.runs_dir = Path(runs_dir)
        self.criteria = criteria or CRITERIA_PRESETS['moderate']
        self.k_values = k_values
        
        # Data storage
        self.eval_results: Dict[str, Dict[str, List[Dict]]] = {}  # {model: {doc: [results]}}
        self._loaded = False
    
    def load_results(
        self,
        exclude_models: Optional[List[str]] = None,
        exclude_docs: Optional[List[str]] = None
    ) -> int:
        """
        Load all eval_result.json files from the runs directory.
        
        Returns:
            Number of results loaded
        """
        self.eval_results = defaultdict(lambda: defaultdict(list))
        exclude_models = exclude_models or []
        exclude_docs = exclude_docs or []
        
        count = 0
        for eval_file in self.runs_dir.rglob('eval_result.json'):
            try:
                with open(eval_file, 'r') as f:
                    data = json.load(f)
                
                model = data.get('config_name', 'unknown')
                doc_id = data.get('document_id', 'unknown')
                
                # Skip excluded
                if model in exclude_models or doc_id in exclude_docs:
                    continue
                
                # Skip baseline runs
                if 'baseline' in str(eval_file):
                    continue
                
                self.eval_results[model][doc_id].append(data)
                count += 1
                
            except Exception as e:
                continue
        
        self._loaded = True
        return count
    
    @staticmethod
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
        
        return len(failures) == 0, failures
    
    @staticmethod
    def calculate_pass_at_k(n: int, c: int, k: int) -> float:
        """
        Calculate pass@k using the unbiased estimator.
        
        pass@k = 1 - C(n-c, k) / C(n, k)
        
        Args:
            n: Total number of samples
            c: Number of successful samples
            k: k value for pass@k
            
        Returns:
            pass@k value between 0 and 1
        """
        if n == 0 or c == 0:
            return 0.0
        if k > n:
            k = n
        if c >= n:
            return 1.0
        
        # Use log to avoid numerical overflow
        log_ratio = 0.0
        for i in range(k):
            if n - c - i <= 0:
                return 1.0
            log_ratio += math.log(n - c - i) - math.log(n - i)
        
        return 1.0 - math.exp(log_ratio)
    
    def get_model_pass_at_k(self, model: str) -> Dict[str, Any]:
        """
        Calculate pass@k metrics for a single model.
        
        Args:
            model: Model name
            
        Returns:
            Dict with pass@k values and detailed breakdown
        """
        if model not in self.eval_results:
            return {}
        
        model_results = self.eval_results[model]
        
        results = {
            'model': model,
            'k_values': self.k_values,
            'pass_at_k': {},
            'by_document': {},
            'aggregate': {
                'total_runs': 0,
                'successful_runs': 0,
                'total_documents': 0,
                'documents_with_success': 0,
            }
        }
        
        all_n = []
        all_c = []
        
        for doc_id, runs in model_results.items():
            n = len(runs)
            c = sum(1 for r in runs if self.is_successful(r, self.criteria)[0])
            
            all_n.append(n)
            all_c.append(c)
            
            results['aggregate']['total_runs'] += n
            results['aggregate']['successful_runs'] += c
            results['aggregate']['total_documents'] += 1
            if c > 0:
                results['aggregate']['documents_with_success'] += 1
            
            # Per-document pass@k
            doc_pass_at_k = {}
            for k in self.k_values:
                doc_pass_at_k[f'pass@{k}'] = self.calculate_pass_at_k(n, c, k)
            
            results['by_document'][doc_id] = {
                'n': n,
                'c': c,
                'success_rate': c / n if n > 0 else 0.0,
                **doc_pass_at_k
            }
        
        # Aggregate pass@k (average across documents)
        for k in self.k_values:
            pass_k_values = [self.calculate_pass_at_k(n, c, k) for n, c in zip(all_n, all_c)]
            results['pass_at_k'][f'pass@{k}'] = np.mean(pass_k_values) if pass_k_values else 0.0
            results['pass_at_k'][f'pass@{k}_std'] = np.std(pass_k_values) if pass_k_values else 0.0
        
        # Overall success rate
        total_n = results['aggregate']['total_runs']
        total_c = results['aggregate']['successful_runs']
        results['aggregate']['overall_success_rate'] = total_c / total_n if total_n > 0 else 0.0
        
        return results
    
    def get_all_pass_at_k(self) -> Dict[str, Dict[str, Any]]:
        """
        Calculate pass@k metrics for all models.
        
        Returns:
            Dict mapping model names to their pass@k results
        """
        return {model: self.get_model_pass_at_k(model) for model in self.eval_results}
    
    def get_summary_dataframe(self) -> pd.DataFrame:
        """
        Get summary DataFrame with pass@k for all models.
        
        Returns:
            DataFrame with model pass@k summary
        """
        rows = []
        
        for model, results in self.get_all_pass_at_k().items():
            row = {
                'model': model,
                'total_runs': results['aggregate']['total_runs'],
                'successful_runs': results['aggregate']['successful_runs'],
                'success_rate': results['aggregate']['overall_success_rate'],
            }
            
            # Add pass@k values
            for k in self.k_values:
                row[f'pass@{k}'] = results['pass_at_k'].get(f'pass@{k}', 0.0)
                row[f'pass@{k}_std'] = results['pass_at_k'].get(f'pass@{k}_std', 0.0)
            
            rows.append(row)
        
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values('pass@1', ascending=False)
        return df
    
    def get_document_level_dataframe(self) -> pd.DataFrame:
        """
        Get document-level pass@k DataFrame.
        
        Returns:
            DataFrame with document-level pass@k
        """
        rows = []
        
        for model, results in self.get_all_pass_at_k().items():
            for doc_id, doc_data in results.get('by_document', {}).items():
                row = {
                    'model': model,
                    'document_id': doc_id,
                    'n': doc_data['n'],
                    'c': doc_data['c'],
                    'success_rate': doc_data['success_rate'],
                }
                
                for k in self.k_values:
                    row[f'pass@{k}'] = doc_data.get(f'pass@{k}', 0.0)
                
                rows.append(row)
        
        return pd.DataFrame(rows)
    
    def get_multi_criteria_comparison(self) -> pd.DataFrame:
        """
        Compare pass@k across different criteria presets.
        
        Returns:
            DataFrame comparing models across criteria presets
        """
        rows = []
        
        for preset_name, preset_criteria in CRITERIA_PRESETS.items():
            # Temporarily switch criteria
            original_criteria = self.criteria
            self.criteria = preset_criteria
            
            for model in self.eval_results:
                results = self.get_model_pass_at_k(model)
                
                row = {
                    'criteria': preset_name,
                    'model': model,
                    'success_rate': results['aggregate']['overall_success_rate'],
                    'pass@1': results['pass_at_k'].get('pass@1', 0.0),
                    'pass@5': results['pass_at_k'].get('pass@5', 0.0),
                }
                rows.append(row)
            
            # Restore original criteria
            self.criteria = original_criteria
        
        return pd.DataFrame(rows)
    
    def generate_report(self, output_format: str = 'dict') -> Any:
        """
        Generate pass@k analysis report.
        
        Args:
            output_format: 'dict', 'markdown', or 'json'
            
        Returns:
            Report in specified format
        """
        report = {
            'criteria': self.criteria.to_dict(),
            'criteria_description': str(self.criteria),
            'k_values': self.k_values,
            'summary': self.get_summary_dataframe().to_dict('records'),
            'by_model': self.get_all_pass_at_k(),
            'multi_criteria_comparison': self.get_multi_criteria_comparison().to_dict('records'),
        }
        
        if output_format == 'dict':
            return report
        elif output_format == 'json':
            return json.dumps(report, indent=2, default=str)
        elif output_format == 'markdown':
            return self._generate_markdown_report(report)
        
        return report
    
    def _generate_markdown_report(self, report: dict) -> str:
        """Generate markdown formatted report."""
        lines = []
        lines.append("# Pass@k Analysis Report\n")
        lines.append(f"**Success Criteria:** {report['criteria_description']}\n")
        lines.append("")
        
        # Summary table
        lines.append("## Summary\n")
        summary_df = pd.DataFrame(report['summary'])
        if not summary_df.empty:
            lines.append(summary_df.to_markdown(index=False))
        lines.append("")
        
        # Multi-criteria comparison
        lines.append("## Multi-Criteria Comparison\n")
        comparison_df = pd.DataFrame(report['multi_criteria_comparison'])
        if not comparison_df.empty:
            pivot = comparison_df.pivot(index='model', columns='criteria', values='pass@1')
            lines.append(pivot.to_markdown())
        
        return "\n".join(lines)
