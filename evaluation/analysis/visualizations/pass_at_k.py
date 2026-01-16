"""
Pass@k Visualizations

Generates visualizations for pass@k metrics similar to SWE-agent benchmark style.

Key Concepts:
- pass@k: Probability of at least one successful run in k independent attempts
- Formula: pass@k = 1 - C(n-c, k) / C(n, k)
  where n = total runs, c = successful runs, k = number of attempts
- Success Criteria Presets define what counts as a "successful" run

Success Criteria Presets:
| Preset      | Fields | Required Comp. | F1 Score | Confidence | Description                |
|-------------|--------|----------------|----------|------------|----------------------------|
| basic       | ≥1     | ≥0%            | ≥0       | -          | Any output                 |
| lenient     | ≥5     | ≥20%           | ≥0       | -          | Minimal quality            |
| moderate    | ≥10    | ≥50%           | ≥0.3     | -          | Recommended default        |
| strict      | ≥15    | ≥70%           | ≥0.5     | ≥0.6       | High quality               |
| very_strict | ≥20    | ≥80%           | ≥0.6     | ≥0.7       | Publication-ready quality  |
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Any


# Success criteria descriptions for figure annotations
CRITERIA_DESCRIPTIONS = {
    'basic': 'Fields≥1, any output counts',
    'lenient': 'Fields≥5, Req.Comp≥20%',
    'moderate': 'Fields≥10, Req.Comp≥50%, F1≥0.3',
    'strict': 'Fields≥15, Req.Comp≥70%, F1≥0.5, Conf≥0.6',
    'very_strict': 'Fields≥20, Req.Comp≥80%, F1≥0.6, Conf≥0.7',
}


class PassAtKVisualizer:
    """Generate pass@k visualizations."""
    
    def __init__(self, output_dir: Path):
        """
        Initialize visualizer.
        
        Args:
            output_dir: Directory to save figures
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Set style
        plt.style.use('seaborn-v0_8-whitegrid')
        
        # Color palette for models (consistent across plots)
        self.model_colors = {
            'openai_gpt5': '#27ae60',
            'gpt5': '#27ae60',
            'anthropic_haiku': '#9b59b6',
            'haiku': '#9b59b6',
            'anthropic_sonnet': '#3498db',
            'sonnet': '#3498db',
            'anthropic_opus': '#e74c3c',
            'opus': '#e74c3c',
            'openai_o3': '#f39c12',
            'o3': '#f39c12',
            'openai_gpt4.1': '#1abc9c',
            'gpt4.1': '#1abc9c',
            'qwen_max': '#e67e22',
            'qwen_plus': '#d35400',
            'qwen_flash': '#c0392b',
            'ollama_gpt-oss': '#7f8c8d',
        }
        
        # Display names
        self.display_names = {
            'openai_gpt5': 'GPT-5',
            'gpt5': 'GPT-5',
            'anthropic_haiku': 'Claude Haiku',
            'haiku': 'Claude Haiku',
            'anthropic_sonnet': 'Claude Sonnet',
            'sonnet': 'Claude Sonnet',
            'anthropic_opus': 'Claude Opus',
            'opus': 'Claude Opus',
            'openai_o3': 'O3',
            'o3': 'O3',
            'openai_gpt4.1': 'GPT-4.1',
            'gpt4.1': 'GPT-4.1',
            'qwen_max': 'Qwen Max',
            'qwen_plus': 'Qwen Plus',
            'qwen_flash': 'Qwen Flash',
            'ollama_gpt-oss': 'GPT-OSS (Ollama)',
        }
    
    def _get_color(self, model: str) -> str:
        """Get color for a model."""
        return self.model_colors.get(model, '#95a5a6')
    
    def _get_display_name(self, model: str) -> str:
        """Get display name for a model."""
        return self.display_names.get(model, model)
    
    def plot_pass_at_k_comparison(
        self,
        summary_df: pd.DataFrame,
        k_values: List[int] = [1, 3, 5, 10],
        filename: str = 'pass_at_k_comparison'
    ):
        """
        Create bar chart comparing pass@k across models.
        
        Args:
            summary_df: DataFrame with model pass@k summary
            k_values: List of k values to plot
            filename: Output filename (without extension)
        """
        fig, ax = plt.subplots(figsize=(14, 9))
        
        # Filter out models with 0 pass@1
        df = summary_df[summary_df['pass@1'] > 0].copy()
        df = df.sort_values('pass@1', ascending=False)
        
        models = df['model'].tolist()
        x = np.arange(len(models))
        width = 0.2
        
        # Colors for different k values
        k_colors = ['#e74c3c', '#f39c12', '#27ae60', '#3498db']
        
        for i, k in enumerate(k_values):
            col = f'pass@{k}'
            if col in df.columns:
                values = df[col].values
                bars = ax.bar(x + i * width, values, width, 
                             label=f'pass@{k}', color=k_colors[i], alpha=0.85)
                
                # Add value labels on bars
                for bar, val in zip(bars, values):
                    if val > 0.05:
                        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                               f'{val:.2f}', ha='center', va='bottom', fontsize=8,
                               rotation=0)
        
        ax.set_xlabel('Model', fontsize=12)
        ax.set_ylabel('pass@k (Probability of Success)', fontsize=12)
        ax.set_title('Pass@k Comparison Across Models', fontsize=14, fontweight='bold')
        ax.set_xticks(x + width * 1.5)
        ax.set_xticklabels([self._get_display_name(m) for m in models], rotation=45, ha='right')
        ax.legend(loc='upper right', fontsize=10, title='k = attempts')
        ax.set_ylim(0, 1.20)
        ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.3)
        
        # Add caption explaining the figure
        caption = (
            "Success Criteria (moderate): Fields≥10, Required Completeness≥50%, F1≥0.3\n"
            "pass@k = probability of ≥1 successful run in k attempts. Higher k → more attempts → higher success probability."
        )
        fig.text(0.5, 0.01, caption, ha='center', fontsize=9, style='italic', 
                wrap=True, color='#555555')
        
        plt.tight_layout(rect=[0, 0.06, 1, 1])
        plt.savefig(self.output_dir / f'{filename}.png', dpi=150, bbox_inches='tight')
        plt.savefig(self.output_dir / f'{filename}.pdf', bbox_inches='tight')
        plt.close()
        
        print(f"    ✅ Saved: {filename}.png, {filename}.pdf")
    
    def plot_pass_at_k_curves(
        self,
        summary_df: pd.DataFrame,
        k_range: range = range(1, 21),
        filename: str = 'pass_at_k_curves'
    ):
        """
        Plot pass@k curves showing how pass rate increases with k.
        
        Args:
            summary_df: DataFrame with model summary (needs total_runs, successful_runs)
            k_range: Range of k values to plot
            filename: Output filename
        """
        fig, ax = plt.subplots(figsize=(12, 9))
        
        # Filter models
        df = summary_df[summary_df['success_rate'] > 0].copy()
        df = df.sort_values('pass@1', ascending=False)
        
        for _, row in df.iterrows():
            model = row['model']
            n = row['total_runs']
            c = row['successful_runs']
            
            # Calculate pass@k for each k
            pass_k_values = []
            for k in k_range:
                if k > n:
                    pass_k_values.append(pass_k_values[-1] if pass_k_values else 0)
                else:
                    pass_k = self._calculate_pass_at_k(n, c, k)
                    pass_k_values.append(pass_k)
            
            color = self._get_color(model)
            label = f"{self._get_display_name(model)} (n={n}, c={c})"
            ax.plot(list(k_range), pass_k_values, 'o-', color=color, 
                   label=label, linewidth=2, markersize=4, alpha=0.8)
        
        ax.set_xlabel('k (Number of Independent Attempts)', fontsize=12)
        ax.set_ylabel('pass@k (Probability of ≥1 Success)', fontsize=12)
        ax.set_title('Pass@k Curves: How Success Probability Increases with More Attempts', 
                    fontsize=14, fontweight='bold')
        ax.legend(loc='lower right', fontsize=9, title='Model (n=total runs, c=successes)')
        ax.set_xlim(0.5, max(k_range) + 0.5)
        ax.set_ylim(0, 1.10)
        ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.3)
        ax.grid(True, alpha=0.3)
        
        # Add annotation for perfect success
        ax.annotate('Perfect success\n(pass@k = 1.0)', xy=(15, 1.0), xytext=(15, 0.82),
                   fontsize=9, ha='center', color='gray',
                   arrowprops=dict(arrowstyle='->', color='gray', alpha=0.5))
        
        # Add caption
        caption = (
            "Formula: pass@k = 1 - C(n-c,k)/C(n,k), where n=total runs, c=successful runs, k=attempts.\n"
            "Success Criteria (moderate): Fields≥10, Required Completeness≥50%, F1≥0.3"
        )
        fig.text(0.5, 0.01, caption, ha='center', fontsize=9, style='italic', 
                wrap=True, color='#555555')
        
        plt.tight_layout(rect=[0, 0.05, 1, 1])
        plt.savefig(self.output_dir / f'{filename}.png', dpi=150, bbox_inches='tight')
        plt.savefig(self.output_dir / f'{filename}.pdf', bbox_inches='tight')
        plt.close()
        
        print(f"    ✅ Saved: {filename}.png, {filename}.pdf")
    
    def plot_multi_criteria_heatmap(
        self,
        comparison_df: pd.DataFrame,
        metric: str = 'pass@1',
        filename: str = 'pass_at_k_multi_criteria_heatmap'
    ):
        """
        Create heatmap showing pass@k across different criteria presets.
        
        Args:
            comparison_df: DataFrame with criteria, model, and metrics
            metric: Which metric to visualize
            filename: Output filename
        """
        # Pivot the data
        pivot_df = comparison_df.pivot(index='model', columns='criteria', values=metric)
        
        # Reorder columns
        criteria_order = ['basic', 'lenient', 'moderate', 'strict', 'very_strict']
        pivot_df = pivot_df[[c for c in criteria_order if c in pivot_df.columns]]
        
        # Sort by moderate criteria
        if 'moderate' in pivot_df.columns:
            pivot_df = pivot_df.sort_values('moderate', ascending=False)
        
        # Rename index for display
        pivot_df.index = [self._get_display_name(m) for m in pivot_df.index]
        
        # Create figure with extra space for legend
        fig, ax = plt.subplots(figsize=(12, 10))
        
        sns.heatmap(pivot_df, annot=True, fmt='.2f', cmap='RdYlGn',
                   vmin=0, vmax=1, ax=ax, cbar_kws={'label': metric},
                   linewidths=0.5)
        
        ax.set_title(f'{metric} Across Different Success Criteria Presets', 
                    fontsize=14, fontweight='bold')
        ax.set_xlabel('Success Criteria Preset (Strictness: basic → very_strict)', fontsize=12)
        ax.set_ylabel('Model', fontsize=12)
        
        # Rotate x labels
        plt.xticks(rotation=45, ha='right')
        
        # Add criteria legend as caption
        criteria_legend = (
            "Success Criteria Definitions:\n"
            "• basic: Fields≥1, any output counts as success\n"
            "• lenient: Fields≥5, Required Completeness≥20%\n"
            "• moderate: Fields≥10, Required Completeness≥50%, F1≥0.3 (recommended)\n"
            "• strict: Fields≥15, Required Completeness≥70%, F1≥0.5, Confidence≥0.6\n"
            "• very_strict: Fields≥20, Required Completeness≥80%, F1≥0.6, Confidence≥0.7"
        )
        fig.text(0.5, -0.02, criteria_legend, ha='center', fontsize=9, 
                wrap=True, color='#333333', family='monospace',
                bbox=dict(boxstyle='round', facecolor='#f8f9fa', edgecolor='#dee2e6', alpha=0.9))
        
        plt.tight_layout(rect=[0, 0.12, 1, 1])
        plt.savefig(self.output_dir / f'{filename}.png', dpi=150, bbox_inches='tight')
        plt.savefig(self.output_dir / f'{filename}.pdf', bbox_inches='tight')
        plt.close()
        
        print(f"    ✅ Saved: {filename}.png, {filename}.pdf")
    
    def plot_success_rate_vs_pass_at_k(
        self,
        summary_df: pd.DataFrame,
        filename: str = 'success_rate_vs_pass_at_k'
    ):
        """
        Scatter plot showing relationship between success rate and pass@k values.
        
        Args:
            summary_df: DataFrame with model summary
            filename: Output filename
        """
        fig, axes = plt.subplots(1, 3, figsize=(15, 6))
        
        df = summary_df[summary_df['success_rate'] > 0].copy()
        
        k_values = [3, 5, 10]
        
        for ax, k in zip(axes, k_values):
            col = f'pass@{k}'
            if col not in df.columns:
                continue
            
            for _, row in df.iterrows():
                model = row['model']
                color = self._get_color(model)
                ax.scatter(row['success_rate'], row[col], 
                          c=color, s=150, alpha=0.7, edgecolors='white', linewidth=1.5)
                ax.annotate(self._get_display_name(model), 
                           (row['success_rate'], row[col]),
                           xytext=(5, 5), textcoords='offset points',
                           fontsize=8, alpha=0.8)
            
            # Add diagonal line (pass@k = success_rate when k=1)
            ax.plot([0, 1], [0, 1], 'k--', alpha=0.3, label='y = x (no improvement)')
            
            ax.set_xlabel('Success Rate (c/n)', fontsize=11)
            ax.set_ylabel(f'pass@{k}', fontsize=11)
            ax.set_title(f'Success Rate vs pass@{k}', fontsize=12, fontweight='bold')
            ax.set_xlim(-0.05, 1.05)
            ax.set_ylim(-0.05, 1.05)
            ax.grid(True, alpha=0.3)
            
            # Add shaded region showing improvement
            x_fill = np.linspace(0, 1, 100)
            ax.fill_between(x_fill, x_fill, 1, alpha=0.1, color='green', 
                           label='Improvement zone')
        
        plt.suptitle('How pass@k Improves Over Raw Success Rate (c/n)', 
                    fontsize=14, fontweight='bold', y=1.02)
        
        # Add caption
        caption = (
            "Success Rate = c/n (successful runs / total runs). "
            "Points above the diagonal line show improvement from multiple attempts.\n"
            "pass@k is always ≥ success_rate, with higher k giving larger improvement for unreliable models."
        )
        fig.text(0.5, -0.02, caption, ha='center', fontsize=9, style='italic', 
                wrap=True, color='#555555')
        
        plt.tight_layout(rect=[0, 0.05, 1, 1])
        plt.savefig(self.output_dir / f'{filename}.png', dpi=150, bbox_inches='tight')
        plt.savefig(self.output_dir / f'{filename}.pdf', bbox_inches='tight')
        plt.close()
        
        print(f"    ✅ Saved: {filename}.png, {filename}.pdf")
    
    def plot_document_level_pass_at_k(
        self,
        doc_df: pd.DataFrame,
        filename: str = 'pass_at_k_by_document'
    ):
        """
        Create grouped bar chart showing pass@k by document for each model.
        
        Args:
            doc_df: DataFrame with document-level pass@k
            filename: Output filename
        """
        if doc_df.empty:
            return
        
        # Filter to models with some success
        successful_models = doc_df.groupby('model')['c'].sum()
        successful_models = successful_models[successful_models > 0].index.tolist()
        df = doc_df[doc_df['model'].isin(successful_models)].copy()
        
        if df.empty:
            return
        
        documents = df['document_id'].unique()
        models = df['model'].unique()
        
        fig, ax = plt.subplots(figsize=(12, 8))
        
        x = np.arange(len(documents))
        width = 0.8 / len(models)
        
        for i, model in enumerate(models):
            model_data = df[df['model'] == model]
            values = []
            for doc in documents:
                doc_row = model_data[model_data['document_id'] == doc]
                if not doc_row.empty:
                    values.append(doc_row['pass@1'].values[0])
                else:
                    values.append(0)
            
            color = self._get_color(model)
            ax.bar(x + i * width, values, width, 
                  label=self._get_display_name(model), color=color, alpha=0.8)
        
        ax.set_xlabel('Document (Test Input)', fontsize=12)
        ax.set_ylabel('pass@1 (Single-Attempt Success Probability)', fontsize=12)
        ax.set_title('Pass@1 by Document and Model', fontsize=14, fontweight='bold')
        ax.set_xticks(x + width * (len(models) - 1) / 2)
        ax.set_xticklabels(documents, rotation=45, ha='right')
        ax.legend(loc='upper right', fontsize=9, title='Model')
        ax.set_ylim(0, 1.15)
        ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.3)
        
        # Add caption
        caption = (
            "pass@1 = success rate for single attempt. "
            "Different documents may have varying complexity affecting model performance.\n"
            "Success Criteria (moderate): Fields≥10, Required Completeness≥50%, F1≥0.3"
        )
        fig.text(0.5, 0.01, caption, ha='center', fontsize=9, style='italic', 
                wrap=True, color='#555555')
        
        plt.tight_layout(rect=[0, 0.06, 1, 1])
        plt.savefig(self.output_dir / f'{filename}.png', dpi=150, bbox_inches='tight')
        plt.savefig(self.output_dir / f'{filename}.pdf', bbox_inches='tight')
        plt.close()
        
        print(f"    ✅ Saved: {filename}.png, {filename}.pdf")
    
    def plot_k_effectiveness(
        self,
        summary_df: pd.DataFrame,
        filename: str = 'k_effectiveness'
    ):
        """
        Show how much pass rate improves from pass@1 to pass@k.
        
        Args:
            summary_df: DataFrame with model summary
            filename: Output filename
        """
        df = summary_df[summary_df['pass@1'] > 0].copy()
        df = df.sort_values('pass@1', ascending=False)
        
        fig, ax = plt.subplots(figsize=(12, 8))
        
        models = df['model'].tolist()
        x = np.arange(len(models))
        
        # Calculate improvements
        pass1 = df['pass@1'].values
        pass5 = df['pass@5'].values
        pass10 = df['pass@10'].values
        
        improvement_5 = pass5 - pass1
        improvement_10 = pass10 - pass1
        
        width = 0.35
        
        # Stacked bars: base pass@1 + improvement
        bars1 = ax.bar(x - width/2, pass1, width, label='pass@1 (base success rate)', 
                      color='#3498db', alpha=0.9)
        bars2 = ax.bar(x - width/2, improvement_5, width, bottom=pass1, 
                      label='+Δ with k=5 attempts', color='#27ae60', alpha=0.7)
        
        bars3 = ax.bar(x + width/2, pass1, width, color='#3498db', alpha=0.9)
        bars4 = ax.bar(x + width/2, improvement_10, width, bottom=pass1,
                      label='+Δ with k=10 attempts', color='#f39c12', alpha=0.7)
        
        ax.set_xlabel('Model', fontsize=12)
        ax.set_ylabel('pass@k (Probability of Success)', fontsize=12)
        ax.set_title('Pass Rate Improvement: Benefit of Multiple Attempts', 
                    fontsize=14, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels([self._get_display_name(m) for m in models], rotation=45, ha='right')
        ax.legend(loc='upper right', fontsize=10, title='Stacked Components')
        ax.set_ylim(0, 1.20)
        ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.3)
        
        # Add annotations showing improvement percentages
        for i, (m, p1, p5, p10) in enumerate(zip(models, pass1, pass5, pass10)):
            if p10 > p1:
                ax.annotate(f'+{(p10-p1)*100:.0f}pp', xy=(i + width/2, p10 + 0.02),
                           ha='center', fontsize=8, color='#d35400', fontweight='bold')
        
        # Add caption
        caption = (
            "Blue bars show base pass@1 (single-attempt success). "
            "Green/orange show additional probability gained with k=5/10 attempts.\n"
            "pp = percentage points improvement. "
            "Models with lower pass@1 benefit more from multiple attempts."
        )
        fig.text(0.5, 0.01, caption, ha='center', fontsize=9, style='italic', 
                wrap=True, color='#555555')
        
        plt.tight_layout(rect=[0, 0.06, 1, 1])
        plt.savefig(self.output_dir / f'{filename}.png', dpi=150, bbox_inches='tight')
        plt.savefig(self.output_dir / f'{filename}.pdf', bbox_inches='tight')
        plt.close()
        
        print(f"    ✅ Saved: {filename}.png, {filename}.pdf")
    
    @staticmethod
    def _calculate_pass_at_k(n: int, c: int, k: int) -> float:
        """Calculate pass@k."""
        import math
        if n == 0 or c == 0:
            return 0.0
        if k > n:
            k = n
        if c >= n:
            return 1.0
        
        log_ratio = 0.0
        for i in range(k):
            if n - c - i <= 0:
                return 1.0
            log_ratio += math.log(n - c - i) - math.log(n - i)
        
        return 1.0 - math.exp(log_ratio)
    
    def generate_all(
        self,
        summary_df: pd.DataFrame,
        doc_df: pd.DataFrame,
        comparison_df: pd.DataFrame
    ):
        """Generate all pass@k visualizations."""
        print("  📊 Pass@k Visualizations:")
        
        self.plot_pass_at_k_comparison(summary_df)
        self.plot_pass_at_k_curves(summary_df)
        self.plot_multi_criteria_heatmap(comparison_df)
        self.plot_success_rate_vs_pass_at_k(summary_df)
        self.plot_document_level_pass_at_k(doc_df)
        self.plot_k_effectiveness(summary_df)
