"""Evidence store: Qdrant payloads + JSONL audit export."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from ..config import config
from .evidence_packets import evidence_packet_dedupe_key
from .section_field_candidates import (
    extract_field_candidates_from_section,
    field_candidate_record_to_dict,
)
from .semantic_index import SemanticIndex

logger = logging.getLogger(__name__)


def stable_evidence_id(record: Dict[str, Any]) -> str:
    """Stable evidence identity used for upsert/dedupe (§12.1).

    Prefer an explicit ``evidence_id`` when present; otherwise derive from the
    same producer/span/field/value key used by packet merge.
    """
    explicit = str(record.get("evidence_id") or "").strip()
    if explicit:
        return explicit
    return evidence_packet_dedupe_key(record)


class EvidenceStore:
    """Persist evidence payloads for downstream reconciliation."""

    def __init__(
        self,
        workspace_root: Path,
        semantic_index: Optional[SemanticIndex] = None,
    ):
        self.workspace_root = Path(workspace_root)
        self.semantic_index = semantic_index
        self.jsonl_path = self.workspace_root / "evidence_store.jsonl"
        self._records: List[Dict[str, Any]] = []
        self._seen_ids: Set[str] = set()

    def _remember(self, record: Dict[str, Any]) -> str:
        eid = stable_evidence_id(record)
        record = dict(record)
        record.setdefault("evidence_id", eid)
        return eid

    def append(self, record: Dict[str, Any]) -> bool:
        """Append one record if its evidence_id is new. Returns True when written."""
        prepared = dict(record)
        eid = self._remember(prepared)
        prepared["evidence_id"] = eid
        if eid in self._seen_ids:
            return False
        self._seen_ids.add(eid)
        self._records.append(prepared)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(prepared, ensure_ascii=False) + "\n")
        return True

    def upsert_many(self, records: Sequence[Dict[str, Any]]) -> int:
        """Upsert records by stable evidence_id; return count newly written."""
        added_records: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            before = len(self._records)
            if self.append(record) and len(self._records) > before:
                added_records.append(self._records[-1])
        if (
            config.evidence_store_enabled
            and self.semantic_index
            and self.semantic_index.is_available()
            and added_records
        ):
            try:
                self.semantic_index.upsert_evidence(added_records)
            except Exception as exc:
                logger.warning("Evidence vector upsert failed: %s", exc)
        return len(added_records)

    def extend(self, records: Sequence[Dict[str, Any]]) -> int:
        """Compatibility alias for ``upsert_many`` (§12.1 dedupe)."""
        return self.upsert_many(records)

    def load_existing(self) -> List[Dict[str, Any]]:
        if not self.jsonl_path.is_file():
            self._records = []
            self._seen_ids = set()
            return []
        records: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        with self.jsonl_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                eid = stable_evidence_id(record)
                record.setdefault("evidence_id", eid)
                if eid in seen:
                    continue
                seen.add(eid)
                records.append(record)
        self._records = records
        self._seen_ids = seen
        return records

    def records(self) -> List[Dict[str, Any]]:
        return list(self._records)

    def serialize(self) -> Dict[str, Any]:
        return {
            "jsonl_path": str(self.jsonl_path),
            "record_count": len(self._records),
        }


def evidence_from_section(
    section: Dict[str, Any],
    *,
    produced_by: str = "section_map_reduce",
    source_meta: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Create evidence records from a section (field candidates + outline fallback)."""
    candidates = extract_field_candidates_from_section(
        section,
        source_meta=source_meta,
        produced_by=produced_by,
    )
    if candidates:
        return candidates

    text = str(section.get("text") or "")
    if not text.strip():
        return []
    section_id = str(section.get("section_id") or "section")
    return [
        {
            "evidence_id": f"{section_id}_outline",
            "packet_id": f"{section_id}_outline",
            "kind": "evidence",
            "field_candidate": section.get("section_type") or "section",
            "field_name": str(section.get("section_type") or "section"),
            "value": str(section.get("title") or section_id),
            "evidence_text": text[:1200],
            "section": section.get("title"),
            "source_id": section.get("source_id"),
            "char_start": section.get("char_start"),
            "char_end": section.get("char_end"),
            "confidence": 0.6,
            "retrieval_method": "section_map_reduce",
            "provenance": {
                "agent": produced_by,
                "strategy": "section_coverage",
            },
            "produced_by": produced_by,
        }
    ]
