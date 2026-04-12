"""On-disk filenames for workflow artifacts.

The FAIRifierState ``artifacts`` dict still uses the key ``metadata_json`` (string
payload). Only the saved filename on disk is ``metadata.json``; older runs may
still have ``metadata_json.json``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

METADATA_OUTPUT_FILENAME = "metadata.json"
LEGACY_METADATA_OUTPUT_FILENAME = "metadata_json.json"

_NON_METADATA_ARTIFACT_EXTENSIONS = {
    "validation_report": ".txt",
    "processing_log": ".jsonl",
}


def artifact_output_filename(artifact_name: str) -> str:
    """Basename when persisting a workflow artifact to disk."""
    if artifact_name == "metadata_json":
        return METADATA_OUTPUT_FILENAME
    ext = _NON_METADATA_ARTIFACT_EXTENSIONS.get(artifact_name, ".json")
    return f"{artifact_name}{ext}"


def metadata_output_write_path(output_dir: Path) -> Path:
    return Path(output_dir) / METADATA_OUTPUT_FILENAME


def resolve_metadata_output_read_path(output_dir: Path) -> Optional[Path]:
    """Prefer ``metadata.json``, then legacy ``metadata_json.json``."""
    d = Path(output_dir)
    primary = d / METADATA_OUTPUT_FILENAME
    if primary.exists():
        return primary
    legacy = d / LEGACY_METADATA_OUTPUT_FILENAME
    if legacy.exists():
        return legacy
    return None


def run_has_metadata_output(run_dir: Path) -> bool:
    return resolve_metadata_output_read_path(run_dir) is not None
