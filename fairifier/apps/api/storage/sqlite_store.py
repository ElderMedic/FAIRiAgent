"""SQLite-backed project storage."""

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import ProjectStore

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS projects (
    project_id  TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


class SQLiteProjectStore(ProjectStore):
    """Thread-safe SQLite implementation of ProjectStore."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            db_path, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute(_CREATE_TABLE)
            self._conn.commit()
        logger.info(
            "SQLiteProjectStore initialised (%s)", db_path
        )

    # ----------------------------------------------------------
    # Public API
    # ----------------------------------------------------------

    def create_project(
        self, project_id: str, data: Dict[str, Any]
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        data.setdefault("status", "pending")
        with self._lock:
            self._conn.execute(
                "INSERT INTO projects "
                "(project_id, data, status, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    project_id,
                    json.dumps(data, ensure_ascii=False),
                    data["status"],
                    now,
                    now,
                ),
            )
            self._conn.commit()

    def get_project(
        self, project_id: str
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM projects "
                "WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["data"])

    def update_project(
        self, project_id: str, data: Dict[str, Any]
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_project(project_id)
        if existing is None:
            raise KeyError(
                f"Project {project_id} not found"
            )
        existing.update(data)
        existing["updated_at"] = now
        status = existing.get("status", "pending")
        with self._lock:
            self._conn.execute(
                "UPDATE projects "
                "SET data = ?, status = ?, updated_at = ? "
                "WHERE project_id = ?",
                (
                    json.dumps(
                        existing, ensure_ascii=False
                    ),
                    status,
                    now,
                    project_id,
                ),
            )
            self._conn.commit()

    def list_projects(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM projects "
                "ORDER BY created_at DESC"
            ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def delete_project(self, project_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM projects "
                "WHERE project_id = ?",
                (project_id,),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
