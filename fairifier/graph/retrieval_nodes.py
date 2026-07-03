"""LangGraph nodes for semantic indexing and section map-reduce coverage."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from langsmith import traceable

from ..config import config
from ..services.chunking import chunk_workspace, serialize_chunking_result
from ..services.evidence_store import EvidenceStore, evidence_from_section
from ..services.semantic_index import SemanticIndex
from .state import FAIRifierState, ProcessingStatus

logger = logging.getLogger(__name__)


class IndexSourcesNode:
    """Chunk sources and build the per-run semantic index."""

    def __init__(self, app=None):
        self.app = app

    @traceable(name="IndexSources", tags=["workflow", "retrieval"])
    async def __call__(self, state: FAIRifierState) -> FAIRifierState:
        workspace_meta = state.get("source_workspace") or {}
        if not (config.semantic_index_enabled and workspace_meta.get("root_dir")):
            state["semantic_index"] = {"status": "skipped", "available": False}
            state["source_chunks"] = []
            state["source_sections"] = []
            return state

        try:
            chunk_result = chunk_workspace(workspace_meta)
            state["source_chunks"] = [
                {
                    "chunk_id": chunk.chunk_id,
                    "source_id": chunk.source_id,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "section_id": chunk.section_id,
                    "section_title": chunk.section_title,
                    "section_type": chunk.section_type,
                }
                for chunk in chunk_result.chunks
            ]
            state["source_sections"] = [
                {
                    "section_id": section.section_id,
                    "source_id": section.source_id,
                    "title": section.title,
                    "section_type": section.section_type,
                    "char_start": section.char_start,
                    "char_end": section.char_end,
                    "chunk_ids": section.chunk_ids,
                    "text": section.text,
                }
                for section in chunk_result.sections
            ]

            session_id = state.get("session_id") or "default"
            semantic_index = SemanticIndex(session_id)
            indexed = 0
            if semantic_index.connect():
                indexed = semantic_index.index_chunks(chunk_result.chunks)

            state["semantic_index"] = {
                **semantic_index.serialize(),
                **serialize_chunking_result(chunk_result),
                "indexed_chunk_count": indexed,
            }
            logger.info(
                "Indexed %s chunks across %s sections (semantic status=%s)",
                len(chunk_result.chunks),
                len(chunk_result.sections),
                semantic_index.status(),
            )
        except Exception as exc:
            logger.warning("IndexSources failed; continuing with lexical retrieval only: %s", exc)
            state.setdefault("errors", []).append(f"IndexSources warning: {exc}")
            state["semantic_index"] = {"status": f"error:{exc}", "available": False}
            state.setdefault("source_chunks", [])
            state.setdefault("source_sections", [])

        return state


class SectionMapReduceNode:
    """Deterministic section coverage via parallel section workers."""

    def __init__(self, app=None):
        self.app = app

    @traceable(name="SectionMapReduce", tags=["workflow", "retrieval"])
    async def __call__(self, state: FAIRifierState) -> FAIRifierState:
        sections = state.get("source_sections") or []
        workspace_meta = state.get("source_workspace") or {}
        if not (config.mapreduce_enabled and sections and workspace_meta.get("root_dir")):
            state["section_coverage"] = {"status": "skipped", "sections_processed": 0}
            return state

        session_id = state.get("session_id") or "default"
        semantic_meta = state.get("semantic_index") or {}
        semantic_index = None
        if semantic_meta.get("available"):
            semantic_index = SemanticIndex(session_id)
            semantic_index.connect()

        evidence_store = EvidenceStore(workspace_meta["root_dir"], semantic_index=semantic_index)
        evidence_store.load_existing()

        max_workers = max(1, int(config.mapreduce_max_workers))
        coverage_records: List[Dict[str, Any]] = []
        new_packets: List[Dict[str, Any]] = []

        def _process_section(section: Dict[str, Any]) -> Dict[str, Any]:
            records = evidence_from_section(section)
            evidence_store.extend(records)
            packets = [
                {
                    "packet_id": record["packet_id"],
                    "field_candidate": record.get("field_candidate"),
                    "value": record.get("value"),
                    "evidence_text": record.get("evidence_text"),
                    "section": record.get("section"),
                    "source_type": "section_map_reduce",
                    "confidence": record.get("confidence", 0.6),
                    "provenance": record.get("provenance", {}),
                }
                for record in records
            ]
            return {
                "section_id": section.get("section_id"),
                "section_type": section.get("section_type"),
                "title": section.get("title"),
                "source_id": section.get("source_id"),
                "char_start": section.get("char_start"),
                "char_end": section.get("char_end"),
                "evidence_count": len(records),
                "packets": packets,
            }

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_process_section, section): section
                for section in sections[: config.mapreduce_max_sections]
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:
                    section = futures[future]
                    logger.warning(
                        "Section worker failed for %s: %s",
                        section.get("section_id"),
                        exc,
                    )
                    continue
                coverage_records.append(
                    {key: value for key, value in result.items() if key != "packets"}
                )
                new_packets.extend(result.get("packets") or [])

        existing_packets = list(state.get("evidence_packets") or [])
        state["evidence_packets"] = existing_packets + new_packets
        state["evidence_store"] = evidence_store.serialize()
        state["section_coverage"] = {
            "status": "completed",
            "sections_processed": len(coverage_records),
            "sections_total": len(sections),
            "evidence_records": len(evidence_store.records()),
            "sections": coverage_records,
        }
        logger.info(
            "Section map-reduce processed %s/%s sections",
            len(coverage_records),
            len(sections),
        )
        return state
