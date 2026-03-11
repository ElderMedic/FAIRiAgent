"""Tests for optional Langfuse observability wiring."""

from fairifier.config import FAIRifierConfig, apply_env_overrides
from fairifier.utils.llm_helper import LLMHelper


def test_langfuse_enabled_with_keys(monkeypatch):
    """Langfuse should auto-enable when both keys are present."""
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.delenv("LANGFUSE_DISABLE", raising=False)

    cfg = FAIRifierConfig()
    apply_env_overrides(cfg)

    assert cfg.enable_langfuse is True
    assert cfg.langfuse_secret_key == "sk-test"
    assert cfg.langfuse_public_key == "pk-test"


def test_langfuse_disable_overrides_keys(monkeypatch):
    """LANGFUSE_DISABLE should force observability off."""
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_DISABLE", "1")

    cfg = FAIRifierConfig()
    apply_env_overrides(cfg)

    assert cfg.enable_langfuse is False


def test_build_run_config_returns_callbacks_when_handler_exists():
    """LLMHelper should return callbacks config when handler is available."""
    helper = LLMHelper.__new__(LLMHelper)
    marker = object()
    helper._langfuse_handler = marker

    run_config = helper._build_run_config()
    assert run_config == {"callbacks": [marker]}


def test_build_run_config_returns_none_without_handler():
    """LLMHelper should skip callback config when handler is missing."""
    helper = LLMHelper.__new__(LLMHelper)
    helper._langfuse_handler = None

    assert helper._build_run_config() is None
