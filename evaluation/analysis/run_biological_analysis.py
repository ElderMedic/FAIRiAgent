#!/usr/bin/env python3
"""
Run Biological Insights Analysis

Comprehensive analysis treating agent outputs as replicated measurements,
enabling biological and methodological insights beyond single-run automation.

Usage:
    python evaluation/analysis/run_biological_analysis.py [--runs-dir PATH] [--output-dir PATH]
"""

import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parents[2]))

from evaluation.analysis.analyzers.biological_insights import BiologicalInsightsAnalyzer
from evaluation.analysis.visualizations.biological_insights import generate_all_biological_visualizations

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_section(title: str, char: str = "="):
    """Print a section header."""
    width = 70
    print(f"\n{char * width}")
    print(f" {title}")
    print(f"{char * width}\n")


def format_table(headers: list, rows: list, widths: list = None) -> str:
    """Format data as a simple text table."""
    if not widths:
        widths = [max(len(str(h)), max(len(str(r[i])) for r in rows) if rows else 0) 
                  for i, h in enumerate(headers)]
    
    lines = []
    header_line = " | ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    separator = "-+-".join("-" * w for w in widths)
    
    lines.append(header_line)
    lines.append(separator)
    
    for row in rows:
        row_line = " | ".join(str(r).ljust(w) for r, w in zip(row, widths))
        lines.append(row_line)
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Run comprehensive biological insights analysis on agent evaluation results'
    )
    parser.add_argument(
        '--runs-dir',
        type=Path,
        default=Path('evaluation/runs'),
        help='Path to evaluation/runs directory (default: evaluation/runs)'
    )
    parser.add_argument(
        '--ground-truth',
        type=Path,
        default=Path('evaluation/datasets/annotated/ground_truth_filtered.json'),
        help='Path to ground truth JSON (default: evaluation/datasets/annotated/ground_truth_filtered.json)'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path('evaluation/analysis/output'),
        help='Output directory for reports and figures (default: evaluation/analysis/output)'
    )
    parser.add_argument(
        '--no-viz',
        action='store_true',
        help='Skip visualization generation'
    )
    parser.add_argument(
        '--all-models',
        action='store_true',
        help='Include all models (including incomplete/ongoing runs). Default: only analyze completed models'
    )
    
    args = parser.parse_args()
    
    print_section("BIOLOGICAL INSIGHTS ANALYSIS")
    print("Treating agent executions as replicated measurements of experimental interpretation")
    print("Enabling biological and methodological insights beyond single-run automation\n")
    
    # Initialize analyzer - filter to completed models by default
    filter_completed = not args.all_models
    logger.info(f"Initializing analyzer with runs from {args.runs_dir}")
    if filter_completed:
        print("Analyzing COMPLETED models only: gpt4.1, gpt5, haiku, o3, sonnet, qwen_flash, qwen_max, qwen_plus")
        print("(Use --all-models to include ongoing runs)\n")
    analyzer = BiologicalInsightsAnalyzer(args.runs_dir, args.ground_truth, filter_completed)
    
    # Load all runs
    n_runs = analyzer.load_all_runs()
    print(f"Loaded {n_runs} evaluation runs\n")
    
    # Generate comprehensive report
    logger.info("Generating comprehensive biological insights report...")
    report = analyzer.generate_comprehensive_report()
    
    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save JSON report
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = args.output_dir / f'biological_insights_{timestamp}.json'
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    logger.info(f"Saved JSON report to {report_path}")
    
    # Also save as latest
    latest_path = args.output_dir / 'biological_insights.json'
    with open(latest_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print_section("ANALYSIS SUMMARY")
    summary = report['summary']
    print(f"Models analyzed: {summary['total_models']}")
    print(f"  - {', '.join(summary['models_analyzed'])}")
    print(f"\nDocuments analyzed: {summary['total_documents']}")
    print(f"  - {', '.join(summary['documents_analyzed'])}")
    print(f"\nTotal runs analyzed: {summary['total_runs']}")
    
    # Print Consensus Analysis Summary
    print_section("1. CONSENSUS ANALYSIS", "-")
    print("High consensus (>90%) = Core experimental variables")
    print("Medium consensus (40-90%) = Domain-dependent metadata")
    print("Low consensus (<40%) = Marginal or reporting-deficient fields\n")
    
    for doc, fields in report['consensus_analysis'].items():
        high = [f for f in fields if f['consensus_tier'] == 'high']
        medium = [f for f in fields if f['consensus_tier'] == 'medium']
        low = [f for f in fields if f['consensus_tier'] == 'low']
        
        print(f"Document: {doc}")
        print(f"  High consensus: {len(high)} fields (core metadata)")
        print(f"  Medium consensus: {len(medium)} fields (contextual metadata)")
        print(f"  Low consensus: {len(low)} fields (marginal/ambiguous)")
        
        if high[:3]:
            print(f"  Top core fields: {', '.join(f['field_name'] for f in high[:3])}")
        print()
    
    # Print Disagreement Analysis Summary
    print_section("2. DISAGREEMENT ANALYSIS", "-")
    print("High disagreement indicates reporting ambiguity in source documents\n")
    
    for doc, fields in report['disagreement_analysis'].items():
        high_disagree = [f for f in fields if f['disagreement_score'] > 0.5]
        if high_disagree:
            print(f"Document: {doc}")
            print(f"  Fields with high disagreement ({len(high_disagree)}):")
            for f in high_disagree[:5]:
                print(f"    - {f['field_name']}: {f['disagreement_score']:.2f}")
                print(f"      Models that include: {', '.join(f['models_that_include'][:3])}")
            print()
    
    # Print Stability Analysis Summary
    print_section("3. INTRA-MODEL STABILITY", "-")
    print("Stability across runs = technical replicate consistency\n")
    
    for model, doc_data in report['stability_analysis'].items():
        all_scores = []
        for doc, fields in doc_data.items():
            all_scores.extend([f['stability_score'] for f in fields])
        
        if all_scores:
            avg_stability = sum(all_scores) / len(all_scores)
            high_stable = sum(1 for s in all_scores if s >= 0.9)
            unstable = sum(1 for s in all_scores if s < 0.5)
            
            print(f"{model}:")
            print(f"  Average stability: {avg_stability:.2f}")
            print(f"  Highly stable fields (>90%): {high_stable}")
            print(f"  Unstable fields (<50%): {unstable}")
            print()
    
    # Print Model Bias Summary
    print_section("4. MODEL BIAS ANALYSIS", "-")
    print("Different models may emphasize different metadata categories\n")
    
    for model, bias_data in report['model_bias_analysis'].items():
        print(f"{model}:")
        print(f"  Total fields extracted: {bias_data['total_fields_extracted']}")
        print(f"  Dominant category: {bias_data['dominant_category']}")
        
        # Top 3 categories
        sorted_cats = sorted(bias_data['category_proportions'].items(), 
                           key=lambda x: x[1], reverse=True)
        for cat, prop in sorted_cats[:3]:
            print(f"    - {cat}: {prop*100:.1f}%")
        print()
    
    # Print Emergent Patterns Summary
    print_section("5. EMERGENT METADATA PATTERNS", "-")
    print("Non-standard fields that may represent implicit community knowledge\n")
    
    emergent = report['emergent_patterns_analysis']
    print(f"Total emergent (non-standard) fields: {emergent['total_emergent_fields']}")
    
    top_candidates = emergent.get('top_candidates', [])[:10]
    if top_candidates:
        print(f"\nTop candidates for standard extension:")
        headers = ['Field Name', 'ISA Sheet', 'Category', 'Score', 'Models']
        rows = [
            (c['field_name'][:30], c['isa_sheet'], c['category'], 
             f"{c['extension_score']:.2f}", len(c['models']))
            for c in top_candidates
        ]
        print(format_table(headers, rows))
    
    # Print Field Importance Summary
    print_section("6. FIELD IMPORTANCE RANKING", "-")
    print("Workflow-critical vs Biologically-critical vs Descriptive\n")
    
    for doc, fields in report['field_importance_analysis'].items():
        workflow_critical = [f for f in fields if f['importance_category'] == 'workflow_critical']
        bio_critical = [f for f in fields if f['importance_category'] == 'biologically_critical']
        
        print(f"Document: {doc}")
        if workflow_critical:
            print(f"  Workflow-critical fields: {len(workflow_critical)}")
            print(f"    Top: {', '.join(f['field_name'] for f in workflow_critical[:3])}")
        if bio_critical:
            print(f"  Biologically-critical fields: {len(bio_critical)}")
            print(f"    Top: {', '.join(f['field_name'] for f in bio_critical[:3])}")
        print()
    
    # Key Insights
    print_section("KEY INSIGHTS FOR DISCUSSION")
    
    for idx, insight in enumerate(report['insights'][:10], 1):
        print(f"{idx}. [{insight['type'].upper()}]")
        print(f"   {insight.get('insight', '')}")
        if 'fields' in insight:
            print(f"   Fields: {', '.join(insight['fields'][:5])}")
        if 'top_candidates' in insight:
            print(f"   Candidates: {', '.join(insight['top_candidates'][:5])}")
        print()
    
    # Generate visualizations
    if not args.no_viz:
        print_section("GENERATING VISUALIZATIONS")
        fig_dir = args.output_dir / 'figures'
        try:
            generated = generate_all_biological_visualizations(report, fig_dir)
            print(f"Generated {len(generated)} visualization files:")
            for path in generated:
                print(f"  - {path}")
        except Exception as e:
            logger.error(f"Failed to generate visualizations: {e}")
            print(f"Warning: Visualization generation failed: {e}")
    
    # Final summary
    print_section("OUTPUT FILES")
    print(f"JSON Report: {report_path}")
    print(f"Latest Report: {latest_path}")
    if not args.no_viz:
        print(f"Figures: {args.output_dir / 'figures'}/")
    
    # Discussion sentence for paper
    print_section("DISCUSSION SENTENCE (for paper)")
    print('"We treat repeated agent executions across models and batches as replicated')
    print('measurements of experimental interpretation, enabling biological and')
    print('methodological insights beyond single-run automation."')
    print()
    print("This analysis reveals:")
    print("- Which metadata fields represent CORE experimental variables (high consensus)")
    print("- Where REPORTING AMBIGUITY exists in scientific literature (high disagreement)")
    print("- How ROBUST agent extraction is across repeated runs (stability)")
    print("- What DOMAIN BIASES different LLMs exhibit (model bias)")
    print("- What IMPLICIT COMMUNITY KNOWLEDGE exists beyond formal standards (emergent patterns)")


if __name__ == '__main__':
    main()
