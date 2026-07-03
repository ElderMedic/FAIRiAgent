"""Shared Qdrant connection helpers for mem0 and semantic retrieval."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

logger = logging.getLogger(__name__)

_LOCAL_HOST_ALIASES = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def is_local_host(host: str) -> bool:
    return (host or "").strip().lower() in _LOCAL_HOST_ALIASES


def http_get_json(url: str, timeout_seconds: int = 2) -> Optional[Dict[str, Any]]:
    req = url if "://" in url else f"http://{url}"
    try:
        with urlopen(req, timeout=max(timeout_seconds, 1)) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return json.loads(payload) if payload else {}
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None


def is_http_endpoint_reachable(url: str, timeout_seconds: int = 2) -> bool:
    req = url if "://" in url else f"http://{url}"
    try:
        with urlopen(req, timeout=max(timeout_seconds, 1)) as response:
            return 200 <= getattr(response, "status", 200) < 500
    except HTTPError as exc:
        return 400 <= exc.code < 500
    except (URLError, TimeoutError):
        return False


def is_qdrant_available(host: str, port: int, timeout_seconds: int = 2) -> bool:
    return is_http_endpoint_reachable(
        f"http://{host}:{port}/collections",
        timeout_seconds=timeout_seconds,
    )


def docker_available() -> bool:
    try:
        check = subprocess.run(
            ["docker", "version"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
        )
        return check.returncode == 0
    except Exception:
        return False


def try_auto_start_qdrant(
    host: str,
    port: int,
    container_name: str,
    timeout_seconds: int = 20,
) -> bool:
    if not is_local_host(host):
        logger.warning(
            "Qdrant host '%s' is not local; auto-start skipped for safety.",
            host,
        )
        return False

    if not docker_available():
        logger.warning("Docker not available; cannot auto-start local Qdrant container.")
        return False

    resolved_name = container_name if port == 6333 else f"{container_name}-{port}"
    check_running = subprocess.run(
        ["docker", "ps", "--filter", f"name=^/{resolved_name}$", "--format", "{{.Names}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if resolved_name in check_running.stdout.splitlines():
        return True

    check_exists = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=^/{resolved_name}$", "--format", "{{.Names}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    if resolved_name in check_exists.stdout.splitlines():
        start_cmd = ["docker", "start", resolved_name]
    else:
        start_cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            resolved_name,
            "--restart",
            "unless-stopped",
            "-p",
            f"{port}:6333",
            "qdrant/qdrant:v1.13.0",
        ]

    start = subprocess.run(
        start_cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if start.returncode != 0:
        logger.warning(
            "Failed to auto-start Qdrant via Docker (%s): %s",
            " ".join(start_cmd),
            (start.stderr or start.stdout or "unknown error").strip().splitlines()[0],
        )
        return False

    deadline = time.time() + max(timeout_seconds, 1)
    while time.time() < deadline:
        if is_qdrant_available(host, port, timeout_seconds=2):
            logger.info("Auto-started local Qdrant container '%s' on port %s.", resolved_name, port)
            return True
        time.sleep(0.5)
    logger.warning("Qdrant container started but did not become healthy within %ss.", timeout_seconds)
    return False


def ensure_qdrant_available(
    host: str,
    port: int,
    *,
    auto_start: bool = True,
    container_name: str = "fairiagent-qdrant",
    healthcheck_timeout_seconds: int = 2,
) -> bool:
    """Return True when Qdrant responds; optionally auto-start a local container."""
    timeout = max(int(healthcheck_timeout_seconds or 2), 1)
    if is_qdrant_available(host, port, timeout_seconds=timeout):
        return True
    if not auto_start:
        return False
    return try_auto_start_qdrant(
        host=host,
        port=port,
        container_name=container_name,
        timeout_seconds=max(timeout * 6, 8),
    )
