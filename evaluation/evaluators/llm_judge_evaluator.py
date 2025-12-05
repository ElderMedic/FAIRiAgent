"""
LLM Judge Evaluator for holistic quality assessment.

Uses LLM to evaluate metadata quality across multiple dimensions:
- Evidence quality
- Contextual appropriateness
- Completeness
- Accuracy
"""

from typing import Dict, List, Any, Optional
import json
import re
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_community.chat_models import ChatOllama


class LLMJudgeEvaluator:
    """Holistic quality evaluation using LLM as judge."""
    
    # Evaluation dimensions and weights
    DIMENSIONS = {
        'evidence_quality': {
            'weight': 0.25,
            'description': 'How well does the evidence support the extracted value?'
        },
        'contextual_appropriateness': {
            'weight': 0.20,
            'description': 'Is the extracted metadata appropriate for the document type?'
        },
        'completeness': {
            'weight': 0.25,
            'description': 'Are all critical metadata fields present?'
        },
        'accuracy': {
            'weight': 0.30,
            'description': 'Are the extracted values factually correct?'
        }
    }
    
    def __init__(self, judge_config: Optional[Dict[str, str]] = None):
        """
        Initialize LLM judge evaluator.
        
        Args:
            judge_config: Configuration for LLM judge
                - provider: anthropic, openai, ollama
                - model: model name
                - api_key: API key (if needed)
                - temperature: temperature setting
        """
        self.judge_config = judge_config or {}
        self.llm_judge = None
        
        if judge_config:
            self._initialize_llm_judge()
    
    def _initialize_llm_judge(self):
        """Initialize LLM for judging."""
        provider = self.judge_config.get('provider', 'anthropic')
        model = self.judge_config.get('model', 'claude-sonnet-4')
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
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
    
    def evaluate_document(
        self,
        fairifier_output: Dict[str, Any],
        ground_truth_doc: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Evaluate overall document-level quality using LLM judge.
        
        Args:
            fairifier_output: FAIRiAgent output
            ground_truth_doc: Optional ground truth for comparison
            
        Returns:
            Multi-dimensional quality assessment
        """
        if not self.llm_judge:
            raise ValueError("LLM judge not initialized. Provide judge_config.")
        
        # Build evaluation prompt
        prompt = self._build_document_eval_prompt(fairifier_output, ground_truth_doc)
        
        # Get LLM judgment
        judgment = self._query_llm_judge(prompt)
        
        # Parse judgment
        parsed = self._parse_judgment(judgment)
        
        # Check if parsing failed
        if 'error' in parsed:
            # Return default scores if parsing failed
            default_dimension_scores = {dim: 0.0 for dim in self.DIMENSIONS}
            return {
                'overall_score': 0.0,
                'dimension_scores': default_dimension_scores,
                'strengths': [],
                'weaknesses': [f"Failed to parse LLM judgment: {parsed.get('error', 'Unknown error')}"],
                'recommendations': ['Review LLM judge response format'],
                'raw_judgment': judgment,
                'parse_error': parsed.get('error')
            }
        
        # Ensure dimension_scores exists
        if 'dimension_scores' not in parsed:
            parsed['dimension_scores'] = {}
        
        # Calculate weighted score
        weighted_score = sum(
            parsed['dimension_scores'].get(dim, 0.0) * self.DIMENSIONS[dim]['weight']
            for dim in self.DIMENSIONS
        )
        
        result = {
            'overall_score': weighted_score,
            'dimension_scores': parsed.get('dimension_scores', {}),
            'strengths': parsed.get('strengths', []),
            'weaknesses': parsed.get('weaknesses', []),
            'recommendations': parsed.get('recommendations', []),
            'raw_judgment': judgment
        }
        
        return result
    
    def evaluate_isa_sheet(
        self,
        sheet_name: str,
        sheet_data: Dict[str, Any],
        document_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate a single ISA sheet for internal coherence.
        
        Args:
            sheet_name: Name of ISA sheet (investigation, study, etc.)
            sheet_data: Sheet data from FAIRiAgent output
            document_context: Optional document context for reference
            
        Returns:
            Quality assessment for this sheet
        """
        if not self.llm_judge:
            raise ValueError("LLM judge not initialized")
        
        prompt = self._build_isa_sheet_eval_prompt(sheet_name, sheet_data, document_context)
        judgment = self._query_llm_judge(prompt)
        parsed = self._parse_judgment(judgment)
        
        return {
            'sheet_name': sheet_name,
            'coherence_score': parsed.get('coherence_score', 0.0),
            'completeness_score': parsed.get('completeness_score', 0.0),
            'issues': parsed.get('issues', []),
            'raw_judgment': judgment
        }
    
    def evaluate_field(
        self,
        field: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Evaluate a single field.
        
        Args:
            field: Field data (field_name, value, evidence, etc.)
            context: Optional context (document type, related fields, etc.)
            
        Returns:
            Field-level quality assessment
        """
        if not self.llm_judge:
            raise ValueError("LLM judge not initialized")
        
        prompt = self._build_field_eval_prompt(field, context)
        judgment = self._query_llm_judge(prompt)
        parsed = self._parse_judgment(judgment)
        
        return {
            'field_name': field.get('field_name'),
            'quality_score': parsed.get('quality_score', 0.0),
            'evidence_quality': parsed.get('evidence_quality', 0.0),
            'issues': parsed.get('issues', []),
            'raw_judgment': judgment
        }
    
    def _build_document_eval_prompt(
        self,
        fairifier_output: Dict[str, Any],
        ground_truth_doc: Optional[Dict[str, Any]]
    ) -> str:
        """Build document-level evaluation prompt."""
        # Extract key information
        document_source = fairifier_output.get('document_source', 'unknown')
        total_fields = fairifier_output.get('statistics', {}).get('total_fields', 0)
        confirmed_fields = fairifier_output.get('statistics', {}).get('confirmed_fields', 0)
        overall_confidence = fairifier_output.get('overall_confidence', 0.0)
        
        # Build field summary
        isa_structure = fairifier_output.get('isa_structure', {})
        field_summary = []
        for sheet_name, sheet_data in isa_structure.items():
            if sheet_name == 'description':
                continue
            n_fields = len(sheet_data.get('fields', []))
            field_summary.append(f"  - {sheet_name}: {n_fields} fields")
        
        field_summary_text = "\n".join(field_summary) if field_summary else "No ISA structure found"
        
        # Add ground truth comparison if available
        gt_context = ""
        if ground_truth_doc:
            gt_fields = ground_truth_doc.get('ground_truth_fields', [])
            gt_context = f"""
**Ground Truth Reference**:
- Expected fields: {len(gt_fields)}
- Required fields: {sum(1 for f in gt_fields if f.get('is_required', False))}

Use this to assess accuracy and completeness."""
        
        prompt = f"""You are evaluating the quality of automatically generated scientific metadata.

**Document**: {document_source}

**Metadata Summary**:
- Total fields: {total_fields}
- Confirmed fields: {confirmed_fields}
- Overall confidence: {overall_confidence:.2f}

**Field Distribution**:
{field_summary_text}
{gt_context}

**Evaluation Dimensions** (provide 0.0-1.0 score for each):

1. **Evidence Quality** (25%): How well is each field supported by evidence from the document?
2. **Contextual Appropriateness** (20%): Are the extracted fields appropriate for this document type and domain?
3. **Completeness** (25%): Are all critical metadata fields present?
4. **Accuracy** (30%): Are the extracted values factually correct and precise?

**Task**: Provide a comprehensive quality assessment.

**Response Format (JSON)**:
{{
  "dimension_scores": {{
    "evidence_quality": 0.0-1.0,
    "contextual_appropriateness": 0.0-1.0,
    "completeness": 0.0-1.0,
    "accuracy": 0.0-1.0
  }},
  "strengths": ["strength 1", "strength 2"],
  "weaknesses": ["weakness 1", "weakness 2"],
  "recommendations": ["recommendation 1", "recommendation 2"]
}}

Respond ONLY with the JSON object."""
        
        return prompt
    
    def _build_isa_sheet_eval_prompt(
        self,
        sheet_name: str,
        sheet_data: Dict[str, Any],
        document_context: Optional[str]
    ) -> str:
        """Build ISA sheet evaluation prompt."""
        fields = sheet_data.get('fields', [])
        field_names = [f.get('field_name', '') for f in fields[:10]]  # First 10
        if len(fields) > 10:
            field_names.append(f"... and {len(fields) - 10} more")
        
        context_text = f"\n**Document Context**: {document_context}" if document_context else ""
        
        prompt = f"""Evaluate the quality and coherence of this ISA sheet.

**ISA Sheet**: {sheet_name}
**Number of fields**: {len(fields)}
**Fields**: {', '.join(field_names)}{context_text}

**Evaluation Criteria**:
1. **Coherence** (0.0-1.0): Do the fields make sense together for this sheet type?
2. **Completeness** (0.0-1.0): Are essential fields for {sheet_name} present?
3. **Issues**: Any problematic or missing fields?

**Response Format (JSON)**:
{{
  "coherence_score": 0.0-1.0,
  "completeness_score": 0.0-1.0,
  "issues": ["issue 1", "issue 2"]
}}

Respond ONLY with the JSON object."""
        
        return prompt
    
    def _build_field_eval_prompt(
        self,
        field: Dict[str, Any],
        context: Optional[Dict[str, Any]]
    ) -> str:
        """Build field-level evaluation prompt."""
        field_name = field.get('field_name', '')
        value = field.get('value', '')
        evidence = field.get('evidence', '')
        confidence = field.get('confidence', 0.0)
        
        context_text = ""
        if context:
            doc_type = context.get('document_type', 'unknown')
            context_text = f"\n**Document Type**: {doc_type}"
        
        prompt = f"""Evaluate the quality of this metadata field extraction.

**Field**: {field_name}
**Extracted Value**: {value}
**Evidence**: {evidence}
**System Confidence**: {confidence:.2f}{context_text}

**Evaluation**:
1. **Quality Score** (0.0-1.0): Overall quality of this extraction
2. **Evidence Quality** (0.0-1.0): How well does the evidence support the value?
3. **Issues**: Any problems with this field?

**Response Format (JSON)**:
{{
  "quality_score": 0.0-1.0,
  "evidence_quality": 0.0-1.0,
  "issues": ["issue 1" if any, else empty list]
}}

Respond ONLY with the JSON object."""
        
        return prompt
    
    def _query_llm_judge(self, prompt: str) -> str:
        """Query LLM judge with prompt."""
        messages = [
            SystemMessage(content="You are an expert evaluator of scientific metadata quality. Provide precise, objective assessments."),
            HumanMessage(content=prompt)
        ]
        
        try:
            response = self.llm_judge.invoke(messages)
            return response.content
        except Exception as e:
            return f'{{"error": "{str(e)}"}}'
    
    def _parse_judgment(self, judgment: str) -> Dict[str, Any]:
        """Parse LLM judgment response."""
        try:
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', judgment, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
                return {'error': 'No JSON found in response', 'raw': judgment}
        except json.JSONDecodeError as e:
            return {'error': f'JSON parse error: {e}', 'raw': judgment}
    
    def evaluate_batch(
        self,
        fairifier_outputs: Dict[str, Dict[str, Any]],
        ground_truth_docs: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Evaluate multiple documents.
        
        Args:
            fairifier_outputs: Dict mapping document_id -> fairifier output
            ground_truth_docs: Optional ground truth docs
            
        Returns:
            Aggregated results
        """
        per_document_results = {}
        
        for doc_id, output in fairifier_outputs.items():
            print(f"LLM Judge evaluating {doc_id}...")
            gt_doc = ground_truth_docs.get(doc_id) if ground_truth_docs else None
            
            result = self.evaluate_document(output, gt_doc)
            per_document_results[doc_id] = result
        
        # Aggregate
        aggregated = self._aggregate_results(per_document_results)
        
        return {
            'per_document': per_document_results,
            'aggregated': aggregated
        }
    
    def _aggregate_results(self, per_document_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate LLM judge results."""
        if not per_document_results:
            return {}
        
        overall_scores = [r['overall_score'] for r in per_document_results.values()]
        
        # Aggregate dimension scores
        dimension_aggregates = {}
        for dim in self.DIMENSIONS:
            scores = [
                r['dimension_scores'].get(dim, 0.0) 
                for r in per_document_results.values()
            ]
            dimension_aggregates[dim] = {
                'mean': sum(scores) / len(scores),
                'min': min(scores),
                'max': max(scores)
            }
        
        return {
            'mean_overall_score': sum(overall_scores) / len(overall_scores),
            'min_overall_score': min(overall_scores),
            'max_overall_score': max(overall_scores),
            'dimension_aggregates': dimension_aggregates,
            'n_documents': len(per_document_results)
        }

