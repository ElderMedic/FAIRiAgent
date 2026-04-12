"""
Run Improved Analysis Script

Implements evaluation improvements based on meeting feedback (2026-01-16):
1. 100% mandatory field coverage as success criterion
2. Field presence matrices
3. Core/shared terms analysis  
4. Stability-completeness trade-off analysis
5. Package selection quality
6. Consensus analysis on successful runs only

Usage:
    python scripts/run_improved_analysis.py --runs-dir evaluation/runs/openai_gpt5.1_20260130_142242 --output-dir evaluation/analysis/improved_output
"""

import sys
from pathlib import Path
import json
import argparse
from typing import Dict, List, Any
import pandas as pd

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from fairifier.output_paths import (
    LEGACY_METADATA_OUTPUT_FILENAME,
    METADATA_OUTPUT_FILENAME,
    resolve_metadata_output_read_path,
)

from evaluation.evaluators.mandatory_coverage_evaluator import MandatoryCoverageEvaluator
from evaluation.evaluators.completeness_evaluator import CompletenessEvaluator
from evaluation.analysis.analyzers.field_presence import FieldPresenceAnalyzer
from evaluation.analysis.analyzers.package_selection_quality import PackageSelectionAnalyzer
from evaluation.analysis.analyzers.stability_completeness import StabilityCompletenessAnalyzer
from evaluation.analysis.visualizations.field_presence_matrix import FieldPresenceMatrixVisualizer
from evaluation.analysis.visualizations.stability_plots import StabilityCompletenessVisualizer


class ImprovedAnalysisRunner:
    """Run improved analysis pipeline."""
    
    def __init__(self, runs_dir: Path, ground_truth_path: Path, output_dir: Path):
        """
        Initialize analysis runner.
        
        Args:
            runs_dir: Directory containing evaluation runs
            ground_truth_path: Path to ground truth JSON
            output_dir: Directory to save analysis outputs
        """
        self.runs_dir = Path(runs_dir)
        self.ground_truth_path = Path(ground_truth_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load ground truth
        with open(self.ground_truth_path, 'r') as f:
            gt_data = json.load(f)
        self.ground_truth = {
            doc['document_id']: doc 
            for doc in gt_data['documents']
        }
        
        # Initialize evaluators and analyzers
        self.mandatory_eval = MandatoryCoverageEvaluator()
        self.completeness_eval = CompletenessEvaluator()
        self.field_presence_analyzer = FieldPresenceAnalyzer()
        self.package_analyzer = PackageSelectionAnalyzer()
        self.stability_analyzer = StabilityCompletenessAnalyzer()
        
        # Initialize visualizers
        self.presence_viz = FieldPresenceMatrixVisualizer(output_dir / 'figures')
        self.stability_viz = StabilityCompletenessVisualizer(output_dir / 'figures')
        
        print(f"✓ Initialized with {len(self.ground_truth)} documents in ground truth")
    
    def load_runs(self) -> List[Dict[str, Any]]:
        """Load all runs from runs directory."""
        runs = []
        
        # Look for evaluation_results.json
        results_file = self.runs_dir / 'results' / 'evaluation_results.json'
        if results_file.exists():
            print(f"Loading from aggregated results: {results_file}")
            with open(results_file, 'r') as f:
                data = json.load(f)
            
            # Extract runs from per_model_results
            for model_name, model_data in data.get('per_model_results', {}).items():
                doc_results = model_data.get('completeness', {}).get('per_document', {})
                
                for doc_id, doc_data in doc_results.items():
                    # This is aggregated data, need to find individual runs
                    # Look for run directories
                    run_dirs = list((self.runs_dir / 'outputs' / model_name / doc_id).glob('run_*'))
                    
                    for run_dir in run_dirs:
                        run_data = self._load_single_run(run_dir, model_name, doc_id)
                        if run_data:
                            runs.append(run_data)
        
        else:
            # Fallback: scan for individual run directories
            print(f"Scanning for individual runs in: {self.runs_dir}")
            seen_run_dirs = set()
            for name in (METADATA_OUTPUT_FILENAME, LEGACY_METADATA_OUTPUT_FILENAME):
                for metadata_file in self.runs_dir.rglob(name):
                    run_dir = metadata_file.parent
                    if run_dir in seen_run_dirs:
                        continue
                    seen_run_dirs.add(run_dir)

                    # Extract model and document from path
                    parts = run_dir.parts

                    model_name = None
                    doc_id = None

                    # Strategy 1: outputs/model/document/run_X structure
                    if "outputs" in parts:
                        idx = parts.index("outputs")
                        if idx + 2 < len(parts):
                            model_name = parts[idx + 1]
                            doc_id = parts[idx + 2]

                    # Strategy 2: document/run_X structure (e.g., qwen_max/earthworm/run_1)
                    elif len(parts) >= 2:
                        parent_name = parts[-2]
                        if parent_name in ["earthworm", "biosensor", "pomato"]:
                            doc_id = parent_name
                            model_name = self.runs_dir.name

                    if model_name and doc_id:
                        run_data = self._load_single_run(run_dir, model_name, doc_id)
                        if run_data:
                            runs.append(run_data)
        
        print(f"✓ Loaded {len(runs)} runs")
        return runs
    
    def _load_single_run(self, run_dir: Path, model_name: str, doc_id: str) -> Dict[str, Any]:
        """Load data from a single run directory."""
        metadata_file = resolve_metadata_output_read_path(run_dir)
        eval_file = run_dir / 'eval_result.json'
        
        if not metadata_file:
            return None
        
        try:
            # Load metadata
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
            
            # Extract fields
            extracted_fields = self._extract_field_names(metadata)
            
            # Load eval result if exists
            eval_result = None
            if eval_file.exists():
                with open(eval_file, 'r') as f:
                    eval_result = json.load(f)
            
            return {
                'run_dir': str(run_dir),
                'model_name': model_name,
                'document_id': doc_id,
                'metadata': metadata,
                'extracted_field_names': list(extracted_fields),
                'eval_result': eval_result,
                'selected_package': self._identify_package(metadata)
            }
        
        except Exception as e:
            print(f"Warning: Failed to load {run_dir}: {e}")
            return None
    
    def _extract_field_names(self, metadata: Dict[str, Any]) -> set:
        """Extract field names from metadata."""
        field_names = set()
        
        isa_structure = metadata.get('isa_structure', {})
        for sheet_name, sheet_data in isa_structure.items():
            if sheet_name == 'description':
                continue
            
            for field in sheet_data.get('fields', []):
                field_name = field.get('field_name', '').strip()
                if field_name:
                    field_names.add(field_name)
        
        return field_names
    
    def _identify_package(self, metadata: Dict[str, Any]) -> str:
        """Identify selected package."""
        workflow_report = metadata.get('workflow_report', {})
        if 'selected_package' in workflow_report:
            return workflow_report['selected_package']
        
        return metadata.get('metadata_summary', {}).get('package', 'default')
    
    def run_analysis(self):
        """Run complete improved analysis."""
        print("\n" + "="*70)
        print("IMPROVED EVALUATION ANALYSIS")
        print("="*70)
        
        # Load runs
        runs = self.load_runs()
        if not runs:
            print("ERROR: No runs found!")
            return
        
        # Group by document
        docs = {}
        for run in runs:
            doc_id = run['document_id']
            if doc_id not in docs:
                docs[doc_id] = []
            docs[doc_id].append(run)
        
        print(f"\n✓ Found {len(docs)} documents")
        
        # Run analyses
        all_results = {
            'mandatory_coverage': {},
            'field_presence': {},
            'package_selection': {},
            'stability_completeness': {}
        }
        
        # 1. Mandatory coverage evaluation
        print("\n" + "-"*70)
        print("1. EVALUATING MANDATORY COVERAGE (Success Criterion)")
        print("-"*70)
        
        for doc_id, doc_runs in docs.items():
            if doc_id not in self.ground_truth:
                print(f"Warning: {doc_id} not in ground truth, skipping")
                continue
            
            gt_doc = self.ground_truth[doc_id]
            
            # Evaluate each run
            run_evaluations = []
            for run in doc_runs:
                eval_result = self.mandatory_eval.evaluate_run_success(
                    run['metadata'],
                    gt_doc
                )
                run_evaluations.append(eval_result)
            
            # Compute success rate
            success_stats = self.mandatory_eval.compute_success_rate(run_evaluations)
            
            all_results['mandatory_coverage'][doc_id] = {
                'stats': success_stats,
                'evaluations': run_evaluations
            }
            
            print(f"\n{doc_id}:")
            print(f"  Success Rate: {success_stats['success_rate']:.1%} ({success_stats['successful_runs']}/{success_stats['total_runs']})")
            print(f"  Package Accuracy: {success_stats['package_selection_accuracy']:.1%}")
            print(f"  Avg Mandatory Coverage: {success_stats['average_mandatory_coverage']:.1%}")
        
        # 2. Field presence analysis
        print("\n" + "-"*70)
        print("2. ANALYZING FIELD PRESENCE PATTERNS")
        print("-"*70)
        
        for doc_id, doc_runs in docs.items():
            if doc_id not in self.ground_truth:
                continue
            
            gt_doc = self.ground_truth[doc_id]
            
            # Create presence matrix
            presence_matrix = self.field_presence_analyzer.create_presence_matrix(
                doc_runs, gt_doc, doc_id
            )
            
            # Compute metrics
            core_fields = self.field_presence_analyzer.compute_core_fields(presence_matrix)
            variable_fields = self.field_presence_analyzer.compute_variable_fields(presence_matrix)
            hallucinations = self.field_presence_analyzer.analyze_hallucinations(presence_matrix)
            stability_metrics = self.field_presence_analyzer.compute_stability_metrics(presence_matrix, doc_id)
            
            all_results['field_presence'][doc_id] = {
                'matrix': presence_matrix,
                'core_fields': core_fields,
                'variable_fields': variable_fields,
                'hallucinations': hallucinations,
                'stability_metrics': stability_metrics
            }
            
            print(f"\n{doc_id}:")
            print(f"  Core fields (100% presence): {len(core_fields['all'])}")
            print(f"  Variable fields: {len(variable_fields['all'])}")
            print(f"  Hallucinations: {hallucinations['total_extra_fields']}")
            
            # Generate visualizations
            self.presence_viz.plot_presence_matrix(presence_matrix, doc_id)
            self.presence_viz.plot_core_fields_summary(presence_matrix, doc_id)
            self.presence_viz.plot_model_field_coverage(presence_matrix, doc_id)
        
        # 3. Stability-completeness analysis
        print("\n" + "-"*70)
        print("3. ANALYZING STABILITY-COMPLETENESS TRADE-OFF")
        print("-"*70)
        
        for doc_id, doc_runs in docs.items():
            if doc_id not in self.ground_truth:
                continue
            
            gt_doc = self.ground_truth[doc_id]
            
            # Analyze trade-off
            tradeoff = self.stability_analyzer.analyze_tradeoff(doc_runs, gt_doc, doc_id)
            
            all_results['stability_completeness'][doc_id] = tradeoff
            
            print(f"\n{doc_id}:")
            print(f"  {tradeoff['interpretation']}")
        
        # Create scatter data and visualize
        scatter_data = self.stability_analyzer.create_scatter_data(
            all_results['stability_completeness']
        )
        
        self.stability_viz.plot_stability_completeness_scatter(scatter_data)
        self.stability_viz.plot_stability_by_document(scatter_data)
        self.stability_viz.plot_mandatory_core_analysis(scatter_data)
        
        comparison_df = self.stability_analyzer.compare_documents(
            all_results['stability_completeness']
        )
        self.stability_viz.plot_document_comparison(comparison_df)
        
        # 4. Package selection analysis
        print("\n" + "-"*70)
        print("4. ANALYZING PACKAGE SELECTION QUALITY")
        print("-"*70)
        
        for doc_id, doc_runs in docs.items():
            if doc_id not in self.ground_truth:
                continue
            
            gt_doc = self.ground_truth[doc_id]
            
            # Analyze package selection
            pkg_analysis = self.package_analyzer.analyze_package_selection(doc_runs, gt_doc)
            
            all_results['package_selection'][doc_id] = pkg_analysis
            
            print(f"\n{doc_id}:")
            print(f"  Correct Package: {pkg_analysis['correct_package_rate']:.1%}")
            print(f"  Domain Aligned: {pkg_analysis['domain_aligned_rate']:.1%}")
            print(f"  High Quality: {pkg_analysis['high_quality_rate']:.1%}")
        
        # Save results
        print("\n" + "-"*70)
        print("5. SAVING RESULTS")
        print("-"*70)
        
        self._save_results(all_results)
        
        print("\n" + "="*70)
        print("ANALYSIS COMPLETE!")
        print("="*70)
        print(f"\nResults saved to: {self.output_dir}")
        print(f"Figures saved to: {self.output_dir / 'figures'}")
    
    def _save_results(self, results: Dict[str, Any]):
        """Save analysis results."""
        # Create tables directory
        tables_dir = self.output_dir / 'tables'
        tables_dir.mkdir(exist_ok=True)
        
        # Save mandatory coverage summary
        mandatory_summary = []
        for doc_id, data in results['mandatory_coverage'].items():
            stats = data['stats']
            mandatory_summary.append({
                'document': doc_id,
                'total_runs': stats['total_runs'],
                'successful_runs': stats['successful_runs'],
                'success_rate': stats['success_rate'],
                'package_accuracy': stats['package_selection_accuracy'],
                'avg_mandatory_coverage': stats['average_mandatory_coverage']
            })
        
        df = pd.DataFrame(mandatory_summary)
        df.to_csv(tables_dir / 'mandatory_coverage_summary.csv', index=False)
        print(f"✓ Saved: tables/mandatory_coverage_summary.csv")
        
        # Save field presence matrices
        for doc_id, data in results['field_presence'].items():
            matrix = data['matrix']
            matrix.to_csv(tables_dir / f'field_presence_matrix_{doc_id}.csv', index=False)
            print(f"✓ Saved: tables/field_presence_matrix_{doc_id}.csv")
        
        # Save stability-completeness data
        scatter_data = self.stability_analyzer.create_scatter_data(
            results['stability_completeness']
        )
        scatter_data.to_csv(tables_dir / 'stability_completeness_data.csv', index=False)
        print(f"✓ Saved: tables/stability_completeness_data.csv")
        
        # Save full results as JSON
        # (Note: DataFrames not serializable, so skip those)
        def make_serializable(obj):
            """Convert non-serializable objects for JSON."""
            if isinstance(obj, (pd.DataFrame, pd.Series)):
                return "DataFrame (see CSV files)"
            elif isinstance(obj, dict):
                return {k: make_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [make_serializable(item) for item in obj]
            else:
                return obj
        
        json_results = {
            'mandatory_coverage': make_serializable(results['mandatory_coverage']),
            'package_selection': make_serializable(results['package_selection']),
            'stability_completeness': make_serializable(results['stability_completeness'])
        }
        
        with open(self.output_dir / 'improved_analysis_results.json', 'w') as f:
            json.dump(json_results, f, indent=2, default=str)
        print(f"✓ Saved: improved_analysis_results.json")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Run improved evaluation analysis')
    parser.add_argument('--runs-dir', type=str, required=True,
                       help='Directory containing evaluation runs')
    parser.add_argument('--ground-truth', type=str,
                       default='evaluation/datasets/annotated/ground_truth_filtered.json',
                       help='Path to ground truth JSON')
    parser.add_argument('--output-dir', type=str,
                       default='evaluation/analysis/improved_output',
                       help='Output directory for analysis results')
    
    args = parser.parse_args()
    
    runner = ImprovedAnalysisRunner(
        runs_dir=Path(args.runs_dir),
        ground_truth_path=Path(args.ground_truth),
        output_dir=Path(args.output_dir)
    )
    
    runner.run_analysis()


if __name__ == '__main__':
    main()
