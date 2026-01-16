#!/usr/bin/env python3
"""
Visualizations for Biological Insights Analysis

Creates publication-ready figures for:
1. Consensus heatmaps (field x document)
2. Model bias radar charts
3. Stability comparisons across models
4. Emergent patterns analysis
5. Field importance hierarchies
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)

# Style settings
plt.style.use('seaborn-v0_8-whitegrid')
COLORS = {
    'high': '#2ecc71',      # Green
    'medium': '#f39c12',    # Orange
    'low': '#e74c3c',       # Red
    'biological': '#3498db',
    'technical_sequencing': '#9b59b6',
    'sample_collection': '#1abc9c',
    'experimental_design': '#e67e22',
    'administrative': '#95a5a6',
    'other': '#7f8c8d'
}


def plot_consensus_heatmap(consensus_data: Dict[str, List[Dict]], 
                          output_path: Path,
                          top_n: int = 30) -> None:
    """
    Create heatmap showing consensus scores across documents and fields.
    
    High consensus = biological signal strength
    """
    # Collect all unique fields across documents
    all_fields = set()
    for doc, fields in consensus_data.items():
        for f in fields[:top_n]:
            all_fields.add((f['field_name'], f['isa_sheet']))
    
    all_fields = sorted(list(all_fields), key=lambda x: x[0])
    documents = list(consensus_data.keys())
    
    # Create matrix
    matrix = np.zeros((len(all_fields), len(documents)))
    
    for doc_idx, doc in enumerate(documents):
        field_scores = {(f['field_name'], f['isa_sheet']): f['consensus_score'] 
                       for f in consensus_data[doc]}
        
        for field_idx, field in enumerate(all_fields):
            matrix[field_idx, doc_idx] = field_scores.get(field, 0)
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, max(8, len(all_fields) * 0.3)))
    
    # Create heatmap
    im = ax.imshow(matrix, cmap='RdYlGn', aspect='auto', vmin=0, vmax=1)
    
    # Labels
    ax.set_xticks(np.arange(len(documents)))
    ax.set_yticks(np.arange(len(all_fields)))
    ax.set_xticklabels(documents, rotation=45, ha='right')
    ax.set_yticklabels([f[0][:40] for f in all_fields], fontsize=8)
    
    # Add colorbar
    cbar = ax.figure.colorbar(im, ax=ax)
    cbar.ax.set_ylabel('Consensus Score', rotation=-90, va="bottom")
    
    # Title
    ax.set_title('Metadata Field Consensus Across Documents\n(Higher = Stronger Biological Signal)')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    logger.info(f"Saved consensus heatmap to {output_path}")


def plot_consensus_tiers(consensus_data: Dict[str, List[Dict]], 
                        output_path: Path) -> None:
    """
    Create stacked bar chart showing distribution of consensus tiers by document,
    with required/recommended breakdown.
    """
    documents = list(consensus_data.keys())
    
    # Count by tier and requirement status
    tier_counts = {doc: {
        'high_required': 0, 'high_recommended': 0, 'high_other': 0,
        'medium_required': 0, 'medium_recommended': 0, 'medium_other': 0,
        'low_required': 0, 'low_recommended': 0, 'low_other': 0
    } for doc in documents}
    
    for doc, fields in consensus_data.items():
        for f in fields:
            tier = f['consensus_tier']
            is_required = f.get('is_required', False)
            is_recommended = f.get('is_recommended', False)
            
            if is_required:
                tier_counts[doc][f'{tier}_required'] += 1
            elif is_recommended:
                tier_counts[doc][f'{tier}_recommended'] += 1
            else:
                tier_counts[doc][f'{tier}_other'] += 1
    
    # Create figure with two subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    x = np.arange(len(documents))
    width = 0.25
    
    # Left plot: By consensus tier
    high_counts = [tier_counts[d]['high_required'] + tier_counts[d]['high_recommended'] + tier_counts[d]['high_other'] for d in documents]
    medium_counts = [tier_counts[d]['medium_required'] + tier_counts[d]['medium_recommended'] + tier_counts[d]['medium_other'] for d in documents]
    low_counts = [tier_counts[d]['low_required'] + tier_counts[d]['low_recommended'] + tier_counts[d]['low_other'] for d in documents]
    
    ax1.bar(x, high_counts, width*2, label='High (>90%)', color=COLORS['high'])
    ax1.bar(x, medium_counts, width*2, bottom=high_counts, label='Medium (40-90%)', color=COLORS['medium'])
    ax1.bar(x, low_counts, width*2, bottom=[h+m for h,m in zip(high_counts, medium_counts)], 
           label='Low (<40%)', color=COLORS['low'])
    
    ax1.set_xlabel('Document')
    ax1.set_ylabel('Number of Fields')
    ax1.set_title('Consensus Tiers Distribution')
    ax1.set_xticks(x)
    ax1.set_xticklabels(documents, rotation=45, ha='right')
    ax1.legend()
    
    # Right plot: Required/Recommended breakdown within high consensus
    high_required = [tier_counts[d]['high_required'] for d in documents]
    high_recommended = [tier_counts[d]['high_recommended'] for d in documents]
    high_other = [tier_counts[d]['high_other'] for d in documents]
    
    ax2.bar(x - width, high_required, width, label='Required', color='#e74c3c')
    ax2.bar(x, high_recommended, width, label='Recommended', color='#f39c12')
    ax2.bar(x + width, high_other, width, label='Emergent (not in GT)', color='#3498db')
    
    ax2.set_xlabel('Document')
    ax2.set_ylabel('Number of Fields')
    ax2.set_title('High Consensus Fields (>90%)\nby Ground Truth Status')
    ax2.set_xticks(x)
    ax2.set_xticklabels(documents, rotation=45, ha='right')
    ax2.legend()
    
    plt.suptitle('Consensus Analysis: Core Metadata Identification', fontsize=12, y=1.02)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    logger.info(f"Saved consensus tiers plot to {output_path}")


def plot_model_bias_radar(model_bias_data: Dict[str, Dict], 
                         output_path: Path) -> None:
    """
    Create radar chart comparing model biases across metadata categories.
    """
    categories = ['biological', 'technical_sequencing', 'sample_collection', 
                  'experimental_design', 'administrative']
    
    models = list(model_bias_data.keys())
    n_models = len(models)
    
    # Prepare data
    angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
    angles += angles[:1]  # Complete the loop
    
    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True))
    
    # Colors for different models
    model_colors = plt.cm.Set2(np.linspace(0, 1, n_models))
    
    for idx, model in enumerate(models):
        proportions = model_bias_data[model].get('category_proportions', {})
        values = [proportions.get(cat, 0) for cat in categories]
        values += values[:1]  # Complete the loop
        
        ax.plot(angles, values, 'o-', linewidth=2, label=model, color=model_colors[idx])
        ax.fill(angles, values, alpha=0.15, color=model_colors[idx])
    
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([c.replace('_', '\n') for c in categories], size=10)
    ax.set_ylim(0, max(0.5, max(
        max(model_bias_data[m].get('category_proportions', {}).values(), default=0)
        for m in models
    ) * 1.1))
    
    ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1))
    ax.set_title('Model Bias Comparison\n(Metadata Category Emphasis)', size=14, pad=20)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    logger.info(f"Saved model bias radar to {output_path}")


def plot_stability_comparison(stability_data: Dict[str, Dict[str, List[Dict]]], 
                             output_path: Path,
                             document: Optional[str] = None) -> None:
    """
    Create box plot comparing field stability across models.
    """
    models = list(stability_data.keys())
    
    # Collect stability scores
    model_scores = {}
    for model in models:
        scores = []
        for doc, fields in stability_data[model].items():
            if document and doc != document:
                continue
            scores.extend([f['stability_score'] for f in fields])
        model_scores[model] = scores
    
    fig, ax = plt.subplots(figsize=(12, 6))
    
    positions = np.arange(len(models))
    bp = ax.boxplot([model_scores[m] for m in models], positions=positions, 
                   widths=0.6, patch_artist=True)
    
    # Color boxes
    colors = plt.cm.Set3(np.linspace(0, 1, len(models)))
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
    
    ax.set_xticklabels(models, rotation=45, ha='right')
    ax.set_ylabel('Stability Score')
    ax.set_ylim(0, 1.1)
    ax.axhline(y=0.9, color='green', linestyle='--', alpha=0.5, label='High stability threshold')
    ax.axhline(y=0.5, color='orange', linestyle='--', alpha=0.5, label='Medium stability threshold')
    
    title = 'Intra-Model Stability Across Runs (Technical Replicate Consistency)'
    if document:
        title += f'\nDocument: {document}'
    ax.set_title(title)
    ax.legend(loc='lower right')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    logger.info(f"Saved stability comparison to {output_path}")


def plot_disagreement_analysis(disagreement_data: Dict[str, List[Dict]], 
                              output_path: Path,
                              top_n: int = 20) -> None:
    """
    Create horizontal bar chart showing fields with highest disagreement.
    These represent reporting ambiguities in source documents.
    """
    # Aggregate across documents
    field_disagreements = defaultdict(list)
    
    for doc, fields in disagreement_data.items():
        for f in fields:
            key = (f['field_name'], f['isa_sheet'])
            field_disagreements[key].append({
                'score': f['disagreement_score'],
                'doc': doc
            })
    
    # Calculate average disagreement
    avg_disagreements = []
    for (field, sheet), occurrences in field_disagreements.items():
        avg_score = np.mean([o['score'] for o in occurrences])
        avg_disagreements.append({
            'field': field,
            'sheet': sheet,
            'avg_disagreement': avg_score,
            'n_docs': len(occurrences)
        })
    
    # Sort and take top N
    avg_disagreements.sort(key=lambda x: x['avg_disagreement'], reverse=True)
    top_fields = avg_disagreements[:top_n]
    
    fig, ax = plt.subplots(figsize=(12, max(6, len(top_fields) * 0.4)))
    
    y_pos = np.arange(len(top_fields))
    scores = [f['avg_disagreement'] for f in top_fields]
    labels = [f"{f['field'][:35]}" for f in top_fields]
    
    # Color by disagreement level
    colors = ['#e74c3c' if s > 0.5 else '#f39c12' if s > 0.2 else '#2ecc71' for s in scores]
    
    bars = ax.barh(y_pos, scores, color=colors, alpha=0.8)
    
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel('Average Disagreement Score')
    ax.set_xlim(0, 1)
    ax.invert_yaxis()
    
    # Add threshold lines
    ax.axvline(x=0.5, color='red', linestyle='--', alpha=0.5, label='High disagreement')
    ax.axvline(x=0.2, color='orange', linestyle='--', alpha=0.5, label='Moderate disagreement')
    
    ax.set_title('Fields with Highest Inter-Model Disagreement\n(Proxy for Reporting Ambiguity in Source Documents)')
    ax.legend(loc='lower right')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    logger.info(f"Saved disagreement analysis to {output_path}")


def plot_emergent_patterns(emergent_data: Dict[str, Any], 
                          output_path: Path,
                          top_n: int = 15) -> None:
    """
    Create visualization of emergent metadata patterns.
    These are non-standard fields that may represent implicit community knowledge.
    """
    top_candidates = emergent_data.get('top_candidates', [])[:top_n]
    
    if not top_candidates:
        logger.warning("No emergent patterns to plot")
        return
    
    fig, axes = plt.subplots(1, 2, figsize=(14, max(6, len(top_candidates) * 0.4)))
    
    # Left: Extension score bar chart
    ax1 = axes[0]
    fields = [f['field_name'][:30] for f in top_candidates]
    scores = [f['extension_score'] for f in top_candidates]
    categories = [f['category'] for f in top_candidates]
    
    colors = [COLORS.get(cat, COLORS['other']) for cat in categories]
    
    y_pos = np.arange(len(fields))
    ax1.barh(y_pos, scores, color=colors, alpha=0.8)
    ax1.set_yticks(y_pos)
    ax1.set_yticklabels(fields, fontsize=9)
    ax1.set_xlabel('Extension Score')
    ax1.set_xlim(0, 1)
    ax1.invert_yaxis()
    ax1.set_title('Top Candidates for Standard Extension')
    
    # Add legend for categories
    unique_cats = list(set(categories))
    patches = [mpatches.Patch(color=COLORS.get(cat, COLORS['other']), label=cat) 
               for cat in unique_cats]
    ax1.legend(handles=patches, loc='lower right', fontsize=8)
    
    # Right: Category distribution pie chart
    ax2 = axes[1]
    cat_dist = emergent_data.get('category_distribution', {})
    
    if cat_dist:
        labels = list(cat_dist.keys())
        sizes = list(cat_dist.values())
        pie_colors = [COLORS.get(l, COLORS['other']) for l in labels]
        
        ax2.pie(sizes, labels=labels, colors=pie_colors, autopct='%1.1f%%',
               startangle=90)
        ax2.set_title('Category Distribution of Emergent Fields')
    
    plt.suptitle('Emergent Metadata Patterns: Implicit Community Knowledge\nNon-standard fields consistently identified across models', 
                fontsize=12, y=1.02)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    logger.info(f"Saved emergent patterns plot to {output_path}")


def plot_field_importance_hierarchy(importance_data: Dict[str, List[Dict]], 
                                   output_path: Path,
                                   document: Optional[str] = None) -> None:
    """
    Create treemap or hierarchical visualization of field importance.
    """
    # Aggregate data
    if document:
        docs_to_use = {document: importance_data.get(document, [])}
    else:
        docs_to_use = importance_data
    
    # Group by importance category
    categories = defaultdict(list)
    
    for doc, fields in docs_to_use.items():
        for f in fields:
            categories[f['importance_category']].append({
                'field': f['field_name'],
                'doc': doc,
                'combined_score': f['combined_score'],
                'consensus': f['consensus_score']
            })
    
    fig, axes = plt.subplots(1, 3, figsize=(15, 6))
    
    importance_order = ['workflow_critical', 'biologically_critical', 'descriptive']
    importance_colors = ['#e74c3c', '#3498db', '#95a5a6']
    
    for idx, (cat, color) in enumerate(zip(importance_order, importance_colors)):
        ax = axes[idx]
        cat_fields = categories.get(cat, [])
        
        if cat_fields:
            # Sort by combined score
            cat_fields.sort(key=lambda x: x['combined_score'], reverse=True)
            top_fields = cat_fields[:15]
            
            y_pos = np.arange(len(top_fields))
            scores = [f['combined_score'] for f in top_fields]
            labels = [f['field'][:25] for f in top_fields]
            
            ax.barh(y_pos, scores, color=color, alpha=0.8)
            ax.set_yticks(y_pos)
            ax.set_yticklabels(labels, fontsize=8)
            ax.invert_yaxis()
        
        ax.set_title(cat.replace('_', ' ').title(), fontsize=11)
        ax.set_xlabel('Combined Score')
    
    plt.suptitle('Field Importance Hierarchy\n(Workflow-Critical vs Biologically-Critical vs Descriptive)', 
                fontsize=12, y=1.02)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    logger.info(f"Saved field importance hierarchy to {output_path}")


def generate_all_biological_visualizations(report_data: Dict[str, Any], 
                                          output_dir: Path) -> List[Path]:
    """
    Generate all biological insights visualizations.
    
    Args:
        report_data: Output from BiologicalInsightsAnalyzer.generate_comprehensive_report()
        output_dir: Directory to save figures
        
    Returns:
        List of paths to generated figures
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    generated_files = []
    
    # 1. Consensus heatmap
    if 'consensus_analysis' in report_data:
        path = output_dir / 'consensus_heatmap.png'
        plot_consensus_heatmap(report_data['consensus_analysis'], path)
        generated_files.append(path)
        
        path = output_dir / 'consensus_tiers.png'
        plot_consensus_tiers(report_data['consensus_analysis'], path)
        generated_files.append(path)
    
    # 2. Model bias radar
    if 'model_bias_analysis' in report_data:
        path = output_dir / 'model_bias_radar.png'
        plot_model_bias_radar(report_data['model_bias_analysis'], path)
        generated_files.append(path)
    
    # 3. Stability comparison
    if 'stability_analysis' in report_data:
        path = output_dir / 'stability_comparison.png'
        plot_stability_comparison(report_data['stability_analysis'], path)
        generated_files.append(path)
    
    # 4. Disagreement analysis
    if 'disagreement_analysis' in report_data:
        path = output_dir / 'disagreement_analysis.png'
        plot_disagreement_analysis(report_data['disagreement_analysis'], path)
        generated_files.append(path)
    
    # 5. Emergent patterns
    if 'emergent_patterns_analysis' in report_data:
        path = output_dir / 'emergent_patterns.png'
        plot_emergent_patterns(report_data['emergent_patterns_analysis'], path)
        generated_files.append(path)
    
    # 6. Field importance
    if 'field_importance_analysis' in report_data:
        path = output_dir / 'field_importance_hierarchy.png'
        plot_field_importance_hierarchy(report_data['field_importance_analysis'], path)
        generated_files.append(path)
    
    logger.info(f"Generated {len(generated_files)} biological insight visualizations")
    return generated_files


def main():
    """Run visualization generation."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate biological insights visualizations')
    parser.add_argument('--input', type=Path, 
                       default=Path('evaluation/analysis/output/biological_insights.json'),
                       help='Path to biological insights JSON')
    parser.add_argument('--output-dir', type=Path, 
                       default=Path('evaluation/analysis/output/figures'),
                       help='Output directory for figures')
    
    args = parser.parse_args()
    
    with open(args.input) as f:
        report_data = json.load(f)
    
    generated = generate_all_biological_visualizations(report_data, args.output_dir)
    
    print(f"Generated {len(generated)} visualizations:")
    for path in generated:
        print(f"  - {path}")


if __name__ == '__main__':
    main()
