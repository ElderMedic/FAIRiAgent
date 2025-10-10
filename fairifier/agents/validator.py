"""Validation agent for SHACL validation and quality assessment."""

from typing import Dict, Any, List, Tuple
from rdflib import Graph
import pyshacl

from .base import BaseAgent
from ..models import FAIRifierState, ValidationResult
from ..config import config


class ValidationAgent(BaseAgent):
    """Agent for validating RDF graphs and assessing metadata quality."""
    
    def __init__(self):
        super().__init__("Validator")
        
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """Validate RDF graph and assess metadata quality."""
        self.log_execution(state, "Starting validation")
        
        try:
            rdf_graph = state.get("rdf_graph", "")
            metadata_fields = state["metadata_fields"]
            
            # Validate RDF syntax
            syntax_valid, syntax_errors = self._validate_rdf_syntax(rdf_graph)
            
            # Perform SHACL validation (basic)
            shacl_valid, shacl_errors, shacl_warnings = self._validate_with_shacl(rdf_graph)
            
            # Assess metadata quality
            quality_score, quality_issues = self._assess_metadata_quality(metadata_fields)
            
            # Combine validation results
            validation_result = ValidationResult(
                is_valid=syntax_valid and shacl_valid and quality_score > 0.6,
                errors=syntax_errors + shacl_errors + quality_issues,
                warnings=shacl_warnings,
                score=quality_score
            )
            
            # Store validation results
            state["validation_results"] = {
                "is_valid": validation_result.is_valid,
                "errors": validation_result.errors,
                "warnings": validation_result.warnings,
                "score": validation_result.score,
                "syntax_valid": syntax_valid,
                "shacl_valid": shacl_valid,
                "quality_score": quality_score
            }
            
            # Generate validation report
            report = self._generate_validation_report(validation_result, metadata_fields)
            
            if "artifacts" not in state:
                state["artifacts"] = {}
            state["artifacts"]["validation_report"] = report
            
            # Update confidence and review flags
            confidence = validation_result.score
            self.update_confidence(state, "validation", confidence)
            
            if not validation_result.is_valid or confidence < config.min_confidence_threshold:
                state["needs_human_review"] = True
            
            self.log_execution(
                state,
                f"Validation completed. Valid: {validation_result.is_valid}, "
                f"Score: {validation_result.score:.2f}, "
                f"Errors: {len(validation_result.errors)}"
            )
            
        except Exception as e:
            self.log_execution(state, f"Validation failed: {str(e)}", "error")
            self.update_confidence(state, "validation", 0.0)
            state["needs_human_review"] = True
        
        return state
    
    def _validate_rdf_syntax(self, rdf_content: str) -> Tuple[bool, List[str]]:
        """Validate RDF syntax."""
        try:
            graph = Graph()
            graph.parse(data=rdf_content, format='turtle')
            return True, []
        except Exception as e:
            return False, [f"RDF syntax error: {str(e)}"]
    
    def _validate_with_shacl(self, rdf_content: str) -> Tuple[bool, List[str], List[str]]:
        """Perform SHACL validation with basic shapes."""
        try:
            # Create basic SHACL shapes for validation
            shapes_graph = self._create_basic_shapes()
            
            # Load data graph
            data_graph = Graph()
            data_graph.parse(data=rdf_content, format='turtle')
            
            # Perform SHACL validation
            conforms, results_graph, results_text = pyshacl.validate(
                data_graph=data_graph,
                shacl_graph=shapes_graph,
                inference='rdfs',
                abort_on_first=False
            )
            
            errors = []
            warnings = []
            
            if not conforms and results_text:
                # Parse validation results
                lines = results_text.split('\n')
                for line in lines:
                    if 'Violation' in line:
                        errors.append(line.strip())
                    elif 'Warning' in line:
                        warnings.append(line.strip())
            
            return conforms, errors, warnings
            
        except Exception as e:
            return False, [f"SHACL validation error: {str(e)}"], []
    
    def _create_basic_shapes(self) -> Graph:
        """Create basic SHACL shapes for validation."""
        shapes_ttl = """
        @prefix sh: <http://www.w3.org/ns/shacl#> .
        @prefix schema: <https://schema.org/> .
        @prefix dcterms: <http://purl.obolibrary.org/obo/> .
        @prefix fairifier: <http://fairifier.org/> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        
        fairifier:DatasetShape
            a sh:NodeShape ;
            sh:targetClass schema:Dataset ;
            sh:property [
                sh:path dcterms:title ;
                sh:minCount 1 ;
                sh:datatype xsd:string ;
                sh:message "Dataset must have a title" ;
            ] ;
            sh:property [
                sh:path schema:author ;
                sh:minCount 1 ;
                sh:message "Dataset must have at least one author" ;
            ] .
        
        fairifier:PersonShape
            a sh:NodeShape ;
            sh:targetClass schema:Person ;
            sh:property [
                sh:path <http://xmlns.com/foaf/0.1/name> ;
                sh:minCount 1 ;
                sh:datatype xsd:string ;
                sh:message "Person must have a name" ;
            ] .
        """
        
        shapes_graph = Graph()
        shapes_graph.parse(data=shapes_ttl, format='turtle')
        return shapes_graph
    
    def _assess_metadata_quality(self, metadata_fields: List[Dict[str, Any]]) -> Tuple[float, List[str]]:
        """Assess the quality of metadata fields."""
        issues = []
        scores = []
        
        if not metadata_fields:
            issues.append("No metadata fields generated")
            return 0.0, issues
        
        # Check required field coverage
        required_fields = [f for f in metadata_fields if f.get("required", False)]
        if len(required_fields) < 3:
            issues.append(f"Insufficient required fields: {len(required_fields)} (expected at least 3)")
        
        required_score = min(len(required_fields) / 5.0, 1.0)
        scores.append(required_score * 0.3)
        
        # Check field completeness (example values)
        fields_with_values = [f for f in metadata_fields if f.get("example_value")]
        completeness_score = len(fields_with_values) / len(metadata_fields) if metadata_fields else 0
        scores.append(completeness_score * 0.3)
        
        if completeness_score < 0.5:
            issues.append(f"Low field completeness: {completeness_score:.1%}")
        
        # Check ontology term coverage
        fields_with_ontology = [f for f in metadata_fields if f.get("ontology_term")]
        ontology_score = len(fields_with_ontology) / len(metadata_fields) if metadata_fields else 0
        scores.append(ontology_score * 0.2)
        
        if ontology_score < 0.3:
            issues.append(f"Low ontology term coverage: {ontology_score:.1%}")
        
        # Check confidence scores
        confidence_scores = [f.get("confidence", 0) for f in metadata_fields]
        avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
        scores.append(avg_confidence * 0.2)
        
        if avg_confidence < 0.6:
            issues.append(f"Low average confidence: {avg_confidence:.2f}")
        
        overall_score = sum(scores)
        return overall_score, issues
    
    def _generate_validation_report(self, validation_result: ValidationResult, metadata_fields: List[Dict[str, Any]]) -> str:
        """Generate human-readable validation report."""
        report_lines = [
            "# FAIRifier Validation Report",
            f"Generated: {self._get_timestamp()}",
            "",
            "## Overall Status",
            f"Valid: {'✓' if validation_result.is_valid else '✗'}",
            f"Quality Score: {validation_result.score:.2f}/1.0",
            ""
        ]
        
        # Metadata summary
        report_lines.extend([
            "## Metadata Summary",
            f"Total fields: {len(metadata_fields)}",
            f"Required fields: {sum(1 for f in metadata_fields if f.get('required', False))}",
            f"Fields with values: {sum(1 for f in metadata_fields if f.get('example_value'))}",
            f"Fields with ontology terms: {sum(1 for f in metadata_fields if f.get('ontology_term'))}",
            ""
        ])
        
        # Errors
        if validation_result.errors:
            report_lines.extend([
                "## Errors",
                *[f"- {error}" for error in validation_result.errors],
                ""
            ])
        
        # Warnings
        if validation_result.warnings:
            report_lines.extend([
                "## Warnings", 
                *[f"- {warning}" for warning in validation_result.warnings],
                ""
            ])
        
        # Recommendations
        report_lines.extend([
            "## Recommendations"
        ])
        
        if validation_result.score < 0.8:
            report_lines.append("- Consider human review to improve metadata quality")
        
        if not validation_result.is_valid:
            report_lines.append("- Fix validation errors before proceeding")
        
        required_fields = [f for f in metadata_fields if f.get("required", False)]
        if len(required_fields) < 5:
            report_lines.append("- Add more required metadata fields")
        
        fields_without_values = [f for f in metadata_fields if not f.get("example_value")]
        if fields_without_values:
            report_lines.append(f"- Provide values for {len(fields_without_values)} empty fields")
        
        return "\n".join(report_lines)
    
    def _get_timestamp(self) -> str:
        """Get current timestamp."""
        from datetime import datetime
        return datetime.now().isoformat()
