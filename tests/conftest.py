"""Pytest configuration and shared fixtures for FAIRiAgent tests."""

# Load test LLM env (Qwen API, qwen-flash) before any fairifier config import
import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    _env_test = Path(__file__).resolve().parent / ".env.test"
    if _env_test.exists():
        load_dotenv(_env_test, override=True)
except Exception:
    pass

# Tests must stay offline and deterministic even when developer shells export
# LangSmith credentials or tracing flags.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

import pytest

collect_ignore = [
    "test_mem0_v3.py",
    "test_mem0_v3_structure.py",
    "test_memory_cloud.py",
]


def _unwrap_traceable(target, attr_name: str) -> None:
    wrapped = getattr(target, attr_name, None)
    if wrapped is None:
        return
    original = getattr(wrapped, "__wrapped__", None)
    if original is not None:
        setattr(target, attr_name, original)


def _disable_langsmith_traceable_wrappers() -> None:
    try:
        from fairifier.agents.critic import CriticAgent
        from fairifier.agents.document_parser import (
            DocumentParserAgent,
        )
        from fairifier.agents.json_generator import (
            JSONGeneratorAgent,
        )
        from fairifier.agents.knowledge_retriever import (
            KnowledgeRetrieverAgent,
        )
        from fairifier.agents.validator import ValidationAgent
        from fairifier.services.mem0_service import Mem0Service
        from fairifier.utils.llm_helper import LLMHelper

        _unwrap_traceable(
            DocumentParserAgent, "execute"
        )
        _unwrap_traceable(
            KnowledgeRetrieverAgent, "execute"
        )
        _unwrap_traceable(
            JSONGeneratorAgent, "execute"
        )
        _unwrap_traceable(ValidationAgent, "execute")
        _unwrap_traceable(CriticAgent, "evaluate")
        _unwrap_traceable(
            CriticAgent, "evaluate_validation"
        )
        _unwrap_traceable(
            LLMHelper, "extract_document_info"
        )
        _unwrap_traceable(
            LLMHelper, "generate_metadata_value"
        )
        _unwrap_traceable(
            LLMHelper, "select_relevant_metadata_fields"
        )
        _unwrap_traceable(
            LLMHelper, "generate_complete_metadata"
        )
        _unwrap_traceable(
            LLMHelper, "evaluate_quality"
        )
        _unwrap_traceable(Mem0Service, "search")
        _unwrap_traceable(Mem0Service, "add")
        _unwrap_traceable(
            Mem0Service, "generate_memory_overview"
        )
    except Exception:
        pass


def pytest_configure(config):
    """Register custom markers."""
    _disable_langsmith_traceable_wrappers()
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )
