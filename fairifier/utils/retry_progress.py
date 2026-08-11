"""Model-independent progress tracking for Critic-driven retries.

The retry controller must distinguish a useful revision from another call to
the same model.  This module deliberately uses deterministic state summaries;
it does not ask an LLM to summarize the previous attempt.  That keeps retry
decisions comparable across providers and makes the decision auditable.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Sequence


_VOLATILE_KEYS = {
    "timestamp",
    "start_time",
    "end_time",
    "processing_start",
    "processing_end",
    "trace_id",
    "run_id",
}


def _stable_value(value: Any) -> Any:
    """Return a JSON-safe value with volatile bookkeeping removed."""
    if isinstance(value, Mapping):
        return {
            str(key): _stable_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_stable_value(item) for item in value]
    if isinstance(value, set):
        return sorted(_stable_value(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _agent_output_payload(agent_name: str, state: Mapping[str, Any]) -> Dict[str, Any]:
    """Select the output-bearing state for an agent, excluding retry metadata."""
    payloads = {
        "DocumentParser": {
            "document_info": state.get("document_info", {}),
            "evidence_packets": state.get("evidence_packets", []),
        },
        "KnowledgeRetriever": {
            "selected_packages": state.get("selected_packages", []),
            "retrieved_knowledge": state.get("retrieved_knowledge", []),
            "metadata_gap_hints": state.get("metadata_gap_hints", []),
        },
        "JSONGenerator": {
            "metadata_fields": state.get("metadata_fields", []),
            "metadata_json": (state.get("artifacts", {}) or {}).get("metadata_json"),
        },
        "BioMetadataAgent": {
            "bio_metadata": state.get("bio_metadata", {}),
            "evidence_packets": state.get("evidence_packets", []),
            "confidence_scores": state.get("confidence_scores", {}),
        },
        "ISAValueMapper": {
            "metadata_fields": state.get("metadata_fields", []),
            "artifacts": state.get("artifacts", {}),
        },
    }
    return payloads.get(
        agent_name,
        {
            key: value
            for key, value in state.items()
            if key not in {"context", "execution_history", "retry_trajectory"}
        },
    )


def capture_agent_output(agent_name: str, state: Mapping[str, Any]) -> Dict[str, Any]:
    """Capture mutable output fields so a worse retry can be rolled back."""
    payload = _agent_output_payload(agent_name, state)
    return deepcopy(payload)


def restore_agent_output(
    agent_name: str,
    state: Dict[str, Any],
    snapshot: Mapping[str, Any],
) -> None:
    """Restore only the output fields owned by an agent."""
    if agent_name == "DocumentParser":
        state["document_info"] = deepcopy(snapshot.get("document_info", {}))
        state["evidence_packets"] = deepcopy(snapshot.get("evidence_packets", []))
    elif agent_name == "KnowledgeRetriever":
        for key in ("selected_packages", "retrieved_knowledge", "metadata_gap_hints"):
            state[key] = deepcopy(snapshot.get(key, []))
    elif agent_name == "JSONGenerator":
        state["metadata_fields"] = deepcopy(snapshot.get("metadata_fields", []))
        artifacts = state.setdefault("artifacts", {})
        if "metadata_json" in snapshot:
            artifacts["metadata_json"] = deepcopy(snapshot.get("metadata_json"))
    elif agent_name == "BioMetadataAgent":
        for key in ("bio_metadata", "evidence_packets", "confidence_scores"):
            state[key] = deepcopy(snapshot.get(key, {} if key != "evidence_packets" else []))
    elif agent_name == "ISAValueMapper":
        state["metadata_fields"] = deepcopy(snapshot.get("metadata_fields", []))
        state["artifacts"] = deepcopy(snapshot.get("artifacts", {}))


def is_better_candidate(
    score: float,
    issues_count: int,
    best: Mapping[str, Any] | None,
) -> bool:
    """Choose the best evaluated candidate without replacing quality by length."""
    if not best:
        return True
    return (float(score), -int(issues_count)) > (
        float(best.get("score", 0.0) or 0.0),
        -int(best.get("issues_count", 0) or 0),
    )


def _compact_summary(value: Any, limit: int = 700) -> str:
    rendered = json.dumps(_stable_value(value), ensure_ascii=False, sort_keys=True)
    return rendered if len(rendered) <= limit else rendered[:limit] + "..."


def output_fingerprint(agent_name: str, state: Mapping[str, Any]) -> str:
    """Hash the deterministic, agent-specific output snapshot."""
    encoded = json.dumps(
        _stable_value(_agent_output_payload(agent_name, state)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def output_summary(agent_name: str, state: Mapping[str, Any]) -> str:
    """Return a bounded audit summary of the output snapshot."""
    return _compact_summary(_agent_output_payload(agent_name, state))


def _normalize_issue(issue: Any) -> str:
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", str(issue or "").lower())
    text = re.sub(r"[^a-z0-9_<>]+", " ", text)
    return " ".join(text.split())


def issue_signature(issues: Iterable[Any]) -> List[str]:
    """Return stable normalized issue identifiers for comparisons and audit."""
    return sorted({normalized for normalized in (_normalize_issue(i) for i in issues) if normalized})


def _issue_similarity(left: Sequence[str], right: Sequence[str]) -> float:
    left_set, right_set = set(left), set(right)
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def classify_retry_progress(
    history: Sequence[Mapping[str, Any]],
    current: Mapping[str, Any],
    min_score_delta: float = 0.02,
) -> Dict[str, Any]:
    """Classify the current attempt relative to the retry trajectory.

    ``improved`` means the output changed and either the score improved by the
    configured material amount or the critic reported materially fewer issues.
    ``stagnant`` means the output is unchanged or the same issues remain without
    a material score gain. ``oscillating`` catches A -> B -> A output cycles.
    """
    if not history:
        return {
            "status": "initial",
            "score_delta": None,
            "same_output": False,
            "repeated_issue": False,
            "feedback_applied": None,
            "issue_similarity": None,
        }

    previous = history[-1]
    score_delta = float(current.get("score", 0.0) or 0.0) - float(
        previous.get("score", 0.0) or 0.0
    )
    same_output = current.get("output_fingerprint") == previous.get("output_fingerprint")
    current_issues = current.get("issue_signature", [])
    previous_issues = previous.get("issue_signature", [])
    similarity = _issue_similarity(current_issues, previous_issues)
    repeated_issue = similarity >= 0.5 or (
        bool(set(current_issues) & set(previous_issues))
        and bool(current_issues)
    )
    oscillating = any(
        item.get("output_fingerprint") == current.get("output_fingerprint")
        for item in history[:-1]
    )
    issue_count_improved = len(current_issues) < len(previous_issues)

    if oscillating:
        status = "oscillating"
    elif same_output and repeated_issue:
        status = "stagnant"
    elif score_delta >= min_score_delta or (issue_count_improved and score_delta >= 0):
        status = "improved"
    elif score_delta < -min_score_delta:
        status = "regressed"
    elif same_output or repeated_issue:
        status = "stagnant"
    else:
        status = "changed_no_quality_gain"

    return {
        "status": status,
        "score_delta": round(score_delta, 4),
        "same_output": same_output,
        "repeated_issue": repeated_issue,
        "feedback_applied": not same_output,
        "issue_similarity": round(similarity, 4),
    }


def build_retry_observation(
    agent_name: str,
    state: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    min_score_delta: float = 0.02,
) -> Dict[str, Any]:
    """Build one deterministic trajectory item for an evaluated attempt."""
    current = {
        "agent_name": agent_name,
        "output_fingerprint": output_fingerprint(agent_name, state),
        "output_summary": output_summary(agent_name, state),
        "issue_signature": issue_signature(
            evaluation.get("issues", []) or evaluation.get("improvement_ops", [])
        ),
        "score": float(evaluation.get("score", 0.0) or 0.0),
    }
    current.update(classify_retry_progress(history, current, min_score_delta))
    current.update(
        {
            "attempt": len(history) + 1,
            "decision": evaluation.get("decision", "ESCALATE"),
            "issues_count": len(evaluation.get("issues", []) or []),
        }
    )
    return current


def should_stop_for_no_progress(
    trajectory: Sequence[Mapping[str, Any]],
    stagnant_limit: int = 1,
) -> str | None:
    """Return a terminal reason when another retry is unlikely to help."""
    if not trajectory:
        return None
    current = trajectory[-1]
    status = current.get("status")
    if status in {"oscillating", "stagnant"}:
        return "oscillation" if status == "oscillating" else "stagnation"
    if status == "regressed":
        recent = trajectory[-(stagnant_limit + 1) :]
        if len(recent) >= stagnant_limit + 1 and all(
            item.get("status") in {"regressed", "stagnant"} for item in recent
        ):
            return "repeated_regression"
    return None


def build_retry_contract(
    evaluation: Mapping[str, Any],
    observation: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Convert critique into explicit, machine-auditable retry obligations."""
    issues = [str(item) for item in (evaluation.get("issues", []) or []) if item]
    suggestions = [
        str(item)
        for item in (
            evaluation.get("improvement_ops", []) or evaluation.get("suggestions", [])
        )
        if item
    ]
    verification = [
        "The next output must be materially different from the failed output.",
        "Re-check every must_change item before returning the result.",
    ]
    if observation and observation.get("status") in {"stagnant", "oscillating"}:
        verification.append(
            "Do not repeat the prior output structure or the repeated issue pattern."
        )
    return {
        "must_change": suggestions[:10],
        "must_not_repeat": issues[:10],
        "verification": verification,
        "previous_output_fingerprint": observation.get("output_fingerprint")
        if observation
        else None,
        "progress_status": observation.get("status") if observation else None,
    }
