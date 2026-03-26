"""Helpers for loading deepagents skill files from the repository."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def load_skill_files(skills_dir: Path) -> Dict[str, Any]:
    """Load all SKILL.md files into the deepagents virtual filesystem shape."""
    if not skills_dir.exists():
        return {}

    try:
        from deepagents.backends.utils import create_file_data
    except Exception:  # pragma: no cover - optional dependency
        return {}

    loaded: Dict[str, Any] = {}
    for path in skills_dir.rglob("SKILL.md"):
        relative = path.relative_to(skills_dir).as_posix()
        loaded[f"/skills/{relative}"] = create_file_data(path.read_text(encoding="utf-8"))
    return loaded
