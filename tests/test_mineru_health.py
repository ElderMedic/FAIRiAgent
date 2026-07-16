"""Tests for MinerU health probes."""

from unittest.mock import patch

from fairifier.services.mineru_health import (
    check_endpoint,
    dependency_errors_for_backend,
    dependency_install_hint_for_backend,
    summarize_mineru_health,
)


def test_summarize_needs_vlm_for_http_client():
    with patch("fairifier.services.mineru_health.cli_version", return_value=(True, "3.4.0")):
        with patch("fairifier.services.mineru_health.check_endpoint") as mock_check:
            mock_check.side_effect = [
                check_endpoint("mineru-api", "http://localhost:8000", default_port=8000),
                check_endpoint("vlm", "http://localhost:30000", default_port=30000),
            ]
            with patch("fairifier.services.mineru_health.probe_tcp", return_value=True):
                health = summarize_mineru_health(
                    cli_path="mineru",
                    vlm_url="http://localhost:30000",
                    api_url="http://localhost:8000",
                    backend="hybrid-http-client",
                )
    assert health["needs_vlm"] is True


def test_summarize_pipeline_skips_vlm_requirement():
    with patch("fairifier.services.mineru_health.cli_version", return_value=(True, "3.4.0")):
        with patch("fairifier.services.mineru_health.check_endpoint") as mock_check:
            mock_check.return_value = check_endpoint(
                "mineru-api", "http://localhost:8000", default_port=8000
            )
            with patch("fairifier.services.mineru_health.probe_tcp", return_value=True):
                health = summarize_mineru_health(
                    cli_path="mineru",
                    vlm_url=None,
                    api_url="http://localhost:8000",
                    backend="pipeline",
                )
    assert health["needs_vlm"] is False


def test_dependency_errors_for_pipeline_backend(monkeypatch):
    monkeypatch.setattr(
        "fairifier.services.mineru_health.importlib.util.find_spec",
        lambda name: None,
    )

    assert dependency_errors_for_backend("pipeline") == [
        "missing_python_module:doclayout_yolo"
    ]
    assert dependency_errors_for_backend("vlm-http-client") == []
    assert dependency_install_hint_for_backend("pipeline") == (
        "pip install 'mineru[pipeline]>=3.4.0,<4'"
    )


def test_summarize_pipeline_marks_missing_dependencies_not_ready(monkeypatch):
    monkeypatch.setattr(
        "fairifier.services.mineru_health.importlib.util.find_spec",
        lambda name: None,
    )
    with patch("fairifier.services.mineru_health.cli_version", return_value=(True, "3.4.0")):
        with patch("fairifier.services.mineru_health.check_endpoint") as mock_check:
            mock_check.return_value = check_endpoint(
                "mineru-api", None, default_port=8000
            )
            health = summarize_mineru_health(
                cli_path="mineru",
                vlm_url=None,
                api_url=None,
                backend="pipeline",
            )

    assert health["ready"] is False
    assert health["dependency_errors"] == ["missing_python_module:doclayout_yolo"]
    assert health["dependency_install_hint"] == (
        "pip install 'mineru[pipeline]>=3.4.0,<4'"
    )
