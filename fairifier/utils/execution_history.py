"""Execution history compaction utilities.

The orchestrator appends one record per agent attempt to
``state["execution_history"]``. Each record contains a Critic evaluation with
verbose prose (``critique``), a full ``issues`` list, and ``improvement_ops`` /
``suggestions`` text. After multiple retries, this accumulates into tens of
KB of stale failure transcript carried in live state — anchoring the LLM to
its own earlier mistakes (the "echo chamber" anti-pattern; see
ARCHITECTURE_REFACTOR_PLAN.md §2.5).

Once an agent attempt is no longer the *latest* one (i.e. a new retry has
started), only its score, decision, and timing remain useful for the
confidence aggregator and the timeline report. Verbose fields are stripped.
The full transcript continues to be written to ``processing_log.jsonl`` for
audit purposes — this module only affects the in-memory state.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# Fields kept verbatim from the top-level execution record.
_TOP_LEVEL_KEYS = (
    "agent_name",
    "attempt",
    "start_time",
    "end_time",
    "success",
    "error",
)

# Fields kept from critic_evaluation. Everything else is dropped.
_KEPT_CRITIC_FIELDS = ("score", "decision")


def compact_execution_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a compact copy of an execution record with verbose fields stripped.

    Preserves: ``agent_name``, ``attempt``, ``start_time``, ``end_time``,
    ``success``, ``error`` (if present); and from ``critic_evaluation``:
    ``score``, ``decision``, plus a numeric ``issues_count`` summary.

    Drops: ``critique`` prose, full ``issues`` list, ``improvement_ops`` text,
    ``suggestions`` text, and any other LLM-generated fields.

    Idempotent — safe to call on already-compacted records.
    """
    if not isinstance(record, dict):
        return record

    out: Dict[str, Any] = {}
    for key in _TOP_LEVEL_KEYS:
        if key in record:
            out[key] = record[key]

    critic_eval = record.get("critic_evaluation")
    if isinstance(critic_eval, dict):
        compact_eval: Dict[str, Any] = {}
        for key in _KEPT_CRITIC_FIELDS:
            if key in critic_eval:
                compact_eval[key] = critic_eval[key]
        # Replace verbose issues list with a count.
        issues = critic_eval.get("issues")
        if isinstance(issues, list):
            compact_eval["issues_count"] = len(issues)
        elif "issues_count" in critic_eval:
            compact_eval["issues_count"] = critic_eval["issues_count"]
        out["critic_evaluation"] = compact_eval
    elif critic_eval is None and "critic_evaluation" in record:
        out["critic_evaluation"] = None

    return out


def compact_prior_attempts_for_agent(
    execution_history: list,
    agent_name: str,
    *,
    keep_latest: bool = True,
) -> int:
    """Compact prior-attempt records for ``agent_name`` in place.

    When the orchestrator starts retry N for an agent, the previous attempt
    (N-1) is no longer the source of truth — its full critic evaluation is
    no longer needed for routing. This function strips verbose fields from
    all but the latest record for the given agent.

    Args:
        execution_history: The mutable list at ``state["execution_history"]``.
        agent_name: Compact only records with this ``agent_name``.
        keep_latest: When True (default), the most recent record for the
            agent is left untouched; only earlier attempts are compacted.

    Returns:
        Number of records that were compacted.
    """
    if not isinstance(execution_history, list) or not execution_history:
        return 0

    indices = [
        i
        for i, rec in enumerate(execution_history)
        if isinstance(rec, dict) and rec.get("agent_name") == agent_name
    ]
    if keep_latest and indices:
        indices = indices[:-1]

    n = 0
    for i in indices:
        execution_history[i] = compact_execution_record(execution_history[i])
        n += 1
    return n
