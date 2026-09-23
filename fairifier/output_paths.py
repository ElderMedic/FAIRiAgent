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


def ensure_output_subdirectories(output_dir: Path) -> None:
    """Eagerly create the complete output layout.

    This helper is retained for callers that explicitly need a materialized
    layout. Runtime entry points should create an artifact's parent directory
    immediately before writing it.
    """
    d = Path(output_dir)
    deliverables_dir(d).mkdir(parents=True, exist_ok=True)
    logs_dir(d).mkdir(parents=True, exist_ok=True)
    reports_dir(d).mkdir(parents=True, exist_ok=True)
    workspace_dir(d).mkdir(parents=True, exist_ok=True)


def get_artifact_write_path(output_dir: Path, artifact_name: str) -> Path:
    """Route workflow artifact payloads into their designated subdirectory."""
    d = Path(output_dir)
    if artifact_name in ("metadata_json", "metadata"):
        return metadata_output_write_path(d)
    if artifact_name in ("isa_values_json", "isa_values"):
        return isa_values_output_write_path(d)
    if artifact_name in ("workflow_report", "workflow_report_json"):
        return reports_dir(d) / "workflow_report.json"
    if artifact_name in ("workflow_report_txt", "workflow_report_text"):
        return reports_dir(d) / "workflow_report.txt"
    if artifact_name == "validation_report":
        return reports_dir(d) / "validation_report.txt"

    if artifact_name in ("auto_repair_trace", "auto_repair_trace_json"):
        return reports_dir(d) / "auto_repair_trace.json"
    if artifact_name == "runtime_config":
        return reports_dir(d) / "runtime_config.json"
    if artifact_name == "extracted_document_content":
        return workspace_dir(d) / "extracted_document_content.txt"
    if artifact_name == "processing_log":
        return logs_dir(d) / "processing_log.jsonl"
    if artifact_name == "llm_responses":
        return logs_dir(d) / "llm_responses.json"
    if artifact_name == "react_scratchpad":
        return logs_dir(d) / "react_scratchpad.json"
    if artifact_name == "full_output":
        return logs_dir(d) / "full_output.log"
    filename = artifact_output_filename(artifact_name)
    return reports_dir(d) / filename


def resolve_processing_log_read_path(output_dir: Path) -> Optional[Path]:
    d = Path(output_dir)
    primary = logs_dir(d) / "processing_log.jsonl"
    if primary.exists():
        return primary
    flat = d / "processing_log.jsonl"
    if flat.exists():
        return flat
    return None


def resolve_full_output_log_read_path(output_dir: Path) -> Optional[Path]:
    d = Path(output_dir)
    primary = logs_dir(d) / "full_output.log"
    if primary.exists():
        return primary
    flat = d / "full_output.log"
    if flat.exists():
        return flat
    return None


def resolve_runtime_config_read_path(output_dir: Path) -> Optional[Path]:
    d = Path(output_dir)
    primary = reports_dir(d) / "runtime_config.json"
    if primary.exists():
        return primary
    flat = d / "runtime_config.json"
    if flat.exists():
        return flat
    return None


def resolve_workflow_report_read_path(output_dir: Path) -> Optional[Path]:
    d = Path(output_dir)
    primary = reports_dir(d) / "workflow_report.json"
    if primary.exists():
        return primary
    flat = d / "workflow_report.json"
    if flat.exists():
        return flat
    return None


def resolve_auto_repair_trace_read_path(output_dir: Path) -> Optional[Path]:
    d = Path(output_dir)
    primary = reports_dir(d) / "auto_repair_trace.json"
    if primary.exists():
        return primary
    flat = d / "auto_repair_trace.json"
    if flat.exists():
        return flat
    return None


def run_has_metadata_output(run_dir: Path) -> bool:
    return resolve_metadata_output_read_path(run_dir) is not None
