"""
Field Presence Analyzer

Analyzes which fields are extracted by which models across multiple runs.
Creates presence matrices showing field extraction patterns.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Set, Tuple
from collections import Counter


class FieldPresenceAnalyzer:
    """Analyze field presence patterns across models and runs."""
    
    def __init__(self):
        """Initialize field presence analyzer."""
        pass
    
    def create_presence_matrix(
        self,
        runs: List[Dict[str, Any]],
        ground_truth: Dict[str, Any],
        document_id: str,
        novel_field_categories: Dict[str, str] = None,
    ) -> pd.DataFrame:
        """
        Create field presence matrix for a specific document.
        
        Args:
            runs: List of run data (must include model_name, extracted_field_names)
            ground_truth: Ground truth document
            document_id: Document identifier
            novel_field_categories: optional {field_name: bucket} override for
                non-GT fields, from ``NovelFieldEvaluator`` (Layer 4):
                ``beneficial_discovery`` / ``domain_insight`` /
                ``unsupported_fabrication`` / ``ungroundable_no_evaluation_data``.
                Field names without an entry here fall back to the flat
                ``EXTRA`` category (pre-redesign behavior) -- pass this in
                when you want ``analyze_hallucinations`` and downstream
                categorized views to distinguish evidence-grounded discoveries
                from actual fabrications instead of lumping them together.
            
        Returns:
            DataFrame with presence matrix
        """
        novel_field_categories = novel_field_categories or {}

        # Get ground truth fields
        gt_fields = ground_truth.get('ground_truth_fields', [])
        
        # Build field metadata lookup
        field_metadata = {}
        for field in gt_fields:
            field_name = field['field_name']
            field_metadata[field_name] = {
                'category': self._get_field_category(field),
                'isa_sheet': field.get('isa_sheet', 'unknown'),
                'package': field.get('package_source', 'default'),
                'in_ground_truth': True
            }
        
        # Collect all extracted fields (including extras)
        all_extracted = set()
        for run in runs:
            all_extracted.update(run.get('extracted_field_names', []))
        
        # Add extra (non-GT) fields to metadata. Category defaults to the
        # flat 'EXTRA' bucket, or the evidence-grounded Layer 4 bucket if the
        # caller supplied one via `novel_field_categories`.
        extra_fields = all_extracted - set(field_metadata.keys())
        for field_name in extra_fields:
            field_metadata[field_name] = {
                'category': novel_field_categories.get(field_name, 'EXTRA'),
                'isa_sheet': 'unknown',
                'package': 'unknown',
                'in_ground_truth': False
            }
        
        # Build presence matrix
        matrix_rows = []
        
        for field_name in sorted(field_metadata.keys()):
            row = {
                'field_name': field_name,
                'category': field_metadata[field_name]['category'],
                'isa_sheet': field_metadata[field_name]['isa_sheet'],
                'package': field_metadata[field_name]['package'],
                'in_ground_truth': field_metadata[field_name]['in_ground_truth']
            }
            
            # For each model, calculate presence across runs
            models = {}
            for run in runs:
                model = run['model_name']
                if model not in models:
                    models[model] = []
                
                present = field_name in run.get('extracted_field_names', [])
                models[model].append(present)
            
            # Add model presence data
            for model, presence_list in models.items():
                # Presence pattern (e.g., "✓✓✗✓✗")
                pattern = ''.join('✓' if p else '✗' for p in presence_list)
                row[f'{model}_pattern'] = pattern
                
                # Presence rate (0-1)
                rate = sum(presence_list) / len(presence_list) if presence_list else 0
                row[f'{model}_rate'] = rate
                
                # Count
                row[f'{model}_count'] = sum(presence_list)
            
            matrix_rows.append(row)
        
        return pd.DataFrame(matrix_rows)
    
    def _get_field_category(self, field: Dict[str, Any]) -> str:
        """Get field category label."""
        if field.get('is_required', False):
            return 'MANDATORY'
        elif field.get('is_recommended', False):
            return 'RECOMMENDED'
        else:
            return 'OPTIONAL'
    
    def compute_core_fields(
        self,
        presence_matrix: pd.DataFrame,
        threshold: float = 1.0
    ) -> Dict[str, List[str]]:
        """
        Identify core fields (present in ≥threshold of runs).
        
        Args:
            presence_matrix: DataFrame from create_presence_matrix()
            threshold: Minimum presence rate (default 1.0 = all runs)
            
        Returns:
            Dict with core fields by category
        """
        # Get model rate columns
        rate_cols = [col for col in presence_matrix.columns if col.endswith('_rate')]
        
        # Calculate consensus rate (average across all models)
        if rate_cols:
            presence_matrix['consensus_rate'] = presence_matrix[rate_cols].mean(axis=1)
        else:
            presence_matrix['consensus_rate'] = 0
        
        # Filter by threshold
        core_fields_df = presence_matrix[presence_matrix['consensus_rate'] >= threshold]
        
        # Group by category
        result = {
            'all': core_fields_df['field_name'].tolist(),
            'by_category': {}
        }
        
        for category in ['MANDATORY', 'RECOMMENDED', 'OPTIONAL', 'EXTRA']:
            cat_fields = core_fields_df[core_fields_df['category'] == category]
            result['by_category'][category] = cat_fields['field_name'].tolist()
        
        return result
    
    def compute_variable_fields(
        self,
        presence_matrix: pd.DataFrame,
        min_threshold: float = 0.1,
        max_threshold: float = 0.9
    ) -> Dict[str, List[str]]:
        """
        Identify variable fields (present in some but not all runs).
        
        Args:
            presence_matrix: DataFrame from create_presence_matrix()
            min_threshold: Minimum presence rate
            max_threshold: Maximum presence rate
            
        Returns:
            Dict with variable fields by category
        """
        # Calculate consensus rate
        rate_cols = [col for col in presence_matrix.columns if col.endswith('_rate')]
        if rate_cols:
            presence_matrix['consensus_rate'] = presence_matrix[rate_cols].mean(axis=1)
        else:
            presence_matrix['consensus_rate'] = 0
        
        # Filter by threshold range
        variable_df = presence_matrix[
            (presence_matrix['consensus_rate'] >= min_threshold) &
            (presence_matrix['consensus_rate'] <= max_threshold)
        ]
        
        # Group by category
        result = {
            'all': variable_df['field_name'].tolist(),
            'by_category': {}
        }
        
        for category in ['MANDATORY', 'RECOMMENDED', 'OPTIONAL', 'EXTRA']:
            cat_fields = variable_df[variable_df['category'] == category]
            result['by_category'][category] = cat_fields['field_name'].tolist()
        
        return result
    
    def compute_model_specific_fields(
        self,
        presence_matrix: pd.DataFrame,
        threshold: float = 0.8
    ) -> Dict[str, List[str]]:
        """
        Identify fields that are predominantly extracted by specific models.
        
        Args:
            presence_matrix: DataFrame from create_presence_matrix()
            threshold: Minimum rate to be considered model-specific
            
        Returns:
            Dict mapping model -> list of model-specific fields
        """
        rate_cols = [col for col in presence_matrix.columns if col.endswith('_rate')]
        models = [col.replace('_rate', '') for col in rate_cols]
        
        result = {model: [] for model in models}
        
        for _, row in presence_matrix.iterrows():
            # Find models with high presence rate for this field
            high_models = [
                m for m in models 
                if row[f'{m}_rate'] >= threshold
            ]
            
            # If only one model has high rate, it's model-specific
            if len(high_models) == 1:
                model = high_models[0]
                result[model].append({
                    'field_name': row['field_name'],
                    'category': row['category'],
                    'rate': row[f'{model}_rate']
                })
        
        return result
    
    def analyze_hallucinations(
        self,
        presence_matrix: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Analyze non-GT ("extra") fields.

        Historically labeled "hallucinations", but per the evaluation-metrics
        redesign not every non-GT field is a fabrication -- if the caller
        passed evidence-grounded ``novel_field_categories`` into
        ``create_presence_matrix`` (Layer 4: beneficial_discovery /
        domain_insight / unsupported_fabrication), this picks up all of
        those buckets (anything with ``in_ground_truth == False``), not just
        the flat legacy ``EXTRA`` label. Callers wanting only true
        fabrications should filter ``extra_fields_data`` on
        ``category == 'unsupported_fabrication'`` afterwards.
        
        Args:
            presence_matrix: DataFrame from create_presence_matrix()
            
        Returns:
            Dict with statistics on non-GT fields
        """
        extra_fields = presence_matrix[~presence_matrix['in_ground_truth']]
        
        if len(extra_fields) == 0:
            return {
                'total_extra_fields': 0,
                'by_model': {},
                'most_common': []
            }
        
        # Calculate hallucination rate by model
        rate_cols = [col for col in extra_fields.columns if col.endswith('_rate')]
        models = [col.replace('_rate', '') for col in rate_cols]
        
        by_model = {}
        for model in models:
            model_extras = extra_fields[extra_fields[f'{model}_rate'] > 0]
            by_model[model] = {
                'count': len(model_extras),
                'fields': model_extras['field_name'].tolist(),
                'avg_rate': extra_fields[f'{model}_rate'].mean()
            }
        
        # Most common hallucinations
        extra_fields_sorted = extra_fields.sort_values(
            by=[col for col in rate_cols],
            ascending=False
        )
        most_common = extra_fields_sorted.head(10)['field_name'].tolist()
        
        return {
            'total_extra_fields': len(extra_fields),
            'by_model': by_model,
            'most_common': most_common,
            'extra_fields_data': extra_fields.to_dict('records')
        }
    
    def compute_stability_metrics(
        self,
        presence_matrix: pd.DataFrame,
        document_id: str
    ) -> Dict[str, Any]:
        """
        Compute stability metrics for each model.
        
        Stability = consistency of field extraction across runs
        
        Args:
            presence_matrix: DataFrame from create_presence_matrix()
            document_id: Document identifier
            
        Returns:
            Dict with stability metrics per model
        """
        rate_cols = [col for col in presence_matrix.columns if col.endswith('_rate')]
        models = [col.replace('_rate', '') for col in rate_cols]
        
        results = {}
        
        for model in models:
            rates = presence_matrix[f'{model}_rate'].values
            
            # Core fields: rate = 1.0 (present in all runs)
            core_count = np.sum(rates == 1.0)
            
            # Variable fields: 0 < rate < 1.0
            variable_count = np.sum((rates > 0) & (rates < 1.0))
            
            # Total unique fields ever extracted
            total_count = np.sum(rates > 0)
            
            # Stability score: proportion of core fields
            stability = core_count / total_count if total_count > 0 else 0
            
            # Coefficient of variation of rates (lower = more stable)
            cv = np.std(rates) / np.mean(rates) if np.mean(rates) > 0 else 0
            
            results[model] = {
                'document_id': document_id,
                'core_fields_count': int(core_count),
                'variable_fields_count': int(variable_count),
                'total_fields_count': int(total_count),
                'stability_score': float(stability),
                'coefficient_variation': float(cv)
            }
        
        return results
