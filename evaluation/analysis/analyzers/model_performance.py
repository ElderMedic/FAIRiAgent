"""
Model Performance Analyzer

Analyzes model performance across different metrics and documents.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any
from scipy import stats


class ModelPerformanceAnalyzer:
    """Analyze model performance metrics."""
    
    def __init__(self, df: pd.DataFrame):
        """
        Initialize analyzer.
        
        Args:
            df: DataFrame from EvaluationDataLoader.get_model_dataframe()
        """
        self.df = df
    
    def get_model_rankings(self, metric: str = 'aggregate_score') -> pd.DataFrame:
        """
        Get model rankings by metric.
        
        Args:
            metric: Metric to rank by
            
        Returns:
            DataFrame with models ranked by metric
        """
        rankings = self.df.groupby('model_name')[metric].agg([
            'mean', 'std', 'min', 'max', 'count'
        ]).sort_values('mean', ascending=False)
        
        rankings.columns = [f'{metric}_{col}' for col in rankings.columns]
        return rankings
    
    def compare_models(self, metric: str = 'aggregate_score') -> Dict[str, Any]:
        """
        Statistical comparison between models.
        
        Args:
            metric: Metric to compare
            
        Returns:
            Dict with comparison statistics
        """
        models = self.df['model_name'].unique()
        comparisons = {}
        
        for i, model1 in enumerate(models):
            for model2 in models[i+1:]:
                data1 = self.df[self.df['model_name'] == model1][metric].dropna()
                data2 = self.df[self.df['model_name'] == model2][metric].dropna()
                
                if len(data1) > 0 and len(data2) > 0:
                    # T-test
                    t_stat, p_value = stats.ttest_ind(data1, data2)
                    
                    comparisons[f'{model1}_vs_{model2}'] = {
                        'model1_mean': data1.mean(),
                        'model2_mean': data2.mean(),
                        'difference': data1.mean() - data2.mean(),
                        't_statistic': t_stat,
                        'p_value': p_value,
                        'significant': p_value < 0.05
                    }
        
        return comparisons
    
    def get_metric_correlations(self) -> pd.DataFrame:
        """
        Get correlations between different metrics.
        
        Returns:
            Correlation matrix
        """
        metrics = [
            'completeness', 'correctness_f1', 'schema_compliance',
            'llm_judge_score', 'internal_confidence', 'retry_rate'
        ]
        
        available_metrics = [m for m in metrics if m in self.df.columns]
        return self.df[available_metrics].corr()
    
    def get_document_performance(self) -> pd.DataFrame:
        """
        Get performance breakdown by document.
        
        Returns:
            DataFrame with document-level performance
        """
        doc_df = self.df.groupby(['model_name', 'document_id']).agg({
            'completeness': 'mean',
            'correctness_f1': 'mean',
            'aggregate_score': 'mean'
        }).reset_index()
        
        return doc_df








