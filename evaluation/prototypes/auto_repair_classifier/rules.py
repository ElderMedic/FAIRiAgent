"""Deterministic fallback policy for FAIRiAgent auto semantic repair."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


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


def normalize_field(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def is_linkage_field(field_name: str) -> bool:
    normalized = normalize_field(field_name)
    return normalized in LINKAGE_FIELDS or normalized.endswith(" identifier")


def repair_rule_score(row: Dict[str, Any]) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    shadow_status = str(row.get("shadow_status") or "").lower()
    shadow_score = as_float(row.get("shadow_score"))
    lexical_hits = as_int(row.get("lexical_hit_count"))
    semantic_hits = as_int(row.get("semantic_hit_count"))
    score_delta = as_float(row.get("score_delta"))

    if shadow_status == "missing":
        score += 3
        reasons.append("shadow_missing")
    elif shadow_status == "wrong":
        score += 2
        reasons.append("shadow_wrong")
    elif shadow_score < 0.5:
        score += 1
        reasons.append("low_shadow_score")

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


def should_repair(row: Dict[str, Any], threshold: int = 4) -> Tuple[bool, int, List[str]]:
    score, reasons = repair_rule_score(row)
    return score >= threshold, score, reasons


def guard_patch_acceptance(row: Dict[str, Any]) -> Tuple[bool, List[str]]:
    failures: List[str] = []
    schema_delta = as_float(row.get("schema_delta"))
    row_alignment_delta = as_float(row.get("row_alignment_f1_delta"))
    extra_delta = as_float(row.get("extra_fields_delta"))
    tuned_score = as_float(row.get("tuned_score"))
    score_delta = as_float(row.get("score_delta"))

    if schema_delta < -0.05:
        failures.append("schema_regression")
    if row_alignment_delta < -0.05 and is_linkage_field(str(row.get("field") or "")):
        failures.append("linkage_row_alignment_regression")
    if extra_delta > 25 and score_delta < 0.4:
        failures.append("extra_field_expansion_without_strong_gain")
    if tuned_score < 0.5:
        failures.append("weak_tuned_value_score")

    return not failures, failures


def fallback_decision(row: Dict[str, Any]) -> Dict[str, Any]:
    repair, score, reasons = should_repair(row)
    guard_ok, guard_failures = guard_patch_acceptance(row)
    return {
        "decision": "semantic_repair" if repair else "keep_shadow",
        "repair_score": score,
        "repair_reasons": reasons,
        "guard_ok": guard_ok,
        "guard_failures": guard_failures,
        "accept_patch": bool(repair and guard_ok),
    }
