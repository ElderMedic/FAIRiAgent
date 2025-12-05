"""
Schema Validator for FAIRiAgent outputs.

Validates:
- JSON structure compliance
- Required fields presence
- Field data types
- Value format compliance (dates, URLs, IDs)
- ISA-Tab structure compliance
"""

from typing import Dict, List, Any, Optional
import json
import re
from datetime import datetime
from urllib.parse import urlparse


class SchemaValidator:
    """Validate FAIRiAgent output against schema requirements."""
    
    def __init__(self):
        """Initialize schema validator."""
        # Define required fields per ISA sheet
        self.required_fields_by_sheet = {
            'investigation': [
                'investigation title',
                'investigation description'
            ],
            'study': [
                'study title',
                'study description'
            ],
            'assay': [
                'assay identifier',
                'assay description'
            ],
            'sample': [
                'sample identifier',
                'sample description'
            ],
            'observationunit': [
                'observation unit identifier',
                'observation unit description'
            ]
        }
        
        # Field type validators
        self.field_validators = {
            'date': self._validate_date,
            'url': self._validate_url,
            'email': self._validate_email,
            'ncbi_taxonomy_id': self._validate_ncbi_taxid,
            'numeric': self._validate_numeric,
            'latitude': self._validate_latitude,
            'longitude': self._validate_longitude
        }
    
    def validate(self, fairifier_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate FAIRiAgent output.
        
        Args:
            fairifier_output: Parsed metadata_json.json from FAIRiAgent
            
        Returns:
            Dict with validation results
        """
        errors = []
        warnings = []
        validations = {}
        
        # 1. JSON structure validation
        structure_valid = self._validate_json_structure(fairifier_output, errors, warnings)
        validations['json_structure'] = structure_valid
        
        # 2. Required fields validation
        required_valid = self._validate_required_fields(fairifier_output, errors, warnings)
        validations['required_fields'] = required_valid
        
        # 3. Field data types validation
        datatypes_valid = self._validate_field_datatypes(fairifier_output, errors, warnings)
        validations['field_datatypes'] = datatypes_valid
        
        # 4. ISA-Tab structure validation
        isa_valid = self._validate_isa_structure(fairifier_output, errors, warnings)
        validations['isa_structure'] = isa_valid
        
        # 5. Value format validation
        format_valid = self._validate_value_formats(fairifier_output, errors, warnings)
        validations['value_formats'] = format_valid
        
        # Calculate overall compliance
        total_checks = len(validations)
        passed_checks = sum(1 for v in validations.values() if v)
        compliance_rate = passed_checks / total_checks if total_checks > 0 else 0.0
        
        is_valid = len(errors) == 0
        
        result = {
            'is_valid': is_valid,
            'schema_compliance_rate': compliance_rate,
            'validations': validations,
            'errors': errors,
            'warnings': warnings,
            'summary': {
                'total_checks': total_checks,
                'passed_checks': passed_checks,
                'critical_errors': len(errors),
                'warnings': len(warnings),
                'status': 'PASS' if is_valid else 'FAIL'
            }
        }
        
        return result
    
    def _validate_json_structure(
        self, 
        data: Dict[str, Any], 
        errors: List[str], 
        warnings: List[str]
    ) -> bool:
        """Validate basic JSON structure."""
        required_top_level = ['fairifier_version', 'generated_at', 'document_source']
        
        for field in required_top_level:
            if field not in data:
                errors.append(f"Missing required top-level field: {field}")
        
        # Check for metadata or isa_structure
        has_metadata = 'metadata' in data or 'isa_structure' in data
        if not has_metadata:
            errors.append("No metadata found (expected 'metadata' or 'isa_structure')")
            return False
        
        return len(errors) == 0
    
    def _validate_required_fields(
        self, 
        data: Dict[str, Any], 
        errors: List[str], 
        warnings: List[str]
    ) -> bool:
        """Validate required fields are present."""
        isa_structure = data.get('isa_structure', {})
        
        for sheet_name, required_fields in self.required_fields_by_sheet.items():
            if sheet_name not in isa_structure:
                warnings.append(f"ISA sheet '{sheet_name}' not found")
                continue
            
            sheet_data = isa_structure[sheet_name]
            fields = sheet_data.get('fields', [])
            field_names = {f.get('field_name', '').lower() for f in fields}
            
            for required_field in required_fields:
                if required_field.lower() not in field_names:
                    errors.append(f"Required field missing in {sheet_name}: {required_field}")
        
        return len([e for e in errors if 'Required field missing' in e]) == 0
    
    def _validate_field_datatypes(
        self, 
        data: Dict[str, Any], 
        errors: List[str], 
        warnings: List[str]
    ) -> bool:
        """Validate field data types."""
        isa_structure = data.get('isa_structure', {})
        
        for sheet_name, sheet_data in isa_structure.items():
            if sheet_name == 'description':
                continue
            
            fields = sheet_data.get('fields', [])
            for field in fields:
                field_name = field.get('field_name', '')
                value = field.get('value')
                
                # Check required field attributes
                if 'field_name' not in field:
                    errors.append(f"Field in {sheet_name} missing 'field_name'")
                
                if value is None:
                    warnings.append(f"Field '{field_name}' in {sheet_name} has null value")
                
                # Validate confidence score
                if 'confidence' in field:
                    conf = field['confidence']
                    if not isinstance(conf, (int, float)) or conf < 0 or conf > 1:
                        warnings.append(f"Invalid confidence value for '{field_name}': {conf}")
        
        return True  # Data type validation is mostly warnings
    
    def _validate_isa_structure(
        self, 
        data: Dict[str, Any], 
        errors: List[str], 
        warnings: List[str]
    ) -> bool:
        """Validate ISA-Tab structure."""
        isa_structure = data.get('isa_structure', {})
        
        if not isa_structure:
            warnings.append("No ISA structure found")
            return False
        
        expected_sheets = ['investigation', 'study', 'assay', 'sample']
        found_sheets = [s for s in expected_sheets if s in isa_structure]
        
        if len(found_sheets) < 2:
            warnings.append(f"Only {len(found_sheets)} ISA sheets found, expected at least 2")
        
        # Validate each sheet has required structure
        for sheet_name in found_sheets:
            sheet_data = isa_structure[sheet_name]
            
            if 'fields' not in sheet_data:
                errors.append(f"ISA sheet '{sheet_name}' missing 'fields' array")
            
            if 'description' not in sheet_data:
                warnings.append(f"ISA sheet '{sheet_name}' missing 'description'")
        
        return True
    
    def _validate_value_formats(
        self, 
        data: Dict[str, Any], 
        errors: List[str], 
        warnings: List[str]
    ) -> bool:
        """Validate specific value formats."""
        isa_structure = data.get('isa_structure', {})
        
        for sheet_name, sheet_data in isa_structure.items():
            if sheet_name == 'description':
                continue
            
            fields = sheet_data.get('fields', [])
            for field in fields:
                field_name = field.get('field_name', '').lower()
                value = field.get('value', '')
                
                # Skip empty or "not specified" values
                if not value or value.lower() in ['not specified', 'not applicable', 'n/a']:
                    continue
                
                # Detect field type from name and validate
                if 'date' in field_name:
                    if not self._validate_date(value):
                        warnings.append(f"Invalid date format for '{field_name}': {value}")
                
                elif 'email' in field_name:
                    if not self._validate_email(value):
                        warnings.append(f"Invalid email format for '{field_name}': {value}")
                
                elif 'url' in field_name or field_name.endswith('_link'):
                    if not self._validate_url(value):
                        warnings.append(f"Invalid URL format for '{field_name}': {value}")
                
                elif 'taxid' in field_name or 'taxonomy' in field_name:
                    if not self._validate_ncbi_taxid(value):
                        warnings.append(f"Invalid NCBI taxonomy ID for '{field_name}': {value}")
                
                elif field_name == 'latitude' or 'latitude' in field_name:
                    if not self._validate_latitude(value):
                        warnings.append(f"Invalid latitude for '{field_name}': {value}")
                
                elif field_name == 'longitude' or 'longitude' in field_name:
                    if not self._validate_longitude(value):
                        warnings.append(f"Invalid longitude for '{field_name}': {value}")
        
        return True  # Format validation mostly produces warnings
    
    # Format validators
    
    def _validate_date(self, value: str) -> bool:
        """Validate date format."""
        date_patterns = [
            r'^\d{4}-\d{2}-\d{2}$',  # YYYY-MM-DD
            r'^\d{4}-\d{2}$',  # YYYY-MM
            r'^\d{4}$',  # YYYY
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',  # ISO 8601
        ]
        
        for pattern in date_patterns:
            if re.match(pattern, str(value)):
                return True
        return False
    
    def _validate_url(self, value: str) -> bool:
        """Validate URL format."""
        try:
            result = urlparse(str(value))
            return all([result.scheme, result.netloc])
        except:
            return False
    
    def _validate_email(self, value: str) -> bool:
        """Validate email format."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, str(value)))
    
    def _validate_ncbi_taxid(self, value: str) -> bool:
        """Validate NCBI taxonomy ID format."""
        # Should be numeric
        return str(value).isdigit()
    
    def _validate_numeric(self, value: str) -> bool:
        """Validate numeric value."""
        try:
            float(value)
            return True
        except:
            return False
    
    def _validate_latitude(self, value: str) -> bool:
        """Validate latitude (-90 to 90)."""
        try:
            lat = float(value)
            return -90 <= lat <= 90
        except:
            return False
    
    def _validate_longitude(self, value: str) -> bool:
        """Validate longitude (-180 to 180)."""
        try:
            lon = float(value)
            return -180 <= lon <= 180
        except:
            return False
    
    def validate_batch(
        self,
        fairifier_outputs: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Validate multiple documents.
        
        Args:
            fairifier_outputs: Dict mapping document_id -> fairifier output
            
        Returns:
            Aggregated validation results
        """
        per_document_results = {}
        
        for doc_id, output in fairifier_outputs.items():
            result = self.validate(output)
            per_document_results[doc_id] = result
        
        # Aggregate statistics
        aggregated = self._aggregate_results(per_document_results)
        
        return {
            'per_document': per_document_results,
            'aggregated': aggregated
        }
    
    def _aggregate_results(self, per_document_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate validation results across documents."""
        if not per_document_results:
            return {}
        
        valid_docs = sum(1 for r in per_document_results.values() if r['is_valid'])
        total_docs = len(per_document_results)
        
        compliance_rates = [r['schema_compliance_rate'] for r in per_document_results.values()]
        total_errors = sum(len(r['errors']) for r in per_document_results.values())
        total_warnings = sum(len(r['warnings']) for r in per_document_results.values())
        
        return {
            'valid_documents': valid_docs,
            'total_documents': total_docs,
            'validation_pass_rate': valid_docs / total_docs if total_docs > 0 else 0.0,
            'mean_compliance_rate': sum(compliance_rates) / len(compliance_rates),
            'min_compliance_rate': min(compliance_rates),
            'max_compliance_rate': max(compliance_rates),
            'total_errors': total_errors,
            'total_warnings': total_warnings
        }

