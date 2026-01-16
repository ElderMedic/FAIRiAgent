#!/usr/bin/env python3
"""
完整分析脚本 - 从 eval_result.json 生成丰富的分析结果
包括：模型排名、热图、文档比较、运行时间、相关性分析等
"""

import json
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evaluation.analysis.config import (
    EXCLUDED_MODELS,
    EXCLUDED_DOCUMENTS,
    EXCLUDED_DIRECTORIES,
    MODEL_DISPLAY_NAMES,
    MODEL_COLORS,
)

# 全局时间戳
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# 设置绘图风格
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
    'axes.spines.top': False,
    'axes.spines.right': False,
    'axes.grid': True,
    'grid.alpha': 0.3,
    'grid.linewidth': 0.5
})


def load_all_runs(runs_dir: Path):
    """加载所有运行数据"""
    runs = []
    
    for model_dir in runs_dir.iterdir():
        if not model_dir.is_dir() or model_dir.name in EXCLUDED_DIRECTORIES:
            continue
        
        model = model_dir.name
        if model in EXCLUDED_MODELS:
            continue
        
        for doc_dir in model_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            
            doc_id = doc_dir.name
            if doc_id in EXCLUDED_DOCUMENTS:
                continue
            
            for run_dir in doc_dir.glob('run_*'):
                if not run_dir.is_dir():
                    continue
                
                eval_file = run_dir / 'eval_result.json'
                if not eval_file.exists():
                    continue
                
                try:
                    with open(eval_file, 'r') as f:
                        data = json.load(f)
                    
                    completeness = data.get('completeness', {})
                    correctness = data.get('correctness', {})
                    internal = data.get('internal_metrics', {})
                    
                    runs.append({
                        'model': model,
                        'model_display': MODEL_DISPLAY_NAMES.get(model, model),
                        'document_id': doc_id,
                        'run_idx': data.get('run_idx', 0),
                        'success': data.get('success', False),
                        'runtime_seconds': data.get('runtime_seconds', 0),
                        'n_fields_extracted': completeness.get('total_extracted_fields', 0),
                        
                        # Completeness
                        'completeness': completeness.get('overall_completeness', 0.0),
                        'required_completeness': completeness.get('required_completeness', 0.0),
                        'recommended_completeness': completeness.get('recommended_completeness', 0.0),
                        'covered_fields': completeness.get('covered_fields', 0),
                        'total_gt_fields': completeness.get('total_ground_truth_fields', 0),
                        
                        # Correctness (original)
                        'f1_score': correctness.get('f1_score', 0.0),
                        'precision': correctness.get('precision', 0.0),
                        'recall': correctness.get('recall', 0.0),
                        
                        # Correctness (confidence-aware)
                        'high_conf_excess': correctness.get('high_conf_excess', 0),
                        'low_conf_excess': correctness.get('low_conf_excess', 0),
                        'adjusted_precision': correctness.get('adjusted_precision', 0.0),
                        'adjusted_f1': correctness.get('adjusted_f1', 0.0),
                        'discovery_bonus': correctness.get('discovery_bonus', 0.0),
                        
                        # Internal
                        'overall_confidence': internal.get('overall_confidence', 0.0),
                        'critic_confidence': internal.get('critic_confidence', 0.0),
                        'structural_confidence': internal.get('structural_confidence', 0.0),
                        'validation_confidence': internal.get('validation_confidence', 0.0),
                        
                        # Agent execution stats (from workflow_report.json)
                        'total_agent_attempts': internal.get('total_agent_attempts', 0),
                        'total_retries': internal.get('total_retries', 0),
                        
                        # Critic trajectory stats (if available from llm_responses.json)
                        'n_critic_steps': len(internal.get('critic_trajectory', [])),
                        'n_revise_decisions': sum(1 for s in internal.get('critic_trajectory', []) if s.get('decision') == 'revise'),
                        'n_accept_decisions': sum(1 for s in internal.get('critic_trajectory', []) if s.get('decision') == 'accept'),
                    })
                except Exception as e:
                    print(f"  ⚠️  Failed to load {eval_file}: {e}")
    
    return pd.DataFrame(runs)


def generate_model_summary(df: pd.DataFrame):
    """生成模型摘要统计"""
    summary = df.groupby('model').agg({
        'completeness': ['mean', 'std', 'count'],
        'f1_score': ['mean', 'std'],
        'precision': ['mean', 'std'],
        'recall': ['mean', 'std'],
        'runtime_seconds': ['mean', 'std'],
        'n_fields_extracted': ['mean', 'std'],
        'overall_confidence': ['mean'],
        # NEW: Confidence-aware metrics
        'adjusted_f1': ['mean', 'std'],
        'adjusted_precision': ['mean', 'std'],
        'high_conf_excess': ['mean'],
        'low_conf_excess': ['mean'],
        'discovery_bonus': ['mean'],
    }).round(3)
    
    summary.columns = ['_'.join(col).strip() for col in summary.columns.values]
    
    # NEW: Adjusted aggregate score (uses adjusted_f1 instead of f1)
    summary['aggregate_score'] = (
        summary['completeness_mean'] * 0.4 +
        summary['adjusted_f1_mean'] * 0.4 +
        summary['overall_confidence_mean'] * 0.2
    ).round(3)
    
    # Also keep original score for comparison
    summary['original_score'] = (
        summary['completeness_mean'] * 0.4 +
        summary['f1_score_mean'] * 0.4 +
        summary['overall_confidence_mean'] * 0.2
    ).round(3)
    
    summary = summary.sort_values('aggregate_score', ascending=False)
    return summary


# ============================================================================
# 图表生成函数
# ============================================================================

def plot_model_rankings(summary: pd.DataFrame, output_dir: Path):
    """模型综合排名图"""
    fig, axes = plt.subplots(1, 3, figsize=(16, 6))
    
    models = summary.index.tolist()
    display_names = [MODEL_DISPLAY_NAMES.get(m, m) for m in models]
    colors = [MODEL_COLORS.get(m, '#7f8c8d') for m in models]
    
    # Plot 1: Aggregate Score
    ax1 = axes[0]
    y_pos = np.arange(len(models))
    ax1.barh(y_pos, summary['aggregate_score'], color=colors, edgecolor='black', linewidth=0.8)
    ax1.set_yticks(y_pos)
    ax1.set_yticklabels(display_names, fontweight='bold')
    ax1.set_xlabel('Aggregate Score', fontweight='bold')
    ax1.set_title('Model Ranking (Aggregate)', fontweight='bold')
    ax1.invert_yaxis()
    for i, v in enumerate(summary['aggregate_score']):
        ax1.text(v + 0.01, i, f'{v:.3f}', va='center', fontsize=10)
    
    # Plot 2: Completeness
    ax2 = axes[1]
    ax2.barh(y_pos, summary['completeness_mean'], color=colors, edgecolor='black', linewidth=0.8)
    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(display_names, fontweight='bold')
    ax2.set_xlabel('Completeness', fontweight='bold')
    ax2.set_title('Field Coverage (Completeness)', fontweight='bold')
    ax2.invert_yaxis()
    for i, v in enumerate(summary['completeness_mean']):
        ax2.text(v + 0.01, i, f'{v:.3f}', va='center', fontsize=10)
    
    # Plot 3: F1 Score
    ax3 = axes[2]
    ax3.barh(y_pos, summary['f1_score_mean'], color=colors, edgecolor='black', linewidth=0.8)
    ax3.set_yticks(y_pos)
    ax3.set_yticklabels(display_names, fontweight='bold')
    ax3.set_xlabel('F1 Score', fontweight='bold')
    ax3.set_title('Correctness (F1 Score)', fontweight='bold')
    ax3.invert_yaxis()
    for i, v in enumerate(summary['f1_score_mean']):
        ax3.text(v + 0.01, i, f'{v:.3f}', va='center', fontsize=10)
    
    plt.tight_layout()
    filename = f'model_rankings_{TIMESTAMP}.png'
    plt.savefig(output_dir / filename, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  ✅ Saved {filename}")


def plot_model_comparison_heatmap(df: pd.DataFrame, output_dir: Path):
    """模型指标热图"""
    metrics = ['completeness', 'f1_score', 'precision', 'recall', 'overall_confidence']
    
    model_data = df.groupby('model')[metrics].mean()
    model_data.index = [MODEL_DISPLAY_NAMES.get(m, m) for m in model_data.index]
    
    fig, ax = plt.subplots(figsize=(10, 8))
    
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
        annot_kws={'size': 11, 'fontweight': 'bold'}
    )
    
    ax.set_title('Model Performance Comparison Across Metrics', fontsize=14, fontweight='bold', pad=20)
    ax.set_xlabel('Model', fontsize=12, fontweight='bold')
    ax.set_ylabel('Metric', fontsize=12, fontweight='bold')
    
    metric_labels = ['Completeness', 'F1 Score', 'Precision', 'Recall', 'Confidence']
    ax.set_yticklabels(metric_labels, rotation=0)
    
    plt.tight_layout()
    filename = f'model_comparison_heatmap_{TIMESTAMP}.png'
    plt.savefig(output_dir / filename, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  ✅ Saved {filename}")


def plot_document_comparison(df: pd.DataFrame, output_dir: Path):
    """文档级别比较"""
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    
    doc_stats = df.groupby(['model', 'document_id']).agg({
        'n_fields_extracted': 'mean',
        'completeness': 'mean',
        'f1_score': 'mean',
    }).reset_index()
    
    documents = sorted(df['document_id'].unique())
    models = sorted(df['model'].unique(), key=lambda m: MODEL_DISPLAY_NAMES.get(m, m))
    x = np.arange(len(models))
    width = 0.35
    
    display_names = [MODEL_DISPLAY_NAMES.get(m, m) for m in models]
    
    # Plot 1: Completeness by Document
    ax1 = axes[0]
    for i, doc in enumerate(documents):
        doc_data = doc_stats[doc_stats['document_id'] == doc]
        values = [doc_data[doc_data['model'] == m]['completeness'].values[0] 
                  if len(doc_data[doc_data['model'] == m]) > 0 else 0 
                  for m in models]
        ax1.bar(x + i*width, values, width, label=doc.title(), edgecolor='black', linewidth=0.8)
    
    ax1.set_xlabel('Model', fontweight='bold')
    ax1.set_ylabel('Completeness', fontweight='bold')
    ax1.set_title('Completeness by Document', fontweight='bold')
    ax1.set_xticks(x + width/2)
    ax1.set_xticklabels(display_names, rotation=45, ha='right')
    ax1.legend(title='Document', loc='lower right')
    ax1.set_ylim(0, 1.1)
    
    # Plot 2: F1 Score by Document
    ax2 = axes[1]
    for i, doc in enumerate(documents):
        doc_data = doc_stats[doc_stats['document_id'] == doc]
        values = [doc_data[doc_data['model'] == m]['f1_score'].values[0] 
                  if len(doc_data[doc_data['model'] == m]) > 0 else 0 
                  for m in models]
        ax2.bar(x + i*width, values, width, label=doc.title(), edgecolor='black', linewidth=0.8)
    
    ax2.set_xlabel('Model', fontweight='bold')
    ax2.set_ylabel('F1 Score', fontweight='bold')
    ax2.set_title('F1 Score by Document', fontweight='bold')
    ax2.set_xticks(x + width/2)
    ax2.set_xticklabels(display_names, rotation=45, ha='right')
    ax2.legend(title='Document', loc='lower right')
    ax2.set_ylim(0, 1.1)
    
    plt.tight_layout()
    filename = f'document_comparison_{TIMESTAMP}.png'
    plt.savefig(output_dir / filename, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  ✅ Saved {filename}")


def plot_runtime_comparison(summary: pd.DataFrame, output_dir: Path):
    """运行时间比较"""
    fig, ax = plt.subplots(figsize=(12, 7))
    
    # Sort by runtime
    sorted_summary = summary.sort_values('runtime_seconds_mean')
    models = sorted_summary.index.tolist()
    display_names = [MODEL_DISPLAY_NAMES.get(m, m) for m in models]
    colors = [MODEL_COLORS.get(m, '#7f8c8d') for m in models]
    
    y_pos = np.arange(len(models))
    ax.barh(y_pos, sorted_summary['runtime_seconds_mean'], 
            xerr=sorted_summary['runtime_seconds_std'], 
            color=colors, capsize=4, edgecolor='black', linewidth=0.8)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(display_names, fontweight='bold')
    ax.set_xlabel('Runtime (seconds)', fontweight='bold')
    ax.set_title('Average Runtime by Model', fontsize=14, fontweight='bold')
    
    # Add value labels
    for i, (mean, std) in enumerate(zip(sorted_summary['runtime_seconds_mean'], sorted_summary['runtime_seconds_std'])):
        ax.text(mean + std + 10, i, f'{mean:.0f}s', va='center', fontsize=10, fontweight='bold')
    
    plt.tight_layout()
    filename = f'runtime_comparison_{TIMESTAMP}.png'
    plt.savefig(output_dir / filename, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  ✅ Saved {filename}")


def plot_metric_correlation(df: pd.DataFrame, output_dir: Path):
    """指标相关性热图"""
    metrics = ['completeness', 'f1_score', 'precision', 'recall', 
               'overall_confidence', 'n_fields_extracted', 'runtime_seconds']
    
    corr_matrix = df[metrics].corr()
    
    # Rename for display
    corr_matrix.index = ['Completeness', 'F1 Score', 'Precision', 'Recall', 
                         'Confidence', 'Fields Extracted', 'Runtime']
    corr_matrix.columns = corr_matrix.index
    
    fig, ax = plt.subplots(figsize=(10, 8))
    sns.heatmap(
        corr_matrix,
        annot=True,
        fmt='.2f',
        cmap='coolwarm',
        center=0,
        vmin=-1,
        vmax=1,
        square=True,
        ax=ax,
        linewidths=0.5,
        annot_kws={'size': 11, 'fontweight': 'bold'}
    )
    
    ax.set_title('Metric Correlations', fontsize=14, fontweight='bold')
    
    plt.tight_layout()
    filename = f'metric_correlation_{TIMESTAMP}.png'
    plt.savefig(output_dir / filename, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  ✅ Saved {filename}")


def plot_precision_recall_tradeoff(df: pd.DataFrame, output_dir: Path):
    """Precision-Recall 散点图"""
    fig, ax = plt.subplots(figsize=(10, 8))
    
    model_stats = df.groupby('model').agg({
        'precision': 'mean',
        'recall': 'mean',
        'f1_score': 'mean'
    }).reset_index()
    
    for _, row in model_stats.iterrows():
        model = row['model']
        display_name = MODEL_DISPLAY_NAMES.get(model, model)
        color = MODEL_COLORS.get(model, '#7f8c8d')
        
        ax.scatter(row['recall'], row['precision'], s=row['f1_score']*500, 
                   c=color, alpha=0.7, edgecolors='black', linewidth=1.5)
        ax.annotate(display_name, (row['recall'], row['precision']), 
                   textcoords="offset points", xytext=(5, 5), fontsize=10, fontweight='bold')
    
    ax.set_xlabel('Recall', fontsize=12, fontweight='bold')
    ax.set_ylabel('Precision', fontsize=12, fontweight='bold')
    ax.set_title('Precision-Recall Trade-off (bubble size = F1)', fontsize=14, fontweight='bold')
    ax.set_xlim(0, 1.1)
    ax.set_ylim(0, 1.1)
    
    # Add diagonal line for reference
    ax.plot([0, 1], [0, 1], '--', color='gray', alpha=0.5)
    
    plt.tight_layout()
    filename = f'precision_recall_tradeoff_{TIMESTAMP}.png'
    plt.savefig(output_dir / filename, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  ✅ Saved {filename}")


def plot_fields_vs_quality(df: pd.DataFrame, output_dir: Path):
    """字段数量 vs 质量分析"""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    model_stats = df.groupby('model').agg({
        'n_fields_extracted': 'mean',
        'precision': 'mean',
        'f1_score': 'mean'
    }).reset_index()
    
    # Plot 1: Fields vs Precision
    ax1 = axes[0]
    for _, row in model_stats.iterrows():
        model = row['model']
        display_name = MODEL_DISPLAY_NAMES.get(model, model)
        color = MODEL_COLORS.get(model, '#7f8c8d')
        ax1.scatter(row['n_fields_extracted'], row['precision'], s=150, 
                   c=color, alpha=0.8, edgecolors='black', linewidth=1.5)
        ax1.annotate(display_name, (row['n_fields_extracted'], row['precision']), 
                    textcoords="offset points", xytext=(5, 5), fontsize=9)
    
    ax1.set_xlabel('Average Fields Extracted', fontweight='bold')
    ax1.set_ylabel('Precision', fontweight='bold')
    ax1.set_title('Fields Extracted vs Precision', fontweight='bold')
    
    # Plot 2: Fields vs F1
    ax2 = axes[1]
    for _, row in model_stats.iterrows():
        model = row['model']
        display_name = MODEL_DISPLAY_NAMES.get(model, model)
        color = MODEL_COLORS.get(model, '#7f8c8d')
        ax2.scatter(row['n_fields_extracted'], row['f1_score'], s=150, 
                   c=color, alpha=0.8, edgecolors='black', linewidth=1.5)
        ax2.annotate(display_name, (row['n_fields_extracted'], row['f1_score']), 
                    textcoords="offset points", xytext=(5, 5), fontsize=9)
    
    ax2.set_xlabel('Average Fields Extracted', fontweight='bold')
    ax2.set_ylabel('F1 Score', fontweight='bold')
    ax2.set_title('Fields Extracted vs F1 Score', fontweight='bold')
    
    plt.tight_layout()
    filename = f'fields_vs_quality_{TIMESTAMP}.png'
    plt.savefig(output_dir / filename, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  ✅ Saved {filename}")


def plot_confidence_analysis(df: pd.DataFrame, output_dir: Path):
    """Confidence scores 分析"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))
    
    # 准备数据
    model_conf = df.groupby('model').agg({
        'overall_confidence': 'mean',
        'critic_confidence': 'mean',
        'structural_confidence': 'mean',
        'total_agent_attempts': 'mean',
        'total_retries': 'mean',
    }).reset_index()
    model_conf['model_display'] = model_conf['model'].map(lambda m: MODEL_DISPLAY_NAMES.get(m, m))
    model_conf = model_conf.sort_values('overall_confidence', ascending=True)
    
    # Plot 1: Confidence scores by model
    ax1 = axes[0, 0]
    x = np.arange(len(model_conf))
    width = 0.25
    ax1.barh(x - width, model_conf['overall_confidence'], width, label='Overall', color='#3498db')
    ax1.barh(x, model_conf['critic_confidence'], width, label='Critic', color='#e74c3c')
    ax1.barh(x + width, model_conf['structural_confidence'], width, label='Structural', color='#2ecc71')
    ax1.set_yticks(x)
    ax1.set_yticklabels(model_conf['model_display'], fontweight='bold')
    ax1.set_xlabel('Confidence Score', fontweight='bold')
    ax1.set_title('Confidence Scores by Model', fontweight='bold')
    ax1.legend(loc='lower right')
    ax1.set_xlim(0, 1.1)
    
    # Plot 2: Agent attempts and retries (from workflow_report.json)
    ax2 = axes[0, 1]
    x = np.arange(len(model_conf))
    width = 0.35
    ax2.bar(x - width/2, model_conf['total_agent_attempts'], width, label='Total Agent Attempts', color='#3498db')
    ax2.bar(x + width/2, model_conf['total_retries'], width, label='Retries', color='#e74c3c')
    ax2.set_xticks(x)
    ax2.set_xticklabels(model_conf['model_display'], rotation=45, ha='right')
    ax2.set_ylabel('Count', fontweight='bold')
    ax2.set_title('Agent Execution Activity', fontweight='bold')
    ax2.legend()
    
    # Plot 3: Confidence vs F1 scatter (Self-assessment calibration)
    ax3 = axes[1, 0]
    model_stats = df.groupby('model').agg({
        'overall_confidence': 'mean',
        'f1_score': 'mean'
    }).reset_index()
    for _, row in model_stats.iterrows():
        model = row['model']
        display_name = MODEL_DISPLAY_NAMES.get(model, model)
        color = MODEL_COLORS.get(model, '#7f8c8d')
        ax3.scatter(row['overall_confidence'], row['f1_score'], s=200, 
                   c=color, alpha=0.8, edgecolors='black', linewidth=1.5)
        ax3.annotate(display_name, (row['overall_confidence'], row['f1_score']), 
                    textcoords="offset points", xytext=(5, 5), fontsize=9)
    ax3.set_xlabel('Overall Confidence (Self-Assessment)', fontweight='bold')
    ax3.set_ylabel('F1 Score (Actual Quality)', fontweight='bold')
    ax3.set_title('Self-Assessment Calibration', fontweight='bold')
    ax3.set_xlim(0, 1.1)
    ax3.set_ylim(0, 1.1)
    # Add diagonal (perfect calibration line)
    ax3.plot([0, 1], [0, 1], '--', color='gray', alpha=0.5, label='Perfect calibration')
    ax3.legend(loc='lower right')
    
    # Plot 4: Critic confidence vs F1 (Critic quality assessment)
    ax4 = axes[1, 1]
    model_stats2 = df.groupby('model').agg({
        'critic_confidence': 'mean',
        'f1_score': 'mean',
        'total_retries': 'mean'
    }).reset_index()
    
    for _, row in model_stats2.iterrows():
        model = row['model']
        display_name = MODEL_DISPLAY_NAMES.get(model, model)
        color = MODEL_COLORS.get(model, '#7f8c8d')
        # Size based on retries
        size = 100 + row['total_retries'] * 50
        ax4.scatter(row['critic_confidence'], row['f1_score'], s=size, 
                   c=color, alpha=0.8, edgecolors='black', linewidth=1.5)
        ax4.annotate(display_name, (row['critic_confidence'], row['f1_score']), 
                    textcoords="offset points", xytext=(5, 5), fontsize=9)
    ax4.set_xlabel('Critic Confidence', fontweight='bold')
    ax4.set_ylabel('F1 Score', fontweight='bold')
    ax4.set_title('Critic Assessment vs Quality (size=retries)', fontweight='bold')
    ax4.set_xlim(0, 1.1)
    ax4.set_ylim(0, 1.1)
    ax4.plot([0, 1], [0, 1], '--', color='gray', alpha=0.5)
    
    plt.tight_layout()
    filename = f'confidence_analysis_{TIMESTAMP}.png'
    plt.savefig(output_dir / filename, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  ✅ Saved {filename}")


def plot_adjusted_vs_original(df: pd.DataFrame, output_dir: Path):
    """对比原始 vs 调整后的评估指标"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))
    
    # Model stats
    model_stats = df.groupby('model').agg({
        'f1_score': 'mean',
        'adjusted_f1': 'mean',
        'precision': 'mean',
        'adjusted_precision': 'mean',
        'high_conf_excess': 'mean',
        'low_conf_excess': 'mean',
        'discovery_bonus': 'mean',
    }).reset_index()
    model_stats['model_display'] = model_stats['model'].map(lambda m: MODEL_DISPLAY_NAMES.get(m, m))
    model_stats = model_stats.sort_values('adjusted_f1', ascending=True)
    
    # Plot 1: F1 vs Adjusted F1
    ax1 = axes[0, 0]
    x = np.arange(len(model_stats))
    width = 0.35
    ax1.barh(x - width/2, model_stats['f1_score'], width, label='Original F1', color='#e74c3c', alpha=0.7)
    ax1.barh(x + width/2, model_stats['adjusted_f1'], width, label='Adjusted F1', color='#27ae60', alpha=0.7)
    ax1.set_yticks(x)
    ax1.set_yticklabels(model_stats['model_display'], fontweight='bold')
    ax1.set_xlabel('F1 Score', fontweight='bold')
    ax1.set_title('Original vs Adjusted F1 Score', fontweight='bold')
    ax1.legend(loc='lower right')
    ax1.set_xlim(0, 1.1)
    
    # Add improvement annotation
    for i, (orig, adj) in enumerate(zip(model_stats['f1_score'], model_stats['adjusted_f1'])):
        diff = adj - orig
        if diff > 0:
            ax1.annotate(f'+{diff:.2f}', (adj + 0.02, i), fontsize=9, color='green', fontweight='bold')
    
    # Plot 2: Precision vs Adjusted Precision
    ax2 = axes[0, 1]
    ax2.barh(x - width/2, model_stats['precision'], width, label='Original Precision', color='#e74c3c', alpha=0.7)
    ax2.barh(x + width/2, model_stats['adjusted_precision'], width, label='Adjusted Precision', color='#27ae60', alpha=0.7)
    ax2.set_yticks(x)
    ax2.set_yticklabels(model_stats['model_display'], fontweight='bold')
    ax2.set_xlabel('Precision', fontweight='bold')
    ax2.set_title('Original vs Adjusted Precision', fontweight='bold')
    ax2.legend(loc='lower right')
    ax2.set_xlim(0, 1.1)
    
    # Plot 3: Excess Fields Breakdown
    ax3 = axes[1, 0]
    ax3.barh(x - width/2, model_stats['high_conf_excess'], width, label='High Conf Excess (≥0.8)', color='#27ae60')
    ax3.barh(x + width/2, model_stats['low_conf_excess'], width, label='Low Conf Excess (<0.8)', color='#e74c3c')
    ax3.set_yticks(x)
    ax3.set_yticklabels(model_stats['model_display'], fontweight='bold')
    ax3.set_xlabel('Number of Excess Fields', fontweight='bold')
    ax3.set_title('Excess Fields by Confidence Level', fontweight='bold')
    ax3.legend(loc='lower right')
    
    # Plot 4: Discovery Bonus
    ax4 = axes[1, 1]
    colors = [MODEL_COLORS.get(m, '#7f8c8d') for m in model_stats['model']]
    ax4.barh(x, model_stats['discovery_bonus'], color=colors, edgecolor='black', linewidth=0.8)
    ax4.set_yticks(x)
    ax4.set_yticklabels(model_stats['model_display'], fontweight='bold')
    ax4.set_xlabel('Discovery Bonus (high_conf_excess / GT_fields)', fontweight='bold')
    ax4.set_title('Potential Discovery Score', fontweight='bold')
    
    # Add values
    for i, v in enumerate(model_stats['discovery_bonus']):
        ax4.text(v + 0.01, i, f'{v:.2f}', va='center', fontsize=10)
    
    plt.tight_layout()
    filename = f'adjusted_vs_original_{TIMESTAMP}.png'
    plt.savefig(output_dir / filename, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  ✅ Saved {filename}")


def plot_boxplot_comparison(df: pd.DataFrame, output_dir: Path):
    """箱线图比较各模型指标分布"""
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    
    # Prepare data with display names
    df_plot = df.copy()
    df_plot['model_display'] = df_plot['model'].map(lambda m: MODEL_DISPLAY_NAMES.get(m, m))
    
    # Sort by aggregate score
    model_order = df_plot.groupby('model_display')['f1_score'].mean().sort_values(ascending=False).index.tolist()
    
    # Completeness
    ax1 = axes[0, 0]
    sns.boxplot(data=df_plot, x='model_display', y='completeness', order=model_order, ax=ax1, palette='Set2')
    ax1.set_xlabel('')
    ax1.set_ylabel('Completeness', fontweight='bold')
    ax1.set_title('Completeness Distribution', fontweight='bold')
    ax1.tick_params(axis='x', rotation=45)
    
    # F1 Score
    ax2 = axes[0, 1]
    sns.boxplot(data=df_plot, x='model_display', y='f1_score', order=model_order, ax=ax2, palette='Set2')
    ax2.set_xlabel('')
    ax2.set_ylabel('F1 Score', fontweight='bold')
    ax2.set_title('F1 Score Distribution', fontweight='bold')
    ax2.tick_params(axis='x', rotation=45)
    
    # Precision
    ax3 = axes[1, 0]
    sns.boxplot(data=df_plot, x='model_display', y='precision', order=model_order, ax=ax3, palette='Set2')
    ax3.set_xlabel('Model', fontweight='bold')
    ax3.set_ylabel('Precision', fontweight='bold')
    ax3.set_title('Precision Distribution', fontweight='bold')
    ax3.tick_params(axis='x', rotation=45)
    
    # Runtime
    ax4 = axes[1, 1]
    sns.boxplot(data=df_plot, x='model_display', y='runtime_seconds', order=model_order, ax=ax4, palette='Set2')
    ax4.set_xlabel('Model', fontweight='bold')
    ax4.set_ylabel('Runtime (seconds)', fontweight='bold')
    ax4.set_title('Runtime Distribution', fontweight='bold')
    ax4.tick_params(axis='x', rotation=45)
    
    plt.tight_layout()
    filename = f'boxplot_comparison_{TIMESTAMP}.png'
    plt.savefig(output_dir / filename, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  ✅ Saved {filename}")


def save_summary_table(summary: pd.DataFrame, output_dir: Path):
    """保存摘要表格"""
    display_df = summary.copy()
    display_df.index = [MODEL_DISPLAY_NAMES.get(m, m) for m in display_df.index]
    
    # Full table with all metrics
    full_cols = ['aggregate_score', 'original_score', 'completeness_mean', 
                 'f1_score_mean', 'adjusted_f1_mean', 'precision_mean', 'adjusted_precision_mean',
                 'recall_mean', 'high_conf_excess_mean', 'low_conf_excess_mean',
                 'discovery_bonus_mean', 'runtime_seconds_mean', 
                 'n_fields_extracted_mean', 'completeness_count']
    
    full_df = display_df[[c for c in full_cols if c in display_df.columns]]
    full_df.columns = ['Adj_Score', 'Orig_Score', 'Complete', 
                       'F1', 'Adj_F1', 'Prec', 'Adj_Prec',
                       'Recall', 'Hi_Excess', 'Lo_Excess',
                       'Discovery', 'Runtime', 'Fields', 'N_Runs']
    
    filename = f'model_rankings_{TIMESTAMP}.csv'
    full_df.to_csv(output_dir / filename)
    print(f"  ✅ Saved {filename}")
    
    print("\n" + "=" * 80)
    print("📊 Model Rankings (with Adjusted Metrics)")
    print("=" * 80)
    print(full_df.to_string())
    
    return full_df


def save_analysis_summary(df: pd.DataFrame, summary: pd.DataFrame, output_dir: Path):
    """保存分析摘要JSON"""
    summary_dict = {
        'generated_at': pd.Timestamp.now().isoformat(),
        'timestamp': TIMESTAMP,
        'n_runs': len(df),
        'n_models': len(df['model'].unique()),
        'n_documents': len(df['document_id'].unique()),
        'runs_per_model': int(len(df) / len(df['model'].unique())),
        'models': df['model'].unique().tolist(),
        'documents': df['document_id'].unique().tolist(),
        'model_rankings': {
            model: {
                'rank': i + 1,
                'display_name': MODEL_DISPLAY_NAMES.get(model, model),
                'aggregate_score': float(summary.loc[model, 'aggregate_score']),
                'completeness': float(summary.loc[model, 'completeness_mean']),
                'f1_score': float(summary.loc[model, 'f1_score_mean']),
                'precision': float(summary.loc[model, 'precision_mean']),
                'recall': float(summary.loc[model, 'recall_mean']),
                'runtime_seconds': float(summary.loc[model, 'runtime_seconds_mean']),
                'n_fields_extracted': float(summary.loc[model, 'n_fields_extracted_mean']),
                'n_runs': int(summary.loc[model, 'completeness_count']),
            }
            for i, model in enumerate(summary.index)
        }
    }
    
    filename = f'analysis_summary_{TIMESTAMP}.json'
    with open(output_dir / filename, 'w') as f:
        json.dump(summary_dict, f, indent=2)
    print(f"  ✅ Saved {filename}")


def save_all_runs_data(df: pd.DataFrame, output_dir: Path):
    """保存完整运行数据"""
    filename = f'all_runs_data_{TIMESTAMP}.csv'
    df.to_csv(output_dir / filename, index=False)
    print(f"  ✅ Saved {filename}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Complete analysis of evaluation results')
    parser.add_argument('--runs-dir', type=Path, default=Path('evaluation/runs'))
    parser.add_argument('--output-dir', type=Path, default=Path('evaluation/analysis/output'))
    
    args = parser.parse_args()
    
    print("=" * 80)
    print(f"📊 FAIRiAgent Complete Analysis ({TIMESTAMP})")
    print("=" * 80)
    
    # Load data
    print("\n📂 Loading runs data...")
    df = load_all_runs(args.runs_dir)
    print(f"  ✅ Loaded {len(df)} runs from {len(df['model'].unique())} models")
    print(f"  📄 Documents: {', '.join(df['document_id'].unique())}")
    
    # Generate summary
    print("\n📈 Generating model summary...")
    summary = generate_model_summary(df)
    
    # Create output directories
    args.output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = args.output_dir / 'figures'
    figures_dir.mkdir(exist_ok=True)
    tables_dir = args.output_dir / 'tables'
    tables_dir.mkdir(exist_ok=True)
    
    # Generate all visualizations
    print("\n🎨 Generating visualizations...")
    plot_model_rankings(summary, figures_dir)
    plot_model_comparison_heatmap(df, figures_dir)
    plot_document_comparison(df, figures_dir)
    plot_runtime_comparison(summary, figures_dir)
    plot_metric_correlation(df, figures_dir)
    plot_precision_recall_tradeoff(df, figures_dir)
    plot_fields_vs_quality(df, figures_dir)
    plot_confidence_analysis(df, figures_dir)
    plot_adjusted_vs_original(df, figures_dir)  # NEW
    plot_boxplot_comparison(df, figures_dir)
    
    # Save tables
    print("\n📋 Saving tables...")
    save_summary_table(summary, tables_dir)
    save_all_runs_data(df, tables_dir)
    save_analysis_summary(df, summary, args.output_dir)
    
    # Print summary
    print("\n" + "=" * 80)
    print("✅ Analysis Complete!")
    print("=" * 80)
    print(f"📁 Output directory: {args.output_dir}")
    print(f"📊 Total runs analyzed: {len(df)}")
    print(f"🤖 Models: {len(df['model'].unique())}")
    print(f"📄 Documents: {len(df['document_id'].unique())}")
    print(f"\n📈 Generated {10} figures and {3} data files")


if __name__ == "__main__":
    main()
