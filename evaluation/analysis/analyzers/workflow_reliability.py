"""
Workflow Reliability Analyzer

Analyzes workflow execution reliability, retry patterns, and failure modes.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any


class WorkflowReliabilityAnalyzer:
    """Analyze workflow reliability metrics."""
    
    def __init__(self, df: pd.DataFrame):
        """
        Initialize analyzer.
        
        Args:
            df: DataFrame from EvaluationDataLoader.get_workflow_reliability_dataframe()
        """
        self.df = df
    
    def get_reliability_summary(self) -> pd.DataFrame:
        """
        Get overall reliability summary by model.
        
        Returns:
            DataFrame with reliability metrics per model
        """
        summary = self.df.groupby('model_name').agg({
            'workflow_status': lambda x: (x == 'completed').sum() / len(x),  # Success rate
            'failed_steps': 'mean',
            'steps_requiring_retry': 'mean',
            'retry_rate': 'mean',
            'needs_human_review': lambda x: x.sum() / len(x)  # Review rate
        }).round(4)
        
        summary.columns = [
            'completion_rate',
            'mean_failed_steps',
            'mean_retry_steps',
            'mean_retry_rate',
            'human_review_rate'
        ]
        
        return summary.sort_values('completion_rate', ascending=False)
    
    def get_agent_reliability(self) -> pd.DataFrame:
        """
        Get reliability metrics per agent.
        
        Returns:
            DataFrame with agent-level reliability
        """
        agents = ['DocumentParser', 'KnowledgeRetriever', 'JSONGenerator', 'Critic', 'Validator']
        
        rows = []
        for agent in agents:
            retry_col = f'{agent}_retries'
            failure_col = f'{agent}_failures'
            
            if retry_col in self.df.columns:
                rows.append({
                    'agent': agent,
                    'mean_retries': self.df[retry_col].mean(),
                    'total_retries': self.df[retry_col].sum(),
                    'runs_with_retries': (self.df[retry_col] > 0).sum(),
                    'mean_failures': self.df[failure_col].mean() if failure_col in self.df.columns else 0,
                    'total_failures': self.df[failure_col].sum() if failure_col in self.df.columns else 0
                })
        
        return pd.DataFrame(rows)
    
    def get_retry_patterns(self) -> Dict[str, Any]:
        """
        Analyze retry patterns.
        
        Returns:
            Dict with retry pattern analysis
        """
        patterns = {
            'total_runs': len(self.df),
            'runs_with_retries': (self.df['steps_requiring_retry'] > 0).sum(),
            'runs_with_failures': (self.df['failed_steps'] > 0).sum(),
            'runs_needing_review': self.df['needs_human_review'].sum(),
            'retry_distribution': self.df['steps_requiring_retry'].value_counts().to_dict(),
            'failure_distribution': self.df['failed_steps'].value_counts().to_dict()
        }
        
        return patterns
    
    def get_model_reliability_comparison(self) -> pd.DataFrame:
        """
        Compare reliability across models.
        
        Returns:
            DataFrame with model reliability comparison
        """
        return self.df.groupby('model_name').agg({
            'workflow_status': lambda x: (x == 'completed').sum() / len(x),
            'retry_rate': 'mean',
            'failed_steps': 'mean',
            'needs_human_review': lambda x: x.sum() / len(x)
        }).round(4)








