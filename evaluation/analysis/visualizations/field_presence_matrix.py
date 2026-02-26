"""
Field Presence Matrix Visualizations

Creates publication-ready field presence matrices showing which fields
are extracted by which models across multiple runs.
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional


class FieldPresenceMatrixVisualizer:
    """Generate field presence matrix visualizations."""
    
    # Category colors
    CATEGORY_COLORS = {
        'MANDATORY': '#e74c3c',      # Red
        'RECOMMENDED': '#f39c12',    # Orange
        'OPTIONAL': '#3498db',       # Blue
        'EXTRA': '#95a5a6'           # Gray
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
            'font.size': 10,
            'axes.titlesize': 13,
            'axes.labelsize': 11,
            'xtick.labelsize': 9,
            'ytick.labelsize': 9,
            'legend.fontsize': 9,
            'figure.titlesize': 14,
            'font.family': 'sans-serif'
        })
    
    def plot_presence_matrix(
        self,
        presence_matrix: pd.DataFrame,
        document_id: str,
        filename: str = 'field_presence_matrix',
        show_pattern: bool = False
    ):
        """
        Create field presence matrix heatmap.
        
        Args:
            presence_matrix: DataFrame from FieldPresenceAnalyzer
            document_id: Document identifier
            filename: Output filename (without extension)
            show_pattern: If True, show ✓✗ pattern; if False, show rate
        """
        # Get model rate columns
        rate_cols = [col for col in presence_matrix.columns if col.endswith('_rate')]
        models = [col.replace('_rate', '') for col in rate_cols]
        
        if not rate_cols:
            print(f"No rate columns found in presence matrix for {document_id}")
            return
        
        # Filter out empty rows
        matrix_filtered = presence_matrix[presence_matrix[rate_cols].sum(axis=1) > 0]
        
        if len(matrix_filtered) == 0:
            print(f"No fields with presence data for {document_id}")
            return
        
        # Sort by category and presence
        matrix_filtered = matrix_filtered.copy()
        category_order = {'MANDATORY': 0, 'RECOMMENDED': 1, 'OPTIONAL': 2, 'EXTRA': 3}
        matrix_filtered['category_order'] = matrix_filtered['category'].map(category_order)
        matrix_filtered = matrix_filtered.sort_values(['category_order', 'field_name'])
        
        # Create figure
        fig_height = max(10, len(matrix_filtered) * 0.25)
        fig, ax = plt.subplots(figsize=(max(12, len(models) * 1.5), fig_height))
        
        # Create heatmap data
        heatmap_data = matrix_filtered[rate_cols].values
        
        # Plot heatmap
        im = ax.imshow(heatmap_data, aspect='auto', cmap='RdYlGn', vmin=0, vmax=1)
        
        # Set ticks
        ax.set_xticks(np.arange(len(models)))
        ax.set_yticks(np.arange(len(matrix_filtered)))
        ax.set_xticklabels(models, rotation=45, ha='right')
        
        # Create y-tick labels with category prefix
        y_labels = []
        for _, row in matrix_filtered.iterrows():
            cat_label = row['category'][0]  # M, R, O, or E
            y_labels.append(f"[{cat_label}] {row['field_name']}")
        ax.set_yticklabels(y_labels, fontsize=8)
        
        # Add value annotations
        for i in range(len(matrix_filtered)):
            for j in range(len(models)):
                value = heatmap_data[i, j]
                if show_pattern:
                    # Show pattern
                    pattern_col = f"{models[j]}_pattern"
                    if pattern_col in matrix_filtered.columns:
                        pattern = matrix_filtered.iloc[i][pattern_col]
                        text = ax.text(j, i, pattern, ha='center', va='center',
                                     color='black' if value < 0.5 else 'white',
                                     fontsize=6)
                else:
                    # Show percentage
                    text = ax.text(j, i, f'{value:.0%}', ha='center', va='center',
                                 color='black' if value < 0.5 else 'white',
                                 fontsize=8)
        
        # Add colorbar
        cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label('Presence Rate', rotation=270, labelpad=20)
        
        # Add category color bars on the left
        for i, (_, row) in enumerate(matrix_filtered.iterrows()):
            color = self.CATEGORY_COLORS[row['category']]
            rect = mpatches.Rectangle((-0.7, i-0.4), 0.3, 0.8, 
                                     color=color, transform=ax.transData,
                                     clip_on=False)
            ax.add_patch(rect)
        
        # Title and labels
        ax.set_title(f'Field Presence Matrix: {document_id}', 
                    fontsize=14, fontweight='bold', pad=20)
        ax.set_xlabel('Model', fontsize=12, fontweight='bold')
        ax.set_ylabel('Field Name [Category]', fontsize=12, fontweight='bold')
        
        # Add legend for categories
        legend_elements = [
            mpatches.Patch(color=self.CATEGORY_COLORS['MANDATORY'], label='[M] Mandatory'),
            mpatches.Patch(color=self.CATEGORY_COLORS['RECOMMENDED'], label='[R] Recommended'),
            mpatches.Patch(color=self.CATEGORY_COLORS['OPTIONAL'], label='[O] Optional'),
            mpatches.Patch(color=self.CATEGORY_COLORS['EXTRA'], label='[E] Extra (not in GT)')
        ]
        ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.15, 1),
                 frameon=True, fancybox=True, shadow=True)
        
        plt.tight_layout()
        plt.savefig(self.output_dir / f'{filename}_{document_id}.png', 
                   dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✓ Saved field presence matrix: {filename}_{document_id}.png")
    
    def plot_core_fields_summary(
        self,
        presence_matrix: pd.DataFrame,
        document_id: str,
        filename: str = 'core_fields_summary'
    ):
        """
        Create summary visualization of core fields.
        
        Args:
            presence_matrix: DataFrame from FieldPresenceAnalyzer
            document_id: Document identifier
            filename: Output filename
        """
        # Calculate consensus rate
        rate_cols = [col for col in presence_matrix.columns if col.endswith('_rate')]
        if not rate_cols:
            return
        
        presence_matrix['consensus_rate'] = presence_matrix[rate_cols].mean(axis=1)
        
        # Group by category and consensus level
        bins = [0, 0.5, 0.8, 1.0]
        labels = ['Low (0-50%)', 'Medium (50-80%)', 'High (80-100%)']
        presence_matrix['consensus_level'] = pd.cut(
            presence_matrix['consensus_rate'], 
            bins=bins, 
            labels=labels,
            include_lowest=True
        )
        
        # Count by category and consensus level
        summary = presence_matrix.groupby(['category', 'consensus_level']).size().unstack(fill_value=0)
        
        # Create stacked bar chart
        fig, ax = plt.subplots(figsize=(10, 6))
        
        summary.plot(kind='bar', stacked=True, ax=ax, 
                    color=['#e74c3c', '#f39c12', '#27ae60'])
        
        ax.set_title(f'Field Consensus Summary: {document_id}', 
                    fontsize=14, fontweight='bold')
        ax.set_xlabel('Field Category', fontsize=12)
        ax.set_ylabel('Number of Fields', fontsize=12)
        ax.set_xticklabels(ax.get_xticklabels(), rotation=0)
        ax.legend(title='Consensus Rate', frameon=True)
        ax.grid(axis='y', alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(self.output_dir / f'{filename}_{document_id}.png', 
                   dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✓ Saved core fields summary: {filename}_{document_id}.png")
    
    def plot_model_field_coverage(
        self,
        presence_matrix: pd.DataFrame,
        document_id: str,
        filename: str = 'model_field_coverage'
    ):
        """
        Plot field coverage by model and category.
        
        Args:
            presence_matrix: DataFrame from FieldPresenceAnalyzer
            document_id: Document identifier
            filename: Output filename
        """
        rate_cols = [col for col in presence_matrix.columns if col.endswith('_rate')]
        models = [col.replace('_rate', '') for col in rate_cols]
        
        if not rate_cols:
            return
        
        # Calculate coverage by category for each model
        coverage_data = []
        for model in models:
            for category in ['MANDATORY', 'RECOMMENDED', 'OPTIONAL']:
                cat_df = presence_matrix[presence_matrix['category'] == category]
                if len(cat_df) > 0:
                    avg_rate = cat_df[f'{model}_rate'].mean()
                    coverage_data.append({
                        'model': model,
                        'category': category,
                        'coverage': avg_rate
                    })
        
        df = pd.DataFrame(coverage_data)
        
        # Create grouped bar chart
        fig, ax = plt.subplots(figsize=(12, 6))
        
        categories = ['MANDATORY', 'RECOMMENDED', 'OPTIONAL']
        x = np.arange(len(models))
        width = 0.25
        
        for i, category in enumerate(categories):
            cat_data = df[df['category'] == category]
            values = [cat_data[cat_data['model'] == m]['coverage'].values[0] 
                     if len(cat_data[cat_data['model'] == m]) > 0 else 0 
                     for m in models]
            ax.bar(x + i*width, values, width, 
                  label=category, color=self.CATEGORY_COLORS[category])
        
        ax.set_title(f'Field Coverage by Model and Category: {document_id}', 
                    fontsize=14, fontweight='bold')
        ax.set_xlabel('Model', fontsize=12)
        ax.set_ylabel('Average Coverage Rate', fontsize=12)
        ax.set_xticks(x + width)
        ax.set_xticklabels(models, rotation=45, ha='right')
        ax.set_ylim(0, 1.1)
        ax.legend(frameon=True)
        ax.grid(axis='y', alpha=0.3)
        
        # Add percentage labels
        for container in ax.containers:
            ax.bar_label(container, fmt='%.0f%%', label_type='edge', fontsize=8,
                        labels=[f'{v:.0%}' for v in container.datavalues])
        
        plt.tight_layout()
        plt.savefig(self.output_dir / f'{filename}_{document_id}.png', 
                   dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✓ Saved model field coverage: {filename}_{document_id}.png")
