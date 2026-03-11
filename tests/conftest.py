"""Pytest configuration and shared fixtures for FAIRiAgent tests."""

# Load test LLM env (Qwen API, qwen3.5-plus) before any fairifier config import
from pathlib import Path
try:
    from dotenv import load_dotenv
    _env_test = Path(__file__).resolve().parent / ".env.test"
    if _env_test.exists():
        load_dotenv(_env_test, override=True)
except Exception:
    pass

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )
