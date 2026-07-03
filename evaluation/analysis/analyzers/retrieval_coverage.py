"""Retrieval coverage analyzer for shadow-mode rollout metrics."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

import pandas as pd


class RetrievalCoverageAnalyzer:
    """Aggregate retrieval/coverage metrics across evaluation runs."""

    def build_document_dataframe(self, evaluation_results: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []
        for run_id, eval_data in evaluation_results.items():
            per_model = eval_data.get("per_model_results", {})
            for model_name, model_data in per_model.items():
                retrieval = model_data.get("retrieval_coverage", {}).get("per_document", {})
                completeness = model_data.get("completeness", {}).get("per_document", {})
                for doc_id, metrics in retrieval.items():
                    comp = completeness.get(doc_id, {}).get("overall_metrics", {})
                    retrieval_block = metrics.get("retrieval_coverage", metrics)
                    section_block = metrics.get("section_coverage", {})
                    rows.append(
                        {
                            "run_id": run_id,
                            "model_name": model_name,
                            "document_id": doc_id,
                            "coverage_score": metrics.get("coverage_score", 0.0),
                            "section_coverage_ratio": self._section_ratio(section_block),
                            "semantic_only_fields": retrieval_block.get("fields_with_semantic_only_candidates", 0),
                            "legacy_only_fields": retrieval_block.get("fields_with_legacy_only_candidates", 0),
                            "hybrid_gain_fields": retrieval_block.get("fields_with_hybrid_gain", 0),
                            "qdrant_fallback_used": retrieval_block.get("qdrant_fallback_used", False),
                            "rerank_timeout_rate": retrieval_block.get("rerank_timeout_rate", 0.0),
                            "evidence_store_items": retrieval_block.get("evidence_store_items", 0),
                            "overall_completeness": comp.get("overall_completeness", 0.0),
                        }
                    )
        return pd.DataFrame(rows)

    def summarize_by_model(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        grouped = (
            df.groupby("model_name")
            .agg(
                mean_coverage_score=("coverage_score", "mean"),
                mean_section_coverage=("section_coverage_ratio", "mean"),
                mean_semantic_only_fields=("semantic_only_fields", "mean"),
                mean_legacy_only_fields=("legacy_only_fields", "mean"),
                mean_hybrid_gain_fields=("hybrid_gain_fields", "mean"),
                qdrant_fallback_rate=("qdrant_fallback_used", "mean"),
                mean_rerank_timeout_rate=("rerank_timeout_rate", "mean"),
                n_documents=("document_id", "count"),
            )
            .reset_index()
        )
        return grouped

    def shadow_gain_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df.empty:
            return {"status": "no_data"}
        return {
            "documents": int(df["document_id"].nunique()),
            "models": int(df["model_name"].nunique()),
            "mean_hybrid_gain_fields": float(df["hybrid_gain_fields"].mean()),
            "mean_semantic_only_fields": float(df["semantic_only_fields"].mean()),
            "qdrant_fallback_rate": float(df["qdrant_fallback_used"].mean()),
            "mean_section_coverage": float(df["section_coverage_ratio"].mean()),
        }

    @staticmethod
    def _section_ratio(section_block: Dict[str, Any]) -> float:
        total = int(section_block.get("sections_total") or section_block.get("planned_sections") or 0)
        processed = int(section_block.get("sections_processed") or section_block.get("processed_sections") or 0)
        if total <= 0:
            return 0.0
        return processed / total
