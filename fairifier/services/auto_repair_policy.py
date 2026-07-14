"""Policy helpers for automatic semantic repair and retrieval mode selection."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


RETRIEVAL_MODES = {"auto", "shadow", "tuned"}

LINKAGE_FIELDS = {
    "investigation identifier",
    "study identifier",
    "assay identifier",
    "sample identifier",
    "observation unit identifier",
    "biological material id",
    "assay identifier reference",
    "sample derived from",
    "same as",
}


def normalize_field(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def normalize_retrieval_mode(value: Any, default: str = "auto") -> str:
    mode = str(value or default).strip().lower()
    return mode if mode in RETRIEVAL_MODES else default


def effective_retrieval_mode(config: Any) -> str:
    """Return the active retrieval mode while preserving legacy shadow config."""
    mode = normalize_retrieval_mode(getattr(config, "retrieval_mode", "auto"))
    if mode in RETRIEVAL_MODES:
        return mode
    if bool(getattr(config, "retrieval_shadow_mode", False)):
        return "shadow"
    return "auto"


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def is_linkage_field(field_name: str) -> bool:
    normalized = normalize_field(field_name)
    return normalized in LINKAGE_FIELDS or normalized.endswith(" identifier")


def repair_rule_score(row: Dict[str, Any]) -> Tuple[int, List[str]]:
    """Score whether a field should be sent to semantic repair."""
    score = 0
    reasons: List[str] = []

    field_status = str(row.get("field_status") or row.get("shadow_status") or "").lower()
    field_score = as_float(row.get("field_score", row.get("shadow_score", 0.0)))
    lexical_hits = as_int(row.get("lexical_hit_count"))
    semantic_hits = as_int(row.get("semantic_hit_count"))
    score_delta = as_float(row.get("score_delta"))

    if field_status == "missing":
        score += 3
        reasons.append("missing_field")
    elif field_status == "wrong":
        score += 2
        reasons.append("wrong_field")
    elif field_score and field_score < 0.5:
        score += 1
        reasons.append("low_field_score")

    if lexical_hits == 0 and semantic_hits > 0:
        score += 3
        reasons.append("lexical_miss_semantic_hit")
    elif semantic_hits > lexical_hits:
        score += 1
        reasons.append("semantic_has_more_evidence")

    if score_delta >= 0.2:
        score += 2
        reasons.append("paired_run_tuned_improved")
    elif score_delta <= -0.2:
        score -= 3
        reasons.append("paired_run_tuned_regressed")

    if is_linkage_field(str(row.get("field") or "")):
        score -= 2
        reasons.append("linkage_field_guard")

    return score, reasons


def should_semantic_repair(row: Dict[str, Any], threshold: int = 4) -> Tuple[bool, int, List[str]]:
    score, reasons = repair_rule_score(row)
    return score >= threshold, score, reasons


def guard_patch_acceptance(row: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Conservative FAIR-DS/ISA guard for accepting a semantic repair patch."""
    failures: List[str] = []
    schema_delta = as_float(row.get("schema_delta"))
    row_alignment_delta = as_float(row.get("row_alignment_f1_delta"))
    extra_delta = as_float(row.get("extra_fields_delta"))
    value_score = as_float(row.get("value_score", row.get("tuned_score", 1.0)), default=1.0)
    score_delta = as_float(row.get("score_delta"))

    if schema_delta < -0.05:
        failures.append("schema_regression")
    if row_alignment_delta < -0.05 and is_linkage_field(str(row.get("field") or "")):
        failures.append("linkage_row_alignment_regression")
    if extra_delta > 25 and score_delta < 0.4:
        failures.append("extra_field_expansion_without_strong_gain")
    if value_score < 0.5:
        failures.append("weak_value_score")

    return not failures, failures


def fallback_decision(row: Dict[str, Any]) -> Dict[str, Any]:
    repair, score, reasons = should_semantic_repair(row)
    guard_ok, guard_failures = guard_patch_acceptance(row)
    return {
        "decision": "semantic_repair" if repair else "keep_shadow",
        "repair_score": score,
        "repair_reasons": reasons,
        "guard_ok": guard_ok,
        "guard_failures": guard_failures,
        "accept_patch": bool(repair and guard_ok),
    }


def auto_prompt_decision(
    *,
    field_name: str,
    lexical_hit_count: int,
    semantic_hit_count: int,
    mode: str,
    adaptive_lexical: bool = True,
) -> Dict[str, Any]:
    """Choose which retrieval evidence can enter the prompt.

    Auto mode is structure-first: lexical evidence is preferred for the initial
    generation prompt. Semantic snippets enter only when lexical search misses,
    which is the lowest-risk subset of Tuned behavior seen in the A/B runs.
    """
    mode = normalize_retrieval_mode(mode)
    row = {
        "field": field_name,
        "field_status": "missing" if lexical_hit_count == 0 else "",
        "lexical_hit_count": lexical_hit_count,
        "semantic_hit_count": semantic_hit_count,
    }
    repair, repair_score, reasons = should_semantic_repair(row)

    if mode == "shadow":
        return {
            "prompt_mode": "shadow_lexical",
            "use_semantic_fallback": False,
            "repair_score": repair_score,
            "repair_reasons": reasons,
        }
    if mode == "tuned":
        return {
            "prompt_mode": "lexical_preferred" if adaptive_lexical and lexical_hit_count else "semantic_fallback",
            "use_semantic_fallback": not (adaptive_lexical and lexical_hit_count),
            "repair_score": repair_score,
            "repair_reasons": reasons,
        }
    if lexical_hit_count > 0:
        return {
            "prompt_mode": "auto_lexical",
            "use_semantic_fallback": False,
            "repair_score": repair_score,
            "repair_reasons": reasons,
        }
    return {
        "prompt_mode": "auto_semantic_fallback" if repair else "auto_no_evidence",
        "use_semantic_fallback": bool(repair),
        "repair_score": repair_score,
        "repair_reasons": reasons,
    }
