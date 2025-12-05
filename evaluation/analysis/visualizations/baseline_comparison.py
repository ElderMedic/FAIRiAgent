"""
Baseline Comparison Visualizations

Generates visualizations comparing baseline vs agentic workflow.
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
from pathlib import Path
from typing import Dict, Any

from ..config import get_model_display_name, get_model_color


class BaselineComparisonVisualizer:
    """Generate baseline vs agentic comparison visualizations."""
    
    def __init__(self, output_dir: Path):
        """
        Initialize visualizer.
        
        Args:
            output_dir: Output directory for figures
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def create_comparison_by_document(
        self,
        agentic_data: Dict[str, Dict[str, Any]],
        baseline_data: Dict[str, Dict[str, Any]]
    ):
        """Create comparison charts by document."""
        # Get all documents
        all_docs = set()
        for model_name, data in agentic_data.items():
            all_docs.update(data['by_document'].keys())
        if baseline_data:
            for model_name, data in baseline_data.items():
                all_docs.update(data['by_document'].keys())
        all_docs = sorted(all_docs)
        
        n_docs = len(all_docs)
        if n_docs == 0:
            return
        
        fig, axes = plt.subplots(n_docs, 3, figsize=(16, 5*n_docs))
        if n_docs == 1:
            axes = [axes]
        
        fig.suptitle('Agentic Workflow vs Single-Prompt Baseline (by Document)', 
                     fontsize=14, fontweight='bold')
        
        # Select representative models
        model_keys = ['gpt4.1', 'gpt5', 'o3', 'sonnet', 'haiku', 'qwen_max', 'qwen_plus']
        
        for doc_idx, doc_id in enumerate(all_docs):
            ax_row = axes[doc_idx]
            
            agentic_fields = []
            agentic_runtimes = []
            agentic_critics = []
            colors = []
            display_names = []
            
            for key in model_keys:
                if key in agentic_data and doc_id in agentic_data[key]['by_document']:
                    doc_data = agentic_data[key]['by_document'][doc_id]
                    if doc_data['n_fields']:
                        agentic_fields.append(np.mean(doc_data['n_fields']))
                        agentic_runtimes.append(np.mean(doc_data['runtimes']))
                        colors.append(get_model_color(key))
                        display_names.append(get_model_display_name(key))
                        if doc_data['critic_scores']:
                            agentic_critics.append(np.mean(doc_data['critic_scores']))
                        else:
                            agentic_critics.append(0)
                        continue
                # Model doesn't have data for this doc
                agentic_fields.append(0)
                agentic_runtimes.append(0)
                agentic_critics.append(0)
                colors.append('#cccccc')
                display_names.append(get_model_display_name(key))
            
            # Baseline data for this document
            baseline_fields = 0
            baseline_runtime = 0
            if baseline_data:
                baseline_key = list(baseline_data.keys())[0]
                if doc_id in baseline_data[baseline_key]['by_document']:
                    doc_data = baseline_data[baseline_key]['by_document'][doc_id]
                    if doc_data['n_fields']:
                        baseline_fields = np.mean(doc_data['n_fields'])
                        baseline_runtime = np.mean(doc_data['runtimes'])
            
            x = np.arange(len(display_names))
            width = 0.7
            
            # Plot 1: Fields Extracted
            ax1 = ax_row[0]
            bars1 = ax1.bar(x, agentic_fields, width, color=colors, edgecolor='white', linewidth=1)
            ax1.axhline(y=baseline_fields, color='#95a5a6', linestyle='--', linewidth=2.5, 
                        label=f'Baseline ({baseline_fields:.0f})')
            ax1.set_ylabel('Avg Fields', fontsize=10)
            ax1.set_title(f'{doc_id}: Fields Extracted', fontsize=11, fontweight='bold')
            ax1.set_xticks(x)
            ax1.set_xticklabels(display_names, rotation=45, ha='right', fontsize=8)
            ax1.legend(loc='upper right', fontsize=8)
            ax1.grid(axis='y', alpha=0.3)
            
            # Plot 2: Runtime
            ax2 = ax_row[1]
            bars2 = ax2.bar(x, agentic_runtimes, width, color=colors, edgecolor='white', linewidth=1)
            ax2.axhline(y=baseline_runtime, color='#95a5a6', linestyle='--', linewidth=2.5, 
                        label=f'Baseline ({baseline_runtime:.0f}s)')
            ax2.set_ylabel('Runtime (s)', fontsize=10)
            ax2.set_title(f'{doc_id}: Runtime', fontsize=11, fontweight='bold')
            ax2.set_xticks(x)
            ax2.set_xticklabels(display_names, rotation=45, ha='right', fontsize=8)
            ax2.legend(loc='upper right', fontsize=8)
            ax2.grid(axis='y', alpha=0.3)
            
            # Plot 3: LLM Judge Score
            ax3 = ax_row[2]
            bars3 = ax3.bar(x, agentic_critics, width, color=colors, edgecolor='white', linewidth=1)
            ax3.axhline(y=0.7, color='green', linestyle='--', linewidth=1.5, alpha=0.5, label='High')
            ax3.axhline(y=0.5, color='orange', linestyle='--', linewidth=1.5, alpha=0.5, label='Medium')
            ax3.set_ylabel('LLM Judge', fontsize=10)
            ax3.set_title(f'{doc_id}: LLM Judge Score', fontsize=11, fontweight='bold')
            ax3.set_xticks(x)
            ax3.set_xticklabels(display_names, rotation=45, ha='right', fontsize=8)
            ax3.legend(loc='upper right', fontsize=8)
            ax3.grid(axis='y', alpha=0.3)
            ax3.set_ylim(0, 1)
        
        # Add legend for model families
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#2ecc71', label='OpenAI'),
            Patch(facecolor='#e74c3c', label='Anthropic'),
            Patch(facecolor='#3498db', label='Qwen'),
            Patch(facecolor='#95a5a6', label='Baseline'),
        ]
        fig.legend(handles=legend_elements, loc='upper center', ncol=4, bbox_to_anchor=(0.5, 0.01))
        
        plt.tight_layout(rect=[0, 0.03, 1, 0.97])
        plt.savefig(self.output_dir / 'baseline_vs_agentic_by_document.png', 
                   dpi=150, bbox_inches='tight')
        plt.close()
        print("  ✅ Saved: baseline_vs_agentic_by_document.png")
    
    def create_overall_comparison(
        self,
        agentic_data: Dict[str, Dict[str, Any]],
        baseline_data: Dict[str, Dict[str, Any]]
    ):
        """Create overall comparison chart (all documents combined)."""
        fig, axes = plt.subplots(1, 3, figsize=(16, 6))
        fig.suptitle('Agentic Workflow vs Single-Prompt Baseline (Overall)', 
                     fontsize=14, fontweight='bold')
        
        model_keys = ['gpt4.1', 'gpt5', 'o3', 'sonnet', 'haiku', 'qwen_max', 'qwen_plus']
        
        agentic_fields = []
        agentic_runtimes = []
        agentic_critics = []
        colors = []
        display_names = []
        n_runs_list = []
        
        for key in model_keys:
            if key in agentic_data and agentic_data[key]['n_fields']:
                agentic_fields.append(np.mean(agentic_data[key]['n_fields']))
                agentic_runtimes.append(np.mean(agentic_data[key]['runtimes']))
                colors.append(get_model_color(key))
                display_names.append(get_model_display_name(key))
                n_runs_list.append(len(agentic_data[key]['n_fields']))
                if agentic_data[key]['critic_scores']:
                    agentic_critics.append(np.mean(agentic_data[key]['critic_scores']))
                else:
                    agentic_critics.append(0)
            else:
                agentic_fields.append(0)
                agentic_runtimes.append(0)
                agentic_critics.append(0)
                colors.append('#cccccc')
                display_names.append(get_model_display_name(key))
                n_runs_list.append(0)
        
        # Baseline data
        baseline_fields = 0
        baseline_runtime = 0
        baseline_n = 0
        if baseline_data:
            baseline_key = list(baseline_data.keys())[0]
            if baseline_data[baseline_key]['n_fields']:
                baseline_fields = np.mean(baseline_data[baseline_key]['n_fields'])
                baseline_runtime = np.mean(baseline_data[baseline_key]['runtimes'])
                baseline_n = len(baseline_data[baseline_key]['n_fields'])
        
        x = np.arange(len(display_names))
        width = 0.7
        
        # Plot 1: Fields Extracted
        ax1 = axes[0]
        bars1 = ax1.bar(x, agentic_fields, width, color=colors, edgecolor='white', linewidth=1)
        ax1.axhline(y=baseline_fields, color='#95a5a6', linestyle='--', linewidth=2.5, 
                    label=f'Baseline ({baseline_fields:.0f}, n={baseline_n})')
        ax1.set_ylabel('Avg Fields Extracted', fontsize=11)
        ax1.set_title('Fields Extracted', fontsize=12, fontweight='bold')
        ax1.set_xticks(x)
        ax1.set_xticklabels(display_names, rotation=45, ha='right', fontsize=9)
        ax1.legend(loc='upper right')
        ax1.grid(axis='y', alpha=0.3)
        # Add value labels
        for bar, field, n in zip(bars1, agentic_fields, n_runs_list):
            if field > 0:
                ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, 
                        f'{field:.0f}\n(n={n})', ha='center', va='bottom', fontsize=7)
        
        # Plot 2: Runtime
        ax2 = axes[1]
        bars2 = ax2.bar(x, agentic_runtimes, width, color=colors, edgecolor='white', linewidth=1)
        ax2.axhline(y=baseline_runtime, color='#95a5a6', linestyle='--', linewidth=2.5, 
                    label=f'Baseline ({baseline_runtime:.0f}s)')
        ax2.set_ylabel('Avg Runtime (seconds)', fontsize=11)
        ax2.set_title('Runtime', fontsize=12, fontweight='bold')
        ax2.set_xticks(x)
        ax2.set_xticklabels(display_names, rotation=45, ha='right', fontsize=9)
        ax2.legend(loc='upper right')
        ax2.grid(axis='y', alpha=0.3)
        
        # Plot 3: LLM Judge Score
        ax3 = axes[2]
        bars3 = ax3.bar(x, agentic_critics, width, color=colors, edgecolor='white', linewidth=1)
        ax3.axhline(y=0.7, color='green', linestyle='--', linewidth=1.5, alpha=0.5, label='High quality')
        ax3.axhline(y=0.5, color='orange', linestyle='--', linewidth=1.5, alpha=0.5, label='Medium quality')
        ax3.set_ylabel('Avg LLM Judge Score', fontsize=11)
        ax3.set_title('LLM Judge Score (Agentic Only)', fontsize=12, fontweight='bold')
        ax3.set_xticks(x)
        ax3.set_xticklabels(display_names, rotation=45, ha='right', fontsize=9)
        ax3.legend(loc='upper right')
        ax3.grid(axis='y', alpha=0.3)
        ax3.set_ylim(0, 1)
        
        # Add legend for model families
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#2ecc71', label='OpenAI'),
            Patch(facecolor='#e74c3c', label='Anthropic'),
            Patch(facecolor='#3498db', label='Qwen'),
            Patch(facecolor='#95a5a6', label='Baseline'),
        ]
        fig.legend(handles=legend_elements, loc='upper center', ncol=4, bbox_to_anchor=(0.5, 0.02))
        
        plt.tight_layout(rect=[0, 0.05, 1, 0.95])
        plt.savefig(self.output_dir / 'baseline_vs_agentic_comparison.png', 
                   dpi=150, bbox_inches='tight')
        plt.close()
        print("  ✅ Saved: baseline_vs_agentic_comparison.png")
    
    def create_fields_by_document(
        self,
        agentic_data: Dict[str, Dict[str, Any]],
        baseline_data: Dict[str, Dict[str, Any]]
    ):
        """Create fields extracted comparison by document."""
        # Get all documents
        all_docs = set()
        for model_name, data in agentic_data.items():
            all_docs.update(data['by_document'].keys())
        if baseline_data:
            for model_name, data in baseline_data.items():
                all_docs.update(data['by_document'].keys())
        
        all_docs = sorted(all_docs)
        n_docs = len(all_docs)
        
        if n_docs == 0:
            return
        
        # Create subplots for each document
        fig, axes = plt.subplots(1, n_docs, figsize=(7*n_docs, 7))
        if n_docs == 1:
            axes = [axes]
        
        fig.suptitle('Fields Extracted by Document: Baseline vs Agentic Workflow', 
                     fontsize=14, fontweight='bold')
        
        for idx, doc_id in enumerate(all_docs):
            ax = axes[idx]
            model_data = []
            
            # Baseline first
            if baseline_data:
                baseline_key = list(baseline_data.keys())[0]
                data = baseline_data[baseline_key]
                if doc_id in data['by_document'] and data['by_document'][doc_id]['n_fields']:
                    doc_fields = data['by_document'][doc_id]['n_fields']
                    model_data.append({
                        'name': baseline_key,
                        'display_name': 'Baseline\n(GPT-4o)',
                        'fields': np.mean(doc_fields),
                        'std': np.std(doc_fields),
                        'n_runs': len(doc_fields),
                        'color': '#95a5a6',
                        'is_baseline': True
                    })
            
            # Agentic models sorted by fields for this document
            agentic_list = []
            for model_name, data in agentic_data.items():
                if doc_id in data['by_document'] and data['by_document'][doc_id]['n_fields']:
                    doc_fields = data['by_document'][doc_id]['n_fields']
                    agentic_list.append({
                        'name': model_name,
                        'display_name': get_model_display_name(model_name),
                        'fields': np.mean(doc_fields),
                        'std': np.std(doc_fields),
                        'n_runs': len(doc_fields),
                        'color': get_model_color(model_name),
                        'is_baseline': False
                    })
            
            # Sort by fields
            agentic_list.sort(key=lambda x: x['fields'], reverse=True)
            model_data.extend(agentic_list)
            
            if not model_data:
                continue
            
            display_names = [m['display_name'] for m in model_data]
            fields = [m['fields'] for m in model_data]
            stds = [m['std'] for m in model_data]
            colors = [m['color'] for m in model_data]
            n_runs = [m['n_runs'] for m in model_data]
            
            # Plot
            x = np.arange(len(display_names))
            bars = ax.bar(x, fields, yerr=stds, capsize=4, color=colors, 
                          edgecolor='white', linewidth=1, alpha=0.9)
            
            ax.set_ylabel('Avg Fields Extracted', fontsize=10)
            ax.set_title(f'Document: {doc_id}', fontsize=12, fontweight='bold')
            ax.set_xticks(x)
            ax.set_xticklabels(display_names, rotation=45, ha='right', fontsize=9)
            ax.grid(axis='y', alpha=0.3)
            
            # Add value labels with n_runs
            for bar, field, std, n in zip(bars, fields, stds, n_runs):
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + std + 2, 
                        f'{field:.0f}\n(n={n})', ha='center', va='bottom', fontsize=8)
            
            # Add improvement annotation
            if model_data and model_data[0].get('is_baseline') and len(model_data) > 1:
                baseline_avg = model_data[0]['fields']
                best_agentic = max([m['fields'] for m in model_data[1:]]) if len(model_data) > 1 else 0
                improvement = ((best_agentic - baseline_avg) / baseline_avg * 100) if baseline_avg > 0 else 0
                if improvement > 0:
                    ax.annotate(f'+{improvement:.0f}%', 
                               xy=(1, best_agentic), 
                               xytext=(2, best_agentic + 15),
                               arrowprops=dict(arrowstyle='->', color='#27ae60', lw=1.5),
                               fontsize=10, color='#27ae60', fontweight='bold')
        
        # Add legend for model families
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#95a5a6', label='Baseline (GPT-4o)'),
            Patch(facecolor='#2ecc71', label='OpenAI'),
            Patch(facecolor='#e74c3c', label='Anthropic'),
            Patch(facecolor='#3498db', label='Qwen'),
        ]
        fig.legend(handles=legend_elements, loc='upper center', ncol=4, 
                   bbox_to_anchor=(0.5, 0.02), fontsize=10)
        
        plt.tight_layout(rect=[0, 0.05, 1, 0.95])
        plt.savefig(self.output_dir / 'fields_extracted_by_document.png', 
                   dpi=150, bbox_inches='tight')
        plt.close()
        print("  ✅ Saved: fields_extracted_by_document.png")

