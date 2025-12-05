"""
Completeness Evaluator for FAIRiAgent outputs.

Evaluates field coverage:
- Overall completeness
- Required vs recommended vs optional
- Per ISA sheet breakdown
- Package-specific coverage
"""

from typing import Dict, List, Any, Set
from pathlib import Path
import json


class CompletenessEvaluator:
    """Evaluate metadata completeness against ground truth."""
    
    def __init__(self):
        """Initialize the completeness evaluator."""
        self.results = {}
    
    def evaluate(
        self, 
        fairifier_output: Dict[str, Any],
        ground_truth_doc: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Evaluate completeness of FAIRiAgent output against ground truth.
        
        Args:
            fairifier_output: Parsed metadata_json.json from FAIRiAgent
            ground_truth_doc: Ground truth annotation for this document
            
        Returns:
            Dict with completeness metrics
        """
        # Extract field sets
        extracted_fields = self._extract_fields_from_fairifier(fairifier_output)
        ground_truth_fields = self._extract_fields_from_ground_truth(ground_truth_doc)
        
        # Categorize ground truth fields
        required_fields = {
            f['field_name'] for f in ground_truth_fields 
            if f.get('is_required', False)
        }
        recommended_fields = {
            f['field_name'] for f in ground_truth_fields 
            if f.get('is_recommended', False)
        }
        optional_fields = {
            f['field_name'] for f in ground_truth_fields 
            if not f.get('is_required', False) and not f.get('is_recommended', False)
        }
        all_gt_fields = {f['field_name'] for f in ground_truth_fields}
        
        # Calculate coverage
        extracted_field_names = {f['field_name'] for f in extracted_fields}
        
        covered_all = extracted_field_names & all_gt_fields
        covered_required = extracted_field_names & required_fields
        covered_recommended = extracted_field_names & recommended_fields
        covered_optional = extracted_field_names & optional_fields
        
        # Overall metrics
        overall_metrics = {
            'total_ground_truth_fields': len(all_gt_fields),
            'total_extracted_fields': len(extracted_field_names),
            'covered_fields': len(covered_all),
            'missing_fields': len(all_gt_fields - extracted_field_names),
            'extra_fields': len(extracted_field_names - all_gt_fields),
            
            'overall_completeness': len(covered_all) / len(all_gt_fields) if all_gt_fields else 0.0,
            'required_completeness': len(covered_required) / len(required_fields) if required_fields else 1.0,
            'recommended_completeness': len(covered_recommended) / len(recommended_fields) if recommended_fields else 1.0,
            'optional_completeness': len(covered_optional) / len(optional_fields) if optional_fields else 1.0,
            
            'missing_required_fields': list(required_fields - extracted_field_names),
            'missing_recommended_fields': list(recommended_fields - extracted_field_names),
            'extra_fields_list': list(extracted_field_names - all_gt_fields)
        }
        
        # ISA sheet breakdown
        isa_metrics = self._compute_isa_sheet_metrics(
            extracted_fields, ground_truth_fields
        )
        
        # Package breakdown
        package_metrics = self._compute_package_metrics(
            extracted_fields, ground_truth_fields
        )
        
        # Build result
        result = {
            'overall_metrics': overall_metrics,
            'by_isa_sheet': isa_metrics,
            'by_package': package_metrics,
            'summary': {
                'overall_completeness': overall_metrics['overall_completeness'],
                'required_completeness': overall_metrics['required_completeness'],
                'recommended_completeness': overall_metrics['recommended_completeness'],
                'critical_missing': len(overall_metrics['missing_required_fields']),
                'status': self._determine_status(overall_metrics)
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
            
            for field in sheet_data.get('fields', []):
                fields.append({
                    'field_name': field.get('field_name', ''),
                    'value': field.get('value', ''),
                    'isa_sheet': sheet_name,
                    'package_source': field.get('package_source', 'default'),
                    'confidence': field.get('confidence', 0.0),
                    'status': field.get('status', 'unknown')
                })
        
        # Fallback: check flat metadata list
        if not fields:
            metadata_list = fairifier_output.get('metadata', [])
            for field in metadata_list:
                fields.append({
                    'field_name': field.get('field_name', ''),
                    'value': field.get('value', ''),
                    'isa_sheet': field.get('isa_sheet', 'unknown'),
                    'package_source': field.get('package_source', 'default'),
                    'confidence': field.get('confidence', 0.0),
                    'status': field.get('status', 'unknown')
                })
        
        return fields
    
    def _extract_fields_from_ground_truth(self, ground_truth_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract expected fields from ground truth."""
        return ground_truth_doc.get('ground_truth_fields', [])
    
    def _compute_isa_sheet_metrics(
        self, 
        extracted_fields: List[Dict[str, Any]], 
        ground_truth_fields: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Compute completeness metrics per ISA sheet."""
        isa_sheets = ['investigation', 'study', 'assay', 'sample', 'observationunit']
        metrics = {}
        
        for sheet in isa_sheets:
            # Ground truth fields for this sheet
            gt_fields_sheet = {
                f['field_name'] for f in ground_truth_fields 
                if f.get('isa_sheet') == sheet
            }
            
            # Extracted fields for this sheet
            ext_fields_sheet = {
                f['field_name'] for f in extracted_fields 
                if f.get('isa_sheet') == sheet
            }
            
            if not gt_fields_sheet:
                continue
            
            covered = ext_fields_sheet & gt_fields_sheet
            missing = gt_fields_sheet - ext_fields_sheet
            
            metrics[sheet] = {
                'total_expected': len(gt_fields_sheet),
                'covered': len(covered),
                'missing': len(missing),
                'completeness': len(covered) / len(gt_fields_sheet) if gt_fields_sheet else 0.0,
                'missing_fields': list(missing)
            }
        
        return metrics
    
    def _compute_package_metrics(
        self, 
        extracted_fields: List[Dict[str, Any]], 
        ground_truth_fields: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Compute completeness metrics per package source."""
        # Get all unique packages from ground truth
        packages = set(f.get('package_source', 'default') for f in ground_truth_fields)
        metrics = {}
        
        for package in packages:
            # Ground truth fields for this package
            gt_fields_pkg = {
                f['field_name'] for f in ground_truth_fields 
                if f.get('package_source') == package
            }
            
            # Extracted fields for this package
            ext_fields_pkg = {
                f['field_name'] for f in extracted_fields 
                if f.get('package_source') == package
            }
            
            if not gt_fields_pkg:
                continue
            
            covered = ext_fields_pkg & gt_fields_pkg
            missing = gt_fields_pkg - ext_fields_pkg
            
            metrics[package] = {
                'total_expected': len(gt_fields_pkg),
                'covered': len(covered),
                'missing': len(missing),
                'completeness': len(covered) / len(gt_fields_pkg) if gt_fields_pkg else 0.0,
                'missing_fields': list(missing)
            }
        
        return metrics
    
    def _determine_status(self, overall_metrics: Dict[str, Any]) -> str:
        """Determine overall status based on completeness."""
        req_comp = overall_metrics['required_completeness']
        overall_comp = overall_metrics['overall_completeness']
        
        if req_comp >= 0.95 and overall_comp >= 0.80:
            return 'EXCELLENT'
        elif req_comp >= 0.90 and overall_comp >= 0.70:
            return 'GOOD'
        elif req_comp >= 0.80:
            return 'ACCEPTABLE'
        elif req_comp >= 0.60:
            return 'POOR'
        else:
            return 'CRITICAL'
    
    def evaluate_batch(
        self,
        fairifier_outputs: Dict[str, Dict[str, Any]],
        ground_truth_docs: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Evaluate multiple documents.
        
        Args:
            fairifier_outputs: Dict mapping document_id -> fairifier output
            ground_truth_docs: Dict mapping document_id -> ground truth
            
        Returns:
            Aggregated results
        """
        per_document_results = {}
        
        for doc_id in ground_truth_docs:
            if doc_id not in fairifier_outputs:
                print(f"Warning: No FAIRiAgent output for {doc_id}")
                continue
            
            result = self.evaluate(
                fairifier_outputs[doc_id],
                ground_truth_docs[doc_id]
            )
            per_document_results[doc_id] = result
        
        # Aggregate statistics
        aggregated = self._aggregate_results(per_document_results)
        
        return {
            'per_document': per_document_results,
            'aggregated': aggregated
        }
    
    def _aggregate_results(self, per_document_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate metrics across all documents."""
        if not per_document_results:
            return {}
        
        # Collect overall completeness scores
        overall_scores = [
            r['overall_metrics']['overall_completeness'] 
            for r in per_document_results.values()
        ]
        required_scores = [
            r['overall_metrics']['required_completeness'] 
            for r in per_document_results.values()
        ]
        recommended_scores = [
            r['overall_metrics']['recommended_completeness'] 
            for r in per_document_results.values()
        ]
        
        # Aggregate ISA sheet metrics
        isa_sheets = ['investigation', 'study', 'assay', 'sample', 'observationunit']
        isa_aggregated = {}
        
        for sheet in isa_sheets:
            sheet_scores = []
            for r in per_document_results.values():
                if sheet in r.get('by_isa_sheet', {}):
                    sheet_scores.append(r['by_isa_sheet'][sheet]['completeness'])
            
            if sheet_scores:
                isa_aggregated[sheet] = {
                    'mean_completeness': sum(sheet_scores) / len(sheet_scores),
                    'min_completeness': min(sheet_scores),
                    'max_completeness': max(sheet_scores),
                    'n_documents': len(sheet_scores)
                }
        
        return {
            'mean_overall_completeness': sum(overall_scores) / len(overall_scores),
            'mean_required_completeness': sum(required_scores) / len(required_scores),
            'mean_recommended_completeness': sum(recommended_scores) / len(recommended_scores),
            'min_overall_completeness': min(overall_scores),
            'max_overall_completeness': max(overall_scores),
            'by_isa_sheet': isa_aggregated,
            'n_documents': len(per_document_results)
        }

