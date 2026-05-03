"""Tests for Gemini provider wiring."""

from types import SimpleNamespace

import pytest

from fairifier.config import FAIRifierConfig, apply_env_overrides
from fairifier.utils.llm_helper import LLMHelper


def test_gemini_provider_uses_google_api_key_alias(monkeypatch):
    """Gemini should accept GOOGLE_API_KEY when LLM_API_KEY is unset."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-test-key")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("FAIRIFIER_LLM_MODEL", raising=False)

    cfg = FAIRifierConfig()
    apply_env_overrides(cfg)

    assert cfg.llm_provider == "gemini"
    assert cfg.llm_api_key == "google-test-key"
    assert cfg.llm_model == "gemini-3.1-pro-preview"
    assert cfg.llm_base_url is None


def test_google_provider_alias_normalizes_to_gemini(monkeypatch):
    """The user-facing 'google' alias should normalize to the gemini provider."""
    monkeypatch.setenv("LLM_PROVIDER", "google")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("FAIRIFIER_LLM_MODEL", raising=False)

    cfg = FAIRifierConfig()
    apply_env_overrides(cfg)

    assert cfg.llm_provider == "gemini"
    assert cfg.llm_api_key == "gemini-test-key"
    assert cfg.llm_model == "gemini-3.1-pro-preview"


@pytest.mark.anyio
async def test_gemini_thinking_budget_when_thinking_enabled(monkeypatch):
    """Gemini should pass thinking_budget when thinking is enabled."""

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
    helper.provider = "gemini"
    helper.model = "gemini-3.1-pro-preview"
    helper.llm = DummyLLM()
    helper._langfuse_handler = None
    helper._log_llm_response = lambda *args, **kwargs: None

    monkeypatch.setattr(config, "llm_enable_thinking", True)
    monkeypatch.setattr(config, "llm_thinking_budget", 2048)

    result = await helper._call_llm(["hello"], operation_name="test-gemini")

    assert result.content == "OK"
    assert helper.llm.bind_calls == [{"thinking_budget": 2048}]
    assert len(helper.llm.ainvoke_calls) == 1


@pytest.mark.anyio
async def test_gemini_thinking_disabled_no_bind(monkeypatch):
    """When thinking is disabled, Gemini should not bind extra parameters."""

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
    helper.provider = "gemini"
    helper.model = "gemini-2.0-flash"
    helper.llm = DummyLLM()
    helper._langfuse_handler = None
    helper._log_llm_response = lambda *args, **kwargs: None

    monkeypatch.setattr(config, "llm_enable_thinking", False)

    result = await helper._call_llm(["hello"], operation_name="test-gemini")

    assert result.content == "OK"
    assert helper.llm.bind_calls == []
    assert len(helper.llm.ainvoke_calls) == 1


def test_initialize_gemini_llm_uses_google_genai_client(monkeypatch):
    """Gemini initialization should use ChatGoogleGenerativeAI with Gemini key."""
    captured = {}

    class FakeChatGoogleGenerativeAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    from fairifier.config import config
    from fairifier.utils import llm_helper as llm_helper_module

    monkeypatch.setattr(llm_helper_module, "ChatGoogleGenerativeAI", FakeChatGoogleGenerativeAI)
    monkeypatch.setattr(config, "llm_api_key", "gemini-key")
    monkeypatch.setattr(config, "llm_temperature", 0.2)
    monkeypatch.setattr(config, "llm_max_tokens", 4096)

    helper = LLMHelper.__new__(LLMHelper)
    helper.provider = "gemini"
    helper.model = "gemini-3.1-pro-preview"

    model = helper._initialize_llm()

    assert isinstance(model, FakeChatGoogleGenerativeAI)
    assert captured["model"] == "gemini-3.1-pro-preview"
    assert captured["google_api_key"] == "gemini-key"
    assert captured["temperature"] == 0.2
    assert captured["max_output_tokens"] == 4096
