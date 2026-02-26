"""
Stability-Completeness Visualizations

Creates publication-ready scatter plots and analyses showing the
relationship between extraction stability and completeness.
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional
from scipy import stats
import sys

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))
from model_config import (
    get_model_metadata,
    get_model_display_name,
    get_model_color,
    get_model_type,
    get_model_marker,
    sort_models_by_family_and_type
)


class StabilityCompletenessVisualizer:
    """Generate stability-completeness visualizations with API/Local distinction."""
    
    # Pattern colors
    PATTERN_COLORS = {
        'IDEAL': '#27ae60',           # Green
        'CONSERVATIVE': '#3498db',     # Blue
        'EXPLORATORY': '#f39c12',      # Orange
        'MODERATE': '#95a5a6',         # Gray
        'POOR': '#e74c3c'              # Red
    }
    
    def __init__(self, output_dir: Path):
        """
        Initialize visualizer.
        
        Args:
            output_dir: Directory to save figures
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Set publication style
        plt.style.use('seaborn-v0_8-paper')
        plt.rcParams.update({
            'font.size': 11,
            'axes.titlesize': 13,
            'axes.labelsize': 12,
            'xtick.labelsize': 10,
            'ytick.labelsize': 10,
            'legend.fontsize': 10,
            'figure.titlesize': 14
        })
    
    def plot_stability_completeness_scatter(
        self,
        scatter_data: pd.DataFrame,
        filename: str = 'stability_completeness_scatter'
    ):
        """
        Create scatter plot of stability vs completeness with API/Local distinction.
        
        Args:
            scatter_data: DataFrame from StabilityCompletenessAnalyzer
            filename: Output filename
        """
        fig, ax = plt.subplots(figsize=(14, 9))
        
        # Add model metadata
        scatter_data['model_type'] = scatter_data['model_name'].apply(get_model_type)
        scatter_data['model_color'] = scatter_data['model_name'].apply(get_model_color)
        scatter_data['model_marker'] = scatter_data['model_name'].apply(get_model_marker)
        scatter_data['model_display'] = scatter_data['model_name'].apply(get_model_display_name)
        
        # Plot by type (API vs Local)
        for model_type in ['api', 'local']:
            type_data = scatter_data[scatter_data['model_type'] == model_type]
            if len(type_data) == 0:
                continue
            
            # Plot each model with its own color
            for _, row in type_data.iterrows():
                ax.scatter(
                    row['completeness_score'],
                    row['stability_score'],
                    s=row['core_fields_count'] * 15,  # Size by core fields
                    c=row['model_color'],
                    marker=row['model_marker'],
                    alpha=0.7,
                    edgecolors='black',
                    linewidth=1,
                    label=f"{row['model_display']} ({row['document_id']})"
                )
        
        # Add quadrant lines
        ax.axhline(y=0.8, color='gray', linestyle='--', alpha=0.3)
        ax.axvline(x=0.7, color='gray', linestyle='--', alpha=0.3)
        
        # Add quadrant labels
        ax.text(0.85, 0.95, 'IDEAL', transform=ax.transAxes,
               fontsize=10, alpha=0.5, ha='center', fontweight='bold')
        ax.text(0.15, 0.95, 'CONSERVATIVE', transform=ax.transAxes,
               fontsize=10, alpha=0.5, ha='center', fontweight='bold')
        ax.text(0.85, 0.05, 'EXPLORATORY', transform=ax.transAxes,
               fontsize=10, alpha=0.5, ha='center', fontweight='bold')
        ax.text(0.15, 0.05, 'POOR', transform=ax.transAxes,
               fontsize=10, alpha=0.5, ha='center', fontweight='bold')
        
        # Labels and title
        ax.set_xlabel('Completeness (vs. Ground Truth)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Stability (Core Fields / Total Fields)', fontsize=12, fontweight='bold')
        ax.set_title('Stability vs. Completeness Trade-off', 
                    fontsize=14, fontweight='bold', pad=20)
        
        ax.set_xlim(-0.05, 1.05)
        ax.set_ylim(-0.05, 1.05)
        ax.grid(True, alpha=0.3)
        
        # Legend
        ax.legend(title='Pattern', loc='center left', bbox_to_anchor=(1, 0.5),
                 frameon=True, fancybox=True, shadow=True)
        
        plt.tight_layout()
        plt.savefig(self.output_dir / f'{filename}.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✓ Saved stability-completeness scatter: {filename}.png")
    
    def plot_stability_by_document(
        self,
        scatter_data: pd.DataFrame,
        filename: str = 'stability_by_document'
    ):
        """
        Create grouped bar chart showing stability by document.
        
        Args:
            scatter_data: DataFrame from StabilityCompletenessAnalyzer
            filename: Output filename
        """
        # Aggregate by document and model
        pivot = scatter_data.pivot_table(
            index='document_id',
            columns='model_name',
            values='stability_score',
            aggfunc='mean'
        )
        
        fig, ax = plt.subplots(figsize=(12, 6))
        pivot.plot(kind='bar', ax=ax, width=0.8)
        
        ax.set_title('Extraction Stability by Document and Model', 
                    fontsize=14, fontweight='bold')
        ax.set_xlabel('Document', fontsize=12, fontweight='bold')
        ax.set_ylabel('Stability Score', fontsize=12, fontweight='bold')
        ax.set_ylim(0, 1.1)
        ax.set_xticklabels(ax.get_xticklabels(), rotation=0)
        ax.legend(title='Model', bbox_to_anchor=(1.05, 1), loc='upper left')
        ax.grid(axis='y', alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(self.output_dir / f'{filename}.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✓ Saved stability by document: {filename}.png")
    
    def plot_mandatory_core_analysis(
        self,
        scatter_data: pd.DataFrame,
        filename: str = 'mandatory_core_analysis'
    ):
        """
        Analyze mandatory fields in core vs. variable sets.
        
        Args:
            scatter_data: DataFrame from StabilityCompletenessAnalyzer
            filename: Output filename
        """
        if 'mandatory_core_rate' not in scatter_data.columns:
            print("Warning: mandatory_core_rate not in data")
            return
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        # Plot 1: Mandatory core rate by model
        model_agg = scatter_data.groupby('model_name')['mandatory_core_rate'].mean().sort_values(ascending=False)
        
        ax1.barh(range(len(model_agg)), model_agg.values, color='#3498db')
        ax1.set_yticks(range(len(model_agg)))
        ax1.set_yticklabels(model_agg.index)
        ax1.set_xlabel('Mandatory Fields in Core (%)', fontsize=11, fontweight='bold')
        ax1.set_title('Mandatory Field Consistency', fontsize=12, fontweight='bold')
        ax1.set_xlim(0, 1.1)
        ax1.grid(axis='x', alpha=0.3)
        
        # Add percentage labels
        for i, v in enumerate(model_agg.values):
            ax1.text(v + 0.02, i, f'{v:.0%}', va='center', fontsize=9)
        
        # Plot 2: Scatter of stability vs mandatory core rate
        for doc in scatter_data['document_id'].unique():
            doc_data = scatter_data[scatter_data['document_id'] == doc]
            ax2.scatter(
                doc_data['mandatory_core_rate'],
                doc_data['stability_score'],
                s=100,
                alpha=0.6,
                label=doc
            )
        
        ax2.set_xlabel('Mandatory Fields in Core (%)', fontsize=11, fontweight='bold')
        ax2.set_ylabel('Overall Stability', fontsize=11, fontweight='bold')
        ax2.set_title('Stability vs. Mandatory Consistency', fontsize=12, fontweight='bold')
        ax2.legend(title='Document')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(self.output_dir / f'{filename}.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✓ Saved mandatory core analysis: {filename}.png")
    
    def plot_document_comparison(
        self,
        comparison_df: pd.DataFrame,
        filename: str = 'document_comparison'
    ):
        """
        Create comparison chart across documents.
        
        Args:
            comparison_df: DataFrame from StabilityCompletenessAnalyzer.compare_documents()
            filename: Output filename
        """
        if len(comparison_df) == 0:
            return
        
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        docs = comparison_df['document_id'].tolist()
        x = np.arange(len(docs))
        
        # Plot 1: Mean stability
        axes[0, 0].bar(x, comparison_df['mean_stability'], color='#3498db', alpha=0.7)
        axes[0, 0].errorbar(x, comparison_df['mean_stability'], 
                           yerr=comparison_df['std_stability'],
                           fmt='none', color='black', capsize=5)
        axes[0, 0].set_xticks(x)
        axes[0, 0].set_xticklabels(docs, rotation=0)
        axes[0, 0].set_ylabel('Mean Stability Score')
        axes[0, 0].set_title('Stability by Document', fontweight='bold')
        axes[0, 0].set_ylim(0, 1.1)
        axes[0, 0].grid(axis='y', alpha=0.3)
        
        # Plot 2: Mean completeness
        axes[0, 1].bar(x, comparison_df['mean_completeness'], color='#27ae60', alpha=0.7)
        axes[0, 1].errorbar(x, comparison_df['mean_completeness'], 
                           yerr=comparison_df['std_completeness'],
                           fmt='none', color='black', capsize=5)
        axes[0, 1].set_xticks(x)
        axes[0, 1].set_xticklabels(docs, rotation=0)
        axes[0, 1].set_ylabel('Mean Completeness Score')
        axes[0, 1].set_title('Completeness by Document', fontweight='bold')
        axes[0, 1].set_ylim(0, 1.1)
        axes[0, 1].grid(axis='y', alpha=0.3)
        
        # Plot 3: Mandatory core rate
        axes[1, 0].bar(x, comparison_df['mean_mandatory_core_rate'], color='#e74c3c', alpha=0.7)
        axes[1, 0].set_xticks(x)
        axes[1, 0].set_xticklabels(docs, rotation=0)
        axes[1, 0].set_ylabel('Mandatory Fields in Core (%)')
        axes[1, 0].set_title('Mandatory Field Consistency', fontweight='bold')
        axes[1, 0].set_ylim(0, 1.1)
        axes[1, 0].grid(axis='y', alpha=0.3)
        
        # Plot 4: Correlation
        colors = ['#27ae60' if c > 0 else '#e74c3c' for c in comparison_df['correlation']]
        axes[1, 1].bar(x, comparison_df['correlation'], color=colors, alpha=0.7)
        axes[1, 1].axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
        axes[1, 1].set_xticks(x)
        axes[1, 1].set_xticklabels(docs, rotation=0)
        axes[1, 1].set_ylabel('Correlation (Stability-Completeness)')
        axes[1, 1].set_title('Stability-Completeness Correlation', fontweight='bold')
        axes[1, 1].set_ylim(-1.1, 1.1)
        axes[1, 1].grid(axis='y', alpha=0.3)
        
        plt.suptitle('Document-Level Analysis', fontsize=16, fontweight='bold', y=1.00)
        plt.tight_layout()
        plt.savefig(self.output_dir / f'{filename}.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✓ Saved document comparison: {filename}.png")
