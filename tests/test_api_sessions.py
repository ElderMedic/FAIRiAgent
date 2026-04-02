from fastapi import FastAPI
from fastapi.testclient import TestClient

from fairifier.apps.api.routers.v1 import router
from fairifier.apps.api.storage.sqlite_store import (
    SQLiteProjectStore,
)
from fairifier.utils.run_control import (
    reset_run_stop_requested,
    run_stop_requested,
)

SESSION_A_HEADERS = {
    "X-FAIRifier-Session-Id": "11111111-1111-4111-8111-111111111111",
    "X-FAIRifier-Session-Started-At": "2026-04-01T10:00:00+00:00",
}

SESSION_B_HEADERS = {
    "X-FAIRifier-Session-Id": "22222222-2222-4222-8222-222222222222",
    "X-FAIRifier-Session-Started-At": "2026-04-01T11:00:00+00:00",
}


def _create_test_app(tmp_path):
    store = SQLiteProjectStore(
        str(tmp_path / "projects.db")
    )
    app = FastAPI()
    app.state.store = store
    app.include_router(router)
    return app, store


def test_project_routes_are_isolated_by_session(tmp_path):
    app, store = _create_test_app(tmp_path)

    store.create_project(
        "proj-a",
        {
            "project_id": "proj-a",
            "project_name": "Session A project",
            "session_id": SESSION_A_HEADERS[
                "X-FAIRifier-Session-Id"
            ],
            "session_started_at": SESSION_A_HEADERS[
                "X-FAIRifier-Session-Started-At"
            ],
            "status": "completed",
        },
    )
    store.create_project(
        "proj-b",
        {
            "project_id": "proj-b",
            "project_name": "Session B project",
            "session_id": SESSION_B_HEADERS[
                "X-FAIRifier-Session-Id"
            ],
            "session_started_at": SESSION_B_HEADERS[
                "X-FAIRifier-Session-Started-At"
            ],
            "status": "running",
        },
    )

    try:
        with TestClient(app) as client:
            list_response = client.get(
                "/api/v1/projects",
                headers=SESSION_A_HEADERS,
            )
            assert list_response.status_code == 200
            projects = list_response.json()["projects"]
            assert len(projects) == 1
            assert projects[0]["project_id"] == "proj-a"
            assert (
                projects[0]["session_id"]
                == SESSION_A_HEADERS[
                    "X-FAIRifier-Session-Id"
                ]
            )
            assert projects[0]["status"] == "completed"
            assert projects[0]["created_at"]
            assert projects[0]["updated_at"]

            own_project = client.get(
                "/api/v1/projects/proj-a",
                headers=SESSION_A_HEADERS,
            )
            assert own_project.status_code == 200

            other_project = client.get(
                "/api/v1/projects/proj-b",
                headers=SESSION_A_HEADERS,
            )
            assert other_project.status_code == 404

            missing_session = client.get(
                "/api/v1/projects"
            )
            assert missing_session.status_code == 400
    finally:
        store.close()


def test_stop_endpoint_sets_project_scoped_stop_flag(
    tmp_path,
):
    app, store = _create_test_app(tmp_path)
    store.create_project(
        "proj-run",
        {
            "project_id": "proj-run",
            "project_name": "Running project",
            "session_id": SESSION_A_HEADERS[
                "X-FAIRifier-Session-Id"
            ],
            "session_started_at": SESSION_A_HEADERS[
                "X-FAIRifier-Session-Started-At"
            ],
            "status": "running",
            "stop_requested": False,
        },
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/projects/proj-run/stop",
                headers=SESSION_A_HEADERS,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["stop_requested"] is True
            assert payload["status"] == "running"
            assert "safe checkpoint" in payload["message"]
            assert run_stop_requested("proj-run") is True

            rejected = client.post(
                "/api/v1/projects/proj-run/stop",
                headers=SESSION_B_HEADERS,
            )
            assert rejected.status_code == 404
    finally:
        reset_run_stop_requested("proj-run")
        store.close()
