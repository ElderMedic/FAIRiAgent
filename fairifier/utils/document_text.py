"""Centralized accessor for document text (P1 §5 of architecture refactor).

Document text used to be carried in ``state["document_content"]`` (hundreds of
KB) through the entire pipeline, even though only the parser, planner, and
JSON generator actually need it. This module centralizes reads and prefers the
on-disk reference (``state["document_text_path"]``), falling back to in-memory
``document_content`` only for legacy/test paths.

See ARCHITECTURE_REFACTOR_PLAN.md §5.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def read_document_text(
    state: Dict[str, Any],
    *,
    max_chars: Optional[int] = None,
) -> str:
    """Return document text, preferring on-disk reference over in-memory copy.

    Lookup order:
    1. ``state["document_text_path"]`` (read from file)
    2. ``state["document_content"]`` (legacy in-memory fallback)
    3. ``""`` (empty)

    Args:
        state: FAIRifierState (or any dict-like with the two keys).
        max_chars: If provided, truncate the returned text to this length.
            ``0`` returns an empty string. ``None`` (default) returns full text.

    Returns:
        The document text (possibly truncated). Never raises on missing /
        unreadable files — falls back through the chain.
    """
    if max_chars is not None and max_chars <= 0:
        return ""

    text = ""
    text_path = state.get("document_text_path")
    if text_path:
        try:
            path = Path(text_path)
            if path.is_file():
                text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""

    if not text:
        text = state.get("document_content") or ""

    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
    return text
