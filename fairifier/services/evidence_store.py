"""Evidence store: Qdrant payloads + JSONL audit export."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..config import config
from .semantic_index import SemanticIndex

logger = logging.getLogger(__name__)


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

    def append(self, record: Dict[str, Any]) -> None:
        self._records.append(record)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def extend(self, records: Sequence[Dict[str, Any]]) -> int:
        count = 0
        for record in records:
            self.append(record)
            count += 1
        if (
            config.evidence_store_enabled
            and self.semantic_index
            and self.semantic_index.is_available()
            and records
        ):
            try:
                self.semantic_index.upsert_evidence(records)
            except Exception as exc:
                logger.warning("Evidence vector upsert failed: %s", exc)
        return count

    def load_existing(self) -> List[Dict[str, Any]]:
        if not self.jsonl_path.is_file():
            return []
        records: List[Dict[str, Any]] = []
        with self.jsonl_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        self._records = records
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
) -> List[Dict[str, Any]]:
    """Create lightweight evidence records from a section outline."""
    text = str(section.get("text") or "")
    if not text.strip():
        return []
    section_id = str(section.get("section_id") or "section")
    return [
        {
            "evidence_id": f"{section_id}_outline",
            "packet_id": f"{section_id}_outline",
            "field_candidate": section.get("section_type") or "section",
            "value": str(section.get("title") or section_id),
            "evidence_text": text[:1200],
            "section": section.get("title"),
            "source_id": section.get("source_id"),
            "char_start": section.get("char_start"),
            "char_end": section.get("char_end"),
            "confidence": 0.6,
            "provenance": {
                "agent": produced_by,
                "strategy": "section_coverage",
            },
            "produced_by": produced_by,
            "kind": "evidence",
        }
    ]
