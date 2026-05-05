"""Compatibility helpers for optional python-dotenv usage."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

try:
    from dotenv import dotenv_values as _dotenv_values
    from dotenv import load_dotenv as _load_dotenv
except ImportError:  # pragma: no cover - fallback
    _load_dotenv = None
    _dotenv_values = None


def _parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_dotenv(
    dotenv_path: Optional[os.PathLike[str] | str] = None,
    override: bool = False,
):
    if _load_dotenv is not None:
        return _load_dotenv(dotenv_path, override=override)

    if dotenv_path is None:
        return False

    path = Path(dotenv_path)
    for key, value in _parse_env_file(path).items():
        if override or key not in os.environ:
            os.environ[key] = value
    return True


def dotenv_values(
    dotenv_path: Optional[os.PathLike[str] | str] = None,
) -> Dict[str, str]:
    if _dotenv_values is not None:
        values = _dotenv_values(dotenv_path)
        return {
            str(key): str(value)
            for key, value in values.items()
            if key is not None and value is not None
        }

    if dotenv_path is None:
        return {}

    return _parse_env_file(Path(dotenv_path))
