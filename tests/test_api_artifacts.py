from fastapi import FastAPI
from fastapi.testclient import TestClient

from fairifier.apps.api.routers.v1 import router
from fairifier.apps.api.services.runner import (
    _persist_run_outputs,
)
from fairifier.apps.api.storage.sqlite_store import (
    SQLiteProjectStore,
)
from fairifier.utils.json_logger import JSONLogger


def test_list_artifacts_includes_nested_files_and_downloads(
    tmp_path,
):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "workflow_report.json").write_text(
        "{}", encoding="utf-8"
    )
    nested_dir = output_dir / "mineru_doc"
    nested_dir.mkdir()
    nested_file = nested_dir / "report.md"
    nested_file.write_text(
        "# converted", encoding="utf-8"
    )
    (output_dir / ".hidden").write_text(
        "skip", encoding="utf-8"
    )
    hidden_nested = nested_dir / ".skip.txt"
    hidden_nested.write_text(
        "skip", encoding="utf-8"
    )

    store = SQLiteProjectStore(
        str(tmp_path / "projects.db")
    )
    app = FastAPI()
    app.state.store = store
    app.include_router(router)

    store.create_project(
        "proj-1",
        {
            "project_id": "proj-1",
            "project_name": "Test Project",
            "status": "completed",
            "output_dir": str(output_dir),
        },
    )

    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/projects/proj-1/artifacts"
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["project_id"] == "proj-1"
            assert payload["artifacts"] == [
                {
                    "name": "mineru_doc/report.md",
                    "size": len("# converted"),
                    "available": True,
                },
                {
                    "name": "workflow_report.json",
                    "size": len("{}"),
                    "available": True,
                },
            ]

            download = client.get(
                "/api/v1/projects/proj-1/artifacts/"
                "mineru_doc/report.md"
            )
            assert download.status_code == 200
            assert (
                download.content.decode("utf-8")
                == "# converted"
            )
    finally:
        store.close()


def test_persist_run_outputs_writes_core_downloadable_files(
    tmp_path,
):
    json_logger = JSONLogger(
        component="test", enable_stdout=False
    )
    json_logger.log_processing_start(
        "document.pdf", "proj-2"
    )
    json_logger.log_processing_end(
        "proj-2", "completed", 1.25
    )

    errors = _persist_run_outputs(
        project_id="proj-2",
        result={
            "artifacts": {
                "metadata_json": '{"ok": true}',
                "validation_report": "looks good",
            }
        },
        output_dir=str(tmp_path),
        json_logger=json_logger,
    )

    assert errors == []
    assert (
        tmp_path / "metadata_json.json"
    ).read_text(encoding="utf-8") == '{"ok": true}'
    assert (
        tmp_path / "validation_report.txt"
    ).read_text(encoding="utf-8") == "looks good"
    processing_log = (
        tmp_path / "processing_log.jsonl"
    ).read_text(encoding="utf-8")
    assert "processing_started" in processing_log
    assert "processing_completed" in processing_log
    assert "artifact_saved" in processing_log
