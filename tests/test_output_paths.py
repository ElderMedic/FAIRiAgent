import json
from pathlib import Path

from fairifier.output_paths import (
    artifact_content_to_text,
    artifact_output_filename,
    metadata_output_write_path,
    resolve_metadata_output_read_path,
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


def test_resolve_metadata_output_read_path_prefers_primary(tmp_path):
    primary = tmp_path / "metadata.json"
    legacy = tmp_path / "metadata_json.json"
    legacy.write_text("{}", encoding="utf-8")
    primary.write_text("{}", encoding="utf-8")

    assert metadata_output_write_path(tmp_path) == primary
    assert resolve_metadata_output_read_path(tmp_path) == primary


def test_resolve_metadata_output_read_path_supports_legacy(tmp_path):
    legacy = tmp_path / "metadata_json.json"
    legacy.write_text("{}", encoding="utf-8")

    assert resolve_metadata_output_read_path(Path(tmp_path)) == legacy
