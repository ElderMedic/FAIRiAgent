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
