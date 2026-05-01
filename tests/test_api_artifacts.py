import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fairifier.apps.api.routers.v1 import (
    _build_word_entries,
    _resolve_default_demo_document_key,
    memory_cloud,
    router,
)
from fairifier.apps.api.services.runner import (
    _persist_run_outputs,
)
from fairifier.apps.api.storage.sqlite_store import (
    SQLiteProjectStore,
)
from fairifier.apps.api.models import DemoDocumentResponse
from fairifier.utils.json_logger import JSONLogger

SESSION_HEADERS = {
    "X-FAIRifier-Session-Id": "11111111-1111-4111-8111-111111111111",
    "X-FAIRifier-Session-Started-At": "2026-04-01T10:00:00+00:00",
}


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
            "session_id": SESSION_HEADERS[
                "X-FAIRifier-Session-Id"
            ],
            "session_started_at": SESSION_HEADERS[
                "X-FAIRifier-Session-Started-At"
            ],
            "status": "completed",
            "output_dir": str(output_dir),
        },
    )

    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/projects/proj-1/artifacts",
                headers=SESSION_HEADERS,
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
                "mineru_doc/report.md",
                headers=SESSION_HEADERS,
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
        tmp_path / "metadata.json"
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


def test_default_demo_document_key_falls_back_to_available_sample():
    documents = [
      DemoDocumentResponse(
          key="earthworm_paper",
          label="Earthworm BioRxiv Paper",
          filename="earthworm_4n_paper_bioRxiv.pdf",
          description="Representative PDF example.",
          size_bytes=123,
      )
    ]

    assert (
        _resolve_default_demo_document_key(documents)
        == "earthworm_paper"
    )


def test_memory_cloud_separates_run_and_user_memory(
    monkeypatch,
    tmp_path,
):
    store = SQLiteProjectStore(
        str(tmp_path / "projects.db")
    )
    app = FastAPI()
    app.state.store = store
    app.include_router(router)

    store.create_project(
        "proj-memory",
        {
            "project_id": "proj-memory",
            "project_name": "Memory Project",
            "session_id": SESSION_HEADERS[
                "X-FAIRifier-Session-Id"
            ],
            "session_started_at": SESSION_HEADERS[
                "X-FAIRifier-Session-Started-At"
            ],
            "status": "completed",
        },
    )

    class FakeMem0:
        def is_available(self):
            return True

        def list_memories(self, session_id, agent_id=None):
            if session_id == "proj-memory":
                return [
                    {
                        "memory": "nanotoxicology uses soil package",
                        "metadata": {"agent_id": "KnowledgeRetriever"},
                    },
                ]
            if session_id == SESSION_HEADERS[
                "X-FAIRifier-Session-Id"
            ]:
                return [
                    {
                        "memory": "earthworm studies use ENVO ontology",
                        "metadata": {"agent_id": "DocumentParser"},
                    },
                    {
                        "memory": "soil studies prefer MIxS fields",
                        "metadata": {"agent_id": "JSONGenerator"},
                    },
                ]
            return []

    monkeypatch.setattr(
        "fairifier.services.mem0_service.get_mem0_service",
        lambda: FakeMem0(),
    )
    monkeypatch.setattr(
        "fairifier.config.config.memory_scope_id",
        None,
    )

    try:
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(store=store)
            )
        )
        response = asyncio.run(
            memory_cloud("proj-memory", request)
        )
        payload = response.model_dump()
        assert payload["memory_enabled"] is True
        assert payload["session_total"] == 1
        assert payload["scope_total"] == 2
        assert {
            entry["text"] for entry in payload["session_words"]
        } >= {"nanotoxicology", "soil", "package"}
        assert {
            entry["text"] for entry in payload["scope_words"]
        } >= {"earthworm", "ontology", "prefer"}
    finally:
        store.close()


def test_memory_word_entries_include_singletons():
    entries = _build_word_entries(
        [
            ("nanotoxicology", "KnowledgeRetriever"),
            ("package", "KnowledgeRetriever"),
        ]
    )

    assert [entry.model_dump() for entry in entries] == [
        {
            "text": "nanotoxicology",
            "value": 1,
            "category": "KnowledgeRetriever",
        },
        {
            "text": "package",
            "value": 1,
            "category": "KnowledgeRetriever",
        },
    ]
