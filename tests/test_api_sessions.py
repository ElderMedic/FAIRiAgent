import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi import HTTPException

from fairifier.apps.api.routers.v1 import (
    create_project,
    get_project,
    list_projects,
    stop_project,
    router,
)
from fairifier.apps.api.storage.sqlite_store import (
    SQLiteProjectStore,
)
from fairifier.utils.run_control import (
    reset_run_stop_requested,
    run_stop_requested,
)


class _EmptyForm:
    def getlist(self, key):
        return []


class _FakeRequest(SimpleNamespace):
    async def form(self):
        return _EmptyForm()


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
        request = _FakeRequest(
            headers=SESSION_A_HEADERS,
            query_params={},
            app=SimpleNamespace(
                state=SimpleNamespace(store=store)
            ),
        )
        projects_response = asyncio.run(
            list_projects(request)
        )
        projects = projects_response.model_dump()[
            "projects"
        ]
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

        own_project = asyncio.run(
            get_project("proj-a", request)
        )
        assert (
            own_project.project_id == "proj-a"
        )

        try:
            asyncio.run(get_project("proj-b", request))
            raise AssertionError(
                "Expected HTTPException for foreign project"
            )
        except HTTPException as exc:
            assert exc.status_code == 404

        try:
            asyncio.run(
                list_projects(
                    _FakeRequest(
                        headers={},
                        query_params={},
                        app=SimpleNamespace(
                            state=SimpleNamespace(
                                store=store
                            )
                        ),
                    )
                )
            )
            raise AssertionError(
                "Expected HTTPException for missing session"
            )
        except HTTPException as exc:
            assert exc.status_code == 400
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
        response = asyncio.run(
            stop_project(
                "proj-run",
                _FakeRequest(
                    headers=SESSION_A_HEADERS,
                    query_params={},
                    app=SimpleNamespace(
                        state=SimpleNamespace(
                            store=store
                        )
                    ),
                ),
            )
        )
        payload = response.model_dump()
        assert payload["stop_requested"] is True
        assert payload["status"] == "running"
        assert "safe checkpoint" in payload["message"]
        assert run_stop_requested("proj-run") is True

        try:
            asyncio.run(
                stop_project(
                    "proj-run",
                    _FakeRequest(
                        headers=SESSION_B_HEADERS,
                        query_params={},
                        app=SimpleNamespace(
                            state=SimpleNamespace(
                                store=store
                            )
                        ),
                    ),
                )
            )
            raise AssertionError(
                "Expected HTTPException for foreign session"
            )
        except HTTPException as exc:
            assert exc.status_code == 404
    finally:
        reset_run_stop_requested("proj-run")
        store.close()


def test_create_project_rejects_non_object_config_overrides(
    tmp_path,
):
    app, store = _create_test_app(tmp_path)

    try:
        request = _FakeRequest(
            headers=SESSION_A_HEADERS,
            query_params={},
            app=SimpleNamespace(
                state=SimpleNamespace(store=store)
            ),
        )
        try:
            asyncio.run(
                create_project(
                    request,
                    files=None,
                    file=None,
                    sample_document="earthworm_paper",
                    config_overrides="[]",
                )
            )
            raise AssertionError("Expected HTTPException for invalid config_overrides")
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "object" in exc.detail.lower()
    finally:
        store.close()
