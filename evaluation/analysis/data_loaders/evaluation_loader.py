"""
Evaluation Data Loader

Automatically discovers and loads evaluation results from all runs.
Supports incremental addition of new runs.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import pandas as pd


class EvaluationDataLoader:
    """
    Load and aggregate evaluation results from multiple runs.
    
    Automatically discovers all evaluation_results.json files in the runs directory
    and provides a unified interface for analysis.
    """
    
    def __init__(self, runs_dir: Path):
        """
        Initialize data loader.
        
        Args:
            runs_dir: Path to evaluation/runs directory
        """
        self.runs_dir = Path(runs_dir)
        self.evaluation_results: Dict[str, Dict[str, Any]] = {}
        self.metadata: Dict[str, Dict[str, Any]] = {}
        
    def discover_runs(self, pattern: Optional[str] = None, exclude_dirs: Optional[List[str]] = None) -> List[Path]:
        """
        Discover all evaluation result files.
        
        Args:
            pattern: Optional pattern to filter runs (e.g., "qwen_*", "openai_*")
            exclude_dirs: Optional list of directory names to exclude (e.g., ["archive"])
            
        Returns:
            List of paths to evaluation_results.json files
        """
        results_files = []
        exclude_dirs = exclude_dirs or ['archive']  # Default exclude archive
        
        # Search for evaluation_results.json ONLY in results/ subdirectories
        # This avoids loading status log files that have the same name
        for results_file in self.runs_dir.rglob('results/evaluation_results.json'):
            run_path_str = str(results_file.relative_to(self.runs_dir))
            
            # Skip if in excluded directory
            skip = False
            for exclude_dir in exclude_dirs:
                if run_path_str.startswith(exclude_dir + '/') or f'/{exclude_dir}/' in run_path_str:
                    skip = True
                    break
            if skip:
                continue
            
            # Skip if pattern doesn't match
            if pattern:
                if pattern not in run_path_str:
                    continue
            
            results_files.append(results_file)
        
        return sorted(results_files)
    
    def load_all(self, pattern: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        Load all evaluation results.
        
        Args:
            pattern: Optional pattern to filter runs
            
        Returns:
            Dict mapping run_id to evaluation results
        """
        results_files = self.discover_runs(pattern)
        
        for results_file in results_files:
            try:
                with open(results_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Generate run identifier from path
                # e.g., "qwen_parallel_20251121_131718/qwen_max"
                rel_path = results_file.relative_to(self.runs_dir)
                run_id = str(rel_path.parent)
                
                self.evaluation_results[run_id] = data
                
                # Extract metadata
                eval_metadata = data.get('evaluation_metadata', {})
                self.metadata[run_id] = {
                    'run_id': run_id,
                    'start_time': eval_metadata.get('start_time'),
                    'end_time': eval_metadata.get('end_time'),
                    'ground_truth': eval_metadata.get('ground_truth'),
                    'n_documents': eval_metadata.get('n_documents', 0)
                }
                
            except Exception as e:
                print(f"⚠️  Failed to load {results_file}: {e}")
                continue
        
        print(f"✅ Loaded {len(self.evaluation_results)} evaluation runs")
        return self.evaluation_results
    
    def get_model_dataframe(self) -> pd.DataFrame:
        """
        Convert evaluation results to a pandas DataFrame for analysis.
        
        Returns:
            DataFrame with one row per model-document combination
        """
        rows = []
        
        for run_id, eval_data in self.evaluation_results.items():
            per_model = eval_data.get('per_model_results', {})
            
            for model_name, model_data in per_model.items():
                # Extract aggregate metrics
                completeness = model_data.get('completeness', {}).get('aggregated', {})
                correctness = model_data.get('correctness', {}).get('aggregated', {})
                schema = model_data.get('schema_validation', {}).get('aggregated', {})
                ontology = model_data.get('ontology', {}).get('aggregated', {})
                llm_judge = model_data.get('llm_judge', {}).get('aggregated', {})
                internal_metrics = model_data.get('internal_metrics', {}).get('aggregated', {})
                
                row = {
                    'run_id': run_id,
                    'model_name': model_name,
                    'aggregate_score': model_data.get('aggregate_score', 0.0),
                    
                    # Completeness
                    'completeness': completeness.get('mean_overall_completeness', 0.0),
                    'required_completeness': completeness.get('mean_required_completeness', 0.0),
                    'recommended_completeness': completeness.get('mean_recommended_completeness', 0.0),
                    
                    # Correctness
                    'correctness_f1': correctness.get('mean_f1_score', 0.0),
                    'field_presence_rate': correctness.get('mean_field_presence_rate', 0.0),
                    'precision': correctness.get('mean_precision', 0.0),
                    'recall': correctness.get('mean_recall', 0.0),
                    
                    # Schema
                    'schema_compliance': schema.get('mean_compliance_rate', 0.0),
                    
                    # Ontology
                    'ontology_usage_rate': ontology.get('mean_ontology_usage_rate', 0.0),
                    
                    # LLM Judge
                    'llm_judge_score': llm_judge.get('mean_overall_score', 0.0),
                    
                    # Internal metrics
                    'internal_confidence': internal_metrics.get('mean_overall_confidence', 0.0),
                    'critic_confidence': internal_metrics.get('mean_critic_confidence', 0.0),
                    'field_confidence': internal_metrics.get('mean_field_confidence', 0.0),
                    'retry_rate': internal_metrics.get('mean_retry_rate', 0.0),
                    'review_rate': internal_metrics.get('review_rate', 0.0),
                    
                    # Document count
                    'n_documents': internal_metrics.get('n_documents', 0)
                }
                
                rows.append(row)
        
        return pd.DataFrame(rows)
    
    def get_document_level_dataframe(self) -> pd.DataFrame:
        """
        Get document-level metrics.
        
        Returns:
            DataFrame with one row per model-document combination
        """
        rows = []
        
        for run_id, eval_data in self.evaluation_results.items():
            per_model = eval_data.get('per_model_results', {})
            
            for model_name, model_data in per_model.items():
                # Get per-document metrics
                completeness_per_doc = model_data.get('completeness', {}).get('per_document', {})
                correctness_per_doc = model_data.get('correctness', {}).get('per_document', {})
                internal_per_doc = model_data.get('internal_metrics', {}).get('per_document', {})
                
                for doc_id in completeness_per_doc.keys():
                    comp = completeness_per_doc.get(doc_id, {})
                    corr = correctness_per_doc.get(doc_id, {})
                    internal = internal_per_doc.get(doc_id, {})
                    retry_analysis = internal.get('retry_analysis', {})
                    
                    row = {
                        'run_id': run_id,
                        'model_name': model_name,
                        'document_id': doc_id,
                        
                        # Completeness
                        'completeness': comp.get('overall_metrics', {}).get('overall_completeness', 0.0),
                        'required_completeness': comp.get('overall_metrics', {}).get('required_completeness', 0.0),
                        
                        # Correctness
                        'correctness_f1': corr.get('summary_metrics', {}).get('f1_score', 0.0),
                        'field_presence_rate': corr.get('summary_metrics', {}).get('field_presence_rate', 0.0),
                        
                        # Internal metrics
                        'overall_confidence': internal.get('metadata_confidence', {}).get('overall_confidence', 0.0),
                        'workflow_status': retry_analysis.get('workflow_status', 'unknown'),
                        'failed_steps': retry_analysis.get('failed_steps', 0),
                        'steps_requiring_retry': retry_analysis.get('steps_requiring_retry', 0),
                        'retry_rate': retry_analysis.get('retry_rate', 0.0),
                        'needs_review': retry_analysis.get('needs_human_review', False)
                    }
                    
                    rows.append(row)
        
        return pd.DataFrame(rows)
    
    def get_workflow_reliability_dataframe(self) -> pd.DataFrame:
        """
        Get workflow reliability metrics (retries, failures, etc.).
        Includes both successful and failed runs.
        
        Returns:
            DataFrame with workflow reliability metrics
        """
        rows = []
        
        # First, get data from evaluation results (completed runs)
        for run_id, eval_data in self.evaluation_results.items():
            per_model = eval_data.get('per_model_results', {})
            
            for model_name, model_data in per_model.items():
                internal_per_doc = model_data.get('internal_metrics', {}).get('per_document', {})
                
                for doc_id, doc_metrics in internal_per_doc.items():
                    retry_analysis = doc_metrics.get('retry_analysis', {})
                    agent_retries = retry_analysis.get('agent_retry_details', {})
                    agent_failures = retry_analysis.get('agent_failure_details', {})
                    
                    row = {
                        'run_id': run_id,
                        'model_name': model_name,
                        'document_id': doc_id,
                        'workflow_status': retry_analysis.get('workflow_status', 'completed'),
                        'total_steps': retry_analysis.get('total_steps', 0),
                        'successful_steps': retry_analysis.get('successful_steps', 0),
                        'failed_steps': retry_analysis.get('failed_steps', 0),
                        'steps_requiring_retry': retry_analysis.get('steps_requiring_retry', 0),
                        'retry_rate': retry_analysis.get('retry_rate', 0.0),
                        'needs_human_review': retry_analysis.get('needs_human_review', False),
                        'is_completed': True
                    }
                    
                    # Add agent-specific retry/failure counts
                    for agent_name in ['DocumentParser', 'KnowledgeRetriever', 'JSONGenerator', 'Critic', 'Validator']:
                        if agent_retries and agent_name in agent_retries:
                            row[f'{agent_name}_retries'] = agent_retries[agent_name].get('retries', 0)
                        else:
                            row[f'{agent_name}_retries'] = 0
                        
                        if agent_failures and agent_name in agent_failures:
                            row[f'{agent_name}_failures'] = agent_failures[agent_name].get('failed_attempts', 0)
                        else:
                            row[f'{agent_name}_failures'] = 0
                    
                    rows.append(row)
        
        # Also scan for failed runs (those with eval_result.json but no metadata_json.json or failed status)
        for run_dir in self.runs_dir.rglob('*'):
            if not run_dir.is_dir():
                continue
            
            # Look for eval_result.json files
            eval_result_files = list(run_dir.glob('eval_result.json'))
            
            for eval_file in eval_result_files:
                try:
                    with open(eval_file, 'r', encoding='utf-8') as f:
                        eval_result = json.load(f)
                    
                    # Check if this is a failed run
                    if not eval_result.get('success', True):
                        # Extract run info from path
                        # e.g., evaluation/runs/qwen_parallel_20251121_131741/qwen_plus/outputs/qwen_plus/earthworm/run_1/eval_result.json
                        parts = eval_file.parts
                        
                        # Try to find model name and document ID from path
                        model_name = None
                        doc_id = None
                        run_id = None
                        
                        for i, part in enumerate(parts):
                            if part == 'outputs' and i + 1 < len(parts):
                                model_name = parts[i + 1]
                            if part in ['earthworm', 'biosensor', 'biorem']:
                                doc_id = part
                            if part.startswith('run_'):
                                # Get parent directories for run_id
                                rel_path = eval_file.relative_to(self.runs_dir)
                                run_id = str(rel_path.parents[3])  # Go up to model config level
                        
                        if model_name and doc_id:
                            error_msg = eval_result.get('error', 'Unknown error')
                            
                            # Determine failure type
                            failure_type = 'unknown'
                            if 'JSON parsing' in error_msg or 'JSON' in error_msg:
                                failure_type = 'json_parsing'
                            elif 'timeout' in error_msg.lower():
                                failure_type = 'timeout'
                            elif 'API' in error_msg or 'network' in error_msg.lower():
                                failure_type = 'api_error'
                            
                            row = {
                                'run_id': run_id or 'unknown',
                                'model_name': model_name,
                                'document_id': doc_id,
                                'workflow_status': 'failed',
                                'total_steps': 0,
                                'successful_steps': 0,
                                'failed_steps': 1,
                                'steps_requiring_retry': 0,
                                'retry_rate': 0.0,
                                'needs_human_review': True,
                                'is_completed': False,
                                'failure_type': failure_type,
                                'error_message': error_msg[:200]  # Truncate long errors
                            }
                            
                            # Initialize agent counts
                            for agent_name in ['DocumentParser', 'KnowledgeRetriever', 'JSONGenerator', 'Critic', 'Validator']:
                                row[f'{agent_name}_retries'] = 0
                                row[f'{agent_name}_failures'] = 0
                            
                            rows.append(row)
                            
                except Exception as e:
                    continue
        
        return pd.DataFrame(rows)

