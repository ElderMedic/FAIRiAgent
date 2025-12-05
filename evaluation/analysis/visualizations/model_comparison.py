"""
Model Comparison Visualizations

Publication-ready visualizations for model performance comparison.
"""

import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional


class ModelComparisonVisualizer:
    """Generate model comparison visualizations."""
    
    def __init__(self, output_dir: Path):
        """
        Initialize visualizer.
        
        Args:
            output_dir: Directory to save figures
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Set publication style with better defaults
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
    
    def plot_model_comparison_heatmap(
        self,
        df: pd.DataFrame,
        metrics: Optional[List[str]] = None,
        filename: str = 'model_comparison_heatmap'
    ):
        """
        Create heatmap comparing models across multiple metrics.
        
        Args:
            df: DataFrame with model performance data
            metrics: List of metrics to include (default: all main metrics)
            filename: Output filename (without extension)
        """
        if metrics is None:
            metrics = [
                'aggregate_score', 'completeness', 'correctness_f1',
                'schema_compliance', 'llm_judge_score', 'internal_confidence'
            ]
        
        # Filter available metrics
        available_metrics = [m for m in metrics if m in df.columns]
        
        # Aggregate by model
        model_data = df.groupby('model_name')[available_metrics].mean()
        
        # Create heatmap with better styling
        fig, ax = plt.subplots(figsize=(12, max(7, len(model_data) * 0.6)))
        
        # Use better colormap and formatting
        sns.heatmap(
            model_data.T,
            annot=True,
            fmt='.3f',
            cmap='RdYlGn',
            center=0.5,
            vmin=0,
            vmax=1,
            cbar_kws={'label': 'Score', 'shrink': 0.8},
            ax=ax,
            linewidths=0.5,
            linecolor='white',
            annot_kws={'size': 10}
        )
        
        ax.set_title('Model Performance Comparison Across Metrics', 
                    fontsize=14, fontweight='bold', pad=20)
        ax.set_xlabel('Model', fontsize=12, fontweight='bold')
        ax.set_ylabel('Metric', fontsize=12, fontweight='bold')
        
        # Improve metric labels
        metric_labels = [label.get_text().replace('_', ' ').title() for label in ax.get_yticklabels()]
        ax.set_yticklabels(metric_labels, rotation=0)
        
        plt.tight_layout()
        
        # Save in multiple formats
        for ext in ['png', 'pdf']:
            fig.savefig(self.output_dir / f'{filename}.{ext}', dpi=self.dpi, bbox_inches='tight')
        
        plt.close()
        print(f"  ✅ Saved: {filename}")
    
    def plot_model_rankings(
        self,
        df: pd.DataFrame,
        metric: str = 'aggregate_score',
        filename: str = 'model_rankings'
    ):
        """
        Create bar chart of model rankings.
        
        Args:
            df: DataFrame with model performance data
            metric: Metric to rank by
            filename: Output filename
        """
        model_means = df.groupby('model_name')[metric].mean().sort_values(ascending=True)
        model_stds = df.groupby('model_name')[metric].std()
        
        fig, ax = plt.subplots(figsize=(10, max(6, len(model_means) * 0.8)))
        
        y_pos = np.arange(len(model_means))
        
        # Use color gradient based on performance
        colors = plt.cm.RdYlGn(np.linspace(0.3, 0.9, len(model_means)))
        
        bars = ax.barh(y_pos, model_means.values, 
                      xerr=model_stds[model_means.index].values,
                      color=colors, alpha=0.8, edgecolor='black', linewidth=1.2)
        
        ax.set_yticks(y_pos)
        ax.set_yticklabels(model_means.index, fontweight='bold')
        ax.set_xlabel(metric.replace('_', ' ').title(), fontsize=12, fontweight='bold')
        ax.set_title(f'Model Rankings by {metric.replace("_", " ").title()}', 
                    fontsize=14, fontweight='bold', pad=15)
        ax.set_xlim(0, max(1.0, model_means.max() * 1.1))
        ax.grid(axis='x', alpha=0.3, linestyle='--')
        
        # Add value labels with better positioning
        for i, (idx, val) in enumerate(model_means.items()):
            std_val = model_stds[model_means.index].iloc[i] if not pd.isna(model_stds[model_means.index].iloc[i]) else 0
            label_x = val + std_val + 0.02
            ax.text(label_x, i, f'{val:.3f}', va='center', fontsize=11, fontweight='bold')
            if std_val > 0:
                ax.text(label_x, i - 0.15, f'±{std_val:.3f}', va='center', fontsize=9, style='italic', color='gray')
        
        plt.tight_layout()
        
        for ext in ['png', 'pdf']:
            fig.savefig(self.output_dir / f'{filename}.{ext}', dpi=self.dpi, bbox_inches='tight')
        
        plt.close()
        print(f"  ✅ Saved: {filename}")
    
    def plot_metric_correlation(
        self,
        df: pd.DataFrame,
        filename: str = 'metric_correlation'
    ):
        """
        Create correlation heatmap between metrics.
        
        Args:
            df: DataFrame with model performance data
            filename: Output filename
        """
        metrics = [
            'completeness', 'correctness_f1', 'schema_compliance',
            'llm_judge_score', 'internal_confidence', 'retry_rate'
        ]
        
        available_metrics = [m for m in metrics if m in df.columns]
        corr_matrix = df[available_metrics].corr()
        
        fig, ax = plt.subplots(figsize=(8, 8))
        sns.heatmap(
            corr_matrix,
            annot=True,
            fmt='.3f',
            cmap='coolwarm',
            center=0,
            vmin=-1,
            vmax=1,
            square=True,
            ax=ax
        )
        
        ax.set_title('Metric Correlations', fontsize=14, fontweight='bold')
        
        plt.tight_layout()
        
        for ext in ['png', 'pdf']:
            fig.savefig(self.output_dir / f'{filename}.{ext}', dpi=self.dpi, bbox_inches='tight')
        
        plt.close()
        print(f"  ✅ Saved: {filename}")
    
    def plot_document_performance(
        self,
        df: pd.DataFrame,
        filename: str = 'document_performance'
    ):
        """
        Create grouped bar chart showing performance per document.
        
        Args:
            df: DataFrame with document-level data
            filename: Output filename
        """
        doc_df = df.groupby(['model_name', 'document_id']).agg({
            'completeness': 'mean',
            'correctness_f1': 'mean'
        }).reset_index()
        
        # Pivot for grouped bar chart
        completeness_pivot = doc_df.pivot(index='document_id', columns='model_name', values='completeness')
        correctness_pivot = doc_df.pivot(index='document_id', columns='model_name', values='correctness_f1')
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
        
        # Completeness plot with better styling
        completeness_pivot.plot(kind='bar', ax=ax1, width=0.75, 
                               color=sns.color_palette("Set2", n_colors=len(completeness_pivot.columns)),
                               edgecolor='black', linewidth=0.8)
        ax1.set_title('Completeness by Document', fontsize=13, fontweight='bold', pad=15)
        ax1.set_ylabel('Completeness Score', fontsize=12, fontweight='bold')
        ax1.set_xlabel('Document', fontsize=12, fontweight='bold')
        ax1.legend(title='Model', title_fontsize=11, fontsize=10, 
                  bbox_to_anchor=(1.02, 1), loc='upper left', frameon=True, fancybox=True, shadow=True)
        ax1.set_ylim(0, 1.05)
        ax1.tick_params(axis='x', rotation=45, labelsize=10)
        ax1.grid(axis='y', alpha=0.3, linestyle='--')
        ax1.set_xticklabels([label.get_text().title() for label in ax1.get_xticklabels()])
        
        # Correctness plot with better styling
        correctness_pivot.plot(kind='bar', ax=ax2, width=0.75,
                              color=sns.color_palette("Set2", n_colors=len(correctness_pivot.columns)),
                              edgecolor='black', linewidth=0.8)
        ax2.set_title('Correctness (F1 Score) by Document', fontsize=13, fontweight='bold', pad=15)
        ax2.set_ylabel('F1 Score', fontsize=12, fontweight='bold')
        ax2.set_xlabel('Document', fontsize=12, fontweight='bold')
        ax2.legend(title='Model', title_fontsize=11, fontsize=10,
                  bbox_to_anchor=(1.02, 1), loc='upper left', frameon=True, fancybox=True, shadow=True)
        ax2.set_ylim(0, 1.05)
        ax2.tick_params(axis='x', rotation=45, labelsize=10)
        ax2.grid(axis='y', alpha=0.3, linestyle='--')
        ax2.set_xticklabels([label.get_text().title() for label in ax2.get_xticklabels()])
        
        plt.tight_layout()
        
        for ext in ['png', 'pdf']:
            fig.savefig(self.output_dir / f'{filename}.{ext}', dpi=self.dpi, bbox_inches='tight')
        
        plt.close()
        print(f"  ✅ Saved: {filename}")

