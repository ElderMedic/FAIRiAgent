import json
from pathlib import Path

import pytest

from fairifier.output_paths import (
    DELIVERABLES_DIRNAME,
    ISA_VALUES_OUTPUT_FILENAME,
    LOGS_DIRNAME,
    METADATA_OUTPUT_FILENAME,
    REPORTS_DIRNAME,
    WORKSPACE_DIRNAME,
    artifact_content_to_text,
    artifact_output_filename,
    deliverables_dir,
    get_artifact_write_path,
    isa_values_output_write_path,
    logs_dir,
    metadata_output_write_path,
    reports_dir,
    resolve_isa_values_read_path,
    resolve_metadata_output_read_path,
    workspace_dir,
)


def test_artifact_output_filename_maps_json_sidecars():
    assert artifact_output_filename("metadata_json") == "metadata.json"
    assert artifact_output_filename("validation_report") == "validation_report.txt"
    assert artifact_output_filename("runtime_config") == "runtime_config.json"
    assert artifact_output_filename("auto_repair_trace") == "auto_repair_trace.json"


def test_artifact_content_to_text_preserves_strings_and_serializes_objects():
    assert artifact_content_to_text("plain") == "plain"

    text = artifact_content_to_text(
        {
            "mode": "deterministic_exact_patch",
            "summary": {"accepted_patch_count": 0, "artifact_count": 2},
        }
    )

    payload = json.loads(text)
    assert payload["summary"]["accepted_patch_count"] == 0
    assert payload["summary"]["artifact_count"] == 2
    assert "\n  " in text


def test_subfolder_dir_helpers(tmp_path: Path):
    assert deliverables_dir(tmp_path) == tmp_path / DELIVERABLES_DIRNAME
    assert logs_dir(tmp_path) == tmp_path / LOGS_DIRNAME
    assert reports_dir(tmp_path) == tmp_path / REPORTS_DIRNAME
    assert workspace_dir(tmp_path) == tmp_path / WORKSPACE_DIRNAME


def test_write_paths(tmp_path: Path):
    assert metadata_output_write_path(tmp_path) == tmp_path / DELIVERABLES_DIRNAME / METADATA_OUTPUT_FILENAME
    assert isa_values_output_write_path(tmp_path) == tmp_path / DELIVERABLES_DIRNAME / ISA_VALUES_OUTPUT_FILENAME


def test_resolve_metadata_and_isa_paths(tmp_path: Path):
    # Test new subdirectory paths
    deliv_dir = tmp_path / DELIVERABLES_DIRNAME
    deliv_dir.mkdir()
    (deliv_dir / METADATA_OUTPUT_FILENAME).write_text("{}")
    (deliv_dir / ISA_VALUES_OUTPUT_FILENAME).write_text("{}")

    assert resolve_metadata_output_read_path(tmp_path) == deliv_dir / METADATA_OUTPUT_FILENAME
    assert resolve_isa_values_read_path(tmp_path) == deliv_dir / ISA_VALUES_OUTPUT_FILENAME


def test_resolve_fallback_flat_paths(tmp_path: Path):
    (tmp_path / METADATA_OUTPUT_FILENAME).write_text("{}")
    (tmp_path / "isa_values_json.json").write_text("{}")

    assert resolve_metadata_output_read_path(tmp_path) == tmp_path / METADATA_OUTPUT_FILENAME
    assert resolve_isa_values_read_path(tmp_path) == tmp_path / "isa_values_json.json"


def test_resolve_isa_values_flat_primary_and_legacy(tmp_path: Path):
    # Flat primary fallback (isa_values.json directly in output_dir)
    (tmp_path / ISA_VALUES_OUTPUT_FILENAME).write_text("{}")
    assert resolve_isa_values_read_path(tmp_path) == tmp_path / ISA_VALUES_OUTPUT_FILENAME


def test_resolve_metadata_output_read_path_supports_legacy(tmp_path: Path):
    legacy = tmp_path / "metadata_json.json"
    legacy.write_text("{}", encoding="utf-8")

    assert resolve_metadata_output_read_path(Path(tmp_path)) == legacy


def test_react_scratchpad_writes_to_logs_dir(tmp_path: Path):
    path = get_artifact_write_path(tmp_path, "react_scratchpad")
    assert path == tmp_path / LOGS_DIRNAME / "react_scratchpad.json"
