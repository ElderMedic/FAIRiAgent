"""Helpers for loading deepagents skill files from the repository."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Per Anthropic-style skill folder: cap markdown files and size (progressive disclosure).
_MAX_MARKDOWN_FILES_PER_SKILL_PACK = 32
_MAX_MARKDOWN_FILE_BYTES = 200_000


def normalize_existing_skill_roots(paths: Sequence[Path]) -> List[Path]:
    """Deduplicate roots, expand user, resolve, keep order; drop missing paths."""
    seen: set[str] = set()
    out: List[Path] = []
    for raw in paths:
        try:
            resolved = raw.expanduser().resolve()
        except OSError:
            continue
        if not resolved.exists():
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        out.append(resolved)
    return out


def _merge_skill_entrypoints(roots: Sequence[Path]) -> Dict[str, Path]:
    """Map virtual path to each winning ``SKILL.md`` (later roots override)."""
    merged: Dict[str, Path] = {}
    for root in normalize_existing_skill_roots(roots):
        for path in root.rglob("SKILL.md"):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            merged[f"/skills/{rel}"] = path
    return merged


def _markdown_files_for_skill_pack(skill_md: Path, root: Path) -> List[Path]:
    """Markdown files belonging to one skill folder, excluding nested sub-skills."""
    pack = skill_md.parent
    try:
        skill_resolved = skill_md.resolve()
    except OSError:
        return [skill_md] if skill_md.is_file() else []

    nested_roots: List[Path] = []
    try:
        for other in pack.rglob("SKILL.md"):
            if not other.is_file():
                continue
            try:
                if other.resolve() == skill_resolved:
                    continue
            except OSError:
                continue
            nested_roots.append(other.parent)
    except OSError:
        nested_roots = []

    out: List[Path] = []
    try:
        candidates = sorted(pack.rglob("*.md"))
    except OSError:
        return []

    pack_resolved = pack.resolve()
    for f in candidates:
        if not f.is_file():
            continue
        try:
            sz = f.stat().st_size
        except OSError:
            continue
        if sz > _MAX_MARKDOWN_FILE_BYTES:
            continue
        skip_nested = False
        for nr in nested_roots:
            try:
                nr_res = nr.resolve()
                if nr_res == pack_resolved:
                    continue
                if f.is_relative_to(nr):
                    skip_nested = True
                    break
            except OSError:
                continue
        if skip_nested:
            continue
        try:
            f.relative_to(root)
        except ValueError:
            continue
        out.append(f)
        if len(out) >= _MAX_MARKDOWN_FILES_PER_SKILL_PACK:
            break
    return out


def _merge_skill_pack_paths(roots: Sequence[Path]) -> Dict[str, Path]:
    """All capped ``*.md`` under each skill directory; later roots win on path clash."""
    merged: Dict[str, Path] = {}
    for root in normalize_existing_skill_roots(roots):
        seen_skill_md: set[str] = set()
        for skill_md in sorted(root.rglob("SKILL.md")):
            if not skill_md.is_file():
                continue
            try:
                key = str(skill_md.resolve())
            except OSError:
                continue
            if key in seen_skill_md:
                continue
            seen_skill_md.add(key)
            for f in _markdown_files_for_skill_pack(skill_md, root):
                try:
                    rel = f.relative_to(root).as_posix()
                except ValueError:
                    continue
                merged[f"/skills/{rel}"] = f
    return merged


def list_skill_virtual_paths(*roots: Path) -> List[str]:
    """Sorted virtual paths for each winning ``SKILL.md`` (entrypoints only)."""
    if not roots:
        return []
    return sorted(_merge_skill_entrypoints(roots).keys())


def _parse_yaml_frontmatter(raw: str) -> Dict[str, Any]:
    """Best-effort YAML frontmatter between leading ``---`` fences."""
    if not raw.lstrip().startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        import yaml

        meta = yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}
    return meta if isinstance(meta, dict) else {}


def iter_skill_catalog_rows(*roots: Path) -> List[Tuple[str, Dict[str, Any]]]:
    """(virtual_path, frontmatter_meta) for each skill entrypoint, sorted by path."""
    if not roots:
        return []
    entry = _merge_skill_entrypoints(roots)
    rows: List[Tuple[str, Dict[str, Any]]] = []
    for vpath in sorted(entry.keys()):
        try:
            text = entry[vpath].read_text(encoding="utf-8")
        except OSError:
            text = ""
        rows.append((vpath, _parse_yaml_frontmatter(text)))
    return rows


def _merge_catalog_rows(
    *roots: Path,
    extra_rows: Optional[Sequence[Tuple[str, Dict[str, Any]]]] = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    rows = list(iter_skill_catalog_rows(*roots))
    if extra_rows:
        rows.extend(extra_rows)
    rows.sort(key=lambda item: item[0])
    return rows


def _catalog_section_lines(vpath: str, meta: Dict[str, Any]) -> List[str]:
    name = str(meta.get("name") or "").strip()
    desc = str(meta.get("description") or "").strip()
    when = str(meta.get("when_to_use") or "").strip()
    lines = [f"## `{vpath}`"]
    if name:
        lines.append(f"- **name**: {name}")
    if desc:
        lines.append(f"- **description**: {desc}")
    if when:
        lines.append(f"- **when_to_use**: {when}")
    lines.append("")
    return lines


def build_skills_catalog_markdown(
    *roots: Path,
    extra_rows: Optional[Sequence[Tuple[str, Dict[str, Any]]]] = None,
) -> str:
    """Full markdown catalog for ``/workspace/skills_catalog.md`` (Level-1 disclosure)."""
    rows = _merge_catalog_rows(*roots, extra_rows=extra_rows)
    lines = [
        "# Skill catalog",
        "",
        "Each row is one skill entrypoint. When the task matches **when_to_use** or the "
        "**description**, open that path and follow the full markdown body (and any linked "
        "``.md`` files in the same folder tree under `/skills/`).",
        "",
    ]
    for vpath, meta in rows:
        lines.extend(_catalog_section_lines(vpath, meta))
    return "\n".join(lines).strip() + "\n"


def format_skills_catalog_for_task(
    *roots: Path,
    max_entries: int = 24,
    extra_rows: Optional[Sequence[Tuple[str, Dict[str, Any]]]] = None,
) -> str:
    """Compact catalog lines for the first user message (trimmed)."""
    rows = _merge_catalog_rows(*roots, extra_rows=extra_rows)
    if not rows:
        return ""
    lines = [
        "Skill entrypoints (read full SKILL.md + sibling .md when matched):",
    ]
    for vpath, meta in rows[:max_entries]:
        name = str(meta.get("name") or "").strip()
        desc = str(meta.get("description") or "").strip()
        when = str(meta.get("when_to_use") or "").strip()
        bits = [f"`{vpath}`"]
        if name:
            bits.append(f"name={name!r}")
        if desc:
            short = desc if len(desc) <= 160 else desc[:157] + "..."
            bits.append(f"desc={short!r}")
        elif when:
            short = when if len(when) <= 160 else when[:157] + "..."
            bits.append(f"when={short!r}")
        lines.append("- " + " | ".join(bits))
    if len(rows) > max_entries:
        lines.append(f"- … {len(rows) - max_entries} more (see /workspace/skills_catalog.md)")
    lines.append(
        "Required: before finalizing, open `/workspace/skills_catalog.md`, pick any matching "
        "skill(s), read those SKILL.md bodies via file tools, and apply their checklists."
    )
    return "\n".join(lines)


def skills_catalog_seed_files(
    *roots: Path,
    create_file_data: Optional[Callable[[str], Any]],
    extra_rows: Optional[Sequence[Tuple[str, Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Virtual file so the model can always open the catalog without scanning ``/skills/``.

    ``create_file_data`` is keyword-only (same factory as deepagents file payloads). Do not pass
    it positionally after ``*roots`` — use ``create_file_data=...``.
    """
    if create_file_data is None or (not roots and not extra_rows):
        return {}
    body = build_skills_catalog_markdown(*roots, extra_rows=extra_rows)
    if not body.strip():
        return {}
    return {"/workspace/skills_catalog.md": create_file_data(body)}


FAIRDS_REMOTE_SKILL_VIRTUAL_PATH = "/skills/remote/fairds-metadata/SKILL.md"


def fairds_remote_skill_catalog_row(
    markdown: str,
) -> Tuple[str, Dict[str, Any]]:
    """Catalog row for a FAIR-DS hosted skill markdown document."""
    return (FAIRDS_REMOTE_SKILL_VIRTUAL_PATH, _parse_yaml_frontmatter(markdown))


def fairds_remote_skill_seed_files(
    markdown: Optional[str],
    *,
    create_file_data: Optional[Callable[[str], Any]],
) -> Dict[str, Any]:
    """Mount a FAIR-DS hosted skill into the deepagents virtual workspace."""
    if not markdown or not markdown.strip() or create_file_data is None:
        return {}
    return {FAIRDS_REMOTE_SKILL_VIRTUAL_PATH: create_file_data(markdown)}


def load_skill_files(*roots: Path) -> Dict[str, Any]:
    """Load skill markdown (SKILL.md + sibling pack ``*.md``) into deepagents file payloads.

    When multiple roots define the same virtual path, the last root wins.
    """
    if not roots:
        return {}

    try:
        from deepagents.backends.utils import create_file_data
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.warning(
            "deepagents not available; SKILL.md will not load (%s roots): %s",
            len(roots),
            exc,
        )
        return {}

    merged = _merge_skill_pack_paths(roots)
    loaded: Dict[str, Any] = {}
    for virtual_path, path in merged.items():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Skip skill file %s: %s", path, exc)
            continue
        loaded[virtual_path] = create_file_data(text)
    return loaded
