"""
Comprehensive Report Generator

Generates all analyses and visualizations for technical reports and manuscripts.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import pandas as pd

from ..data_loaders import EvaluationDataLoader
from ..analyzers import (
    ModelPerformanceAnalyzer,
    WorkflowReliabilityAnalyzer,
    FailurePatternAnalyzer,
    PassAtKAnalyzer,
    CRITERIA_PRESETS,
)
from ..visualizations import (
    ModelComparisonVisualizer,
    WorkflowReliabilityVisualizer,
    FailureAnalysisVisualizer,
    PassAtKVisualizer,
)
from ..baseline_comparison import load_agentic_data, load_baseline_data
from ..visualizations.baseline_comparison import BaselineComparisonVisualizer


class ReportGenerator:
    """Generate comprehensive analysis report."""
    
    def __init__(
        self,
        runs_dir: Path,
        output_dir: Path,
        pattern: Optional[str] = None
    ):
        """
        Initialize report generator.
        
        Args:
            runs_dir: Path to evaluation/runs directory
            output_dir: Output directory for reports and figures
            pattern: Optional pattern to filter runs (e.g., "qwen_*")
        """
        self.runs_dir = Path(runs_dir)
        self.output_dir = Path(output_dir)
        self.pattern = pattern
        
        # Create output subdirectories
        self.figures_dir = self.output_dir / 'figures'
        self.tables_dir = self.output_dir / 'tables'
        self.data_dir = self.output_dir / 'data'
        
        for dir_path in [self.figures_dir, self.tables_dir, self.data_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize data loader with filters
        from evaluation.analysis.config import EXCLUDED_MODELS, EXCLUDED_DOCUMENTS
        self.loader = EvaluationDataLoader(self.runs_dir)
        self.excluded_models = EXCLUDED_MODELS
        self.excluded_documents = EXCLUDED_DOCUMENTS
        self.loader.load_all(
            pattern=pattern,
            exclude_models=EXCLUDED_MODELS,
            exclude_docs=EXCLUDED_DOCUMENTS
        )
        
        # Load dataframes
        self.model_df = self.loader.get_model_dataframe()
        self.doc_df = self.loader.get_document_level_dataframe()
        self.reliability_df = self.loader.get_workflow_reliability_dataframe()
        
        # Initialize analyzers
        self.performance_analyzer = ModelPerformanceAnalyzer(self.model_df)
        self.reliability_analyzer = WorkflowReliabilityAnalyzer(self.reliability_df)
        self.failure_analyzer = FailurePatternAnalyzer(
            self.reliability_df,
            self.loader.evaluation_results
        )
        
        # Initialize visualizers
        self.model_viz = ModelComparisonVisualizer(self.figures_dir)
        self.reliability_viz = WorkflowReliabilityVisualizer(self.figures_dir)
        self.failure_viz = FailureAnalysisVisualizer(self.figures_dir)
        self.baseline_viz = BaselineComparisonVisualizer(self.figures_dir)
        self.pass_at_k_viz = PassAtKVisualizer(self.figures_dir)
        
        # Load baseline comparison data (if available)
        self.agentic_data = None
        self.baseline_data = None
        try:
            self.agentic_data = load_agentic_data(self.runs_dir)
            self.baseline_data = load_baseline_data(self.runs_dir)
            if self.baseline_data:
                print(f"  ✅ Found {len(self.baseline_data)} baseline configuration(s)")
        except Exception as e:
            print(f"  ⚠️  Could not load baseline data: {e}")
        
        # Initialize pass@k analyzer
        self.pass_at_k_analyzer = PassAtKAnalyzer(
            self.runs_dir,
            criteria=CRITERIA_PRESETS['moderate'],
            k_values=[1, 3, 5, 10]
        )
        n_pass_at_k = self.pass_at_k_analyzer.load_results(
            exclude_models=EXCLUDED_MODELS,
            exclude_docs=EXCLUDED_DOCUMENTS
        )
        print(f"  ✅ Loaded {n_pass_at_k} runs for pass@k analysis")
    
    def generate_all(self):
        """Generate all analyses and visualizations."""
        print(f"\n{'='*80}")
        print("📊 FAIRiAgent Evaluation Analysis Report Generation")
        print(f"{'='*80}\n")
        
        print(f"📁 Output directory: {self.output_dir}")
        print(f"📊 Loaded {len(self.loader.evaluation_results)} evaluation runs")
        print(f"🤖 Found {len(self.model_df['model_name'].unique())} unique models")
        print(f"📄 Found {len(self.doc_df['document_id'].unique())} unique documents\n")
        
        # Generate visualizations
        print(f"{'='*80}")
        print("📈 Generating Visualizations")
        print(f"{'='*80}\n")
        
        self._generate_model_visualizations()
        self._generate_reliability_visualizations()
        self._generate_failure_visualizations()
        
        # Generate baseline comparisons (if available)
        if self.baseline_data:
            print(f"\n{'='*80}")
            print("📊 Generating Baseline Comparisons")
            print(f"{'='*80}\n")
            self._generate_baseline_comparisons()
        
        # Generate pass@k analysis
        print(f"\n{'='*80}")
        print("🎯 Generating Pass@k Analysis")
        print(f"{'='*80}\n")
        
        self._generate_pass_at_k_analysis()
        
        # Generate tables
        print(f"\n{'='*80}")
        print("📋 Generating Tables")
        print(f"{'='*80}\n")
        
        self._generate_tables()
        
        # Generate summary
        print(f"\n{'='*80}")
        print("📝 Generating Summary")
        print(f"{'='*80}\n")
        
        self._generate_summary()
        
        print(f"\n{'='*80}")
        print("✅ Analysis complete!")
        print(f"📁 Results saved to: {self.output_dir}")
        print(f"{'='*80}\n")
    
    def _generate_model_visualizations(self):
        """Generate model comparison visualizations."""
        print("  📊 Model Performance Visualizations:")
        
        self.model_viz.plot_model_comparison_heatmap(self.model_df)
        self.model_viz.plot_model_rankings(self.model_df, metric='aggregate_score')
        self.model_viz.plot_model_rankings(self.model_df, metric='completeness', filename='model_rankings_completeness')
        self.model_viz.plot_model_rankings(self.model_df, metric='correctness_f1', filename='model_rankings_correctness')
        self.model_viz.plot_metric_correlation(self.model_df)
        self.model_viz.plot_document_performance(self.doc_df)
    
    def _generate_reliability_visualizations(self):
        """Generate workflow reliability visualizations."""
        print("\n  🔄 Workflow Reliability Visualizations:")
        
        self.reliability_viz.plot_retry_rates(self.reliability_df)
        self.reliability_viz.plot_agent_retry_patterns(self.reliability_df)
        self.reliability_viz.plot_completion_rates(self.reliability_df)
    
    def _generate_failure_visualizations(self):
        """Generate failure analysis visualizations."""
        print("\n  ❌ Failure Analysis Visualizations:")
        
        self.failure_viz.plot_failure_by_agent(self.reliability_df)
        self.failure_viz.plot_failure_by_document(self.reliability_df)
        self.failure_viz.plot_failure_by_model(self.reliability_df)
    
    def _generate_baseline_comparisons(self):
        """Generate baseline vs agentic comparison visualizations."""
        if not self.agentic_data or not self.baseline_data:
            return
        
        print("  📊 Baseline Comparison Visualizations:")
        
        self.baseline_viz.create_overall_comparison(self.agentic_data, self.baseline_data)
        self.baseline_viz.create_comparison_by_document(self.agentic_data, self.baseline_data)
        self.baseline_viz.create_fields_by_document(self.agentic_data, self.baseline_data)
    
    def _generate_pass_at_k_analysis(self):
        """Generate pass@k analysis tables, visualizations, and report."""
        print("  📊 Pass@k Analysis (Tables):")
        
        # Generate summary table for each criteria preset
        for preset_name in ['lenient', 'moderate', 'strict']:
            self.pass_at_k_analyzer.criteria = CRITERIA_PRESETS[preset_name]
            
            summary_df = self.pass_at_k_analyzer.get_summary_dataframe()
            if not summary_df.empty:
                # Save CSV
                csv_path = self.tables_dir / f'pass_at_k_{preset_name}.csv'
                summary_df.to_csv(csv_path, index=False)
                
                # Save LaTeX
                # Select key columns for LaTeX
                latex_cols = ['model', 'total_runs', 'success_rate', 'pass@1', 'pass@3', 'pass@5', 'pass@10']
                latex_df = summary_df[[c for c in latex_cols if c in summary_df.columns]]
                latex_path = self.tables_dir / f'pass_at_k_{preset_name}.tex'
                latex_df.to_latex(latex_path, index=False, float_format='%.3f')
                
                print(f"    ✅ Saved: pass_at_k_{preset_name}.csv, pass_at_k_{preset_name}.tex")
        
        # Generate document-level pass@k (using moderate criteria)
        self.pass_at_k_analyzer.criteria = CRITERIA_PRESETS['moderate']
        summary_df = self.pass_at_k_analyzer.get_summary_dataframe()
        doc_df = self.pass_at_k_analyzer.get_document_level_dataframe()
        if not doc_df.empty:
            doc_df.to_csv(self.tables_dir / 'pass_at_k_by_document.csv', index=False)
            print(f"    ✅ Saved: pass_at_k_by_document.csv")
        
        # Generate multi-criteria comparison
        comparison_df = self.pass_at_k_analyzer.get_multi_criteria_comparison()
        if not comparison_df.empty:
            comparison_df.to_csv(self.tables_dir / 'pass_at_k_multi_criteria.csv', index=False)
            print(f"    ✅ Saved: pass_at_k_multi_criteria.csv")
        
        # Generate full JSON report
        report = self.pass_at_k_analyzer.generate_report(output_format='dict')
        report_path = self.data_dir / 'pass_at_k_report.json'
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"    ✅ Saved: pass_at_k_report.json")
        
        # Generate visualizations
        print("\n  📈 Pass@k Visualizations:")
        if not summary_df.empty:
            self.pass_at_k_viz.generate_all(summary_df, doc_df, comparison_df)
    
    def _generate_tables(self):
        """Generate LaTeX and CSV tables."""
        # Model rankings
        rankings = self.performance_analyzer.get_model_rankings()
        rankings.to_csv(self.tables_dir / 'model_rankings.csv')
        rankings.to_latex(self.tables_dir / 'model_rankings.tex', float_format='%.4f')
        print(f"  ✅ Saved: model_rankings.csv, model_rankings.tex")
        
        # Reliability summary
        reliability_summary = self.reliability_analyzer.get_reliability_summary()
        reliability_summary.to_csv(self.tables_dir / 'reliability_summary.csv')
        reliability_summary.to_latex(self.tables_dir / 'reliability_summary.tex', float_format='%.4f')
        print(f"  ✅ Saved: reliability_summary.csv, reliability_summary.tex")
        
        # Agent reliability
        agent_reliability = self.reliability_analyzer.get_agent_reliability()
        agent_reliability.to_csv(self.tables_dir / 'agent_reliability.csv')
        agent_reliability.to_latex(self.tables_dir / 'agent_reliability.tex', float_format='%.4f')
        print(f"  ✅ Saved: agent_reliability.csv, agent_reliability.tex")
        
        # Failure patterns
        failure_by_agent = self.failure_analyzer.get_failure_by_agent()
        failure_by_agent.to_csv(self.tables_dir / 'failure_by_agent.csv')
        failure_by_agent.to_latex(self.tables_dir / 'failure_by_agent.tex', float_format='%.4f')
        print(f"  ✅ Saved: failure_by_agent.csv, failure_by_agent.tex")
    
    def _generate_summary(self):
        """Generate summary JSON and markdown."""
        # Save processed data
        self.model_df.to_csv(self.data_dir / 'model_performance.csv', index=False)
        self.doc_df.to_csv(self.data_dir / 'document_performance.csv', index=False)
        self.reliability_df.to_csv(self.data_dir / 'workflow_reliability.csv', index=False)
        print(f"  ✅ Saved processed data to {self.data_dir}")
        
        # Generate summary statistics
        summary = {
            'generated_at': datetime.now().isoformat(),
            'n_runs': len(self.loader.evaluation_results),
            'n_models': len(self.model_df['model_name'].unique()),
            'n_documents': len(self.doc_df['document_id'].unique()),
            'model_rankings': self.performance_analyzer.get_model_rankings().to_dict(),
            'reliability_summary': self.reliability_analyzer.get_reliability_summary().to_dict(),
            'retry_patterns': self.reliability_analyzer.get_retry_patterns(),
            'pass_at_k': {
                'criteria': str(self.pass_at_k_analyzer.criteria),
                'summary': self.pass_at_k_analyzer.get_summary_dataframe().to_dict('records')
            }
        }
        
        with open(self.output_dir / 'analysis_summary.json', 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, default=str)
        
        print(f"  ✅ Saved: analysis_summary.json")








