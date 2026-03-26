"""Helpers for per-run retrieval cache state."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, MutableMapping


def ensure_retrieval_cache(state: MutableMapping[str, Any]) -> Dict[str, Any]:
    """Ensure FAIRifier state contains a retrieval cache dictionary."""
    cache = state.setdefault("retrieval_cache", {})
    if not isinstance(cache, dict):
        cache = {}
        state["retrieval_cache"] = cache
    return cache


def get_cache_bucket(
    state_or_cache: MutableMapping[str, Any],
    bucket_name: str,
) -> Dict[str, Any]:
    """Return a named cache bucket under the per-run retrieval cache."""
    cache = ensure_retrieval_cache(state_or_cache)
    bucket = cache.setdefault(bucket_name, {})
    if not isinstance(bucket, dict):
        bucket = {}
        cache[bucket_name] = bucket
    return bucket


def make_cache_key(namespace: str, payload: Dict[str, Any]) -> str:
    """Build a deterministic cache key for tool requests."""
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def get_cached_value(cache_bucket: Dict[str, Any], cache_key: str) -> Any:
    """Return a defensive copy of a cached value if present."""
    if cache_key not in cache_bucket:
        return None
    return copy.deepcopy(cache_bucket[cache_key])


def store_cached_value(cache_bucket: Dict[str, Any], cache_key: str, value: Any) -> Any:
    """Store and return a defensive copy of the cached value."""
    cache_bucket[cache_key] = copy.deepcopy(value)
    return copy.deepcopy(value)
