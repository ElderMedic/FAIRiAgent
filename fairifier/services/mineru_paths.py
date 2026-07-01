"""MinerU output path helpers for vlm, hybrid, pipeline, and office layouts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Subdirectory names used by MinerU 2.x–3.x backends under ``{output}/{doc_stem}/``.
_KNOWN_PARSE_DIR_NAMES = frozenset({"vlm", "office"})
_PIPELINE_METHODS = frozenset({"auto", "txt", "ocr"})


def is_parse_subdir(name: str) -> bool:
    """Return True if *name* looks like a MinerU parse output folder."""
    if name in _KNOWN_PARSE_DIR_NAMES:
        return True
    if name.startswith("hybrid_"):
        return True
    return name in _PIPELINE_METHODS


def iter_parse_dirs(doc_root: Path) -> List[Path]:
    """Return parse subdirectories under ``{mineru_output}/{doc_stem}/``."""
    if not doc_root.is_dir():
        return []
    return sorted(
        (child for child in doc_root.iterdir() if child.is_dir() and is_parse_subdir(child.name)),
        key=lambda p: p.name,
    )


def _markdown_candidates(parse_dir: Path, doc_stem: str) -> List[Path]:
    exact = parse_dir / f"{doc_stem}.md"
    if exact.is_file():
        return [exact]
    return sorted(parse_dir.glob("*.md"), key=lambda p: p.name)


def find_markdown_in_tree(
    root: Path,
    doc_stem: str,
) -> Optional[Tuple[Path, Optional[Path]]]:
    """Locate the best Markdown file and optional images directory under *root*.

    Search order:
    1. ``{root}/{doc_stem}/{vlm|office|hybrid_*|auto|txt|ocr}/{doc_stem}.md``
    2. Any ``*.md`` under parse dirs whose stem contains *doc_stem*
    3. First ``*.md`` anywhere under *root* (recursive)
    """
    doc_root = root / doc_stem
    for parse_dir in iter_parse_dirs(doc_root):
        for md_path in _markdown_candidates(parse_dir, doc_stem):
            images_dir = md_path.parent / "images"
            return md_path, images_dir if images_dir.is_dir() else None

    for parse_dir in iter_parse_dirs(doc_root):
        for md_path in parse_dir.rglob("*.md"):
            if doc_stem in md_path.stem:
                images_dir = md_path.parent / "images"
                return md_path, images_dir if images_dir.is_dir() else None

    all_md = sorted(root.rglob("*.md"), key=lambda p: len(str(p)))
    if not all_md:
        return None
    md_path = all_md[0]
    images_dir = md_path.parent / "images"
    return md_path, images_dir if images_dir.is_dir() else None


def discover_structured_artifacts(parse_dir: Path, doc_stem: str) -> Dict[str, Path]:
    """Return paths to MinerU structured JSON artifacts next to the markdown stem."""
    artifacts: Dict[str, Path] = {}
    mapping = {
        "content_list_v2": f"{doc_stem}_content_list_v2.json",
        "content_list": f"{doc_stem}_content_list.json",
        "middle_json": f"{doc_stem}_middle.json",
        "model_json": f"{doc_stem}_model.json",
    }
    for key, filename in mapping.items():
        candidate = parse_dir / filename
        if candidate.is_file():
            artifacts[key] = candidate
    return artifacts


def load_content_list_v2(path: Path, *, max_blocks: int = 500) -> List[Dict[str, Any]]:
    """Load content_list_v2 blocks for source-grounding metadata."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        blocks = raw
    elif isinstance(raw, dict):
        blocks = raw.get("pages") or raw.get("content") or []
        if isinstance(blocks, dict):
            blocks = list(blocks.values())
    else:
        return []

    normalized: List[Dict[str, Any]] = []
    for block in blocks[:max_blocks]:
        if not isinstance(block, dict):
            continue
        entry: Dict[str, Any] = {
            "type": block.get("type"),
            "text": block.get("text") or block.get("content") or "",
            "page_idx": block.get("page_idx"),
            "bbox": block.get("bbox"),
        }
        if block.get("img_path"):
            entry["img_path"] = block["img_path"]
        normalized.append(entry)
    return normalized
