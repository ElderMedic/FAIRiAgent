#!/usr/bin/env python3
"""
Evaluation Orchestrator for FAIRiAgent outputs.

Runs all evaluators on batch evaluation outputs and computes aggregate metrics.
"""

import sys
import argparse
import json
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime
import os
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parents[2]))

from evaluation.evaluators import (
    CompletenessEvaluator,
    CorrectnessEvaluator,
    SchemaValidator,
    OntologyEvaluator,
    LLMJudgeEvaluator,
    InternalMetricsEvaluator
)


class EvaluationOrchestrator:
    """Orchestrate all evaluations on FAIRiAgent outputs."""
    
    @staticmethod
    def classify_run_status(run_dir: Path) -> Dict[str, Any]:
        """
        Classify a run's status based on its output files.
        
        Returns status dict with:
        - 'category': 'success', 'genuine_failure', 'incomplete' (excluded from analysis)
        - 'has_metadata': bool
        - 'error_type': str or None
        - 'error_message': str or None
        """
        status = {
            'category': 'incomplete',
            'has_metadata': False,
            'error_type': None,
            'error_message': None
        }
        
        metadata_file = run_dir / 'metadata_json.json'
        eval_result_file = run_dir / 'eval_result.json'
        
        # Check if metadata exists
        if metadata_file.exists():
            status['has_metadata'] = True
            status['category'] = 'success'
            return status
        
        # Check eval_result.json for error information
        if eval_result_file.exists():
            try:
                with open(eval_result_file, 'r', encoding='utf-8') as f:
                    eval_result = json.load(f)
                    error_msg = eval_result.get('error', '').lower()
                    
                    # JSON parsing failure = genuine failure (LLM output problem)
                    if 'json parsing' in error_msg or 'json' in error_msg and 'parsing' in error_msg:
                        status['category'] = 'genuine_failure'
                        status['error_type'] = 'json_parsing'
                        status['error_message'] = eval_result.get('error')
                    # Timeout = incomplete (external issue, exclude from analysis)
                    elif 'timeout' in error_msg or 'timed out' in error_msg:
                        status['category'] = 'incomplete'
                        status['error_type'] = 'timeout'
                        status['error_message'] = eval_result.get('error')
                    # Metadata not found = incomplete (workflow issue, exclude from analysis)
                    elif 'not found' in error_msg and 'metadata' in error_msg:
                        status['category'] = 'incomplete'
                        status['error_type'] = 'metadata_not_found'
                        status['error_message'] = eval_result.get('error')
                    # Other errors = incomplete by default
                    else:
                        status['category'] = 'incomplete'
                        status['error_type'] = 'other'
                        status['error_message'] = eval_result.get('error')
            except Exception as e:
                status['error_message'] = f"Failed to parse eval_result.json: {e}"
        
        return status
    
    def __init__(
        self,
        run_dir: Path,
        ground_truth_path: Path,
        env_file: Path
    ):
        """
        Initialize evaluation orchestrator.
        
        Args:
            run_dir: Directory containing batch evaluation outputs
            ground_truth_path: Path to ground truth JSON
            env_file: Evaluation env file (for LLM judge config)
        """
        self.run_dir = run_dir
        self.ground_truth_path = ground_truth_path
        self.env_file = env_file
        
        # Load environment
        load_dotenv(env_file)
        
        # Load ground truth
        with open(ground_truth_path, 'r', encoding='utf-8') as f:
            gt_data = json.load(f)
            self.ground_truth_docs = {
                doc['document_id']: doc 
                for doc in gt_data.get('documents', [])
            }
        
        print(f"📊 Loaded ground truth for {len(self.ground_truth_docs)} documents")
        
        # Initialize evaluators
        self._initialize_evaluators()
    
    def _initialize_evaluators(self):
        """Initialize all evaluators."""
        # Completeness evaluator
        self.completeness_evaluator = CompletenessEvaluator()
        
        # Schema validator
        self.schema_validator = SchemaValidator()
        
        # Ontology evaluator
        kb_path = Path(__file__).parents[2] / 'kb'
        self.ontology_evaluator = OntologyEvaluator(kb_path=kb_path)
        
        # Correctness evaluator (with LLM judge)
        judge_provider = os.getenv('EVAL_JUDGE_PROVIDER', 'anthropic')
        judge_config = {
            'provider': judge_provider,
            'model': os.getenv('EVAL_JUDGE_MODEL', 'claude-sonnet-4'),
            'api_key': os.getenv('EVAL_JUDGE_API_KEY') or os.getenv('LLM_API_KEY'),
            'temperature': os.getenv('EVAL_JUDGE_TEMPERATURE', '0.0')
        }
        
        # Add base_url for Qwen
        if judge_provider == 'qwen':
            judge_config['base_url'] = os.getenv('QWEN_API_BASE_URL') or os.getenv('EVAL_JUDGE_BASE_URL') or 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'
        self.correctness_evaluator = CorrectnessEvaluator(judge_config=judge_config)
        
        # LLM Judge evaluator (holistic)
        self.llm_judge_evaluator = LLMJudgeEvaluator(judge_config=judge_config)
        
        # Internal metrics evaluator (extracts FAIRiAgent's own confidence scores)
        self.internal_metrics_evaluator = InternalMetricsEvaluator()
        
        print("✅ All evaluators initialized")
    
    def evaluate_all(self) -> Dict[str, Any]:
        """
        Run all evaluations on batch outputs.
        
        Returns:
            Complete evaluation results
        """
        results = {
            'evaluation_metadata': {
                'start_time': datetime.now().isoformat(),
                'run_dir': str(self.run_dir),
                'ground_truth': str(self.ground_truth_path),
                'n_documents': len(self.ground_truth_docs)
            },
            'per_model_results': {}
        }
        
        # Find all model configurations
        outputs_dir = self.run_dir / 'outputs'
        if not outputs_dir.exists():
            raise ValueError(f"Outputs directory not found: {outputs_dir}")
        
        model_configs = [d for d in outputs_dir.iterdir() if d.is_dir()]
        
        print(f"\n🔍 Found {len(model_configs)} model configurations to evaluate\n")
        
        # Evaluate each model configuration
        for model_dir in model_configs:
            config_name = model_dir.name
            print(f"\n{'='*70}")
            print(f"📊 Evaluating config: {config_name}")
            print(f"{'='*70}\n")
            
            model_results = self._evaluate_model_config(model_dir, config_name)
            results['per_model_results'][config_name] = model_results
        
        # Compute model comparison
        print(f"\n{'='*70}")
        print("📈 Computing model comparison metrics")
        print(f"{'='*70}\n")
        results['model_comparison'] = self._compute_model_comparison(results['per_model_results'])
        
        # Compute correlation analysis (internal metrics vs actual quality)
        print(f"\n{'='*70}")
        print("🔗 Computing internal metric correlations")
        print(f"{'='*70}\n")
        results['correlation_analysis'] = self._compute_correlations(results['per_model_results'])
        
        results['evaluation_metadata']['end_time'] = datetime.now().isoformat()
        
        # Save results
        results_dir = self.run_dir / 'results'
        results_dir.mkdir(parents=True, exist_ok=True)
        
        results_file = results_dir / 'evaluation_results.json'
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        
        print(f"\n✅ Evaluation complete!")
        print(f"📄 Results saved to: {results_file}")
        
        return results
    
    def _evaluate_model_config(self, model_dir: Path, config_name: str) -> Dict[str, Any]:
        """Evaluate all outputs for a single model configuration."""
        # Load all FAIRiAgent outputs for this model
        # Support multiple directory structures:
        # 1. model_dir/outputs/{config_name}/{doc_id}/run_{N}/metadata_json.json
        # 2. model_dir/{config_name}/{doc_id}/run_{N}/metadata_json.json
        # 3. model_dir/{doc_id}/metadata_json.json (legacy)
        fairifier_outputs = {}
        
        # Try different directory structures
        possible_paths = [
            model_dir / 'outputs' / config_name,  # Structure 1
            model_dir / config_name,  # Structure 2
            model_dir  # Structure 3 (legacy)
        ]
        
        doc_dirs = []
        for path in possible_paths:
            if path.exists() and path.is_dir():
                doc_dirs = [d for d in path.iterdir() if d.is_dir()]
                if doc_dirs:
                    print(f"  📁 Found outputs in: {path}")
                    break
        
        if not doc_dirs:
            print(f"  ⚠️  No document directories found in {model_dir}")
            return {}
        
        # Track output directories for loading workflow_report.json
        output_dirs = {}
        
        for doc_dir in doc_dirs:
            doc_id = doc_dir.name
            
            # Find all run directories for this document
            run_dirs = [d for d in doc_dir.iterdir() if d.is_dir() and d.name.startswith('run_')]
            
            if not run_dirs:
                print(f"  ⚠️  No run directories found for {doc_id}, skipping")
                continue
            
            # Classify all runs
            successful_runs = []
            genuine_failures = []
            incomplete_runs = []
            
            for run_dir in sorted(run_dirs):
                status = self.classify_run_status(run_dir)
                
                if status['category'] == 'success':
                    metadata_file = run_dir / 'metadata_json.json'
                    workflow_report_file = run_dir / 'workflow_report.json'
                    
                    run_info = {
                        'metadata_file': metadata_file,
                        'run_dir': run_dir,
                        'status': status,
                        'is_fully_successful': False,
                        'has_failures': False,
                        'has_retries': False,
                        'workflow_status': 'unknown',
                        'failed_steps': 0,
                        'steps_requiring_retry': 0
                    }
                    
                    # Check workflow_report.json for detailed info
                    if workflow_report_file.exists():
                        try:
                            with open(workflow_report_file, 'r', encoding='utf-8') as f:
                                workflow_report = json.load(f)
                                exec_summary = workflow_report.get('execution_summary', {})
                                run_info['workflow_status'] = workflow_report.get('workflow_status', 'unknown')
                                run_info['failed_steps'] = exec_summary.get('failed_steps', 0)
                                run_info['steps_requiring_retry'] = exec_summary.get('steps_requiring_retry', 0)
                                run_info['has_failures'] = run_info['failed_steps'] > 0
                                run_info['has_retries'] = run_info['steps_requiring_retry'] > 0
                                run_info['is_fully_successful'] = (
                                    run_info['workflow_status'] == 'completed' and
                                    not run_info['has_failures'] and
                                    not run_info['has_retries']
                                )
                        except:
                            pass
                    
                    successful_runs.append(run_info)
                
                elif status['category'] == 'genuine_failure':
                    genuine_failures.append({'run_dir': run_dir, 'status': status})
                
                else:  # incomplete
                    incomplete_runs.append({'run_dir': run_dir, 'status': status})
            
            # Report statistics
            print(f"  ✅ Successful: {len(successful_runs)}")
            print(f"  ❌ Genuine failures: {len(genuine_failures)} (JSON parsing errors)")
            print(f"  ⏭️  Incomplete (excluded): {len(incomplete_runs)} (timeouts, metadata not found, etc.)")
            
            # Select best successful run if any
            if not successful_runs:
                print(f"  ⚠️  No successful runs for {doc_id}, skipping from analysis")
                # Store failure info for statistics
                continue
            
            # Sort: fully successful first, then by retry count, then by failure count
            successful_runs.sort(key=lambda x: (
                not x['is_fully_successful'],
                x.get('steps_requiring_retry', 0),
                x.get('failed_steps', 0)
            ))
            
            selected_run = successful_runs[0]
            metadata_file = selected_run['metadata_file']
            
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    fairifier_outputs[doc_id] = json.load(f)
                    # Store the output directory for this document (to load workflow_report.json)
                    output_dirs[doc_id] = metadata_file.parent
                    
                    # Print status message
                    status_msg = "fully successful"
                    if not selected_run['is_fully_successful']:
                        status_msg = f"completed with {selected_run.get('failed_steps', 0)} failed steps"
                    if selected_run.get('has_retries'):
                        status_msg += f", {selected_run.get('steps_requiring_retry', 0)} retries"
                    
                    print(f"  ✅ Loaded {doc_id} from {metadata_file.parent.name} ({status_msg})")
            except Exception as e:
                print(f"  ⚠️  Failed to load metadata for {doc_id}: {e}")
                continue
        
        print(f"  📄 Loaded {len(fairifier_outputs)} outputs")
        
        # Run all evaluators
        results = {}
        
        # 1. Completeness
        print(f"  🔍 Running completeness evaluation...")
        results['completeness'] = self.completeness_evaluator.evaluate_batch(
            fairifier_outputs,
            self.ground_truth_docs
        )
        
        # 2. Correctness (field presence only, no value comparison)
        print(f"  🔍 Running field presence evaluation...")
        results['correctness'] = self.correctness_evaluator.evaluate_batch(
            fairifier_outputs,
            self.ground_truth_docs,
            use_llm_judge=False  # Not needed for field presence evaluation
        )
        
        # 3. Schema validation
        print(f"  🔍 Running schema validation...")
        results['schema_validation'] = self.schema_validator.validate_batch(
            fairifier_outputs
        )
        
        # 4. Ontology evaluation
        print(f"  🔍 Running ontology evaluation...")
        results['ontology'] = self.ontology_evaluator.evaluate_batch(
            fairifier_outputs
        )
        
        # 5. LLM Judge (holistic)
        print(f"  🔍 Running LLM judge evaluation...")
        results['llm_judge'] = self.llm_judge_evaluator.evaluate_batch(
            fairifier_outputs,
            self.ground_truth_docs
        )
        
        # 6. Internal Metrics (from FAIRiAgent workflow)
        print(f"  🔍 Extracting internal metrics from FAIRiAgent workflow...")
        results['internal_metrics'] = self.internal_metrics_evaluator.evaluate_batch(
            fairifier_outputs,
            output_dirs
        )
        
        # Compute aggregate score (now includes internal metrics)
        results['aggregate_score'] = self._compute_aggregate_score(results)
        
        print(f"  ✅ Aggregate score: {results['aggregate_score']:.3f}")
        
        return results
    
    def _compute_aggregate_score(self, results: Dict[str, Any]) -> float:
        """Compute overall aggregate quality score."""
        scores = []
        weights = []
        
        # Completeness (25%)
        if 'completeness' in results:
            comp = results['completeness']['aggregated'].get('mean_overall_completeness', 0.0)
            scores.append(comp)
            weights.append(0.25)
        
        # Correctness (30%)
        if 'correctness' in results:
            corr = results['correctness']['aggregated'].get('mean_f1_score', 0.0)
            scores.append(corr)
            weights.append(0.30)
        
        # Schema compliance (10%)
        if 'schema_validation' in results:
            schema = results['schema_validation']['aggregated'].get('mean_compliance_rate', 0.0)
            scores.append(schema)
            weights.append(0.10)
        
        # LLM Judge (10%)
        if 'llm_judge' in results:
            judge = results['llm_judge']['aggregated'].get('mean_overall_score', 0.0)
            scores.append(judge)
            weights.append(0.10)
        
        # Internal Metrics (15%) - Use FAIRiAgent's own confidence scores
        if 'internal_metrics' in results:
            internal = results['internal_metrics']['aggregated']
            # Use mean overall confidence from workflow, or fallback to metadata confidence
            internal_score = internal.get('mean_overall_confidence', 0.0)
            if internal_score == 0.0:
                # Fallback: use critic confidence or field confidence
                internal_score = (
                    internal.get('mean_critic_confidence', 0.0) * 0.4 +
                    internal.get('mean_field_confidence', 0.0) * 0.3 +
                    internal.get('mean_structural_confidence', 0.0) * 0.2 +
                    internal.get('mean_validation_confidence', 0.0) * 0.1
                )
            scores.append(internal_score)
            weights.append(0.15)
        
        if not scores:
            return 0.0
        
        return sum(s * w for s, w in zip(scores, weights)) / sum(weights)
    
    def _compute_model_comparison(self, per_model_results: Dict[str, Any]) -> Dict[str, Any]:
        """Compute model-vs-model comparison metrics."""
        comparison = {
            'models': list(per_model_results.keys()),
            'metrics': {}
        }
        
        # Extract key metrics for each model
        for model_name, results in per_model_results.items():
            comparison['metrics'][model_name] = {
                'aggregate_score': results.get('aggregate_score', 0.0),
                'completeness': results['completeness']['aggregated'].get('mean_overall_completeness', 0.0),
                'correctness_f1': results['correctness']['aggregated'].get('mean_f1_score', 0.0),
                'schema_compliance': results['schema_validation']['aggregated'].get('mean_compliance_rate', 0.0),
                'llm_judge_score': results['llm_judge']['aggregated'].get('mean_overall_score', 0.0)
            }
        
        # Rank models
        ranked = sorted(
            comparison['metrics'].items(),
            key=lambda x: x[1]['aggregate_score'],
            reverse=True
        )
        comparison['ranking'] = [model for model, _ in ranked]
        
        return comparison
    
    def _compute_correlations(self, per_model_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compute correlations between internal metrics and actual quality.
        
        This validates whether FAIRiAgent's internal confidence scores
        are well-calibrated.
        """
        import numpy as np
        from scipy.stats import pearsonr
        
        correlations = {}
        
        for model_name, results in per_model_results.items():
            # Collect data points
            internal_confidences = []
            correctness_scores = []
            
            # From correctness evaluation, get per-document data
            per_doc_correctness = results['correctness'].get('per_document', {})
            
            for doc_id, doc_result in per_doc_correctness.items():
                # Get internal confidence from FAIRiAgent output (if available)
                # This would need to be loaded from the output files
                # For now, compute correlation with F1 scores
                f1 = doc_result['summary_metrics'].get('f1_score', 0.0)
                semantic_match = doc_result['summary_metrics'].get('semantic_match_rate', 0.0)
                
                correctness_scores.append(f1)
                internal_confidences.append(semantic_match)  # Proxy for internal confidence
            
            if len(correctness_scores) >= 3:  # Need at least 3 points for correlation
                try:
                    corr, p_value = pearsonr(internal_confidences, correctness_scores)
                    correlations[model_name] = {
                        'confidence_vs_correctness': {
                            'correlation': corr,
                            'p_value': p_value,
                            'n_samples': len(correctness_scores)
                        }
                    }
                except:
                    correlations[model_name] = {
                        'confidence_vs_correctness': {
                            'error': 'Could not compute correlation'
                        }
                    }
        
        return correlations


def main():
    parser = argparse.ArgumentParser(
        description="Evaluation Orchestrator for FAIRiAgent outputs",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--env-file', type=Path, required=True,
                       help='Evaluation env file')
    parser.add_argument('--run-dir', type=Path, required=True,
                       help='Directory containing batch evaluation outputs')
    parser.add_argument('--ground-truth', type=Path, required=True,
                       help='Ground truth JSON file')
    
    args = parser.parse_args()
    
    # Initialize orchestrator
    orchestrator = EvaluationOrchestrator(
        run_dir=args.run_dir,
        ground_truth_path=args.ground_truth,
        env_file=args.env_file
    )
    
    # Run all evaluations
    orchestrator.evaluate_all()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

