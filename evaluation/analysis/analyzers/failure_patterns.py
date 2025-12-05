"""
Failure Pattern Analyzer

Analyzes failure patterns, error types, and failure causes.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any
from collections import Counter


class FailurePatternAnalyzer:
    """Analyze failure patterns and causes."""
    
    def __init__(self, df: pd.DataFrame, evaluation_results: Dict[str, Dict[str, Any]]):
        """
        Initialize analyzer.
        
        Args:
            df: DataFrame from EvaluationDataLoader.get_workflow_reliability_dataframe()
            evaluation_results: Raw evaluation results dict
        """
        self.df = df
        self.evaluation_results = evaluation_results
    
    def get_failure_by_agent(self) -> pd.DataFrame:
        """
        Get failure counts by agent.
        
        Returns:
            DataFrame with failure counts per agent
        """
        agents = ['DocumentParser', 'KnowledgeRetriever', 'JSONGenerator', 'Critic', 'Validator']
        
        rows = []
        for agent in agents:
            failure_col = f'{agent}_failures'
            if failure_col in self.df.columns:
                rows.append({
                    'agent': agent,
                    'total_failures': self.df[failure_col].sum(),
                    'runs_with_failures': (self.df[failure_col] > 0).sum(),
                    'failure_rate': (self.df[failure_col] > 0).sum() / len(self.df)
                })
        
        return pd.DataFrame(rows).sort_values('total_failures', ascending=False)
    
    def get_failure_by_document(self) -> pd.DataFrame:
        """
        Get failure rates by document.
        
        Returns:
            DataFrame with failure rates per document
        """
        return self.df.groupby('document_id').agg({
            'failed_steps': 'mean',
            'steps_requiring_retry': 'mean',
            'needs_human_review': lambda x: x.sum() / len(x)
        }).round(4)
    
    def get_failure_by_model(self) -> pd.DataFrame:
        """
        Get failure rates by model.
        
        Returns:
            DataFrame with failure rates per model
        """
        return self.df.groupby('model_name').agg({
            'failed_steps': 'mean',
            'steps_requiring_retry': 'mean',
            'needs_human_review': lambda x: x.sum() / len(x),
            'workflow_status': lambda x: (x == 'completed').sum() / len(x)
        }).round(4)








