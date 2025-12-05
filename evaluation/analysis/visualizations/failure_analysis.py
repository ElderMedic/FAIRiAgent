"""
Failure Analysis Visualizations

Visualizations for failure patterns and error analysis.
"""

import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any


class FailureAnalysisVisualizer:
    """Generate failure analysis visualizations."""
    
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
    
    def plot_failure_by_agent(
        self,
        df: pd.DataFrame,
        filename: str = 'failure_by_agent'
    ):
        """
        Plot failure counts by agent.
        
        Args:
            df: DataFrame with failure data
            filename: Output filename
        """
        agents = ['DocumentParser', 'KnowledgeRetriever', 'JSONGenerator', 'Critic', 'Validator']
        
        agent_failures = []
        for agent in agents:
            failure_col = f'{agent}_failures'
            if failure_col in df.columns:
                total = df[failure_col].sum()
                runs_with = (df[failure_col] > 0).sum()
                agent_failures.append({
                    'agent': agent,
                    'total_failures': total,
                    'runs_with_failures': runs_with,
                    'failure_rate': runs_with / len(df) if len(df) > 0 else 0
                })
        
        if not agent_failures:
            print(f"  ⚠️  No failure data available for {filename}")
            return
        
        agent_df = pd.DataFrame(agent_failures).sort_values('total_failures', ascending=True)
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
        
        # Total failures
        colors = plt.cm.Reds(np.linspace(0.4, 0.9, len(agent_df)))
        agent_df.plot(x='agent', y='total_failures', kind='barh', ax=ax1, 
                     legend=False, color=colors, edgecolor='black', linewidth=1.2)
        ax1.set_title('Total Failures by Agent', fontsize=13, fontweight='bold', pad=15)
        ax1.set_xlabel('Total Failures', fontsize=12, fontweight='bold')
        ax1.set_ylabel('Agent', fontsize=12, fontweight='bold')
        ax1.grid(axis='x', alpha=0.3, linestyle='--')
        
        # Add value labels
        for i, (idx, row) in enumerate(agent_df.iterrows()):
            ax1.text(row['total_failures'] + 0.1, i, f"{int(row['total_failures'])}", 
                    va='center', fontsize=11, fontweight='bold')
        
        # Failure rate
        agent_df.plot(x='agent', y='failure_rate', kind='barh', ax=ax2,
                     legend=False, color=plt.cm.Oranges(np.linspace(0.4, 0.9, len(agent_df))),
                     edgecolor='black', linewidth=1.2)
        ax2.set_title('Failure Rate by Agent', fontsize=13, fontweight='bold', pad=15)
        ax2.set_xlabel('Failure Rate', fontsize=12, fontweight='bold')
        ax2.set_ylabel('Agent', fontsize=12, fontweight='bold')
        ax2.set_xlim(0, 1)
        ax2.grid(axis='x', alpha=0.3, linestyle='--')
        
        # Add percentage labels
        for i, (idx, row) in enumerate(agent_df.iterrows()):
            ax2.text(row['failure_rate'] + 0.02, i, f"{row['failure_rate']:.1%}", 
                    va='center', fontsize=11, fontweight='bold')
        
        plt.tight_layout()
        
        for ext in ['png', 'pdf']:
            fig.savefig(self.output_dir / f'{filename}.{ext}', dpi=self.dpi, bbox_inches='tight')
        
        plt.close()
        print(f"  ✅ Saved: {filename}")
    
    def plot_failure_by_document(
        self,
        df: pd.DataFrame,
        filename: str = 'failure_by_document'
    ):
        """
        Plot failure rates by document.
        
        Args:
            df: DataFrame with failure data
            filename: Output filename
        """
        doc_failures = df.groupby('document_id').agg({
            'failed_steps': 'mean',
            'steps_requiring_retry': 'mean',
            'is_completed': lambda x: (x == True).sum() / len(x) if len(x) > 0 else 0
        }).sort_values('failed_steps', ascending=True)
        
        doc_failures.columns = ['mean_failed_steps', 'mean_retry_steps', 'completion_rate']
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
        
        x = np.arange(len(doc_failures))
        width = 0.35
        
        # Failed vs retry steps
        ax1.barh(x - width/2, doc_failures['mean_failed_steps'], width, 
                label='Failed Steps', alpha=0.8, color='#d62728', edgecolor='black', linewidth=1)
        ax1.barh(x + width/2, doc_failures['mean_retry_steps'], width, 
                label='Retry Steps', alpha=0.8, color='#ff7f0e', edgecolor='black', linewidth=1)
        
        ax1.set_yticks(x)
        ax1.set_yticklabels([d.title() for d in doc_failures.index], fontweight='bold')
        ax1.set_xlabel('Mean Steps', fontsize=12, fontweight='bold')
        ax1.set_title('Failure Patterns by Document', fontsize=13, fontweight='bold', pad=15)
        ax1.legend(fontsize=11, frameon=True, fancybox=True, shadow=True)
        ax1.grid(axis='x', alpha=0.3, linestyle='--')
        
        # Completion rate
        colors = plt.cm.RdYlGn(doc_failures['completion_rate'].values)
        ax2.barh(x, doc_failures['completion_rate'], color=colors, 
                alpha=0.8, edgecolor='black', linewidth=1.2)
        ax2.set_yticks(x)
        ax2.set_yticklabels([d.title() for d in doc_failures.index], fontweight='bold')
        ax2.set_xlabel('Completion Rate', fontsize=12, fontweight='bold')
        ax2.set_title('Workflow Completion Rate by Document', fontsize=13, fontweight='bold', pad=15)
        ax2.set_xlim(0, 1.05)
        ax2.grid(axis='x', alpha=0.3, linestyle='--')
        
        # Add percentage labels
        for i, (idx, row) in enumerate(doc_failures.iterrows()):
            ax2.text(row['completion_rate'] + 0.02, i, f"{row['completion_rate']:.1%}", 
                    va='center', fontsize=11, fontweight='bold')
        
        plt.tight_layout()
        
        for ext in ['png', 'pdf']:
            fig.savefig(self.output_dir / f'{filename}.{ext}', dpi=self.dpi, bbox_inches='tight')
        
        plt.close()
        print(f"  ✅ Saved: {filename}")
    
    def plot_failure_by_model(
        self,
        df: pd.DataFrame,
        filename: str = 'failure_by_model'
    ):
        """
        Plot failure rates by model.
        
        Args:
            df: DataFrame with failure data
            filename: Output filename
        """
        model_failures = df.groupby('model_name').agg({
            'failed_steps': 'mean',
            'steps_requiring_retry': 'mean',
            'needs_human_review': lambda x: x.sum() / len(x) if len(x) > 0 else 0,
            'is_completed': lambda x: (x == True).sum() / len(x) if len(x) > 0 else 0
        }).sort_values('failed_steps', ascending=True)
        
        model_failures.columns = ['mean_failed_steps', 'mean_retry_steps', 'review_rate', 'completion_rate']
        
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        x = np.arange(len(model_failures))
        width = 0.25
        
        # Failed steps, retry steps, review rate
        ax1.bar(x - width, model_failures['mean_failed_steps'], width, 
               label='Failed Steps', alpha=0.8, color='#d62728', edgecolor='black', linewidth=1)
        ax1.bar(x, model_failures['mean_retry_steps'], width, 
               label='Retry Steps', alpha=0.8, color='#ff7f0e', edgecolor='black', linewidth=1)
        ax1.bar(x + width, model_failures['review_rate'], width, 
               label='Review Rate', alpha=0.8, color='#9467bd', edgecolor='black', linewidth=1)
        
        ax1.set_xticks(x)
        ax1.set_xticklabels(model_failures.index, rotation=45, ha='right', fontweight='bold')
        ax1.set_ylabel('Rate', fontsize=12, fontweight='bold')
        ax1.set_title('Failure Patterns by Model', fontsize=13, fontweight='bold', pad=15)
        ax1.legend(fontsize=10, frameon=True, fancybox=True, shadow=True)
        ax1.grid(axis='y', alpha=0.3, linestyle='--')
        
        # Completion rate
        colors = plt.cm.RdYlGn(model_failures['completion_rate'].values)
        ax2.bar(x, model_failures['completion_rate'], color=colors, 
               alpha=0.8, edgecolor='black', linewidth=1.2)
        ax2.set_xticks(x)
        ax2.set_xticklabels(model_failures.index, rotation=45, ha='right', fontweight='bold')
        ax2.set_ylabel('Completion Rate', fontsize=12, fontweight='bold')
        ax2.set_title('Workflow Completion Rate by Model', fontsize=13, fontweight='bold', pad=15)
        ax2.set_ylim(0, 1.05)
        ax2.grid(axis='y', alpha=0.3, linestyle='--')
        
        # Add percentage labels
        for i, (idx, row) in enumerate(model_failures.iterrows()):
            ax2.text(i, row['completion_rate'] + 0.02, f"{row['completion_rate']:.1%}", 
                    ha='center', fontsize=10, fontweight='bold')
        
        # Failure type distribution (if available)
        if 'failure_type' in df.columns:
            failure_types = df[df['failure_type'].notna()]['failure_type'].value_counts()
            if len(failure_types) > 0:
                ax3.pie(failure_types.values, labels=failure_types.index, autopct='%1.1f%%',
                       startangle=90, colors=sns.color_palette("Set2", n_colors=len(failure_types)))
                ax3.set_title('Failure Type Distribution', fontsize=13, fontweight='bold', pad=15)
            else:
                ax3.text(0.5, 0.5, 'No failure type data', ha='center', va='center', 
                        transform=ax3.transAxes, fontsize=12)
                ax3.set_title('Failure Type Distribution', fontsize=13, fontweight='bold', pad=15)
        else:
            ax3.text(0.5, 0.5, 'No failure type data', ha='center', va='center', 
                    transform=ax3.transAxes, fontsize=12)
            ax3.set_title('Failure Type Distribution', fontsize=13, fontweight='bold', pad=15)
        
        # Success vs failure count
        if 'is_completed' in df.columns:
            success_failure = df.groupby('model_name')['is_completed'].agg([
                lambda x: (x == True).sum(),
                lambda x: (x == False).sum()
            ])
            success_failure.columns = ['Completed', 'Failed']
            
            x_pos = np.arange(len(success_failure))
            ax4.bar(x_pos, success_failure['Completed'], width=0.4, 
                   label='Completed', alpha=0.8, color='#2ca02c', edgecolor='black', linewidth=1)
            ax4.bar(x_pos + 0.4, success_failure['Failed'], width=0.4, 
                   label='Failed', alpha=0.8, color='#d62728', edgecolor='black', linewidth=1)
            
            ax4.set_xticks(x_pos + 0.2)
            ax4.set_xticklabels(success_failure.index, rotation=45, ha='right', fontweight='bold')
            ax4.set_ylabel('Number of Runs', fontsize=12, fontweight='bold')
            ax4.set_title('Completed vs Failed Runs by Model', fontsize=13, fontweight='bold', pad=15)
            ax4.legend(fontsize=10, frameon=True, fancybox=True, shadow=True)
            ax4.grid(axis='y', alpha=0.3, linestyle='--')
        
        plt.tight_layout()
        
        for ext in ['png', 'pdf']:
            fig.savefig(self.output_dir / f'{filename}.{ext}', dpi=self.dpi, bbox_inches='tight')
        
        plt.close()
        print(f"  ✅ Saved: {filename}")
