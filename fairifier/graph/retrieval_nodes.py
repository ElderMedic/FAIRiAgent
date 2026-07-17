"""LangGraph nodes for semantic indexing and section map-reduce coverage."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

try:
    from langsmith import traceable
except ImportError:
    def traceable(*args, **kwargs):
        def decorator(func):
            return func
        if args and callable(args[0]):
            return args[0]
        return decorator

from ..config import config
from ..services.chunking import chunk_workspace, serialize_chunking_result
from ..services.evidence_packets import merge_evidence_packets
from ..services.evidence_store import EvidenceStore, evidence_from_section
from ..services.section_field_candidates import field_candidate_record_to_dict
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

        source_meta: Dict[str, Dict[str, Any]] = {}
        try:
            manifest_path = Path(workspace_meta.get("manifest_path", ""))
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                for entry in manifest.get("sources", []):
                    sid = str(entry.get("source_id") or "")
                    if sid:
                        source_meta[sid] = entry
        except (OSError, json.JSONDecodeError):
            source_meta = {}

        max_workers = max(1, int(config.mapreduce_max_workers))
        coverage_records: List[Dict[str, Any]] = []
        new_packets: List[Dict[str, Any]] = []
        section_field_candidates: List[Dict[str, Any]] = []

        def _process_section(section: Dict[str, Any]) -> Dict[str, Any]:
            records = evidence_from_section(section, source_meta=source_meta)
            evidence_store.extend(records)
            packets = [
                {
                    "packet_id": record["packet_id"],
                    "field_candidate": record.get("field_candidate") or record.get("field_name"),
                    "value": record.get("value"),
                    "evidence_text": record.get("evidence_text"),
                    "section": record.get("section"),
                    "source_type": "section_map_reduce",
                    "confidence": record.get("confidence", 0.6),
                    "provenance": record.get("provenance", {}),
                    "retrieval_method": record.get("retrieval_method", "section_map_reduce"),
                }
                for record in records
            ]
            field_candidates = [
                field_candidate_record_to_dict(record)
                for record in records
                if record.get("kind") == "field_candidate"
            ]
            return {
                "section_id": section.get("section_id"),
                "section_type": section.get("section_type"),
                "title": section.get("title"),
                "source_id": section.get("source_id"),
                "char_start": section.get("char_start"),
                "char_end": section.get("char_end"),
                "evidence_count": len(records),
                "field_candidate_count": len(field_candidates),
                "packets": packets,
                "field_candidates": field_candidates,
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
                    {key: value for key, value in result.items() if key not in {"packets", "field_candidates"}}
                )
                new_packets.extend(result.get("packets") or [])
                section_field_candidates.extend(result.get("field_candidates") or [])

        existing_packets = list(state.get("evidence_packets") or [])
        state["evidence_packets"] = merge_evidence_packets(existing_packets, new_packets)
        state["section_field_candidates"] = (
            list(state.get("section_field_candidates") or []) + section_field_candidates
        )
        state["evidence_store"] = evidence_store.serialize()

        sections_by_type: Dict[str, int] = {}
        for section in sections[: config.mapreduce_max_sections]:
            section_type = str(section.get("section_type") or "unknown")
            sections_by_type[section_type] = sections_by_type.get(section_type, 0) + 1

        state["section_coverage"] = {
            "status": "completed",
            "planned_sections": len(sections),
            "processed_sections": len(coverage_records),
            "sections_processed": len(coverage_records),
            "sections_total": len(sections),
            "skipped_duplicate_sections": max(0, len(sections) - len(coverage_records)),
            "timed_out_sections": 0,
            "sections_by_type": sections_by_type,
            "evidence_records": len(evidence_store.records()),
            "field_candidates": len(section_field_candidates),
            "sections": coverage_records,
        }
        logger.info(
            "Section map-reduce processed %s/%s sections",
            len(coverage_records),
            len(sections),
        )
        return state
