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
- Values-first references derive unique fields from populated ``expected_rows``;
  final matrix columns count as presence even when their cells are empty.
- ``field_level_recall`` and ``populated_field_level_recall`` use unique
  (field, ISOSA level) pairs, independently of entity counts or row alignment.

Extra (non-GT) fields are reported in ``excess_field_details`` for
inspection, but are no longer penalized/exempted based on the model's own
self-reported confidence. Confidence is not a defensible signal for whether
an extra field is legitimate; see
``evaluation/evaluators/novel_field_evaluator.py`` (Layer 4) for the
evidence-grounded replacement (``precision_excl_discoveries``).
"""

from typing import Dict, List, Any, Optional, Tuple, Mapping
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
from ._value_matching import normalise_field_name


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
        use_llm_judge: bool = False,  # Not used for field presence evaluation
        *,
        ground_truth_values_doc: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate field presence (not values) of FAIRiAgent output against ground truth.
        
        Only checks if fields were extracted, not their values.
        
        Args:
            fairifier_output: Parsed metadata.json from FAIRiAgent
            ground_truth_doc: Ground truth annotation for this document
            use_llm_judge: Not used (kept for compatibility)
            ground_truth_values_doc: Optional expected_rows reference. Supplies
                field names when the explicit field list is absent, and sheet
                placement where available. Repeated rows do not add fields.
            
        Returns:
            Dict with field presence metrics
        """
        # Extract fields
        extracted_fields = self._extract_fields_from_fairifier(fairifier_output)
        gt_field_names, gt_field_level_pairs, reference_source = self._reference_fields(
            ground_truth_doc, ground_truth_values_doc
        )
        
        # Build lookup maps (only field names matter)
        extracted_field_names = {f['field_name'] for f in extracted_fields}
        extracted_pairs = {
            (field['isa_sheet'], field['field_name'])
            for field in extracted_fields if field.get('isa_sheet')
        }
        populated_pairs = {
            (field['isa_sheet'], field['field_name'])
            for field in extracted_fields
            if field.get('isa_sheet') and self._has_value(field.get('value'))
        }
        
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
                occurrences = [f for f in extracted_fields if f['field_name'] == field_name]
                extracted_field = occurrences[0]
                has_value = any(self._has_value(f.get('value')) for f in occurrences)
                has_evidence = any(f.get('evidence') for f in occurrences)
                is_confirmed = any(
                    str(f.get('status', '')).lower() == 'confirmed' for f in occurrences
                )
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
        n_gt_pairs = len(gt_field_level_pairs)
        present_pairs = len(gt_field_level_pairs & extracted_pairs)
        populated_gt_pairs = len(gt_field_level_pairs & populated_pairs)

        result = {
            'field_level_results': field_results,
            'excess_field_details': excess_field_details,
            'summary_metrics': {
                'reference_source': reference_source,
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
                # Unique (field, ISOSA level) recall includes missing fields in
                # its denominator. It is independent of predicted row counts.
                'total_ground_truth_field_level_pairs': n_gt_pairs,
                'present_field_level_pairs': present_pairs,
                'populated_field_level_pairs': populated_gt_pairs,
                'field_level_recall': present_pairs / n_gt_pairs if n_gt_pairs else None,
                'populated_field_level_recall': populated_gt_pairs / n_gt_pairs if n_gt_pairs else None,
            }
        }
        
        return result
    
    @staticmethod
    def _has_value(value: Any) -> bool:
        if isinstance(value, (list, dict, tuple, set)):
            return bool(value)
        return value is not None and bool(str(value).strip())

    @staticmethod
    def _sheet_name(name: Any) -> str:
        normalized = re.sub(r"[\s_-]+", "", str(name or "").lower())
        return normalized if normalized in {
            'investigation', 'study', 'observationunit', 'sample', 'assay'
        } else ''

    @classmethod
    def _reference_fields(cls, ground_truth_doc, values_doc=None):
        """Use explicit field scope first; derive it from populated GT rows otherwise."""
        explicit = [
            field for field in ground_truth_doc.get('ground_truth_fields', [])
            if isinstance(field, Mapping) and field.get('field_name')
        ]
        names = {normalise_field_name(field['field_name']) for field in explicit}
        pairs = {
            (cls._sheet_name(field.get('isa_sheet')), normalise_field_name(field['field_name']))
            for field in explicit if cls._sheet_name(field.get('isa_sheet'))
        }
        values_reference = values_doc if values_doc is not None else ground_truth_doc
        row_pairs = set()
        for sheet, block in values_reference.get('isa_sheets', {}).items():
            level = cls._sheet_name(sheet)
            if not level or not isinstance(block, Mapping):
                continue
            for row in block.get('expected_rows', []):
                if not isinstance(row, Mapping):
                    continue
                row_pairs.update(
                    (level, normalise_field_name(name))
                    for name, value in row.items()
                    if isinstance(name, str) and name.strip()
                    and not name.startswith('_') and cls._has_value(value)
                )
        if explicit:
            pairs.update(pair for pair in row_pairs if pair[1] in names)
            return names, pairs, 'ground_truth_fields'
        return (
            {name for _, name in row_pairs}, row_pairs,
            'isa_sheets.expected_rows' if row_pairs else 'unavailable',
        )

    def _extract_fields_from_fairifier(self, fairifier_output: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Read declarations and columns; use final rows for populated-field checks."""
        fields = {}
        matrices = {}
        for representation in ('isa_structure', 'isa_values'):
            for sheet_name, block in (fairifier_output.get(representation) or {}).items():
                sheet = self._sheet_name(sheet_name)
                if not sheet or not isinstance(block, Mapping):
                    continue
                for field in block.get('fields', []):
                    if isinstance(field, Mapping) and field.get('field_name'):
                        name = normalise_field_name(field['field_name'])
                        fields[(sheet, name)] = {
                            **dict(field), 'field_name': name, 'isa_sheet': sheet,
                        }
                if isinstance(block.get('columns'), list) and isinstance(block.get('rows'), list):
                    matrices[sheet] = block

        for sheet, block in matrices.items():
            # A declaration's example value cannot fill an empty final cell.
            for (field_sheet, _), field in fields.items():
                if field_sheet == sheet:
                    field['value'] = ''
            columns = [normalise_field_name(str(column)) for column in block['columns']]
            for name in columns:
                if name:
                    fields.setdefault((sheet, name), {'field_name': name, 'isa_sheet': sheet})
            for row in block['rows']:
                if isinstance(row, list):
                    row_values = dict(zip(columns, row))
                elif isinstance(row, Mapping):
                    row_values = {normalise_field_name(str(k)): v for k, v in row.items()}
                else:
                    continue
                for name in columns:
                    if name and self._has_value(row_values.get(name)):
                        fields[(sheet, name)]['value'] = row_values[name]

        if not fields:
            for field in fairifier_output.get('metadata', []):
                if isinstance(field, Mapping) and field.get('field_name'):
                    name = normalise_field_name(field['field_name'])
                    sheet = self._sheet_name(field.get('isa_sheet'))
                    fields[(sheet, name)] = {
                        **dict(field), 'field_name': name, 'isa_sheet': sheet,
                    }
        return list(fields.values())
    
    
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
