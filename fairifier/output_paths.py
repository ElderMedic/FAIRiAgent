"""On-disk filenames and path resolution for workflow artifacts.

Artifacts are reorganized into subdirectories:
- deliverables/
- logs/
- reports/
- workspace/

Backward compatibility is preserved for flat output directories from prior runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

DELIVERABLES_DIRNAME = "deliverables"
LOGS_DIRNAME = "logs"
REPORTS_DIRNAME = "reports"
WORKSPACE_DIRNAME = "workspace"

METADATA_OUTPUT_FILENAME = "metadata.json"
LEGACY_METADATA_OUTPUT_FILENAME = "metadata_json.json"
ISA_VALUES_OUTPUT_FILENAME = "isa_values.json"
LEGACY_ISA_VALUES_FILENAME = "isa_values_json.json"

# FAIR Data Station: POST /api/isa output (one workbook, ISA-level tabs + Help)
FAIRDS_METADATA_EXCEL_FILENAME = "metadata_fairds.xlsx"

_NON_METADATA_ARTIFACT_EXTENSIONS = {
    "validation_report": ".txt",
    "processing_log": ".jsonl",
}


def deliverables_dir(output_dir: Path) -> Path:
    return Path(output_dir) / DELIVERABLES_DIRNAME


def logs_dir(output_dir: Path) -> Path:
    return Path(output_dir) / LOGS_DIRNAME


def reports_dir(output_dir: Path) -> Path:
    return Path(output_dir) / REPORTS_DIRNAME


def workspace_dir(output_dir: Path) -> Path:
    return Path(output_dir) / WORKSPACE_DIRNAME


def artifact_output_filename(artifact_name: str) -> str:
    """Basename when persisting a workflow artifact to disk."""
    if artifact_name == "metadata_json":
        return METADATA_OUTPUT_FILENAME
    ext = _NON_METADATA_ARTIFACT_EXTENSIONS.get(artifact_name, ".json")
    return f"{artifact_name}{ext}"


def artifact_content_to_text(content: Any) -> str:
    """Serialize workflow artifact payloads for CLI/API/evaluation output files."""
    if isinstance(content, str):
        return content
    return json.dumps(content, indent=2, ensure_ascii=False)


def metadata_output_write_path(output_dir: Path) -> Path:
    return deliverables_dir(output_dir) / METADATA_OUTPUT_FILENAME


def resolve_metadata_output_read_path(output_dir: Path) -> Optional[Path]:
    d = Path(output_dir)
    primary = d / DELIVERABLES_DIRNAME / METADATA_OUTPUT_FILENAME
    if primary.exists():
        return primary
    flat_primary = d / METADATA_OUTPUT_FILENAME
    if flat_primary.exists():
        return flat_primary
    legacy = d / LEGACY_METADATA_OUTPUT_FILENAME
    if legacy.exists():
        return legacy
    return None


def isa_values_output_write_path(output_dir: Path) -> Path:
    return deliverables_dir(output_dir) / ISA_VALUES_OUTPUT_FILENAME


def resolve_isa_values_read_path(output_dir: Path) -> Optional[Path]:
    d = Path(output_dir)
    primary = d / DELIVERABLES_DIRNAME / ISA_VALUES_OUTPUT_FILENAME
    if primary.exists():
        return primary
    flat_primary = d / ISA_VALUES_OUTPUT_FILENAME
    if flat_primary.exists():
        return flat_primary
    legacy = d / LEGACY_ISA_VALUES_FILENAME
    if legacy.exists():
        return legacy
    return None


def run_has_metadata_output(run_dir: Path) -> bool:
    return resolve_metadata_output_read_path(run_dir) is not None
