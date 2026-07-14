"""Deterministic auto-repair candidate detection for FAIR-DS metadata."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Tuple

from .auto_repair_policy import fallback_decision, normalize_field


MISSING_VALUE_MARKERS = {
    "",
    "not specified",
    "not provided",
    "not available",
    "unknown",
    "n/a",
    "na",
    "none",
}


def _knowledge_field_name(item: Dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(
        item.get("field_name")
        or item.get("name")
        or item.get("term")
        or metadata.get("name")
        or metadata.get("label")
        or ""
    ).strip()


def _knowledge_requirement(item: Dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    requirement = str(metadata.get("requirement") or item.get("requirement") or "").strip().upper()
    if requirement in {"MANDATORY", "RECOMMENDED", "OPTIONAL"}:
        return requirement
    if bool(metadata.get("required") or item.get("required")):
        return "MANDATORY"
    return "OPTIONAL"


def _knowledge_sheet(item: Dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(
        metadata.get("isa_sheet")
        or metadata.get("sheet")
        or item.get("isa_sheet")
        or item.get("isa_level")
        or ""
    ).strip().lower()


def _metadata_field_name(item: Dict[str, Any]) -> str:
    return str(item.get("field_name") or item.get("name") or "").strip()


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    normalized = str(value).strip().lower()
    return normalized in MISSING_VALUE_MARKERS


def _best_existing_field(fields: List[Dict[str, Any]], field_name: str) -> Dict[str, Any]:
    normalized = normalize_field(field_name)
    candidates = [
        field for field in fields
        if normalize_field(_metadata_field_name(field)) == normalized
    ]
    if not candidates:
        return {}
    return max(candidates, key=lambda field: float(field.get("confidence") or 0.0))


def _build_knowledge_index(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _knowledge_field_name(item)
        if not name:
            continue
        key = normalize_field(name)
        index.setdefault(
            key,
            {
                "field": name,
                "requirement": _knowledge_requirement(item),
                "isa_sheet": _knowledge_sheet(item),
                "raw": item,
            },
        )
    return index


def _candidate_reason(existing: Dict[str, Any], requirement: str) -> Tuple[bool, str, float]:
    if not existing:
        return requirement in {"MANDATORY", "RECOMMENDED"}, "missing_field", 0.0
    confidence = float(existing.get("confidence") or 0.0)
    if _is_missing_value(existing.get("value")):
        return requirement in {"MANDATORY", "RECOMMENDED"}, "missing_value", confidence
    if confidence < 0.6:
        return True, "low_confidence", confidence
    if existing.get("status_reason") == "missing_source_reference":
        return True, "missing_source_reference", confidence
    return False, "ok", confidence


def generate_auto_repair_trace(state: Dict[str, Any]) -> Dict[str, Any]:
    """Build a deterministic repair trace without mutating metadata values."""
    retrieved_knowledge = [
        item for item in (state.get("retrieved_knowledge") or [])
        if isinstance(item, dict)
    ]
    metadata_fields = [
        item for item in (state.get("metadata_fields") or [])
        if isinstance(item, dict)
    ]
    retrieval_telemetry = state.get("retrieval_telemetry") or {}
    knowledge_index = _build_knowledge_index(retrieved_knowledge)

    candidates: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for key, info in sorted(knowledge_index.items()):
        field_name = info["field"]
        requirement = info["requirement"]
        existing = _best_existing_field(metadata_fields, field_name)
        should_consider, reason, confidence = _candidate_reason(existing, requirement)
        telemetry = retrieval_telemetry.get(key) if isinstance(retrieval_telemetry, dict) else {}
        if not isinstance(telemetry, dict):
            telemetry = {}
        row = {
            "field": field_name,
            "field_status": "missing" if reason in {"missing_field", "missing_value"} else reason,
            "field_score": confidence,
            "lexical_hit_count": int(telemetry.get("lexical_hit_count") or 0),
            "semantic_hit_count": int(telemetry.get("semantic_hit_count") or 0),
        }
        decision = fallback_decision(row)
        record = {
            "field": field_name,
            "normalized_field": key,
            "requirement": requirement,
            "isa_sheet": info.get("isa_sheet", ""),
            "reason": reason,
            "current_confidence": round(confidence, 4),
            "lexical_hit_count": row["lexical_hit_count"],
            "semantic_hit_count": row["semantic_hit_count"],
            "prompt_mode": telemetry.get("prompt_mode"),
            "retrieval_mode": telemetry.get("retrieval_mode"),
            "decision": decision["decision"],
            "accept_patch": decision["accept_patch"],
            "repair_score": decision["repair_score"],
            "repair_reasons": decision["repair_reasons"],
            "guard_ok": decision["guard_ok"],
            "guard_failures": decision["guard_failures"],
        }
        if should_consider and decision["decision"] == "semantic_repair":
            candidates.append(record)
        elif should_consider:
            skipped.append(record)

    trace = {
        "generated_at": datetime.now().isoformat(),
        "mode": "deterministic_trace",
        "summary": {
            "knowledge_fields": len(knowledge_index),
            "metadata_fields": len(metadata_fields),
            "candidate_count": len(candidates),
            "skipped_gap_count": len(skipped),
            "accepted_patch_count": 0,
            "metadata_mutated": False,
        },
        "candidates": candidates,
        "skipped_gaps": skipped[:100],
        "notes": [
            "This trace is diagnostic only; metadata.json values are not mutated by this node.",
            "Targeted semantic LLM patching must pass FAIR-DS/ISA guards before future acceptance.",
        ],
    }
    return trace


def serialize_auto_repair_trace(trace: Dict[str, Any]) -> str:
    return json.dumps(trace, indent=2, ensure_ascii=False)
