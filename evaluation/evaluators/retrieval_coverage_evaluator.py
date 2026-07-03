"""Retrieval coverage evaluator for hybrid retrieval rollout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class RetrievalCoverageEvaluator:
    """Evaluate retrieval coverage metrics from workflow reports."""

    def evaluate_document(
        self,
        metadata_json: Dict[str, Any],
        workflow_report: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "retrieval_metrics": {},
            "section_coverage": {},
            "coverage_score": 0.0,
            "fields_with_hybrid_telemetry": 0,
            "sections_processed": 0,
        }
        if not workflow_report:
            return result

        retrieval_metrics = workflow_report.get("retrieval_metrics") or {}
        section_coverage = workflow_report.get("section_coverage") or {}
        field_stats: List[Dict[str, Any]] = retrieval_metrics.get("field_retrieval_stats") or []

        hybrid_fields = sum(
            1 for item in field_stats if int(item.get("hybrid_hit_count") or 0) > 0
        )
        lexical_fields = sum(
            1 for item in field_stats if int(item.get("lexical_hit_count") or 0) > 0
        )
        sections_processed = int(section_coverage.get("sections_processed") or 0)
        sections_total = int(section_coverage.get("sections_total") or 0)

        coverage_score = 0.0
        if sections_total > 0:
            coverage_score += 0.5 * (sections_processed / sections_total)
        if field_stats:
            coverage_score += 0.5 * (lexical_fields / len(field_stats))

        result["retrieval_metrics"] = retrieval_metrics
        result["section_coverage"] = section_coverage
        result["fields_with_hybrid_telemetry"] = hybrid_fields
        result["sections_processed"] = sections_processed
        result["coverage_score"] = round(coverage_score, 4)
        return result

    def evaluate_batch(
        self,
        fairifier_outputs: Dict[str, Dict[str, Any]],
        output_dirs: Optional[Dict[str, Path]] = None,
    ) -> Dict[str, Any]:
        per_document: Dict[str, Any] = {}
        for doc_id, metadata_json in fairifier_outputs.items():
            workflow_report = None
            if output_dirs and doc_id in output_dirs:
                report_path = output_dirs[doc_id] / "workflow_report.json"
                if report_path.exists():
                    try:
                        workflow_report = json.loads(report_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        workflow_report = None
            per_document[doc_id] = self.evaluate_document(metadata_json, workflow_report)

        coverage_scores = [doc.get("coverage_score", 0.0) for doc in per_document.values()]
        return {
            "per_document": per_document,
            "aggregated": {
                "mean_coverage_score": sum(coverage_scores) / len(coverage_scores) if coverage_scores else 0.0,
                "documents_with_section_coverage": sum(
                    1 for doc in per_document.values() if int(doc.get("sections_processed") or 0) > 0
                ),
            },
        }
