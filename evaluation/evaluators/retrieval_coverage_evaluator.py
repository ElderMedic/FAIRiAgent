"""Retrieval coverage evaluator for hybrid retrieval rollout."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class RetrievalCoverageEvaluator:
    """Evaluate retrieval coverage metrics from workflow reports."""

    def evaluate_document(
        self,
        metadata_json: Dict[str, Any],
        workflow_report: Optional[Dict[str, Any]] = None,
        *,
        ground_truth_doc: Optional[Dict[str, Any]] = None,
        evidence_store_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "retrieval_coverage": {},
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

        hybrid_gain_fields = 0
        legacy_only_fields = 0
        semantic_only_fields = 0
        for item in field_stats:
            lexical_hits = int(item.get("lexical_hit_count") or 0)
            semantic_hits = int(item.get("semantic_hit_count") or 0)
            hybrid_hits = int(item.get("hybrid_hit_count") or 0)
            if hybrid_hits > lexical_hits:
                hybrid_gain_fields += 1
            if lexical_hits > 0 and semantic_hits == 0:
                legacy_only_fields += 1
            if semantic_hits > 0 and lexical_hits == 0:
                semantic_only_fields += 1

        sections_total = int(
            section_coverage.get("sections_total")
            or section_coverage.get("planned_sections")
            or 0
        )
        sections_processed = int(
            section_coverage.get("sections_processed")
            or section_coverage.get("processed_sections")
            or 0
        )
        section_coverage_ratio = (
            sections_processed / sections_total if sections_total > 0 else 0.0
        )

        fields_with_source_refs = self._count_source_grounded_fields(metadata_json)
        evidence_overlap = self._estimate_evidence_overlap(
            metadata_json,
            ground_truth_doc,
            evidence_store_path,
        )

        retrieval_coverage = {
            "section_coverage_ratio": round(section_coverage_ratio, 4),
            "fields_with_source_refs": fields_with_source_refs,
            "fields_with_semantic_only_candidates": semantic_only_fields,
            "fields_with_legacy_only_candidates": legacy_only_fields,
            "fields_with_hybrid_gain": hybrid_gain_fields,
            "qdrant_fallback_used": bool(retrieval_metrics.get("qdrant_fallback_used", False)),
            "rerank_timeout_rate": float(retrieval_metrics.get("rerank_timeout_rate") or 0.0),
            "evidence_store_items": int(retrieval_metrics.get("evidence_items") or 0),
            "semantic_index_status": retrieval_metrics.get("semantic_index_status"),
            "evidence_overlap": evidence_overlap,
        }

        coverage_score = 0.0
        if sections_total > 0:
            coverage_score += 0.4 * section_coverage_ratio
        if field_stats:
            coverage_score += 0.3 * (legacy_only_fields / len(field_stats))
            coverage_score += 0.3 * (hybrid_gain_fields / len(field_stats))

        result["retrieval_coverage"] = retrieval_coverage
        result["section_coverage"] = section_coverage
        result["retrieval_metrics"] = retrieval_metrics
        result["fields_with_hybrid_telemetry"] = hybrid_gain_fields
        result["sections_processed"] = sections_processed
        result["coverage_score"] = round(coverage_score, 4)
        return result

    def _count_source_grounded_fields(self, metadata_json: Dict[str, Any]) -> int:
        count = 0
        pattern = re.compile(r"[A-Za-z0-9_]+:\d+-\d+")
        isa_structure = metadata_json.get("isa_structure", {})
        for sheet_name, sheet_data in isa_structure.items():
            if sheet_name == "description" or not isinstance(sheet_data, dict):
                continue
            for field in sheet_data.get("fields", []):
                if not isinstance(field, dict):
                    continue
                evidence = " ".join(
                    str(field.get(key) or "")
                    for key in ("evidence", "source_ref", "provenance", "notes")
                )
                if pattern.search(evidence):
                    count += 1
        return count

    def _estimate_evidence_overlap(
        self,
        metadata_json: Dict[str, Any],
        ground_truth_doc: Optional[Dict[str, Any]],
        evidence_store_path: Optional[Path],
    ) -> Dict[str, Any]:
        """Best-effort overlap between extracted refs and ground-truth evidence strings."""
        overlap = {
            "tier": "source_ref_presence_only",
            "matched_fields": 0,
            "annotated_fields": 0,
            "exact_span_matches": 0,
            "section_text_matches": 0,
        }
        if not ground_truth_doc:
            return overlap

        gt_values = ground_truth_doc.get("ground_truth_fields") or []
        overlap["annotated_fields"] = len(gt_values)
        extracted_names = set()
        isa_structure = metadata_json.get("isa_structure", {})
        for sheet_data in isa_structure.values():
            if not isinstance(sheet_data, dict):
                continue
            for field in sheet_data.get("fields", []):
                if isinstance(field, dict) and field.get("field_name"):
                    extracted_names.add(str(field["field_name"]).lower())

        for gt_field in gt_values:
            name = str(gt_field.get("field_name") or "").lower()
            if name and name in extracted_names:
                overlap["matched_fields"] += 1

        evidence_texts: List[str] = []
        if evidence_store_path and evidence_store_path.is_file():
            for line in evidence_store_path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = str(record.get("evidence_text") or record.get("text") or "")
                if text:
                    evidence_texts.append(text.lower())

        for gt_field in gt_values:
            evidence = str(gt_field.get("_evidence") or gt_field.get("evidence") or "").lower()
            if not evidence:
                continue
            if any(evidence[:40] in text for text in evidence_texts if len(evidence) >= 8):
                overlap["section_text_matches"] += 1

        if overlap["section_text_matches"] > 0:
            overlap["tier"] = "section_text_match"
        elif overlap["matched_fields"] > 0:
            overlap["tier"] = "field_name_match"
        return overlap

    def evaluate_batch(
        self,
        fairifier_outputs: Dict[str, Dict[str, Any]],
        output_dirs: Optional[Dict[str, Path]] = None,
        ground_truth_docs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        per_document: Dict[str, Any] = {}
        for doc_id, metadata_json in fairifier_outputs.items():
            workflow_report = None
            evidence_store_path = None
            if output_dirs and doc_id in output_dirs:
                output_dir = output_dirs[doc_id]
                report_path = output_dir / "workflow_report.json"
                if report_path.exists():
                    try:
                        workflow_report = json.loads(report_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        workflow_report = None
                candidate = output_dir / "source_workspace" / "evidence_store.jsonl"
                if candidate.is_file():
                    evidence_store_path = candidate

            per_document[doc_id] = self.evaluate_document(
                metadata_json,
                workflow_report,
                ground_truth_doc=(ground_truth_docs or {}).get(doc_id),
                evidence_store_path=evidence_store_path,
            )

        coverage_scores = [doc.get("coverage_score", 0.0) for doc in per_document.values()]
        hybrid_gain = [
            doc.get("retrieval_coverage", {}).get("fields_with_hybrid_gain", 0)
            for doc in per_document.values()
        ]
        return {
            "per_document": per_document,
            "aggregated": {
                "mean_coverage_score": sum(coverage_scores) / len(coverage_scores) if coverage_scores else 0.0,
                "mean_hybrid_gain_fields": sum(hybrid_gain) / len(hybrid_gain) if hybrid_gain else 0.0,
                "documents_with_section_coverage": sum(
                    1 for doc in per_document.values() if int(doc.get("sections_processed") or 0) > 0
                ),
                "qdrant_fallback_rate": sum(
                    1
                    for doc in per_document.values()
                    if doc.get("retrieval_coverage", {}).get("qdrant_fallback_used")
                ) / len(per_document) if per_document else 0.0,
            },
        }
