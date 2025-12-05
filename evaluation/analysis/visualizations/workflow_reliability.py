"""
Workflow Reliability Visualizations

Visualizations for workflow execution reliability, retries, and failures.
"""

import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any


class WorkflowReliabilityVisualizer:
    """Generate workflow reliability visualizations."""
    
    def __init__(self, output_dir: Path):
        """
        Initialize visualizer.
        
        Args:
            output_dir: Directory to save figures
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        plt.style.use('seaborn-v0_8-paper')
        sns.set_palette("Set2")
        plt.rcParams.update({
            'font.size': 11,
            'axes.titlesize': 13,
            'axes.labelsize': 11,
            'xtick.labelsize': 10,
            'ytick.labelsize': 10,
            'legend.fontsize': 10,
            'figure.titlesize': 14,
            'font.family': 'sans-serif',
            'font.sans-serif': ['Arial', 'DejaVu Sans', 'Liberation Sans'],
            'axes.spines.top': False,
            'axes.spines.right': False,
            'axes.grid': True,
            'grid.alpha': 0.3,
            'grid.linewidth': 0.5
        })
        self.figsize = (10, 7)
        self.dpi = 300
    
    def plot_retry_rates(
        self,
        df: pd.DataFrame,
        filename: str = 'retry_rates'
    ):
        """
        Plot retry rates by model.
        
        Args:
            df: DataFrame with workflow reliability data
            filename: Output filename
        """
        model_retries = df.groupby('model_name')['retry_rate'].agg(['mean', 'std']).sort_values('mean')
        
        fig, ax = plt.subplots(figsize=self.figsize)
        
        y_pos = np.arange(len(model_retries))
        bars = ax.barh(y_pos, model_retries['mean'].values, xerr=model_retries['std'].values)
        
        ax.set_yticks(y_pos)
        ax.set_yticklabels(model_retries.index)
        ax.set_xlabel('Mean Retry Rate', fontsize=12)
        ax.set_title('Workflow Retry Rates by Model', fontsize=14, fontweight='bold')
        ax.set_xlim(0, max(model_retries['mean'].max() * 1.2, 0.1))
        
        # Add value labels
        for i, (idx, val) in enumerate(model_retries['mean'].items()):
            ax.text(val + 0.01, i, f'{val:.3f}', va='center', fontsize=10)
        
        plt.tight_layout()
        
        for ext in ['png', 'pdf']:
            fig.savefig(self.output_dir / f'{filename}.{ext}', dpi=self.dpi, bbox_inches='tight')
        
        plt.close()
        print(f"  ✅ Saved: {filename}")
    
    def plot_agent_retry_patterns(
        self,
        df: pd.DataFrame,
        filename: str = 'agent_retry_patterns'
    ):
        """
        Plot retry patterns by agent.
        
        Args:
            df: DataFrame with workflow reliability data
            filename: Output filename
        """
        agents = ['DocumentParser', 'KnowledgeRetriever', 'JSONGenerator', 'Critic', 'Validator']
        
        agent_data = []
        for agent in agents:
            retry_col = f'{agent}_retries'
            if retry_col in df.columns:
                agent_data.append({
                    'agent': agent,
                    'mean_retries': df[retry_col].mean(),
                    'runs_with_retries': (df[retry_col] > 0).sum()
                })
        
        agent_df = pd.DataFrame(agent_data)
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        # Mean retries per agent
        agent_df.sort_values('mean_retries', ascending=True).plot(
            x='agent', y='mean_retries', kind='barh', ax=ax1, legend=False
        )
        ax1.set_title('Mean Retries per Agent', fontsize=12, fontweight='bold')
        ax1.set_xlabel('Mean Retries', fontsize=11)
        ax1.set_ylabel('Agent', fontsize=11)
        
        # Runs with retries
        agent_df.sort_values('runs_with_retries', ascending=True).plot(
            x='agent', y='runs_with_retries', kind='barh', ax=ax2, legend=False, color='orange'
        )
        ax2.set_title('Runs with Retries per Agent', fontsize=12, fontweight='bold')
        ax2.set_xlabel('Number of Runs', fontsize=11)
        ax2.set_ylabel('Agent', fontsize=11)
        
        plt.tight_layout()
        
        for ext in ['png', 'pdf']:
            fig.savefig(self.output_dir / f'{filename}.{ext}', dpi=self.dpi, bbox_inches='tight')
        
        plt.close()
        print(f"  ✅ Saved: {filename}")
    
    def plot_completion_rates(
        self,
        df: pd.DataFrame,
        filename: str = 'completion_rates'
    ):
        """
        Plot workflow completion rates by model.
        
        Args:
            df: DataFrame with workflow reliability data
            filename: Output filename
        """
        completion_rates = df.groupby('model_name').apply(
            lambda x: (x['workflow_status'] == 'completed').sum() / len(x)
        ).sort_values(ascending=True)
        
        fig, ax = plt.subplots(figsize=self.figsize)
        
        y_pos = np.arange(len(completion_rates))
        bars = ax.barh(y_pos, completion_rates.values, color='green', alpha=0.7)
        
        ax.set_yticks(y_pos)
        ax.set_yticklabels(completion_rates.index)
        ax.set_xlabel('Completion Rate', fontsize=12)
        ax.set_title('Workflow Completion Rates by Model', fontsize=14, fontweight='bold')
        ax.set_xlim(0, 1)
        
        # Add value labels
        for i, val in enumerate(completion_rates.values):
            ax.text(val + 0.01, i, f'{val:.1%}', va='center', fontsize=10)
        
        plt.tight_layout()
        
        for ext in ['png', 'pdf']:
            fig.savefig(self.output_dir / f'{filename}.{ext}', dpi=self.dpi, bbox_inches='tight')
        
        plt.close()
        print(f"  ✅ Saved: {filename}")

