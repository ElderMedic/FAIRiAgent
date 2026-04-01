"""Background runner for the FAIRifier LangGraph workflow."""

import asyncio
import json
import logging
import os
import threading
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from ..storage.base import ProjectStore
from .event_bus import WorkflowEvent, event_bus
from fairifier.utils.json_logger import JSONLogger
from fairifier.utils.run_control import reset_run_stop_requested

logger = logging.getLogger(__name__)
_CONFIG_OVERRIDE_LOCK = threading.Lock()
_CONFIG_OVERRIDE_FIELDS = (
    "llm_provider",
    "llm_model",
    "llm_base_url",
    "llm_api_key",
    "fair_ds_api_url",
)
_SSE_LOG_PREFIXES = (
    "fairifier.graph.langgraph_app",
    "fairifier.agents",
    "fairifier.utils.llm_helper",
)
_STAGE_PROGRESS_HINTS = (
    ("Step 1: DocumentParser", "document_parser", 15),
    ("Step 2: Planning workflow strategy", "planner", 30),
    ("Step 3: KnowledgeRetriever", "knowledge_retriever", 50),
    ("Step 4: JSONGenerator", "json_generator", 75),
    ("Step 5", "validation", 90),
)


class _WorkflowLogHandler(logging.Handler):
    """Bridge workflow logs into SSE so the WebUI reflects real progress."""

    def __init__(self, project_id: str) -> None:
        super().__init__(level=logging.INFO)
        self.project_id = project_id

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith(_SSE_LOG_PREFIXES):
            return

        try:
            message = record.getMessage().strip()
        except Exception:
            return

        if not message:
            return

        event_bus.publish_sync(
            WorkflowEvent(
                event_type="log",
                project_id=self.project_id,
                data={"message": message},
            )
        )

        for marker, stage, progress in _STAGE_PROGRESS_HINTS:
            if marker in message:
                event_bus.publish_sync(
                    WorkflowEvent(
                        event_type="stage_change",
                        project_id=self.project_id,
                        data={"stage": stage, "message": message},
                    )
                )
                event_bus.publish_sync(
                    WorkflowEvent(
                        event_type="progress",
                        project_id=self.project_id,
                        data={"progress": progress, "message": message},
                    )
                )
                break


def run_workflow_task(
    project_id: str,
    file_path: str,
    store: ProjectStore,
    output_dir: Optional[str] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
    demo_mode: bool = False,
) -> None:
    """Run the FAIRifier workflow synchronously.

    Designed to be called inside ``threading.Thread``.
    """
    json_logger = JSONLogger(
        component="fairifier.web_api", enable_stdout=False
    )
    try:
        existing_project = store.get_project(project_id) or {}
        if not existing_project.get("stop_requested"):
            reset_run_stop_requested(project_id)
        json_logger.log_processing_start(
            file_path, project_id
        )
        store.update_project(
            project_id, {"status": "running"}
        )
        event_bus.publish_sync(
            WorkflowEvent(
                event_type="stage_change",
                project_id=project_id,
                data={
                    "stage": "running",
                    "message": "Workflow started",
                },
            )
        )

        workflow_log_handler = _WorkflowLogHandler(project_id)
        logging.getLogger().addHandler(workflow_log_handler)
        try:
            with _CONFIG_OVERRIDE_LOCK:
                original_config = _snapshot_config_state()
                try:
                    if config_overrides:
                        _apply_config_overrides(config_overrides)

                    from fairifier.graph.langgraph_app import (
                        FAIRifierLangGraphApp,
                    )

                    app = FAIRifierLangGraphApp()

                    event_bus.publish_sync(
                        WorkflowEvent(
                            event_type="progress",
                            project_id=project_id,
                            data={
                                "progress": 5,
                                "message": (
                                    "LangGraph app initialised, "
                                    "executing workflow"
                                ),
                            },
                        )
                    )
                    result = asyncio.run(
                        app.run(file_path, project_id, output_dir)
                    )
                finally:
                    _restore_config_state(original_config)
        finally:
            logging.getLogger().removeHandler(workflow_log_handler)

        status = result.get("status", "completed")
        duration_seconds = result.get("duration_seconds")
        json_logger.log_processing_end(
            project_id,
            status,
            float(duration_seconds)
            if isinstance(duration_seconds, (int, float))
            else 0.0,
        )

        persisted_output_dir = (
            result.get("output_dir") or output_dir
        )
        persistence_errors = _persist_run_outputs(
            project_id=project_id,
            result=result,
            output_dir=persisted_output_dir,
            json_logger=json_logger,
        )
        store.update_project(
            project_id,
            {
                "status": status,
                "confidence_scores": result.get(
                    "confidence_scores", {}
                ),
                "needs_review": result.get(
                    "needs_human_review", False
                ),
                "errors": result.get("errors", []),
                "execution_summary": result.get("execution_summary", {}),
                "quality_metrics": result.get("quality_metrics", {}),
                "output_dir": persisted_output_dir,
                "artifacts": _serialisable_artifacts(
                    result.get("artifacts", {})
                ),
                "message": (
                    "Run stopped by user"
                    if status == "interrupted"
                    else f"Workflow {status}"
                ),
                "processing_end": result.get(
                    "processing_end"
                ),
                "persistence_errors": persistence_errors,
                "stop_requested": False,
            },
        )

        event_bus.publish_sync(
            WorkflowEvent(
                event_type=(
                    "stopped"
                    if status == "interrupted"
                    else "completed"
                ),
                project_id=project_id,
                data={
                    "status": status,
                    "progress": 100,
                    "confidence_scores": result.get(
                        "confidence_scores", {}
                    ),
                    "message": (
                        "Run stopped by user"
                        if status == "interrupted"
                        else f"Workflow {status}"
                    ),
                },
            )
        )

        logger.info(
            "Workflow completed for project %s "
            "(status=%s)",
            project_id,
            status,
        )

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error(
            "Workflow failed for project %s: %s\n%s",
            project_id,
            exc,
            tb,
        )
        store.update_project(
            project_id,
            {
                "status": "failed",
                "errors": [str(exc)],
                "message": str(exc),
                "stop_requested": False,
            },
        )
        event_bus.publish_sync(
            WorkflowEvent(
                event_type="error",
                project_id=project_id,
                data={"error": str(exc)},
            )
        )

    finally:
        reset_run_stop_requested(project_id)
        try:
            os.unlink(file_path)
        except OSError:
            pass


def _apply_config_overrides(
    overrides: Dict[str, Any],
) -> None:
    """Apply per-run overrides to the config singleton."""
    from fairifier.config import config
    from fairifier.services.mem0_service import (
        reset_mem0_service,
    )
    from fairifier.utils.llm_helper import (
        reset_llm_helper,
    )

    for attr in _CONFIG_OVERRIDE_FIELDS:
        val = overrides.get(attr)
        if val is not None:
            setattr(config, attr, val)
    reset_llm_helper()
    reset_mem0_service()


def _snapshot_config_state() -> Dict[str, Any]:
    """Capture mutable per-run config so request overrides do not leak globally."""
    from fairifier.config import config

    return {
        field: getattr(config, field)
        for field in _CONFIG_OVERRIDE_FIELDS
    }


def _restore_config_state(state: Dict[str, Any]) -> None:
    """Restore mutable config after a request-scoped run."""
    from fairifier.config import config
    from fairifier.services.mem0_service import (
        reset_mem0_service,
    )
    from fairifier.utils.llm_helper import (
        reset_llm_helper,
    )

    for field, value in state.items():
        setattr(config, field, value)
    reset_llm_helper()
    reset_mem0_service()


def _persist_run_outputs(
    *,
    project_id: str,
    result: Dict[str, Any],
    output_dir: Optional[str],
    json_logger: JSONLogger,
) -> list[str]:
    """Persist downloadable files for the Web UI result page."""
    if not output_dir:
        return []

    errors: list[str] = []
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    artifacts = result.get("artifacts", {})
    if isinstance(artifacts, dict):
        extensions = {
            "metadata_json": ".json",
            "validation_report": ".txt",
            "processing_log": ".jsonl",
        }
        for artifact_name, content in artifacts.items():
            if not content:
                continue
            ext = extensions.get(artifact_name, ".json")
            artifact_path = output_path / f"{artifact_name}{ext}"
            try:
                text = (
                    content
                    if isinstance(content, str)
                    else json.dumps(
                        content,
                        indent=2,
                        ensure_ascii=False,
                    )
                )
                artifact_path.write_text(
                    text, encoding="utf-8"
                )
                json_logger.info(
                    "artifact_saved",
                    project_id=project_id,
                    filename=artifact_path.name,
                    size_bytes=artifact_path.stat().st_size,
                )
            except Exception as exc:
                msg = (
                    f"Failed to save artifact "
                    f"{artifact_path.name}: {exc}"
                )
                logger.warning(msg)
                errors.append(msg)

    log_path = output_path / "processing_log.jsonl"
    try:
        with log_path.open("w", encoding="utf-8") as fh:
            for log_entry in json_logger.get_logs():
                fh.write(
                    json.dumps(
                        log_entry, ensure_ascii=False
                    )
                    + "\n"
                )
    except Exception as exc:
        msg = f"Failed to save processing_log.jsonl: {exc}"
        logger.warning(msg)
        errors.append(msg)

    try:
        from fairifier.utils.llm_helper import (
            get_llm_helper,
            save_llm_responses,
        )

        llm_helper = get_llm_helper()
        if (
            llm_helper is not None
            and getattr(
                llm_helper, "llm_responses", None
            )
        ):
            save_llm_responses(output_path, llm_helper)
    except Exception as exc:
        msg = f"Failed to save llm_responses.json: {exc}"
        logger.warning(msg)
        errors.append(msg)

    return errors


def _serialisable_artifacts(artifacts: Any) -> list[str]:
    """Return artifact names (keys) as a list."""
    if isinstance(artifacts, dict):
        return list(artifacts.keys())
    return []
