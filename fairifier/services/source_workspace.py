"""Source workspace utilities for agentic search over input files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..config import config


@dataclass
class SourceRecord:
    """Normalized source unit preserved in the workspace."""

    source_id: str
    path: str
    method: str
    content: str
    content_type: str = "text"
    source_role: str = "unknown"
    relevance_score: float = 1.0
    tables: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SourceWorkspace:
    """Pointers to materialized source workspace artifacts."""

    root_dir: Path
    manifest_path: Path
    summary_path: Path
    source_paths: Dict[str, Path]
    table_paths: Dict[str, Path]
    manifest: Dict[str, Any]


def _safe_source_filename(source_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_id).strip("_")
    return f"{safe or 'source'}.md"


def _infer_role(path: str, content_type: str) -> str:
    lowered = path.lower()
    if any(token in lowered for token in ("supp", "supplement", "appendix")):
        return "supplement"
    if content_type == "table" or lowered.endswith((".csv", ".tsv", ".xlsx", ".xls")):
        return "table"
    if any(token in lowered for token in ("protocol", "methods")):
        return "protocol"
    if any(token in lowered for token in ("metadata", "isa", "sample")):
        return "metadata_table"
    if lowered.endswith((".md", ".txt", ".pdf")):
        return "main_manuscript"
    return "unknown"


def _inventory_excerpt(content: str, max_chars: int) -> str:
    text = content.strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 24)].rstrip() + "\n[... preview truncated ...]"


def _json_safe_value(value: Any) -> Any:
    """Normalize common pandas/numpy scalars into JSON-safe values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return _json_safe_value(value.item())
        except Exception:
            pass
    return str(value)


def build_source_workspace(
    records: Iterable[SourceRecord],
    output_dir: Path,
    *,
    workspace_dir_name: Optional[str] = None,
) -> SourceWorkspace:
    """Materialize source files and a manifest without dropping source content."""
    workspace_name = workspace_dir_name or config.source_workspace_dir_name
    root_dir = Path(output_dir) / workspace_name
    sources_dir = root_dir / "sources"
    tables_dir = root_dir / "tables"
    sources_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    source_paths: Dict[str, Path] = {}
    table_paths: Dict[str, Path] = {}
    manifest_sources: List[Dict[str, Any]] = []
    summary_lines = ["# Source Workspace", ""]

    for index, record in enumerate(records, start=1):
        source_id = record.source_id or f"source_{index:03d}"
        role = record.source_role
        if role == "unknown" and config.source_role_detection_enabled:
            role = _infer_role(record.path, record.content_type)

        source_path = sources_dir / _safe_source_filename(source_id)
        source_path.write_text(record.content, encoding="utf-8")
        source_paths[source_id] = source_path

        table_refs: List[Dict[str, Any]] = []
        for table_index, table in enumerate(record.tables or [], start=1):
            table_name = str(table.get("name") or f"table_{table_index}")
            rows = table.get("rows") or []
            table_path = tables_dir / f"{source_id}_{table_index:02d}.jsonl"
            with table_path.open("w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(_json_safe_value(row), ensure_ascii=False) + "\n")
            table_key = f"{source_id}:{table_name}"
            table_paths[table_key] = table_path
            table_refs.append(
                {
                    "name": table_name,
                    "path": str(table_path.relative_to(root_dir)),
                    "rows": len(rows),
                }
            )

        entry = {
            "source_id": source_id,
            "path": record.path,
            "method": record.method,
            "content_type": record.content_type,
            "source_role": role,
            "relevance_score": record.relevance_score,
            "chars": len(record.content),
            "workspace_path": str(source_path.relative_to(root_dir)),
            "tables": table_refs,
        }
        manifest_sources.append(entry)
        summary_lines.extend(
            [
                f"## {source_id}: {record.path}",
                f"- method: {record.method}",
                f"- role: {role}",
                f"- content_type: {record.content_type}",
                f"- chars: {len(record.content)}",
                "",
                _inventory_excerpt(record.content, config.source_inventory_max_chars_per_source),
                "",
            ]
        )

    manifest = {
        "version": 1,
        "source_count": len(manifest_sources),
        "sources": manifest_sources,
    }
    manifest_path = root_dir / "source_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path = root_dir / "source_workspace.md"
    summary_path.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")

    return SourceWorkspace(
        root_dir=root_dir,
        manifest_path=manifest_path,
        summary_path=summary_path,
        source_paths=source_paths,
        table_paths=table_paths,
        manifest=manifest,
    )


def load_source_workspace(metadata: Dict[str, Any]) -> SourceWorkspace:
    """Load a SourceWorkspace from serialized conversion/state metadata."""
    root_dir = Path(metadata["root_dir"])
    manifest_path = Path(metadata["manifest_path"])
    summary_path = Path(metadata["summary_path"])
    source_paths = {
        str(source_id): Path(path)
        for source_id, path in (metadata.get("source_paths") or {}).items()
    }
    table_paths = {
        str(table_id): Path(path)
        for table_id, path in (metadata.get("table_paths") or {}).items()
    }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return SourceWorkspace(
        root_dir=root_dir,
        manifest_path=manifest_path,
        summary_path=summary_path,
        source_paths=source_paths,
        table_paths=table_paths,
        manifest=manifest,
    )


def _source_entries(workspace: SourceWorkspace) -> List[Dict[str, Any]]:
    return [
        entry for entry in workspace.manifest.get("sources", [])
        if isinstance(entry, dict) and entry.get("source_id") in workspace.source_paths
    ]


_ROLE_PRIORITY: Dict[str, int] = {
    "main_manuscript": 0,
    "protocol": 1,
    "table": 2,
    "metadata_table": 3,
    "supplement": 4,
    "unknown": 5,
}


def source_role_priority(role: str) -> int:
    """Return a sort-priority for a source role (lower = more authoritative)."""
    return _ROLE_PRIORITY.get(role, 5)


def rank_source_entries(workspace: SourceWorkspace) -> List[Dict[str, Any]]:
    """Return manifest entries sorted by role priority then relevance score."""
    entries = _source_entries(workspace)
    return sorted(
        entries,
        key=lambda e: (
            source_role_priority(e.get("source_role", "unknown")),
            -(e.get("relevance_score") or 0.0),
        ),
    )


def grep_sources(
    workspace: SourceWorkspace,
    query: str,
    *,
    source_ids: Optional[List[str]] = None,
    context_chars: Optional[int] = None,
    max_results: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Search source text and return compact excerpts with offsets."""
    if not query:
        return []
    allowed = set(source_ids or [])
    context = config.source_grep_context_chars if context_chars is None else context_chars
    limit = config.source_max_search_results if max_results is None else max_results
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results: List[Dict[str, Any]] = []

    for entry in rank_source_entries(workspace):
        source_id = str(entry["source_id"])
        if allowed and source_id not in allowed:
            continue
        text = workspace.source_paths[source_id].read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            start = max(0, match.start() - context)
            end = min(len(text), match.end() + context)
            results.append(
                {
                    "source_id": source_id,
                    "source_path": entry.get("path"),
                    "start": match.start(),
                    "end": match.end(),
                    "excerpt": text[start:end],
                }
            )
            if len(results) >= limit:
                return results
    return results


def read_source_span(
    workspace: SourceWorkspace,
    source_id: str,
    start: int = 0,
    end: Optional[int] = None,
    *,
    max_chars: Optional[int] = None,
) -> Dict[str, Any]:
    """Read a bounded source span by character offset."""
    path = workspace.source_paths[source_id]
    text = path.read_text(encoding="utf-8")
    start = max(0, int(start))
    effective_max = config.source_read_max_chars if max_chars is None else max_chars
    if end is None:
        end = start + effective_max
    end = min(len(text), int(end), start + effective_max)
    return {
        "source_id": source_id,
        "start": start,
        "end": end,
        "text": text[start:end],
        "truncated": end < len(text),
    }


def search_table(
    workspace: SourceWorkspace,
    query: str,
    *,
    source_ids: Optional[List[str]] = None,
    max_rows: Optional[int] = None,
    max_matches: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Search materialized table JSONL rows without relying on table preview text."""
    if not query:
        return []
    allowed = set(source_ids or [])
    row_limit = config.table_search_max_rows if max_rows is None else max_rows
    match_limit = config.table_search_max_matches if max_matches is None else max_matches
    needle = query.casefold()
    matches: List[Dict[str, Any]] = []

    for table_key, table_path in workspace.table_paths.items():
        source_id, table_name = table_key.split(":", 1)
        if allowed and source_id not in allowed:
            continue
        with table_path.open("r", encoding="utf-8") as fh:
            for row_index, line in enumerate(fh):
                if row_index >= row_limit:
                    break
                row = json.loads(line)
                if not isinstance(row, dict):
                    continue
                for column, value in row.items():
                    column_text = str(column)
                    value_text = str(value)
                    if needle in column_text.casefold() or needle in value_text.casefold():
                        matches.append(
                            {
                                "source_id": source_id,
                                "table": table_name,
                                "row_index": row_index,
                                "column": column_text,
                                "value": value_text,
                                "row": row,
                            }
                        )
                        if len(matches) >= match_limit:
                            return matches
    return matches
