"""
Layer 1 - Field Coverage Evaluator for FAIRiAgent outputs.

Evaluates field *presence* (name matching only, never values):
- Field extraction rate (which field names were extracted)
- **Headline:** ``field_coverage_recall`` (TP/(TP+FN) on field *names*; equals
  ``CompletenessEvaluator``'s ``overall_completeness`` for flat GT lists)
- **Diagnostic only:** ``field_coverage_precision`` / ``field_coverage_f1``
  (penalize non-GT field names -- not used for metadata-extraction headline)
- ``gt_field_populated_rate``: for GT fields that were extracted, what
  fraction have *any* non-empty value. This is NOT a correctness/value
  check -- see ``evaluation/evaluators/value_accuracy_evaluator.py``
  (Layer 2) for real value-vs-GT comparison.

Extra (non-GT) fields are reported in ``excess_field_details`` for
inspection, but are no longer penalized/exempted based on the model's own
self-reported confidence. Confidence is not a defensible signal for whether
an extra field is legitimate; see
``evaluation/evaluators/novel_field_evaluator.py`` (Layer 4) for the
evidence-grounded replacement (``precision_excl_discoveries``).
"""

from typing import Dict, List, Any, Optional, Tuple
import os
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
try:
    from langchain_ollama import ChatOllama
except ImportError:
    from langchain_community.chat_models import ChatOllama  # deprecated fallback
import json
import re

from fairifier.utils.dotenv_compat import load_dotenv


class CorrectnessEvaluator:
    """Evaluate field presence (not values) in extracted metadata."""
    
    def __init__(self, judge_config: Optional[Dict[str, str]] = None):
        """
        Initialize correctness evaluator.
        
        Args:
            judge_config: Configuration for LLM judge
                - provider: anthropic, openai, ollama
                - model: model name
                - api_key: API key (if needed)
                - temperature: temperature setting
        """
        self.judge_config = judge_config or {}
        self.llm_judge = None
        
        # Initialize LLM judge if config provided
        if judge_config:
            self._initialize_llm_judge()
    
    def _initialize_llm_judge(self):
        """Initialize LLM for semantic matching."""
        provider = self.judge_config.get('provider', 'anthropic')
        model = self.judge_config.get('model', 'claude-sonnet-4-6')
        api_key = self.judge_config.get('api_key')
        temperature = float(self.judge_config.get('temperature', 0.0))
        
        if provider == 'anthropic':
            self.llm_judge = ChatAnthropic(
                model=model,
                api_key=api_key,
                temperature=temperature
            )
        elif provider == 'openai':
            self.llm_judge = ChatOpenAI(
                model=model,
                api_key=api_key,
                temperature=temperature
            )
        elif provider == 'ollama':
            base_url = self.judge_config.get('base_url', 'http://localhost:11434')
            self.llm_judge = ChatOllama(
                model=model,
                base_url=base_url,
                temperature=temperature
            )
        elif provider == 'qwen':
            # Qwen uses OpenAI-compatible API
            base_url = self.judge_config.get('base_url', 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1')
            self.llm_judge = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=base_url,
                temperature=temperature
            )
        elif provider == 'deepseek':
            # DeepSeek uses OpenAI-compatible API
            base_url = self.judge_config.get('base_url', 'https://api.deepseek.com/v1')
            self.llm_judge = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=base_url,
                temperature=temperature
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
    
    def evaluate(
        self,
        fairifier_output: Dict[str, Any],
        ground_truth_doc: Dict[str, Any],
        use_llm_judge: bool = False  # Not used for field presence evaluation
    ) -> Dict[str, Any]:
        """
        Evaluate field presence (not values) of FAIRiAgent output against ground truth.
        
        Only checks if fields were extracted, not their values.
        
        Args:
            fairifier_output: Parsed metadata.json from FAIRiAgent
            ground_truth_doc: Ground truth annotation for this document
            use_llm_judge: Not used (kept for compatibility)
            
        Returns:
            Dict with field presence metrics
        """
        # Extract fields
        extracted_fields = self._extract_fields_from_fairifier(fairifier_output)
        ground_truth_fields = ground_truth_doc.get('ground_truth_fields', [])
        
        # Build lookup maps (only field names matter)
        extracted_field_names = {f['field_name'] for f in extracted_fields}
        gt_field_names = {f['field_name'] for f in ground_truth_fields}
        gt_map = {f['field_name']: f for f in ground_truth_fields}
        
        # Evaluate field-by-field (GT-only quality; extras are reported separately)
        field_results = {}
        present_fields = 0
        missing_fields = 0
        gt_fields_with_values = 0
        gt_fields_with_evidence = 0
        gt_fields_confirmed = 0
        
        for field_name in gt_field_names:
            is_present = field_name in extracted_field_names
            
            if is_present:
                present_fields += 1
                extracted_field = next(f for f in extracted_fields if f['field_name'] == field_name)
                has_value = bool(extracted_field.get('value'))
                has_evidence = bool(extracted_field.get('evidence'))
                is_confirmed = str(extracted_field.get('status', '')).lower() == 'confirmed'
                if has_value:
                    gt_fields_with_values += 1
                if has_evidence:
                    gt_fields_with_evidence += 1
                if is_confirmed:
                    gt_fields_confirmed += 1
                field_results[field_name] = {
                    'is_present': True,
                    'status': 'PRESENT',
                    'confidence': extracted_field.get('confidence', 0.0),
                    'has_value': has_value,
                    'has_evidence': has_evidence,
                    'is_confirmed': is_confirmed,
                }
            else:
                missing_fields += 1
                field_results[field_name] = {
                    'is_present': False,
                    'status': 'MISSING',
                    'confidence': 0.0,
                    'has_value': False,
                    'has_evidence': False,
                    'is_confirmed': False,
                }
        
        # Calculate metrics based on field presence only
        n_gt_fields = len(gt_field_names)
        n_extracted_fields = len(extracted_field_names)
        n_correct_present = present_fields  # Fields that should be present and are present
        
        # True Positives: fields in both GT and extracted
        tp = len(extracted_field_names & gt_field_names)
        # False Positives: fields extracted but not in GT
        fp = len(extracted_field_names - gt_field_names)
        # False Negatives: fields in GT but not extracted
        fn = len(gt_field_names - extracted_field_names)
        # True Negatives: not applicable (we don't track fields that shouldn't exist)

        # Report extra (non-GT) fields for inspection. Classification into
        # beneficial_discovery / domain_insight / unsupported_fabrication is
        # done by NovelFieldEvaluator (Layer 4), which grounds each extra
        # field against the source document instead of trusting the model's
        # own confidence score.
        excess_field_names = extracted_field_names - gt_field_names
        excess_field_details = [
            {
                'field_name': field['field_name'],
                'confidence': field.get('confidence', 0.0),
                'status': field.get('status', ''),
            }
            for field in extracted_fields
            if field['field_name'] in excess_field_names
        ]

        # field_coverage_precision/recall/f1: TP/FP/FN on field *names* only.
        # This measures "was the field name mentioned", not correctness of
        # its value -- see ValueAccuracyEvaluator (Layer 2) for that.
        field_coverage_precision = tp / n_extracted_fields if n_extracted_fields > 0 else 0.0
        field_coverage_recall = tp / n_gt_fields if n_gt_fields > 0 else 0.0
        field_coverage_f1 = (
            2 * (field_coverage_precision * field_coverage_recall)
            / (field_coverage_precision + field_coverage_recall)
            if (field_coverage_precision + field_coverage_recall) > 0
            else 0.0
        )

        result = {
            'field_level_results': field_results,
            'excess_field_details': excess_field_details,
            'summary_metrics': {
                'total_ground_truth_fields': n_gt_fields,
                'total_extracted_fields': n_extracted_fields,
                'present_fields': present_fields,
                'missing_fields': missing_fields,
                'field_presence_rate': present_fields / n_gt_fields if n_gt_fields > 0 else 0.0,
                'true_positives': tp,
                'false_positives': fp,
                'false_negatives': fn,
                # Layer 1: field-name coverage only (never checks values).
                'field_coverage_precision': field_coverage_precision,
                'field_coverage_recall': field_coverage_recall,
                'field_coverage_f1': field_coverage_f1,
                # GT-only quality metrics: these ignore extra fields entirely.
                'gt_completeness': present_fields / n_gt_fields if n_gt_fields > 0 else 0.0,
                # "Has any non-empty value" -- NOT a correctness/value-accuracy
                # check. Renamed from the old, misleading `gt_value_accuracy`.
                'gt_field_populated_rate': gt_fields_with_values / n_gt_fields if n_gt_fields > 0 else 0.0,
                'gt_evidence_accuracy': gt_fields_with_evidence / n_gt_fields if n_gt_fields > 0 else 0.0,
                'gt_confirmed_accuracy': gt_fields_confirmed / n_gt_fields if n_gt_fields > 0 else 0.0,
            }
        }
        
        return result
    
    def _extract_fields_from_fairifier(self, fairifier_output: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract all fields from FAIRiAgent output."""
        fields = []
        
        # Check ISA structure
        isa_structure = fairifier_output.get('isa_structure', {})
        for sheet_name, sheet_data in isa_structure.items():
            if sheet_name == 'description':
                continue
            
            if isinstance(sheet_data, dict):
                for field in sheet_data.get('fields', []):
                    fields.append({
                        'field_name': field.get('field_name', ''),
                        'value': field.get('value', ''),
                        'evidence': field.get('evidence', ''),
                        'confidence': field.get('confidence', 0.0),
                        'status': field.get('status', ''),  # confirmed/provisional
                    })
        
        # Fallback: check flat metadata list
        if not fields:
            metadata_list = fairifier_output.get('metadata', [])
            for field in metadata_list:
                fields.append({
                    'field_name': field.get('field_name', ''),
                    'value': field.get('value', ''),
                    'evidence': field.get('evidence', ''),
                    'confidence': field.get('confidence', 0.0),
                    'status': field.get('status', ''),
                })
        
        return fields
    
    
    def evaluate_batch(
        self,
        fairifier_outputs: Dict[str, Dict[str, Any]],
        ground_truth_docs: Dict[str, Dict[str, Any]],
        use_llm_judge: bool = False  # Not used, kept for compatibility
    ) -> Dict[str, Any]:
        """
        Evaluate multiple documents (field presence only).
        
        Args:
            fairifier_outputs: Dict mapping document_id -> fairifier output
            ground_truth_docs: Dict mapping document_id -> ground truth
            use_llm_judge: Not used (kept for compatibility)
            
        Returns:
            Aggregated results
        """
        per_document_results = {}
        
        for doc_id in ground_truth_docs:
            if doc_id not in fairifier_outputs:
                print(f"Warning: No FAIRiAgent output for {doc_id}")
                continue
            
            print(f"Evaluating field presence for {doc_id}...")
            result = self.evaluate(
                fairifier_outputs[doc_id],
                ground_truth_docs[doc_id],
                use_llm_judge=False
            )
            per_document_results[doc_id] = result
        
        # Aggregate statistics
        aggregated = self._aggregate_results(per_document_results)
        
        return {
            'per_document': per_document_results,
            'aggregated': aggregated
        }
    
    def _aggregate_results(self, per_document_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate field presence metrics across all documents."""
        if not per_document_results:
            return {}
        
        # Collect metrics
        field_presence_rates = []
        gt_completeness_scores = []
        gt_field_populated_rates = []
        gt_evidence_accuracies = []
        gt_confirmed_accuracies = []
        precisions = []
        recalls = []
        f1_scores = []
        
        for result in per_document_results.values():
            metrics = result['summary_metrics']
            field_presence_rates.append(metrics['field_presence_rate'])
            gt_completeness_scores.append(metrics['gt_completeness'])
            gt_field_populated_rates.append(metrics['gt_field_populated_rate'])
            gt_evidence_accuracies.append(metrics['gt_evidence_accuracy'])
            gt_confirmed_accuracies.append(metrics['gt_confirmed_accuracy'])
            precisions.append(metrics['field_coverage_precision'])
            recalls.append(metrics['field_coverage_recall'])
            f1_scores.append(metrics['field_coverage_f1'])
        
        return {
            'mean_field_presence_rate': sum(field_presence_rates) / len(field_presence_rates),
            'mean_gt_completeness': sum(gt_completeness_scores) / len(gt_completeness_scores),
            'mean_gt_field_populated_rate': sum(gt_field_populated_rates) / len(gt_field_populated_rates),
            'mean_gt_evidence_accuracy': sum(gt_evidence_accuracies) / len(gt_evidence_accuracies),
            'mean_gt_confirmed_accuracy': sum(gt_confirmed_accuracies) / len(gt_confirmed_accuracies),
            'mean_field_coverage_precision': sum(precisions) / len(precisions),
            'mean_field_coverage_recall': sum(recalls) / len(recalls),
            'mean_field_coverage_f1': sum(f1_scores) / len(f1_scores),
            'min_field_coverage_f1': min(f1_scores),
            'max_field_coverage_f1': max(f1_scores),
            'n_documents': len(per_document_results)
        }
