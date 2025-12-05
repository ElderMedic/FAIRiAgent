"""
Ontology Evaluator for FAIRiAgent outputs.

Evaluates:
- Ontology term usage rate
- Ontology term validity (check against known ontologies)
- Appropriate ontology selection (using LLM-as-judge)
"""

from typing import Dict, List, Any, Optional, Set
import json
from pathlib import Path


class OntologyEvaluator:
    """Evaluate ontology term usage and validity."""
    
    def __init__(self, kb_path: Optional[Path] = None):
        """
        Initialize ontology evaluator.
        
        Args:
            kb_path: Path to knowledge base directory (contains ontologies.json)
        """
        self.kb_path = kb_path or Path(__file__).parents[2] / 'kb'
        self.ontologies = self._load_ontologies()
    
    def _load_ontologies(self) -> Dict[str, Any]:
        """Load ontology definitions from knowledge base."""
        ontology_file = self.kb_path / 'ontologies.json'
        
        if not ontology_file.exists():
            print(f"Warning: Ontology file not found at {ontology_file}")
            return {}
        
        try:
            with open(ontology_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading ontologies: {e}")
            return {}
    
    def evaluate(self, fairifier_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate ontology usage in FAIRiAgent output.
        
        Args:
            fairifier_output: Parsed metadata_json.json from FAIRiAgent
            
        Returns:
            Dict with ontology metrics
        """
        # Extract fields
        fields = self._extract_fields_from_fairifier(fairifier_output)
        
        # Analyze ontology usage
        fields_with_ontology = []
        ontology_term_validations = []
        ontology_usage_by_type = {}
        
        for field in fields:
            field_name = field.get('field_name', '')
            value = field.get('value', '')
            ontology_term = field.get('ontology_term')
            
            if ontology_term:
                fields_with_ontology.append(field_name)
                
                # Validate ontology term
                validation = self._validate_ontology_term(ontology_term, field_name, value)
                ontology_term_validations.append({
                    'field_name': field_name,
                    'ontology_term': ontology_term,
                    'validation': validation
                })
                
                # Track by ontology type
                ontology_type = self._detect_ontology_type(ontology_term)
                if ontology_type not in ontology_usage_by_type:
                    ontology_usage_by_type[ontology_type] = []
                ontology_usage_by_type[ontology_type].append(field_name)
        
        # Calculate metrics
        total_fields = len(fields)
        fields_with_ontology_count = len(fields_with_ontology)
        valid_ontology_terms = sum(1 for v in ontology_term_validations if v['validation']['is_valid'])
        
        ontology_usage_rate = fields_with_ontology_count / total_fields if total_fields > 0 else 0.0
        ontology_validity_rate = valid_ontology_terms / fields_with_ontology_count if fields_with_ontology_count > 0 else 0.0
        
        # Identify fields that should have ontology terms
        expected_ontology_fields = self._identify_expected_ontology_fields(fields)
        missing_ontology_fields = [
            f for f in expected_ontology_fields 
            if f not in fields_with_ontology
        ]
        
        result = {
            'summary_metrics': {
                'total_fields': total_fields,
                'fields_with_ontology': fields_with_ontology_count,
                'ontology_usage_rate': ontology_usage_rate,
                'valid_ontology_terms': valid_ontology_terms,
                'ontology_validity_rate': ontology_validity_rate,
                'expected_ontology_fields': len(expected_ontology_fields),
                'missing_ontology_fields': len(missing_ontology_fields)
            },
            'ontology_usage_by_type': ontology_usage_by_type,
            'ontology_term_validations': ontology_term_validations,
            'missing_ontology_fields': missing_ontology_fields
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
            
            for field in sheet_data.get('fields', []):
                fields.append({
                    'field_name': field.get('field_name', ''),
                    'value': field.get('value', ''),
                    'ontology_term': field.get('ontology_term'),
                    'isa_sheet': sheet_name
                })
        
        # Fallback: check flat metadata list
        if not fields:
            metadata_list = fairifier_output.get('metadata', [])
            for field in metadata_list:
                fields.append({
                    'field_name': field.get('field_name', ''),
                    'value': field.get('value', ''),
                    'ontology_term': field.get('ontology_term'),
                    'isa_sheet': field.get('isa_sheet', 'unknown')
                })
        
        return fields
    
    def _validate_ontology_term(
        self, 
        ontology_term: str, 
        field_name: str, 
        value: str
    ) -> Dict[str, Any]:
        """
        Validate an ontology term.
        
        Args:
            ontology_term: Ontology term (e.g., "ENVO:00002007")
            field_name: Field name
            value: Field value
            
        Returns:
            Validation result
        """
        # Check format
        if ':' not in ontology_term:
            return {
                'is_valid': False,
                'reason': 'Invalid format (missing colon separator)',
                'ontology_type': 'unknown'
            }
        
        ontology_prefix, ontology_id = ontology_term.split(':', 1)
        ontology_type = ontology_prefix.upper()
        
        # Check if ontology is recognized
        if ontology_type not in self.ontologies:
            return {
                'is_valid': False,
                'reason': f'Unknown ontology: {ontology_type}',
                'ontology_type': ontology_type
            }
        
        # Check ID format (should be numeric for most ontologies)
        if not ontology_id.isdigit():
            return {
                'is_valid': False,
                'reason': f'Invalid ID format: {ontology_id}',
                'ontology_type': ontology_type
            }
        
        # For deeper validation, would need to query ontology APIs (OLS, BioPortal)
        # For now, accept if format is correct and ontology is known
        
        return {
            'is_valid': True,
            'reason': 'Format valid, ontology recognized',
            'ontology_type': ontology_type
        }
    
    def _detect_ontology_type(self, ontology_term: str) -> str:
        """Detect ontology type from term."""
        if ':' in ontology_term:
            return ontology_term.split(':', 1)[0].upper()
        return 'UNKNOWN'
    
    def _identify_expected_ontology_fields(self, fields: List[Dict[str, Any]]) -> List[str]:
        """Identify fields that should have ontology terms."""
        # Fields that typically should have ontology terms
        ontology_expected_keywords = [
            'environment', 'organism', 'taxonom', 'tissue', 'cell type',
            'disease', 'phenotype', 'anatomy', 'developmental stage',
            'material', 'chemical', 'geographic location'
        ]
        
        expected_fields = []
        
        for field in fields:
            field_name = field.get('field_name', '').lower()
            
            # Check if field name suggests ontology term needed
            for keyword in ontology_expected_keywords:
                if keyword in field_name:
                    expected_fields.append(field.get('field_name', ''))
                    break
        
        return expected_fields
    
    def evaluate_batch(
        self,
        fairifier_outputs: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Evaluate ontology usage across multiple documents.
        
        Args:
            fairifier_outputs: Dict mapping document_id -> fairifier output
            
        Returns:
            Aggregated results
        """
        per_document_results = {}
        
        for doc_id, output in fairifier_outputs.items():
            result = self.evaluate(output)
            per_document_results[doc_id] = result
        
        # Aggregate statistics
        aggregated = self._aggregate_results(per_document_results)
        
        return {
            'per_document': per_document_results,
            'aggregated': aggregated
        }
    
    def _aggregate_results(self, per_document_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate ontology metrics across documents."""
        if not per_document_results:
            return {}
        
        usage_rates = []
        validity_rates = []
        ontology_types_used = set()
        
        for result in per_document_results.values():
            metrics = result['summary_metrics']
            usage_rates.append(metrics['ontology_usage_rate'])
            validity_rates.append(metrics['ontology_validity_rate'])
            
            # Collect all ontology types used
            for ont_type in result['ontology_usage_by_type'].keys():
                ontology_types_used.add(ont_type)
        
        return {
            'mean_ontology_usage_rate': sum(usage_rates) / len(usage_rates),
            'mean_ontology_validity_rate': sum(validity_rates) / len(validity_rates),
            'min_usage_rate': min(usage_rates),
            'max_usage_rate': max(usage_rates),
            'ontology_types_used': list(ontology_types_used),
            'n_documents': len(per_document_results)
        }

