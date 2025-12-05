"""
Internal Metrics Evaluator for FAIRiAgent.

Extracts and analyzes confidence scores, critic judgments, and quality metrics
that are generated during the FAIRiAgent workflow execution.
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
import json


class InternalMetricsEvaluator:
    """
    Evaluator for internal FAIRiAgent metrics.
    
    Extracts:
    - Overall confidence scores
    - Critic confidence scores
    - Structural confidence scores
    - Validation confidence scores
    - Field-level confidence scores
    - Critic decisions (ACCEPT/RETRY/ESCALATE)
    - Quality metrics (confirmed vs provisional fields)
    - Retry patterns
    - Human review flags
    """
    
    def __init__(self):
        """Initialize internal metrics evaluator."""
        pass
    
    def evaluate_document(
        self,
        metadata_json: Dict[str, Any],
        workflow_report: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Evaluate a single document's internal metrics.
        
        Args:
            metadata_json: FAIRiAgent metadata_json.json content
            workflow_report: FAIRiAgent workflow_report.json content (optional)
            
        Returns:
            Dict with internal metrics analysis
        """
        result = {
            'metadata_confidence': {},
            'field_confidence_stats': {},
            'workflow_quality_metrics': {},
            'critic_analysis': {},
            'retry_analysis': {},
            'human_review_flags': {}
        }
        
        # Extract from metadata_json.json
        result['metadata_confidence'] = {
            'overall_confidence': metadata_json.get('overall_confidence', 0.0),
            'needs_review': metadata_json.get('needs_review', False)
        }
        
        # Extract field-level confidence scores
        field_confidences = []
        confirmed_fields = 0
        provisional_fields = 0
        
        isa_structure = metadata_json.get('isa_structure', {})
        for sheet_name, sheet_data in isa_structure.items():
            if sheet_name == 'description':
                continue
            
            for field in sheet_data.get('fields', []):
                confidence = field.get('confidence', 0.0)
                field_confidences.append(confidence)
                
                status = field.get('status', 'unknown')
                if status == 'confirmed':
                    confirmed_fields += 1
                elif status == 'provisional':
                    provisional_fields += 1
        
        if field_confidences:
            result['field_confidence_stats'] = {
                'mean_confidence': sum(field_confidences) / len(field_confidences),
                'min_confidence': min(field_confidences),
                'max_confidence': max(field_confidences),
                'median_confidence': sorted(field_confidences)[len(field_confidences) // 2],
                'high_confidence_fields': sum(1 for c in field_confidences if c >= 0.8),
                'medium_confidence_fields': sum(1 for c in field_confidences if 0.5 <= c < 0.8),
                'low_confidence_fields': sum(1 for c in field_confidences if c < 0.5),
                'total_fields': len(field_confidences),
                'confirmed_fields': confirmed_fields,
                'provisional_fields': provisional_fields,
                'confirmation_rate': confirmed_fields / len(field_confidences) if field_confidences else 0.0
            }
        
        # Extract from workflow_report.json if available
        if workflow_report:
            quality_metrics = workflow_report.get('quality_metrics', {})
            result['workflow_quality_metrics'] = {
                'overall_confidence': quality_metrics.get('overall_confidence', 0.0),
                'critic_confidence': quality_metrics.get('critic_confidence', 0.0),
                'structural_confidence': quality_metrics.get('structural_confidence', 0.0),
                'validation_confidence': quality_metrics.get('validation_confidence', 0.0),
                'metadata_overall_confidence': quality_metrics.get('metadata_overall_confidence', 0.0),
                'total_fields': quality_metrics.get('total_fields', 0),
                'confirmed_fields': quality_metrics.get('confirmed_fields', 0),
                'provisional_fields': quality_metrics.get('provisional_fields', 0),
                'needs_review': quality_metrics.get('needs_review', False)
            }
            
            # Execution summary
            execution_summary = workflow_report.get('execution_summary', {})
            result['retry_analysis'] = {
                'total_steps': execution_summary.get('total_steps', 0),
                'successful_steps': execution_summary.get('successful_steps', 0),
                'failed_steps': execution_summary.get('failed_steps', 0),
                'steps_requiring_retry': execution_summary.get('steps_requiring_retry', 0),
                'retry_rate': execution_summary.get('steps_requiring_retry', 0) / execution_summary.get('total_steps', 1) if execution_summary.get('total_steps', 0) > 0 else 0.0,
                'needs_human_review': execution_summary.get('needs_human_review', False),
                'workflow_status': workflow_report.get('workflow_status', 'unknown')
            }
            
            # Agents execution details - record all agents, not just those with retries
            agents_executed = execution_summary.get('agents_executed', {})
            agent_retry_details = {}
            agent_failure_details = {}
            
            for agent_name, agent_stats in agents_executed.items():
                total_attempts = agent_stats.get('total_attempts', 1)
                successful = agent_stats.get('successful', 0)
                failed = agent_stats.get('failed', 0)
                
                # Record retry details for agents with retries
                if total_attempts > 1:
                    agent_retry_details[agent_name] = {
                        'total_attempts': total_attempts,
                        'retries': total_attempts - 1,
                        'successful': successful,
                        'failed': failed
                    }
                
                # Record failure details for agents with failures
                if failed > 0:
                    agent_failure_details[agent_name] = {
                        'total_attempts': total_attempts,
                        'successful_attempts': successful,
                        'failed_attempts': failed,
                        'retries': total_attempts - 1 if total_attempts > 1 else 0
                    }
            
            if agent_retry_details:
                result['retry_analysis']['agent_retry_details'] = agent_retry_details
            if agent_failure_details:
                result['retry_analysis']['agent_failure_details'] = agent_failure_details
            
            # Timeline failures (from workflow_report timeline if available)
            timeline = workflow_report.get('timeline', [])
            failed_attempts = []
            for entry in timeline:
                if not entry.get('success', True):
                    failed_attempts.append({
                        'agent': entry.get('agent'),
                        'attempt': entry.get('attempt'),
                        'start_time': entry.get('start_time'),
                        'end_time': entry.get('end_time')
                    })
            
            if failed_attempts:
                result['retry_analysis']['failed_attempts_timeline'] = failed_attempts
        
        # Human review flags
        result['human_review_flags'] = {
            'needs_review_metadata': metadata_json.get('needs_review', False),
            'needs_review_workflow': workflow_report.get('execution_summary', {}).get('needs_human_review', False) if workflow_report else False,
            'low_overall_confidence': result['metadata_confidence']['overall_confidence'] < 0.7,
            'high_provisional_rate': result['field_confidence_stats'].get('confirmation_rate', 1.0) < 0.7 if result['field_confidence_stats'] else False
        }
        
        return result
    
    def evaluate_batch(
        self,
        fairifier_outputs: Dict[str, Dict[str, Any]],
        output_dirs: Optional[Dict[str, Path]] = None
    ) -> Dict[str, Any]:
        """
        Evaluate internal metrics for a batch of documents.
        
        Args:
            fairifier_outputs: Dict mapping doc_id to metadata_json.json content
            output_dirs: Optional dict mapping doc_id to output directory path (to load workflow_report.json)
            
        Returns:
            Dict with per-document and aggregated metrics
        """
        per_document = {}
        
        for doc_id, metadata_json in fairifier_outputs.items():
            # Try to load workflow_report.json if output_dirs provided
            workflow_report = None
            if output_dirs and doc_id in output_dirs:
                output_dir = output_dirs[doc_id]
                workflow_report_path = output_dir / 'workflow_report.json'
                if workflow_report_path.exists():
                    try:
                        with open(workflow_report_path, 'r', encoding='utf-8') as f:
                            workflow_report = json.load(f)
                    except Exception as e:
                        pass  # Silently skip if can't load
        
            per_document[doc_id] = self.evaluate_document(metadata_json, workflow_report)
        
        # Aggregate metrics
        aggregated = self._aggregate_metrics(per_document)
        
        return {
            'per_document': per_document,
            'aggregated': aggregated
        }
    
    def _aggregate_metrics(self, per_document: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate metrics across all documents."""
        if not per_document:
            return {}
        
        # Aggregate confidence scores
        overall_confidences = []
        critic_confidences = []
        structural_confidences = []
        validation_confidences = []
        field_mean_confidences = []
        confirmation_rates = []
        
        for doc_metrics in per_document.values():
            # Metadata confidence
            overall_conf = doc_metrics.get('metadata_confidence', {}).get('overall_confidence', 0.0)
            if overall_conf > 0:
                overall_confidences.append(overall_conf)
            
            # Workflow quality metrics
            workflow_metrics = doc_metrics.get('workflow_quality_metrics', {})
            if workflow_metrics:
                if workflow_metrics.get('critic_confidence', 0.0) > 0:
                    critic_confidences.append(workflow_metrics['critic_confidence'])
                if workflow_metrics.get('structural_confidence', 0.0) > 0:
                    structural_confidences.append(workflow_metrics['structural_confidence'])
                if workflow_metrics.get('validation_confidence', 0.0) > 0:
                    validation_confidences.append(workflow_metrics['validation_confidence'])
            
            # Field confidence stats
            field_stats = doc_metrics.get('field_confidence_stats', {})
            if field_stats:
                mean_conf = field_stats.get('mean_confidence', 0.0)
                if mean_conf > 0:
                    field_mean_confidences.append(mean_conf)
                
                conf_rate = field_stats.get('confirmation_rate', 0.0)
                if conf_rate > 0:
                    confirmation_rates.append(conf_rate)
        
        # Aggregate retry metrics
        total_steps = 0
        total_retries = 0
        docs_needing_review = 0
        
        for doc_metrics in per_document.values():
            retry_analysis = doc_metrics.get('retry_analysis', {})
            total_steps += retry_analysis.get('total_steps', 0)
            total_retries += retry_analysis.get('steps_requiring_retry', 0)
            
            if retry_analysis.get('needs_human_review', False):
                docs_needing_review += 1
        
        aggregated = {
            'mean_overall_confidence': sum(overall_confidences) / len(overall_confidences) if overall_confidences else 0.0,
            'min_overall_confidence': min(overall_confidences) if overall_confidences else 0.0,
            'max_overall_confidence': max(overall_confidences) if overall_confidences else 0.0,
            
            'mean_critic_confidence': sum(critic_confidences) / len(critic_confidences) if critic_confidences else 0.0,
            'mean_structural_confidence': sum(structural_confidences) / len(structural_confidences) if structural_confidences else 0.0,
            'mean_validation_confidence': sum(validation_confidences) / len(validation_confidences) if validation_confidences else 0.0,
            
            'mean_field_confidence': sum(field_mean_confidences) / len(field_mean_confidences) if field_mean_confidences else 0.0,
            'mean_confirmation_rate': sum(confirmation_rates) / len(confirmation_rates) if confirmation_rates else 0.0,
            
            'total_workflow_steps': total_steps,
            'total_retries': total_retries,
            'mean_retry_rate': total_retries / total_steps if total_steps > 0 else 0.0,
            'docs_needing_review': docs_needing_review,
            'review_rate': docs_needing_review / len(per_document) if per_document else 0.0,
            
            'n_documents': len(per_document)
        }
        
        return aggregated

