"""
Schema Validator for FAIRiAgent outputs.

Validates:
- JSON structure compliance
- Required fields presence
- Field data types
- Value format compliance (dates, URLs, IDs)
- ISA-Tab structure compliance

Implementation is delegated to fairifier.validation.metadata_json_format
(single source of truth).
"""

from typing import Dict, Any

from fairifier.validation.metadata_json_format import (
    REQUIRED_FIELDS_BY_SHEET,
    check_metadata_json_output,
)


class SchemaValidator:
    """Validate FAIRiAgent output against schema requirements."""

    def __init__(self):
        """Initialize schema validator."""
        self.required_fields_by_sheet = dict(REQUIRED_FIELDS_BY_SHEET)

    def validate(self, fairifier_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate FAIRiAgent output.

        Args:
            fairifier_output: Parsed metadata_json.json from FAIRiAgent

        Returns:
            Dict with validation results
        """
        return check_metadata_json_output(fairifier_output)

    def validate_batch(
        self,
        fairifier_outputs: Dict[str, Dict[str, Any]],
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

        aggregated = self._aggregate_results(per_document_results)

        return {
            "per_document": per_document_results,
            "aggregated": aggregated,
        }

    def _aggregate_results(
        self, per_document_results: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Aggregate validation results across documents."""
        if not per_document_results:
            return {}

        valid_docs = sum(1 for r in per_document_results.values() if r["is_valid"])
        total_docs = len(per_document_results)

        compliance_rates = [
            r["schema_compliance_rate"] for r in per_document_results.values()
        ]
        total_errors = sum(
            len(r["errors"]) for r in per_document_results.values()
        )
        total_warnings = sum(
            len(r["warnings"]) for r in per_document_results.values()
        )
        pass_rate = valid_docs / total_docs if total_docs > 0 else 0.0
        mean_rate = sum(compliance_rates) / len(compliance_rates)

        return {
            "valid_documents": valid_docs,
            "total_documents": total_docs,
            "validation_pass_rate": pass_rate,
            "mean_compliance_rate": mean_rate,
            "min_compliance_rate": min(compliance_rates),
            "max_compliance_rate": max(compliance_rates),
            "total_errors": total_errors,
            "total_warnings": total_warnings,
        }
