"""
Evaluation modules for FAIRiAgent outputs.
"""

from .completeness_evaluator import CompletenessEvaluator
from .correctness_evaluator import CorrectnessEvaluator
from .schema_validator import SchemaValidator
from .ontology_evaluator import OntologyEvaluator
from .llm_judge_evaluator import LLMJudgeEvaluator
from .internal_metrics_evaluator import InternalMetricsEvaluator
from .retrieval_coverage_evaluator import RetrievalCoverageEvaluator
from .value_accuracy_evaluator import ValueAccuracyEvaluator
from .structural_evaluator import StructuralEvaluator
from .novel_field_evaluator import NovelFieldEvaluator, find_source_text
from .nli_evaluator import NLIFaithfulnessEvaluator

__all__ = [
    'CompletenessEvaluator',
    'CorrectnessEvaluator',
    'SchemaValidator',
    'OntologyEvaluator',
    'LLMJudgeEvaluator',
    'InternalMetricsEvaluator',
    'RetrievalCoverageEvaluator',
    # Evaluation-metrics redesign (Layers 2-4 + calibration fast-follow)
    'ValueAccuracyEvaluator',
    'StructuralEvaluator',
    'NovelFieldEvaluator',
    'NLIFaithfulnessEvaluator',
    'find_source_text',
    'calibration',
]
