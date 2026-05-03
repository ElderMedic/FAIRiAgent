"""Tests for DeepSeek provider wiring."""

from types import SimpleNamespace

import pytest

from fairifier.config import FAIRifierConfig, apply_env_overrides
from fairifier.utils.llm_helper import LLMHelper


def test_deepseek_provider_uses_deepseek_api_key_alias(monkeypatch):
    """DeepSeek should accept DEEPSEEK_API_KEY when LLM_API_KEY is unset."""
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test-key")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("FAIRIFIER_LLM_MODEL", raising=False)

    cfg = FAIRifierConfig()
    apply_env_overrides(cfg)

    assert cfg.llm_provider == "deepseek"
    assert cfg.llm_api_key == "sk-deepseek-test-key"
    assert cfg.llm_model == "deepseek-v4-pro"
    assert cfg.llm_base_url == "https://api.deepseek.com"


def test_deepseek_provider_default_base_url(monkeypatch):
    """DeepSeek should default to api.deepseek.com when base_url is the Ollama default."""
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.delenv("FAIRIFIER_LLM_MODEL", raising=False)

    cfg = FAIRifierConfig()
    apply_env_overrides(cfg)

    assert cfg.llm_provider == "deepseek"
    assert cfg.llm_base_url == "https://api.deepseek.com"


def test_deepseek_custom_base_url(monkeypatch):
    """DeepSeek should respect DEEPSEEK_API_BASE_URL override."""
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_API_BASE_URL", "https://custom-deepseek.example.com")
    monkeypatch.delenv("FAIRIFIER_LLM_MODEL", raising=False)

    cfg = FAIRifierConfig()
    apply_env_overrides(cfg)

    assert cfg.llm_base_url == "https://custom-deepseek.example.com"


@pytest.mark.anyio
async def test_deepseek_thinking_enabled_extra_body(monkeypatch):
    """DeepSeek should pass thinking.type=enabled when thinking is on."""

    class DummyLLM:
        def __init__(self):
            self.bind_calls = []
            self.ainvoke_calls = []

        def bind(self, **kwargs):
            self.bind_calls.append(kwargs)
            return self

        async def ainvoke(self, messages, config=None):
            self.ainvoke_calls.append({"messages": messages, "config": config})
            return SimpleNamespace(content="OK")

    from fairifier.config import config

    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "deepseek"
    helper.model = "deepseek-v4-pro"
    helper.llm = DummyLLM()
    helper._langfuse_handler = None
    helper._log_llm_response = lambda *args, **kwargs: None

    monkeypatch.setattr(config, "llm_enable_thinking", True)

    result = await helper._call_llm(["hello"], operation_name="test-deepseek")

    assert result.content == "OK"
    assert helper.llm.bind_calls == [
        {"extra_body": {"thinking": {"type": "enabled"}}, "reasoning_effort": "high"}
    ]
    assert len(helper.llm.ainvoke_calls) == 1


@pytest.mark.anyio
async def test_deepseek_thinking_disabled_extra_body(monkeypatch):
    """DeepSeek should pass thinking.type=disabled when thinking is off."""

    class DummyLLM:
        def __init__(self):
            self.bind_calls = []
            self.ainvoke_calls = []

        def bind(self, **kwargs):
            self.bind_calls.append(kwargs)
            return self

        async def ainvoke(self, messages, config=None):
            self.ainvoke_calls.append({"messages": messages, "config": config})
            return SimpleNamespace(content="OK")

    from fairifier.config import config

    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "deepseek"
    helper.model = "deepseek-v4-flash"
    helper.llm = DummyLLM()
    helper._langfuse_handler = None
    helper._log_llm_response = lambda *args, **kwargs: None

    monkeypatch.setattr(config, "llm_enable_thinking", False)

    result = await helper._call_llm(["hello"], operation_name="test-deepseek")

    assert result.content == "OK"
    assert helper.llm.bind_calls == [
        {"extra_body": {"thinking": {"type": "disabled"}}}
    ]
    assert len(helper.llm.ainvoke_calls) == 1


@pytest.mark.anyio
async def test_deepseek_falls_back_to_plain_invoke(monkeypatch):
    """DeepSeek should fall back to plain invoke when thinking bind fails."""

    class DummyLLM:
        def __init__(self):
            self.bind_calls = []
            self.ainvoke_calls = []

        def bind(self, **kwargs):
            self.bind_calls.append(kwargs)
            if "extra_body" in kwargs:
                raise ValueError("thinking not supported by this model")
            return self

        async def ainvoke(self, messages, config=None):
            self.ainvoke_calls.append({"messages": messages, "config": config})
            return SimpleNamespace(content="fallback OK")

    from fairifier.config import config

    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "deepseek"
    helper.model = "deepseek-chat"
    helper.llm = DummyLLM()
    helper._langfuse_handler = None
    helper._log_llm_response = lambda *args, **kwargs: None

    monkeypatch.setattr(config, "llm_enable_thinking", True)

    result = await helper._call_llm(["hello"], operation_name="test-deepseek-fallback")

    assert result.content == "fallback OK"
    # First call: bind with thinking (fails). Then fallback: direct ainvoke.
    assert len(helper.llm.ainvoke_calls) == 1
