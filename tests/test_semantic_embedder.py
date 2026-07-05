"""Regression tests for semantic embedder initialization failures."""

from __future__ import annotations

import fairifier.services.semantic_index as semantic_index_module
from fairifier.services.semantic_index import _encode_query, _get_embedder


def test_get_embedder_does_not_cache_failed_client(monkeypatch):
    semantic_index_module._EMBEDDER = None

    class BrokenClient:
        def initialize(self):
            raise RuntimeError("model load failed")

    monkeypatch.setattr(
        semantic_index_module,
        "EmbeddingClient",
        lambda **kwargs: BrokenClient(),
    )

    assert _get_embedder() is None
    assert semantic_index_module._EMBEDDER is None
    assert _get_embedder() is None


def test_encode_query_returns_none_when_embedder_unavailable(monkeypatch):
    semantic_index_module._EMBEDDER = None
    monkeypatch.setattr(semantic_index_module, "_get_embedder", lambda: None)
    assert _encode_query("sample query") is None


def test_resolve_embedding_vector_size_uses_probe_not_stale_config(monkeypatch):
    semantic_index_module._EMBEDDER = None

    class ProbeClient:
        def encode(self, texts, is_query=False):
            return [[0.1] * 768]

    monkeypatch.setattr(semantic_index_module, "_get_embedder", lambda: ProbeClient())
    monkeypatch.setattr(semantic_index_module.config, "retrieval_embedding_dims", 384)
    from fairifier.services.semantic_index import _resolve_embedding_vector_size

    assert _resolve_embedding_vector_size() == 768
