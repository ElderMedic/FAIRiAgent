"""
Mandatory Coverage Evaluator for FAIRiAgent outputs.

Evaluates whether runs meet the critical success criterion:
100% coverage of mandatory fields for the selected metadata package.
"""

from typing import Dict, List, Any, Set
import json


class MandatoryCoverageEvaluator:
    """Evaluate mandatory field coverage as success criterion."""
    
    def __init__(self):
        """Initialize the mandatory coverage evaluator."""
        pass
    
    def evaluate_run_success(
        self, 
        fairifier_output: Dict[str, Any],
        ground_truth_doc: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Determine if a run meets success criteria.
        
        Success = 100% mandatory fields covered for selected package
        
        Args:
            fairifier_output: Parsed metadata.json from FAIRiAgent
            ground_truth_doc: Ground truth annotation for this document
            
        Returns:
            Dict with success evaluation results
        """
        # Extract fields
        extracted_fields = self._extract_field_names(fairifier_output)
        ground_truth_fields = ground_truth_doc.get('ground_truth_fields', [])
        
        # Identify selected package
        selected_package = self._identify_package(fairifier_output)
        expected_package = ground_truth_doc.get('metadata', {}).get('expected_package', 'default')
        
        # Get mandatory fields for selected package
        mandatory_fields = {
            f['field_name'] for f in ground_truth_fields
            if f.get('is_required', False) and 
               f.get('package_source', 'default') == selected_package
        }
        
        # Also include default mandatory fields (always required)
        default_mandatory = {
            f['field_name'] for f in ground_truth_fields
            if f.get('is_required', False) and 
               f.get('package_source', 'default') == 'default'
        }
        
        all_mandatory = mandatory_fields | default_mandatory
        
        # Calculate coverage
        covered_mandatory = extracted_fields & all_mandatory
        missing_mandatory = all_mandatory - extracted_fields
        
        mandatory_coverage = len(covered_mandatory) / len(all_mandatory) if all_mandatory else 1.0
        
        # Determine success
        is_successful = (mandatory_coverage == 1.0)
        
        # Package correctness
        package_correct = (selected_package == expected_package)
        
        return {
            'is_successful': is_successful,
            'selected_package': selected_package,
            'expected_package': expected_package,
            'package_correct': package_correct,
            'mandatory_fields_total': len(all_mandatory),
            'mandatory_fields_covered': len(covered_mandatory),
            'mandatory_fields_missing': len(missing_mandatory),
            'mandatory_coverage': mandatory_coverage,
            'missing_mandatory_fields': list(missing_mandatory),
            'success_criterion': '100% mandatory coverage',
            'failure_reason': self._determine_failure_reason(
                is_successful, package_correct, missing_mandatory
            )
        }
    
    def _extract_field_names(self, fairifier_output: Dict[str, Any]) -> Set[str]:
        """Extract all field names from FAIRiAgent output."""
        field_names = set()
        
        # Check ISA structure
        isa_structure = fairifier_output.get('isa_structure', {})
        for sheet_name, sheet_data in isa_structure.items():
            if sheet_name == 'description':
                continue
            
            for field in sheet_data.get('fields', []):
                field_name = field.get('field_name', '').strip()
                if field_name:
                    field_names.add(field_name)
        
        # Fallback: check flat metadata list
        if not field_names:
            metadata_list = fairifier_output.get('metadata', [])
            for field in metadata_list:
                field_name = field.get('field_name', '').strip()
                if field_name:
                    field_names.add(field_name)
        
        return field_names
    
    def _identify_package(self, fairifier_output: Dict[str, Any]) -> str:
        """Identify the metadata package selected by the agent."""
        # Check workflow report
        workflow_report = fairifier_output.get('workflow_report', {})
        if 'selected_package' in workflow_report:
            return workflow_report['selected_package']
        
        # Check metadata
        metadata = fairifier_output.get('metadata_summary', {})
        if 'package' in metadata:
            return metadata['package']
        
        # Check isa_structure
        isa = fairifier_output.get('isa_structure', {})
        if 'metadata_package' in isa:
            return isa['metadata_package']
        
        # Default fallback
        return 'default'
    
    def _determine_failure_reason(
        self,
        is_successful: bool,
        package_correct: bool,
        missing_mandatory: Set[str]
    ) -> str:
        """Determine why a run failed."""
        if is_successful:
            return None
        
        if not package_correct:
            return "WRONG_PACKAGE_SELECTED"
        
        if len(missing_mandatory) > 5:
            return "MANY_MANDATORY_MISSING"
        elif len(missing_mandatory) > 0:
            return "FEW_MANDATORY_MISSING"
        else:
            return "UNKNOWN"
    
    def compute_success_rate(
        self,
        run_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Compute success rate across multiple runs.
        
        Args:
            run_results: List of evaluation results from evaluate_run_success()
            
        Returns:
            Dict with success rate statistics
        """
        total_runs = len(run_results)
        successful_runs = sum(1 for r in run_results if r['is_successful'])
        
        # Package selection accuracy
        correct_package = sum(1 for r in run_results if r['package_correct'])
        
        # Average mandatory coverage
        avg_coverage = sum(r['mandatory_coverage'] for r in run_results) / total_runs if total_runs else 0
        
        # Failure breakdown
        failure_reasons = {}
        for result in run_results:
            if not result['is_successful']:
                reason = result['failure_reason']
                failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
        
        return {
            'total_runs': total_runs,
            'successful_runs': successful_runs,
            'failed_runs': total_runs - successful_runs,
            'success_rate': successful_runs / total_runs if total_runs else 0.0,
            'package_selection_accuracy': correct_package / total_runs if total_runs else 0.0,
            'average_mandatory_coverage': avg_coverage,
            'failure_reasons': failure_reasons
        }
    
    def filter_successful_runs(
        self,
        all_runs: List[Dict[str, Any]],
        run_evaluations: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Filter runs into successful and failed groups.
        
        Args:
            all_runs: List of all run data (with metadata and eval results)
            run_evaluations: List of mandatory coverage evaluations (from evaluate_run_success)
            
        Returns:
            Tuple of (successful_runs, failed_runs)
        """
        successful = []
        failed = []
        
        for run, evaluation in zip(all_runs, run_evaluations):
            if evaluation['is_successful']:
                successful.append({**run, 'mandatory_eval': evaluation})
            else:
                failed.append({**run, 'mandatory_eval': evaluation})
        
        return successful, failed
