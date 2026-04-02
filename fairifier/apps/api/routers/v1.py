"""V1 API router -- versioned under ``/api/v1``."""

import asyncio
import importlib.util
import json
import logging
import os
import socket
import tempfile
import threading
from uuid import UUID
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import FileResponse, StreamingResponse

from ..models import (
    DemoDocumentResponse,
    DemoOptionsResponse,
    HealthResponse,
    MemoryCloudResponse,
    MemoryWordEntry,
    OllamaModelResponse,
    OllamaModelsResponse,
    ProjectListResponse,
    ProjectResponse,
    ResourceLoadResponse,
    ServiceStatusResponse,
    SystemStatusResponse,
)
from ..services.event_bus import WorkflowEvent, event_bus
from ..services.runner import run_workflow_task
from ..storage.base import ProjectStore
from ..system_metrics import collect_resource_metrics_with_gpu
from fairifier.utils.run_control import set_run_stop_requested

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["v1"])

API_VERSION = "1.4.0"
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OLLAMA_PROVIDER = "ollama"
DEFAULT_OLLAMA_MODEL = "qwen3:8b"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
SESSION_ID_HEADER = "X-FAIRifier-Session-Id"
SESSION_STARTED_AT_HEADER = "X-FAIRifier-Session-Started-At"
_DEMO_DOCUMENTS = {
    "earthworm_paper": {
        "path": PROJECT_ROOT / "examples" / "inputs" / "earthworm_4n_paper_bioRxiv.pdf",
        "label": "Earthworm BioRxiv Paper",
        "description": "Bundled reference PDF for end-to-end testing.",
    },
}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _get_store(request: Request) -> ProjectStore:
    return request.app.state.store  # type: ignore[return-value]


def _project_to_response(data: dict) -> ProjectResponse:
    return ProjectResponse(
        project_id=data.get("project_id", ""),
        project_name=data.get("project_name"),
        filename=data.get("filename"),
        input_files=data.get("input_files"),
        session_id=data.get("session_id"),
        session_started_at=data.get("session_started_at"),
        status=data.get("status", "unknown"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
        stop_requested=data.get("stop_requested"),
        stop_requested_at=data.get("stop_requested_at"),
        confidence_scores=data.get("confidence_scores"),
        needs_review=data.get("needs_review"),
        errors=data.get("errors"),
        artifacts=data.get("artifacts"),
        execution_summary=data.get("execution_summary"),
        quality_metrics=data.get("quality_metrics"),
        message=data.get("message"),
    )


def _build_demo_document_response(
    key: str, meta: dict
) -> DemoDocumentResponse:
    path = meta["path"]
    size_bytes = path.stat().st_size if path.is_file() else 0
    return DemoDocumentResponse(
        key=key,
        label=meta["label"],
        filename=path.name,
        description=meta["description"],
        size_bytes=size_bytes,
    )


def _resolve_default_demo_document_key(
    documents: list[DemoDocumentResponse],
) -> str:
    if documents:
        return documents[0].key
    return ""


def _parse_session_id(raw_value: Optional[str]) -> str:
    if not raw_value:
        raise HTTPException(
            status_code=400,
            detail="Missing session identifier",
        )
    try:
        return str(UUID(raw_value))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid session identifier",
        ) from exc


def _parse_session_started_at(
    raw_value: Optional[str],
) -> Optional[str]:
    if not raw_value:
        return None
    try:
        datetime.fromisoformat(
            raw_value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid session timestamp",
        ) from exc
    return raw_value


def _get_session_context(request: Request) -> tuple[str, Optional[str]]:
    session_id = _parse_session_id(
        request.headers.get(SESSION_ID_HEADER)
        or request.query_params.get("session_id")
        or request.query_params.get("session")
    )
    session_started_at = _parse_session_started_at(
        request.headers.get(SESSION_STARTED_AT_HEADER)
        or request.query_params.get("session_started_at")
        or request.query_params.get("ts")
    )
    return session_id, session_started_at


def _get_project_for_session(
    request: Request, project_id: str
) -> dict:
    store = _get_store(request)
    session_id, _ = _get_session_context(request)
    data = store.get_project(project_id)
    if data is None or data.get("session_id") != session_id:
        raise HTTPException(
            status_code=404, detail="Project not found"
        )
    return data


def _probe_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _is_hidden_artifact(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _list_artifact_files(base: Path) -> list[dict]:
    artifacts: list[dict] = []
    for path in sorted(
        base.rglob("*"),
        key=lambda p: p.relative_to(base).as_posix(),
    ):
        if not path.is_file():
            continue
        rel_path = path.relative_to(base)
        if _is_hidden_artifact(rel_path):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        artifacts.append(
            {
                "name": rel_path.as_posix(),
                "size": size,
                "available": True,
            }
        )
    return artifacts


def _infer_service_status(
    *,
    name: str,
    label: str,
    enabled: bool,
    reachable: bool,
    message: str,
    endpoint: Optional[str] = None,
    details: Optional[dict] = None,
) -> ServiceStatusResponse:
    if not enabled:
        status = "disabled"
    elif reachable:
        status = "ready"
    else:
        status = "warning"
    return ServiceStatusResponse(
        name=name,
        label=label,
        enabled=enabled,
        reachable=reachable,
        status=status,
        message=message,
        endpoint=endpoint,
        details=details,
    )


def _fetch_ollama_models_payload(
    base_url: str, timeout: int = 3
) -> tuple[bool, str, list[dict]]:
    try:
        import requests
    except ImportError:
        return False, "requests not installed", []

    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/api/tags",
            timeout=timeout,
        )
        if response.status_code != 200:
            return (
                False,
                f"Ollama returned HTTP {response.status_code}",
                [],
            )
        payload = response.json()
        models = payload.get("models") or []
        if not isinstance(models, list):
            return False, "Invalid Ollama response payload", []
        return True, f"{len(models)} models available", models
    except requests.exceptions.RequestException as exc:
        message = f"Cannot reach Ollama at {base_url.rstrip('/')}"
        detail = str(exc)
        if "Connection refused" in detail:
            message += " (connection refused)"
        elif "Read timed out" in detail or "ConnectTimeout" in detail:
            message += " (request timed out)"
        return False, message, []
    except (ValueError, KeyError) as exc:
        return False, f"Invalid Ollama response: {exc}", []


def _build_mineru_status_message(
    *,
    cli_detected: bool,
    server_reachable: bool,
    server_configured: bool,
) -> str:
    if cli_detected and server_reachable:
        return "CLI and MinerU server reachable"
    if cli_detected and not server_configured:
        return "CLI detected, but MinerU server URL is not configured"
    if cli_detected and not server_reachable:
        return "CLI detected, but MinerU server is unreachable"
    if not cli_detected and server_reachable:
        return "MinerU server reachable, but CLI is not installed"
    if not server_configured:
        return "MinerU CLI missing and server URL is not configured"
    return "MinerU CLI missing and server is unreachable"


def _build_system_status() -> SystemStatusResponse:
    from fairifier.config import config as fc
    from fairifier.services.fair_data_station import FAIRDataStationClient
    from fairifier.services.mem0_service import (
        _is_ollama_available,
        _is_qdrant_available,
        _ollama_has_model,
    )
    from fairifier.services.mineru_client import MinerUClient

    services: list[ServiceStatusResponse] = []

    ollama_ok, ollama_msg, ollama_models = _fetch_ollama_models_payload(
        DEFAULT_OLLAMA_BASE_URL,
        timeout=3,
    )
    ollama_default_model_available = False
    if ollama_ok:
        ollama_default_model_available = any(
            str(item.get("name") or item.get("model")) == DEFAULT_OLLAMA_MODEL
            for item in ollama_models
            if isinstance(item, dict)
        )
    services.append(
        _infer_service_status(
            name="ollama",
            label="Ollama",
            enabled=True,
            reachable=ollama_ok,
            message=ollama_msg,
            endpoint=DEFAULT_OLLAMA_BASE_URL,
            details={
                "default_model": DEFAULT_OLLAMA_MODEL,
                "model_count": len(ollama_models),
                "base_url_reachable": ollama_ok,
                "default_model_available": ollama_default_model_available,
            },
        )
    )

    mineru_cli_exists = True
    if fc.mineru_enabled:
        mineru_client = MinerUClient(
            cli_path=fc.mineru_cli_path,
            server_url=fc.mineru_server_url or "",
            backend=fc.mineru_backend,
            timeout_seconds=fc.mineru_timeout_seconds,
        )
        mineru_cli_exists = mineru_client.is_available()
        mineru_reachable = False
        if fc.mineru_server_url:
            from urllib.parse import urlparse

            parsed = urlparse(fc.mineru_server_url)
            mineru_reachable = _probe_tcp(
                parsed.hostname or "localhost",
                parsed.port or 30000,
            )
        services.append(
            _infer_service_status(
                name="mineru",
                label="MinerU",
                enabled=True,
                reachable=bool(mineru_cli_exists and mineru_reachable),
                message=_build_mineru_status_message(
                    cli_detected=mineru_cli_exists,
                    server_reachable=mineru_reachable,
                    server_configured=bool(fc.mineru_server_url),
                ),
                endpoint=fc.mineru_server_url,
                details={
                    "cli_path": fc.mineru_cli_path,
                    "backend": fc.mineru_backend,
                    "cli_detected": mineru_cli_exists,
                    "server_reachable": mineru_reachable,
                    "timeout_seconds": fc.mineru_timeout_seconds,
                },
            )
        )
    else:
        services.append(
            _infer_service_status(
                name="mineru",
                label="MinerU",
                enabled=False,
                reachable=False,
                message="Disabled; PDF/text fallback parsing will be used.",
                endpoint=fc.mineru_server_url,
                details={
                    "cli_path": fc.mineru_cli_path,
                    "backend": fc.mineru_backend,
                    "cli_detected": False,
                    "server_reachable": False,
                    "timeout_seconds": fc.mineru_timeout_seconds,
                },
            )
        )

    fair_ds_ok = False
    fair_ds_msg = "Not configured"
    fair_ds_error = None
    if fc.fair_ds_api_url:
        try:
            fair_ds_client = FAIRDataStationClient(
                fc.fair_ds_api_url,
                timeout=5,
            )
            fair_ds_ok = fair_ds_client.is_available()
            fair_ds_msg = (
                "API reachable" if fair_ds_ok else "No response"
            )
        except Exception as exc:
            fair_ds_msg = str(exc)
            fair_ds_error = str(exc)
    services.append(
        _infer_service_status(
            name="fair_ds",
            label="FAIR-DS API",
            enabled=bool(fc.fair_ds_api_url),
            reachable=fair_ds_ok,
            message=fair_ds_msg,
            endpoint=fc.fair_ds_api_url,
            details={
                "api_root_reachable": fair_ds_ok,
                "timeout_seconds": 5,
                "last_error": fair_ds_error,
            },
        )
    )

    qdrant_ok = _is_qdrant_available(
        fc.mem0_qdrant_host,
        fc.mem0_qdrant_port,
        timeout_seconds=max(int(fc.mem0_healthcheck_timeout_seconds or 2), 1),
    )
    services.append(
        _infer_service_status(
            name="qdrant",
            label="Qdrant",
            enabled=fc.mem0_enabled,
            reachable=qdrant_ok,
            message=(
                "Vector store reachable"
                if qdrant_ok
                else "Vector store unreachable"
            ),
            endpoint=f"http://{fc.mem0_qdrant_host}:{fc.mem0_qdrant_port}",
            details={
                "host": fc.mem0_qdrant_host,
                "port": fc.mem0_qdrant_port,
                "collection": fc.mem0_collection_name,
                "reachable": qdrant_ok,
            },
        )
    )

    mem0_package_installed = importlib.util.find_spec("mem0") is not None
    effective_mem0_provider = (
        "openai"
        if fc.llm_provider == "qwen"
        else fc.mem0_llm_provider
    )
    effective_mem0_base = (
        fc.llm_base_url
        if fc.llm_provider == "qwen"
        else fc.mem0_llm_base_url
        or fc.mem0_ollama_base_url
        or fc.llm_base_url
    )
    memory_llm_reachable = None
    memory_model_available = None
    if not fc.mem0_enabled:
        mem0_ready = False
        mem0_msg = "Disabled"
    elif not mem0_package_installed:
        mem0_ready = False
        mem0_msg = "mem0 package not installed"
    elif not qdrant_ok:
        mem0_ready = False
        mem0_msg = "Qdrant unavailable"
    elif effective_mem0_provider == "ollama":
        memory_llm_reachable = _is_ollama_available(
            effective_mem0_base,
            timeout_seconds=2,
        )
        memory_model_available = _ollama_has_model(
            effective_mem0_base,
            fc.mem0_llm_model or fc.llm_model,
            timeout_seconds=2,
        )
        ollama_llm_ok = bool(
            memory_llm_reachable and memory_model_available
        )
        mem0_ready = ollama_llm_ok
        mem0_msg = (
            "Memory ready"
            if ollama_llm_ok
            else "Ollama-backed memory unavailable"
        )
    else:
        mem0_ready = bool(
            (fc.mem0_llm_api_key or fc.llm_api_key)
            and qdrant_ok
        )
        mem0_msg = (
            "Memory ready"
            if mem0_ready
            else "Memory LLM credentials missing"
        )
    services.append(
        _infer_service_status(
            name="mem0",
            label="Memory",
            enabled=fc.mem0_enabled,
            reachable=mem0_ready,
            message=mem0_msg,
            endpoint=effective_mem0_base,
            details={
                "provider": effective_mem0_provider,
                "llm_model": fc.mem0_llm_model or fc.llm_model,
                "embedding_provider": fc.mem0_embedding_provider,
                "embedding_model": fc.mem0_embedding_model,
                "package_installed": mem0_package_installed,
                "qdrant_reachable": qdrant_ok,
                "memory_llm_reachable": memory_llm_reachable,
                "memory_model_available": memory_model_available,
            },
        )
    )

    active_config = {
        "llm_provider": fc.llm_provider,
        "llm_model": fc.llm_model,
        "llm_base_url": fc.llm_base_url,
        "fair_ds_api_url": fc.fair_ds_api_url,
        "mineru_enabled": fc.mineru_enabled,
        "mineru_server_url": fc.mineru_server_url,
        "mem0_enabled": fc.mem0_enabled,
        "mem0_llm_provider": fc.mem0_llm_provider,
        "mem0_embedding_provider": fc.mem0_embedding_provider,
        "qdrant_endpoint": f"{fc.mem0_qdrant_host}:{fc.mem0_qdrant_port}",
    }

    return SystemStatusResponse(
        timestamp=datetime.now(timezone.utc).isoformat(),
        active_config=active_config,
        services=services,
    )


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc).isoformat(),
        version=API_VERSION,
    )


@router.get("/demo-options", response_model=DemoOptionsResponse)
async def demo_options() -> DemoOptionsResponse:
    from fairifier.utils.llm_helper import (
        check_ollama_model_available,
    )

    ollama_available, _ = check_ollama_model_available(
        DEFAULT_OLLAMA_BASE_URL,
        DEFAULT_OLLAMA_MODEL,
        timeout=2,
    )

    documents = [
        _build_demo_document_response(key, meta)
        for key, meta in _DEMO_DOCUMENTS.items()
        if meta["path"].is_file()
    ]

    return DemoOptionsResponse(
        default_demo_document_key=_resolve_default_demo_document_key(documents),
        default_ollama_provider=DEFAULT_OLLAMA_PROVIDER,
        default_ollama_model=DEFAULT_OLLAMA_MODEL,
        default_ollama_base_url=DEFAULT_OLLAMA_BASE_URL,
        ollama_available=ollama_available,
        documents=documents,
    )


@router.get("/system/status", response_model=SystemStatusResponse)
async def system_status() -> SystemStatusResponse:
    return _build_system_status()


@router.get("/system/resource-load", response_model=ResourceLoadResponse)
async def resource_load(request: Request) -> ResourceLoadResponse:
    """Return coarse server resource usage for display purposes.

    ``active_runs`` counts workflow projects that are *pending* or *running*
    **for the same browser session** as the request headers (not server-wide).

    GPU stats use ``nvidia-smi`` when available (NVIDIA driver). No paths,
    hostnames, usernames, or per-process details are included.

    Metrics use stdlib + /proc on Linux (no psutil required). Work is run in a
    thread pool so the event loop is not blocked during the CPU sample window.
    """
    session_id, _ = _get_session_context(request)
    store = _get_store(request)
    try:
        projects = store.list_projects()
        active_runs = sum(
            1
            for p in projects
            if p.get("session_id") == session_id
            and p.get("status") in ("pending", "running")
        )
    except Exception:
        active_runs = 0

    (
        cpu_pct,
        memory_pct,
        memory_used_gb,
        memory_total_gb,
        disk_pct,
        gpu_util_pct,
        gpu_memory_used_gb,
        gpu_memory_total_gb,
    ) = await asyncio.to_thread(collect_resource_metrics_with_gpu)

    return ResourceLoadResponse(
        cpu_pct=cpu_pct,
        memory_pct=memory_pct,
        memory_used_gb=memory_used_gb,
        memory_total_gb=memory_total_gb,
        disk_pct=disk_pct,
        active_runs=active_runs,
        gpu_util_pct=gpu_util_pct,
        gpu_memory_used_gb=gpu_memory_used_gb,
        gpu_memory_total_gb=gpu_memory_total_gb,
    )


@router.get("/system/ollama-models", response_model=OllamaModelsResponse)
async def ollama_models(
    base_url: Optional[str] = Query(default=None),
) -> OllamaModelsResponse:
    resolved_base_url = (
        base_url.strip()
        if base_url and base_url.strip()
        else DEFAULT_OLLAMA_BASE_URL
    )
    reachable, message, models = _fetch_ollama_models_payload(
        resolved_base_url,
        timeout=3,
    )
    normalized_models = [
        OllamaModelResponse(
            name=str(item.get("name") or item.get("model")),
            size=item.get("size"),
            digest=item.get("digest"),
            modified_at=item.get("modified_at"),
        )
        for item in models
        if isinstance(item, dict)
        and (item.get("name") or item.get("model"))
    ]
    return OllamaModelsResponse(
        base_url=resolved_base_url,
        reachable=reachable,
        message=message,
        models=normalized_models,
    )


# ------------------------------------------------------------------
# Projects
# ------------------------------------------------------------------


@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=201,
)
async def create_project(
    request: Request,
    files: Optional[list[UploadFile]] = File(default=None),
    file: Optional[UploadFile] = File(default=None),
    project_name: Optional[str] = Form(default=None),
    config_overrides: Optional[str] = Form(default=None),
    demo: Optional[bool] = Form(default=False),
    sample_document: Optional[str] = Form(default=None),
) -> ProjectResponse:
    """Upload a document and kick off the workflow."""
    from fairifier.config import config as fc

    store = _get_store(request)
    session_id, session_started_at = _get_session_context(
        request
    )

    uploaded_files: list[UploadFile] = []
    if files:
        uploaded_files.extend(files)
    if file is not None:
        uploaded_files.append(file)

    if not uploaded_files and not sample_document:
        raise HTTPException(
            status_code=400,
            detail="Provide either a file or sample_document",
        )
    if uploaded_files and sample_document:
        raise HTTPException(
            status_code=400,
            detail="Provide uploaded files or sample_document, not both",
        )

    source_filename: str
    input_filenames: list[str]
    if sample_document:
        doc_meta = _DEMO_DOCUMENTS.get(sample_document)
        if doc_meta is None or not doc_meta["path"].is_file():
            raise HTTPException(
                status_code=400,
                detail="Unknown sample_document",
            )
        source_path = doc_meta["path"]
        content = source_path.read_bytes()
        source_filename = source_path.name
        input_filenames = [source_filename]
        suffix = source_path.suffix
        max_bytes = fc.max_document_size_mb * 1024 * 1024
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    "File too large. "
                    f"Max size: {fc.max_document_size_mb} MB"
                ),
            )
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix
        ) as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = tmp.name
    else:
        max_bytes = fc.max_document_size_mb * 1024 * 1024
        file_payloads: list[tuple[str, bytes]] = []
        for idx, uploaded in enumerate(uploaded_files, start=1):
            raw_name = (uploaded.filename or "").strip()
            if not raw_name:
                raw_name = f"input_{idx}"
            safe_name = Path(raw_name).name
            if not safe_name:
                safe_name = f"input_{idx}"
            blob = await uploaded.read()
            if len(blob) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"File '{safe_name}' is too large. "
                        f"Max size: {fc.max_document_size_mb} MB"
                    ),
                )
            file_payloads.append((safe_name, blob))

        input_filenames = [name for name, _ in file_payloads]
        source_filename = input_filenames[0] if len(input_filenames) == 1 else f"{len(input_filenames)} input files"

        if len(file_payloads) == 1:
            single_name, single_content = file_payloads[0]
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=Path(single_name).suffix
            ) as tmp:
                tmp.write(single_content)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = tmp.name
        else:
            tmp_dir = tempfile.mkdtemp(prefix="fairifier_upload_bundle_")
            for idx, (safe_name, blob) in enumerate(file_payloads, start=1):
                target_name = f"{idx:02d}_{safe_name}"
                target_path = Path(tmp_dir) / target_name
                target_path.write_bytes(blob)
            tmp_path = tmp_dir

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    project_id = f"fairifier_{ts}"
    now = datetime.now(timezone.utc).isoformat()
    output_dir = str((fc.output_path / project_id).resolve())
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    overrides_dict = None
    if config_overrides:
        try:
            overrides_dict = json.loads(config_overrides)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail="config_overrides must be valid JSON",
            )

    project_data = {
        "project_id": project_id,
        "project_name": project_name or source_filename,
        "filename": source_filename,
        "input_files": input_filenames,
        "session_id": session_id,
        "session_started_at": session_started_at or now,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "output_dir": output_dir,
        "demo": bool(demo),
        "sample_document": sample_document,
        "stop_requested": False,
        "message": (
            f"Project {project_id} created "
            "-- workflow starting"
        ),
    }
    store.create_project(project_id, project_data)

    thread = threading.Thread(
        target=run_workflow_task,
        args=(project_id, tmp_path, store),
        kwargs={
            "output_dir": output_dir,
            "config_overrides": overrides_dict,
            "demo_mode": bool(demo),
            "user_session_id": session_id,
        },
        daemon=True,
    )
    thread.start()

    logger.info(
        "Started project %s for file %s",
        project_id,
        source_filename,
    )
    return _project_to_response(project_data)


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    request: Request,
) -> ProjectListResponse:
    store = _get_store(request)
    session_id, _ = _get_session_context(request)
    rows = store.list_projects()
    return ProjectListResponse(
        projects=[
            _project_to_response(r)
            for r in rows
            if r.get("session_id") == session_id
        ]
    )


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
)
async def get_project(
    project_id: str, request: Request
) -> ProjectResponse:
    data = _get_project_for_session(request, project_id)
    return _project_to_response(data)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str, request: Request
) -> dict:
    store = _get_store(request)
    _get_project_for_session(request, project_id)
    deleted = store.delete_project(project_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail="Project not found"
        )
    return {"message": f"Project {project_id} deleted"}


@router.post(
    "/projects/{project_id}/stop",
    response_model=ProjectResponse,
)
async def stop_project(
    project_id: str, request: Request
) -> ProjectResponse:
    store = _get_store(request)
    data = _get_project_for_session(request, project_id)
    status = str(data.get("status") or "unknown")
    if status not in {"pending", "running"}:
        return _project_to_response(data)

    now = datetime.now(timezone.utc).isoformat()
    set_run_stop_requested(True, run_id=project_id)
    store.update_project(
        project_id,
        {
            "stop_requested": True,
            "stop_requested_at": now,
            "message": (
                "Stop requested. Waiting for the workflow "
                "to reach a safe checkpoint."
            ),
        },
    )
    event_bus.publish_sync(
        WorkflowEvent(
            event_type="stop_requested",
            project_id=project_id,
            data={
                "message": (
                    "Stop requested. Waiting for the workflow "
                    "to reach a safe checkpoint."
                ),
                "status": status,
            },
        )
    )
    return _project_to_response(
        store.get_project(project_id) or data
    )


# ------------------------------------------------------------------
# Artifacts
# ------------------------------------------------------------------


@router.get("/projects/{project_id}/artifacts")
async def list_artifacts(
    project_id: str, request: Request
) -> dict:
    data = _get_project_for_session(request, project_id)
    output_dir = data.get("output_dir")
    if not output_dir:
        return {"project_id": project_id, "artifacts": []}

    base = Path(output_dir)
    if not base.is_dir():
        return {"project_id": project_id, "artifacts": []}

    return {
        "project_id": project_id,
        "artifacts": _list_artifact_files(base),
    }


@router.get(
    "/projects/{project_id}/artifacts/{artifact_name:path}"
)
async def get_artifact(
    project_id: str,
    artifact_name: str,
    request: Request,
) -> FileResponse:
    data = _get_project_for_session(request, project_id)
    output_dir = data.get("output_dir")
    if not output_dir:
        raise HTTPException(
            status_code=404,
            detail="No output directory for this project",
        )

    base_dir = Path(output_dir).resolve()
    artifact_path = (base_dir / artifact_name).resolve()
    try:
        artifact_path.relative_to(base_dir)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid artifact path",
        )

    if _is_hidden_artifact(
        artifact_path.relative_to(base_dir)
    ) or not artifact_path.is_file():
        raise HTTPException(
            status_code=404, detail="Artifact not found"
        )

    return FileResponse(
        path=str(artifact_path), filename=artifact_name
    )


# ------------------------------------------------------------------
# SSE event stream
# ------------------------------------------------------------------


async def _sse_generator(
    project_id: str,
    queue: asyncio.Queue[WorkflowEvent],
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted events until completion."""
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=30.0
                )
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            yield event.to_sse()

            if event.event_type in (
                "completed",
                "error",
            ):
                break
    finally:
        event_bus.unsubscribe(project_id, queue)


_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "that", "this", "these", "those", "it", "its",
    "as", "if", "not", "no", "so", "up", "out", "more", "than", "then",
    "also", "about", "into", "using", "used", "via", "based", "per",
    "between", "identified", "selected", "requires", "required", "within",
    "across", "during", "after", "before", "through", "all", "each",
    "which", "when", "where", "how", "what", "well", "can", "use",
})


def _tokenize_memories(
    memories: list,
) -> list:
    """Extract (word, category) pairs from a list of mem0 memory dicts."""
    import re
    pairs: list[tuple[str, str]] = []
    for m in memories:
        text = m.get("memory", "")
        category = (
            m.get("metadata", {}).get("agent_id")
            or m.get("metadata", {}).get("workflow_step")
            or "unknown"
        )
        for word in re.findall(r"[a-zA-Z]{3,}", text):
            w = word.lower()
            if w not in _STOP_WORDS:
                pairs.append((w, category))
    return pairs


def _build_word_entries(pairs: list) -> list[MemoryWordEntry]:
    """Aggregate (word, category) pairs into MemoryWordEntry list."""
    from collections import Counter, defaultdict
    freq: Counter = Counter(w for w, _ in pairs)
    cat_map: dict = defaultdict(Counter)
    for w, cat in pairs:
        cat_map[w][cat] += 1
    return [
        MemoryWordEntry(
            text=word,
            value=count,
            category=cat_map[word].most_common(1)[0][0],
        )
        for word, count in freq.most_common(80)
        if count >= 2
    ]


@router.get("/projects/{project_id}/memory-cloud", response_model=MemoryCloudResponse)
async def memory_cloud(project_id: str, request: Request) -> MemoryCloudResponse:
    """Return word-frequency data extracted from this project's memories.

    Two views are returned:
    - session_words: memories scoped to this specific run (session_id = project_id)
    - scope_words:   memories scoped to the shared memory_scope_id (cross-run learning)

    Only word frequencies and agent categories are exposed — no raw memory text,
    no file paths, no user identifiers.
    """
    from fairifier.services.mem0_service import mem0_service

    if not mem0_service.is_available():
        return MemoryCloudResponse(
            session_words=[],
            scope_words=[],
            session_total=0,
            scope_total=0,
            memory_enabled=False,
        )

    store = _get_store(request)
    try:
        project_data = store.get_project(project_id)
    except Exception:
        project_data = {}

    # session scope = this run only
    session_id = project_data.get("session_id") or project_id
    session_mems = mem0_service.list_memories(session_id=session_id)

    # shared scope = cross-run learning pool (may equal session_id if not configured)
    from fairifier.config import config as fc
    scope_id = fc.memory_scope_id or session_id
    if scope_id != session_id:
        scope_mems = mem0_service.list_memories(session_id=scope_id)
    else:
        scope_mems = session_mems

    session_pairs = _tokenize_memories(session_mems)
    scope_pairs = _tokenize_memories(scope_mems)

    return MemoryCloudResponse(
        session_words=_build_word_entries(session_pairs),
        scope_words=_build_word_entries(scope_pairs),
        session_total=len(session_mems),
        scope_total=len(scope_mems),
        memory_enabled=True,
    )


@router.get("/projects/{project_id}/events")
async def project_events(
    project_id: str, request: Request
) -> StreamingResponse:
    """SSE stream of workflow events for a project."""
    _get_project_for_session(request, project_id)

    queue = event_bus.subscribe(project_id)
    return StreamingResponse(
        _sse_generator(project_id, queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
