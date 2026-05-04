"""Context usage observability (P2 §6 of architecture refactor).

Records the token cost of state passed to each agent at runtime — write-only
monitoring; never trims or modifies state. This gives operators visibility
into where context budget is going (and an early warning before model context
limits are hit) without ever silently dropping domain content.

Per refactor plan §6: completeness > efficiency for metadata extraction.
A trimmed evidence packet may be the only source for a required FAIR-DS field.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# State fields whose token cost is worth tracking (the rest — scalars, paths,
# session IDs — are too small to be interesting for budget analysis).
_TRACKED_FIELDS = (
    "document_info",
    "document_info_by_source",
    "evidence_packets",
    "retrieved_knowledge",
    "metadata_fields",
    "selected_packages",
    "metadata_gap_hints",
    "inferred_metadata_extensions",
    "api_capabilities",
    "retrieval_cache",
    "validation_results",
    "execution_history",
    "execution_plan",
    "plan_tasks",
    "context",
    "agent_guidance",
    "react_scratchpad",
    "human_interventions",
    "document_content",  # transient fallback only; should be small / None
)


# Lazily-initialized tiktoken encoder (cl100k_base is a reasonable default
# tokenizer; works for GPT-4-class models and is close enough for estimation).
_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is not None:
        return _encoder
    try:
        import tiktoken  # type: ignore

        _encoder = tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - defensive
        _encoder = False  # sentinel: encoder unavailable
    return _encoder


def estimate_tokens(value: Any) -> int:
    """Estimate the token count of a value.

    For dicts/lists, serializes to JSON first (the form most often sent to
    LLMs). For strings, counts directly. Scalars return ~1 token.

    Falls back to a chars/4 heuristic if tiktoken is unavailable.
    """
    if value is None:
        return 0
    if isinstance(value, str):
        return _count_str(value)
    if isinstance(value, (int, float, bool)):
        return 1
    try:
        text = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    return _count_str(text)


def _count_str(text: str) -> int:
    if not text:
        return 0
    enc = _get_encoder()
    if enc is False or enc is None:
        # 1 token ~= 4 characters of English text on average.
        return max(1, len(text) // 4)
    return len(enc.encode(text))


def estimate_state_usage(state: Dict[str, Any]) -> Dict[str, Any]:
    """Return a per-field token-cost breakdown of the live state.

    Result shape::

        {
            "fields": {"document_info": 120, "evidence_packets": 1840, ...},
            "total": 5400,
        }

    Only metadata-bearing fields are included (see ``_TRACKED_FIELDS``).
    """
    fields: Dict[str, int] = {}
    total = 0
    for key in _TRACKED_FIELDS:
        if key not in state:
            continue
        value = state.get(key)
        cost = estimate_tokens(value)
        fields[key] = cost
        total += cost
    return {"fields": fields, "total": total}


def log_context_usage(
    agent_name: str,
    state: Dict[str, Any],
    *,
    log_path: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record per-field token usage at an agent boundary.

    Writes a single JSONL line to ``log_path`` (typically the run's
    ``processing_log.jsonl``) and emits a debug log record. NEVER modifies
    ``state``.

    Returns the usage record so callers may inspect it (e.g. for tests or
    early-warning logic), but the function is fundamentally side-effect-only.
    """
    usage = estimate_state_usage(state)
    record = {
        "event": "context_usage",
        "agent": agent_name,
        "timestamp": datetime.now().isoformat(),
        "total_tokens": usage["total"],
        "fields": usage["fields"],
    }
    if extra:
        record.update(extra)

    logger.debug(
        "context_usage agent=%s total=%d top=%s",
        agent_name,
        usage["total"],
        sorted(usage["fields"].items(), key=lambda kv: kv[1], reverse=True)[:3],
    )

    if log_path:
        try:
            path = Path(log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:  # pragma: no cover - defensive
            logger.debug("Failed to write context_usage log to %s: %s", log_path, exc)

    return record
