"""Generic workspace tools for agentic ISA structure recovery."""

from __future__ import annotations

import json
import re
import subprocess
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool


def _workspace_root(source_workspace: Dict[str, Any]) -> Path:
    root_dir = source_workspace.get("root_dir")
    if root_dir:
        return Path(root_dir)
    source_paths = [
        Path(path)
        for path in (source_workspace.get("source_paths") or {}).values()
        if path
    ]
    if source_paths:
        return source_paths[0].parent
    summary_path = source_workspace.get("summary_path")
    if summary_path:
        return Path(summary_path).parent
    return Path.cwd()


def _workspace_sources(source_workspace: Dict[str, Any]) -> List[Dict[str, Any]]:
    manifest_path = source_workspace.get("manifest_path")
    if manifest_path:
        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            sources = manifest.get("sources") or []
            if isinstance(sources, list):
                return [entry for entry in sources if isinstance(entry, dict)]
        except Exception:
            pass

    entries: List[Dict[str, Any]] = []
    for source_id, path in (source_workspace.get("source_paths") or {}).items():
        entries.append(
            {
                "source_id": str(source_id),
                "path": str(path),
                "workspace_path": Path(path).name,
                "source_role": "unknown",
            }
        )
    return entries


def _resolve_source_path(source_workspace: Dict[str, Any], source_id: str) -> Optional[Path]:
    source_paths = source_workspace.get("source_paths") or {}
    path = source_paths.get(source_id)
    if path:
        return Path(path)
    for entry in _workspace_sources(source_workspace):
        if entry.get("source_id") == source_id and entry.get("path"):
            return Path(str(entry["path"]))
    return None


def _selected_source_ids(source_workspace: Dict[str, Any], source_ids: str = "") -> List[str]:
    available = [str(entry.get("source_id")) for entry in _workspace_sources(source_workspace)]
    if not source_ids.strip():
        return available
    allowed = {item.strip() for item in source_ids.split(",") if item.strip()}
    return [source_id for source_id in available if source_id in allowed]


def _grep_matches(
    source_workspace: Dict[str, Any],
    query: str,
    *,
    source_ids: str = "",
    max_results: int = 8,
    context_chars: int = 280,
) -> List[Dict[str, Any]]:
    if not query:
        return []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    matches: List[Dict[str, Any]] = []
    for source_id in _selected_source_ids(source_workspace, source_ids):
        path = _resolve_source_path(source_workspace, source_id)
        if not path or not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            start = max(0, match.start() - context_chars)
            end = min(len(text), match.end() + context_chars)
            matches.append(
                {
                    "source_id": source_id,
                    "path": str(path),
                    "start": match.start(),
                    "end": match.end(),
                    "excerpt": text[start:end],
                }
            )
            if len(matches) >= max_results:
                return matches
    return matches


def _search_tables(
    source_workspace: Dict[str, Any],
    query: str,
    *,
    source_ids: str = "",
    max_matches: int = 8,
) -> List[Dict[str, Any]]:
    if not query:
        return []
    selected = set(_selected_source_ids(source_workspace, source_ids))
    needle = query.casefold()
    matches: List[Dict[str, Any]] = []
    for table_id, table_path in (source_workspace.get("table_paths") or {}).items():
        table_source_id = str(table_id).split(":", 1)[0]
        if selected and table_source_id not in selected:
            continue
        path = Path(table_path)
        if not path.exists():
            continue
        for idx, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if needle not in raw_line.casefold():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                row = raw_line
            matches.append(
                {
                    "table_id": str(table_id),
                    "source_id": table_source_id,
                    "row_number": idx,
                    "row": row,
                }
            )
            if len(matches) >= max_matches:
                return matches
    return matches


_ALLOWED_SHELL_PREFIXES = {
    "rg",
    "grep",
    "sed",
    "awk",
    "head",
    "tail",
    "cut",
    "sort",
    "uniq",
    "wc",
    "cat",
    "tr",
}


def _validate_shell_command(command: str) -> Optional[str]:
    stripped = command.strip()
    if not stripped:
        return "Shell command must not be empty."
    if any(token in stripped for token in (";", "&&", "||", ">", "<", "`", "$(", "${")):
        return "Shell command contains blocked shell syntax."
    try:
        first = shlex.split(stripped)[0]
    except Exception:
        return "Shell command could not be parsed."
    if first not in _ALLOWED_SHELL_PREFIXES:
        return f"Shell command '{first}' is not in the read-only allowlist."
    return None


def _default_shell_targets(source_workspace: Dict[str, Any], root_dir: Path) -> List[str]:
    targets: List[str] = []
    for path in (source_workspace.get("source_paths") or {}).values():
        p = Path(path)
        try:
            targets.append(str(p.relative_to(root_dir)))
        except ValueError:
            targets.append(str(p))
    for path in (source_workspace.get("table_paths") or {}).values():
        p = Path(path)
        try:
            targets.append(str(p.relative_to(root_dir)))
        except ValueError:
            targets.append(str(p))
    for key in ("summary_path", "manifest_path"):
        raw = source_workspace.get(key)
        if not raw:
            continue
        p = Path(raw)
        try:
            targets.append(str(p.relative_to(root_dir)))
        except ValueError:
            targets.append(str(p))
    return list(dict.fromkeys(targets))


def _prepare_shell_command(command: str, source_workspace: Dict[str, Any], root_dir: Path) -> str:
    """Add default workspace targets to grep-like commands that omit paths."""
    parts = shlex.split(command)
    if not parts or parts[0] not in {"rg", "grep"}:
        return command

    has_explicit_target = False
    for token in parts[1:]:
        if token.startswith("-"):
            continue
        candidate = Path(token)
        if candidate.is_absolute() and candidate.exists():
            has_explicit_target = True
            break
        if (root_dir / candidate).exists():
            has_explicit_target = True
            break

    if has_explicit_target:
        return command

    parts.extend(_default_shell_targets(source_workspace, root_dir))
    return " ".join(shlex.quote(part) for part in parts)


def create_isa_structure_tools(source_workspace: Optional[Dict[str, Any]] = None) -> List:
    """Create generic tools for agentic ISA structuring from source workspaces."""
    workspace = source_workspace or {}
    root_dir = _workspace_root(workspace)

    @tool
    def list_workspace_sources() -> Dict[str, Any]:
        """List source files available for ISA structuring, including source_id and path."""
        return {
            "success": True,
            "data": {
                "root_dir": str(root_dir),
                "sources": _workspace_sources(workspace),
            },
            "error": None,
        }

    @tool
    def grep_source_workspace(query: str, source_ids: str = "", max_results: int = 8) -> Dict[str, Any]:
        """Search source text by exact substring and return compact excerpts with offsets."""
        matches = _grep_matches(
            workspace,
            query,
            source_ids=source_ids,
            max_results=max_results,
        )
        return {"success": True, "data": {"matches": matches}, "error": None}

    @tool
    def read_source_excerpt(source_id: str, start: int = 0, max_chars: int = 4000) -> Dict[str, Any]:
        """Read a bounded excerpt from one workspace source by source_id."""
        path = _resolve_source_path(workspace, source_id)
        if not path or not path.exists():
            return {"success": False, "data": None, "error": f"Unknown source_id: {source_id}"}
        text = path.read_text(encoding="utf-8")
        safe_start = max(0, int(start))
        safe_end = min(len(text), safe_start + max(1, int(max_chars)))
        return {
            "success": True,
            "data": {
                "source_id": source_id,
                "path": str(path),
                "start": safe_start,
                "end": safe_end,
                "text": text[safe_start:safe_end],
                "truncated": safe_end < len(text),
            },
            "error": None,
        }

    @tool
    def search_workspace_tables(query: str, source_ids: str = "", max_matches: int = 8) -> Dict[str, Any]:
        """Search materialized table rows when tables exist in the source workspace."""
        matches = _search_tables(
            workspace,
            query,
            source_ids=source_ids,
            max_matches=max_matches,
        )
        return {"success": True, "data": {"matches": matches}, "error": None}

    @tool
    def run_source_shell_command(command: str) -> Dict[str, Any]:
        """Run a read-only shell command in the workspace root for flexible text inspection."""
        error = _validate_shell_command(command)
        if error:
            return {"success": False, "data": None, "error": error}
        effective_command = _prepare_shell_command(command, workspace, root_dir)
        try:
            completed = subprocess.run(
                ["bash", "-c", effective_command],
                cwd=str(root_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            return {"success": False, "data": None, "error": str(exc)}
        return {
            "success": completed.returncode == 0,
            "data": {
                "command": effective_command,
                "cwd": str(root_dir),
                "returncode": completed.returncode,
                "stdout": completed.stdout[:12000],
                "stderr": completed.stderr[:4000],
            },
            "error": None if completed.returncode == 0 else f"command exited {completed.returncode}",
        }

    return [
        list_workspace_sources,
        grep_source_workspace,
        read_source_excerpt,
        search_workspace_tables,
        run_source_shell_command,
    ]


__all__ = ["create_isa_structure_tools"]
