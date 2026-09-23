"""Pre-flight treats missing local embeddings as a warning."""

import builtins

from fairifier.cli import _check_llm_preflight, _check_semantic_embedder_preflight
from fairifier.config import config


def test_semantic_preflight_warns_without_sentence_transformers(monkeypatch):
    monkeypatch.setattr(config, "semantic_index_enabled", True)
    monkeypatch.setattr(config, "retrieval_embedding_backend", "local")
    monkeypatch.setattr(config, "jina_api_key", "")
    monkeypatch.setattr(config, "retrieval_embedding_base_url", "")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers" or name.startswith("sentence_transformers."):
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    installed, message = _check_semantic_embedder_preflight()

    assert installed is False
    assert "lexical retrieval still runs" in message


def test_llm_preflight_rejects_a_cloud_provider_left_on_ollama(monkeypatch):
    monkeypatch.setattr(config, "llm_provider", "zhipu")
    monkeypatch.setattr(config, "llm_model", "glm-5.2")
    monkeypatch.setattr(config, "llm_base_url", "http://host.docker.internal:11434")

    ok, message = _check_llm_preflight()

    assert ok is False
    assert "host.docker.internal" in message


def test_llm_preflight_reports_the_resolved_cloud_endpoint(monkeypatch):
    monkeypatch.setattr(config, "llm_provider", "deepseek")
    monkeypatch.setattr(config, "llm_model", "deepseek-v4-pro")
    monkeypatch.setattr(config, "llm_base_url", "https://api.deepseek.com")

    ok, message = _check_llm_preflight()

    assert ok is True
    assert "https://api.deepseek.com" in message
