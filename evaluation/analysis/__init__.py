"""
FAIRiAgent Evaluation Analysis Framework

Comprehensive data analysis and visualization for evaluation results.
Designed to easily incorporate new evaluation runs.
"""

from .data_loaders import EvaluationDataLoader
from .analyzers import (
    ModelPerformanceAnalyzer,
    WorkflowReliabilityAnalyzer,
    FailurePatternAnalyzer
)
from .visualizations import (
    ModelComparisonVisualizer,
    WorkflowReliabilityVisualizer,
    FailureAnalysisVisualizer
)
from .reports import ReportGenerator

__all__ = [
    'EvaluationDataLoader',
    'ModelPerformanceAnalyzer',
    'WorkflowReliabilityAnalyzer',
    'FailurePatternAnalyzer',
    'ModelComparisonVisualizer',
    'WorkflowReliabilityVisualizer',
    'FailureAnalysisVisualizer',
    'ReportGenerator'
]








