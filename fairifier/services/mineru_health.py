"""Shared MinerU CLI / mineru-api / VLM health probes."""

from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import requests


@dataclass
class MinerUEndpointStatus:
    """Reachability for one MinerU-related endpoint."""

    name: str
    url: Optional[str]
    tcp_reachable: bool
    http_ok: bool
    http_status: Optional[int]
    message: str


def probe_tcp(host: str, port: int, *, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_http(
    base_url: str,
    *,
    paths: Optional[List[str]] = None,
    timeout: float = 3.0,
) -> Tuple[bool, Optional[int], str]:
    """Try HTTP GET on *base_url* with candidate health paths."""
    if not base_url:
        return False, None, "URL not configured"
    candidates = paths or ["/health", "/docs", "/openapi.json", "/"]
    last_error = "no response"
    for path in candidates:
        url = f"{base_url.rstrip('/')}{path}"
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code < 500:
                return True, response.status_code, f"HTTP {response.status_code} on {path}"
        except requests.exceptions.RequestException as exc:
            last_error = str(exc)
    return False, None, last_error


def cli_version(cli_path: str, *, timeout: float = 5.0) -> Tuple[bool, str]:
    try:
        completed = subprocess.run(
            [cli_path, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return False, "CLI not found"
    except subprocess.TimeoutExpired:
        return True, "CLI present (version check timed out)"
    except OSError as exc:
        return False, str(exc)

    if completed.returncode == 0:
        return True, (completed.stdout or completed.stderr or "unknown").strip()
    return False, (completed.stderr or completed.stdout or "version check failed").strip()


def check_endpoint(
    name: str,
    url: Optional[str],
    *,
    default_port: int,
    http_paths: Optional[List[str]] = None,
) -> MinerUEndpointStatus:
    if not url:
        return MinerUEndpointStatus(
            name=name,
            url=None,
            tcp_reachable=False,
            http_ok=False,
            http_status=None,
            message="not configured",
        )

    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or default_port
    tcp_ok = probe_tcp(host, port)
    http_ok, status_code, http_msg = probe_http(url, paths=http_paths)

    if http_ok:
        message = http_msg
    elif tcp_ok:
        message = f"TCP open on {host}:{port} ({http_msg})"
    else:
        message = f"unreachable on {host}:{port}"

    return MinerUEndpointStatus(
        name=name,
        url=url,
        tcp_reachable=tcp_ok,
        http_ok=http_ok,
        http_status=status_code,
        message=message,
    )


def summarize_mineru_health(
    *,
    cli_path: str,
    vlm_url: Optional[str],
    api_url: Optional[str],
    backend: str,
    requires_vlm: bool = True,
) -> dict:
    """Return a structured health summary for CLI, mineru-api, and VLM endpoints."""
    cli_ok, cli_version_text = cli_version(cli_path)
    api_status = check_endpoint("mineru-api", api_url, default_port=8000)
    vlm_status = check_endpoint(
        "vlm",
        vlm_url,
        default_port=30000,
        http_paths=["/health", "/v1/models", "/models", "/"],
    )

    http_client_backends = ("vlm-http-client", "hybrid-http-client")
    needs_vlm = requires_vlm and any(token in backend for token in http_client_backends)

    ready = cli_ok
    if api_url:
        ready = ready and api_status.tcp_reachable
    if needs_vlm:
        ready = ready and vlm_status.tcp_reachable

    return {
        "ready": ready,
        "cli_ok": cli_ok,
        "cli_version": cli_version_text,
        "api": api_status,
        "vlm": vlm_status,
        "needs_vlm": needs_vlm,
    }
