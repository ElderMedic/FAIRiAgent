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
    FailurePatternAnalyzer
)
from ..visualizations import (
    ModelComparisonVisualizer,
    WorkflowReliabilityVisualizer,
    FailureAnalysisVisualizer
)


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
        
        # Initialize data loader
        self.loader = EvaluationDataLoader(self.runs_dir)
        self.loader.load_all(pattern)
        
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
            'retry_patterns': self.reliability_analyzer.get_retry_patterns()
        }
        
        with open(self.output_dir / 'analysis_summary.json', 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, default=str)
        
        print(f"  ✅ Saved: analysis_summary.json")








