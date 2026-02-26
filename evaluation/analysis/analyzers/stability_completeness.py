"""
Stability-Completeness Trade-off Analyzer

Analyzes the relationship between extraction stability (consistency across runs)
and completeness (coverage of ground truth fields).

Addresses the research question:
"Why is earthworm more stable but lower completeness?"
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Set, Tuple
from scipy import stats


class StabilityCompletenessAnalyzer:
    """Analyze stability-completeness trade-offs."""
    
    def __init__(self):
        """Initialize analyzer."""
        pass
    
    def analyze_tradeoff(
        self,
        runs: List[Dict[str, Any]],
        ground_truth: Dict[str, Any],
        document_id: str
    ) -> Dict[str, Any]:
        """
        Analyze stability vs completeness trade-off for a document.
        
        Args:
            runs: List of runs for same document
            ground_truth: Ground truth document
            document_id: Document identifier
            
        Returns:
            Dict with trade-off analysis
        """
        # Group by model
        models = {}
        for run in runs:
            model = run['model_name']
            if model not in models:
                models[model] = []
            models[model].append(run)
        
        # Analyze each model
        model_analyses = {}
        for model, model_runs in models.items():
            analysis = self._analyze_model_tradeoff(
                model_runs, ground_truth, document_id, model
            )
            model_analyses[model] = analysis
        
        # Compute correlations across models
        stabilities = [a['stability_score'] for a in model_analyses.values()]
        completenesses = [a['completeness_score'] for a in model_analyses.values()]
        
        correlation, p_value = stats.pearsonr(stabilities, completenesses) if len(stabilities) > 2 else (0, 1)
        
        return {
            'document_id': document_id,
            'n_models': len(model_analyses),
            'models': model_analyses,
            'correlation': {
                'stability_completeness': correlation,
                'p_value': p_value,
                'significant': p_value < 0.05
            },
            'interpretation': self._interpret_document_pattern(model_analyses)
        }
    
    def _analyze_model_tradeoff(
        self,
        runs: List[Dict[str, Any]],
        ground_truth: Dict[str, Any],
        document_id: str,
        model_name: str
    ) -> Dict[str, Any]:
        """Analyze trade-off for a single model."""
        # Collect field sets from all runs
        field_sets = [
            set(run.get('extracted_field_names', []))
            for run in runs
        ]
        
        if not field_sets:
            return self._empty_analysis(document_id, model_name)
        
        # Core fields: present in ALL runs
        core_fields = set.intersection(*field_sets) if field_sets else set()
        
        # Variable fields: present in SOME but not ALL runs
        all_fields = set.union(*field_sets) if field_sets else set()
        variable_fields = all_fields - core_fields
        
        # Ground truth fields
        gt_fields = set(f['field_name'] for f in ground_truth.get('ground_truth_fields', []))
        
        # Stability metric
        stability_score = len(core_fields) / len(all_fields) if all_fields else 0
        
        # Completeness metric
        completeness_score = len(all_fields & gt_fields) / len(gt_fields) if gt_fields else 0
        
        # Quality breakdown
        core_correct = len(core_fields & gt_fields)
        core_hallucinated = len(core_fields - gt_fields)
        variable_correct = len(variable_fields & gt_fields)
        variable_hallucinated = len(variable_fields - gt_fields)
        
        # Mandatory fields analysis
        mandatory_fields = {
            f['field_name'] for f in ground_truth.get('ground_truth_fields', [])
            if f.get('is_required', False)
        }
        mandatory_in_core = len(core_fields & mandatory_fields)
        mandatory_in_variable = len(variable_fields & mandatory_fields)
        
        # Pattern classification
        pattern = self._classify_pattern(stability_score, completeness_score)
        
        return {
            'document_id': document_id,
            'model_name': model_name,
            'n_runs': len(runs),
            
            # Field counts
            'core_fields_count': len(core_fields),
            'variable_fields_count': len(variable_fields),
            'total_unique_fields': len(all_fields),
            
            # Core metrics
            'stability_score': stability_score,
            'completeness_score': completeness_score,
            
            # Quality breakdown
            'core_correct': core_correct,
            'core_hallucinated': core_hallucinated,
            'variable_correct': variable_correct,
            'variable_hallucinated': variable_hallucinated,
            
            # Mandatory analysis
            'mandatory_total': len(mandatory_fields),
            'mandatory_in_core': mandatory_in_core,
            'mandatory_in_variable': mandatory_in_variable,
            'mandatory_core_rate': mandatory_in_core / len(mandatory_fields) if mandatory_fields else 0,
            
            # Classification
            'pattern': pattern,
            'interpretation': self._interpret_pattern(
                pattern, core_correct, mandatory_in_core, len(mandatory_fields)
            ),
            
            # Field lists
            'core_fields': list(core_fields),
            'variable_fields': list(variable_fields)
        }
    
    def _empty_analysis(self, document_id: str, model_name: str) -> Dict[str, Any]:
        """Return empty analysis for edge cases."""
        return {
            'document_id': document_id,
            'model_name': model_name,
            'n_runs': 0,
            'stability_score': 0,
            'completeness_score': 0,
            'pattern': 'NO_DATA'
        }
    
    def _classify_pattern(self, stability: float, completeness: float) -> str:
        """Classify stability-completeness pattern."""
        if stability >= 0.8 and completeness >= 0.7:
            return 'IDEAL'  # High stability, high completeness
        elif stability >= 0.8 and completeness < 0.7:
            return 'CONSERVATIVE'  # High stability, low completeness
        elif stability < 0.6 and completeness >= 0.7:
            return 'EXPLORATORY'  # Low stability, high completeness
        elif stability < 0.6 and completeness < 0.5:
            return 'POOR'  # Low stability, low completeness
        else:
            return 'MODERATE'  # Middle ground
    
    def _interpret_pattern(
        self,
        pattern: str,
        core_correct: int,
        mandatory_in_core: int,
        mandatory_total: int
    ) -> str:
        """Generate human-readable interpretation."""
        if pattern == 'IDEAL':
            return f"Model consistently extracts comprehensive field set ({core_correct} correct core fields, {mandatory_in_core}/{mandatory_total} mandatory in core)"
        
        elif pattern == 'CONSERVATIVE':
            mandatory_rate = mandatory_in_core / mandatory_total if mandatory_total else 0
            if mandatory_rate >= 0.9:
                return f"Model consistently extracts core mandatory fields ({mandatory_in_core}/{mandatory_total}) but explores optional fields variably"
            else:
                return f"Model consistently extracts limited field set, missing some mandatory fields ({mandatory_in_core}/{mandatory_total})"
        
        elif pattern == 'EXPLORATORY':
            return f"Model explores diverse fields across runs but lacks consistency (only {core_correct} consistently correct)"
        
        elif pattern == 'POOR':
            return "Model shows both low consistency and low completeness - unstable and incomplete"
        
        else:
            return "Model shows moderate stability and completeness"
    
    def _interpret_document_pattern(
        self,
        model_analyses: Dict[str, Dict[str, Any]]
    ) -> str:
        """Interpret overall pattern across models for a document."""
        patterns = [a['pattern'] for a in model_analyses.values()]
        pattern_counts = pd.Series(patterns).value_counts()
        
        dominant_pattern = pattern_counts.index[0] if len(pattern_counts) > 0 else 'UNKNOWN'
        
        # Check if high mandatory in core is common
        avg_mandatory_core_rate = np.mean([
            a.get('mandatory_core_rate', 0)
            for a in model_analyses.values()
        ])
        
        if dominant_pattern == 'CONSERVATIVE' and avg_mandatory_core_rate >= 0.8:
            return (
                f"Most models show CONSERVATIVE pattern: consistently extract core mandatory "
                f"fields ({avg_mandatory_core_rate:.1%} mandatory in core) but vary on optional fields. "
                f"This explains high stability with moderate completeness."
            )
        elif dominant_pattern == 'IDEAL':
            return "Most models achieve IDEAL pattern: high stability and high completeness"
        else:
            return f"Dominant pattern: {dominant_pattern}"
    
    def create_scatter_data(
        self,
        all_analyses: Dict[str, Dict[str, Any]]
    ) -> pd.DataFrame:
        """
        Create scatter plot data for stability vs completeness.
        
        Args:
            all_analyses: Dict mapping document_id -> analysis result
            
        Returns:
            DataFrame with scatter plot data
        """
        rows = []
        
        for doc_id, analysis in all_analyses.items():
            for model_name, model_data in analysis.get('models', {}).items():
                rows.append({
                    'document_id': doc_id,
                    'model_name': model_name,
                    'stability_score': model_data['stability_score'],
                    'completeness_score': model_data['completeness_score'],
                    'core_fields_count': model_data['core_fields_count'],
                    'pattern': model_data['pattern'],
                    'mandatory_core_rate': model_data.get('mandatory_core_rate', 0)
                })
        
        return pd.DataFrame(rows)
    
    def compare_documents(
        self,
        analyses: Dict[str, Dict[str, Any]]
    ) -> pd.DataFrame:
        """
        Compare stability-completeness patterns across documents.
        
        Args:
            analyses: Dict mapping document_id -> analysis result
            
        Returns:
            DataFrame with document comparison
        """
        rows = []
        
        for doc_id, analysis in analyses.items():
            models = analysis.get('models', {})
            
            if not models:
                continue
            
            # Aggregate across models
            stabilities = [m['stability_score'] for m in models.values()]
            completenesses = [m['completeness_score'] for m in models.values()]
            mandatory_rates = [m.get('mandatory_core_rate', 0) for m in models.values()]
            
            rows.append({
                'document_id': doc_id,
                'n_models': len(models),
                'mean_stability': np.mean(stabilities),
                'std_stability': np.std(stabilities),
                'mean_completeness': np.mean(completenesses),
                'std_completeness': np.std(completenesses),
                'mean_mandatory_core_rate': np.mean(mandatory_rates),
                'correlation': analysis.get('correlation', {}).get('stability_completeness', 0),
                'interpretation': analysis.get('interpretation', '')
            })
        
        return pd.DataFrame(rows)
