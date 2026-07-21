"""Deterministic auto-repair candidate detection for FAIR-DS metadata."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .auto_repair_policy import (
    fallback_decision,
    guard_patch_acceptance,
    is_linkage_field,
    normalize_field,
)
from ..validation.metadata_json_format import (
    validate_field_datatypes,
    validate_json_structure,
    validate_source_grounding,
    validate_value_formats,
)


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

SINGLE_ROW_SHEETS = {"investigation", "study"}
DETERMINISTIC_PATCH_MIN_CONFIDENCE = 0.55


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


def _candidate_field_name(item: Dict[str, Any]) -> str:
    return str(
        item.get("field_name")
        or item.get("field_candidate")
        or item.get("name")
        or ""
    ).strip()


def _candidate_value(item: Dict[str, Any]) -> Any:
    return item.get("value") or item.get("extracted_value")


def _candidate_evidence(item: Dict[str, Any]) -> str:
    evidence = (
        item.get("evidence")
        or item.get("evidence_text")
        or item.get("supporting_evidence")
        or ""
    )
    return str(evidence).strip()


def _candidate_has_provenance(item: Dict[str, Any]) -> bool:
    provenance = item.get("provenance")
    return bool(
        item.get("source_id")
        or item.get("char_start") is not None
        or item.get("packet_id")
        or item.get("evidence_id")
        or (isinstance(provenance, dict) and provenance)
    )


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _candidate_summary(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        "field_name": _candidate_field_name(item),
        "value": _candidate_value(item),
        "confidence": round(_as_float(item.get("confidence"), 0.0), 4),
        "source_id": item.get("source_id"),
        "source_role": item.get("source_role"),
        "char_start": item.get("char_start"),
        "char_end": item.get("char_end"),
        "retrieval_method": item.get("retrieval_method"),
        "evidence": _candidate_evidence(item)[:500],
    }


def _classifier_shadow_prediction(
    predictions: Optional[Any],
    field_name: str,
) -> Dict[str, Any]:
    """Return an optional classifier prediction for trace-only comparison."""
    if not predictions:
        return {}
    key = normalize_field(field_name)
    prediction: Any = None
    if isinstance(predictions, dict):
        prediction = predictions.get(key) or predictions.get(field_name)
    elif isinstance(predictions, list):
        for item in predictions:
            if not isinstance(item, dict):
                continue
            item_field = str(
                item.get("field")
                or item.get("field_name")
                or item.get("name")
                or ""
            )
            if normalize_field(item_field) == key:
                prediction = item
                break
    if not isinstance(prediction, dict):
        return {}
    allowed = {
        "label",
        "decision",
        "probability",
        "score",
        "threshold",
        "model",
        "model_version",
        "features",
        "reasons",
    }
    return {name: prediction[name] for name in allowed if name in prediction}


def _candidate_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for collection_name in ("section_field_candidates", "evidence_packets"):
        for item in state.get(collection_name, []) or []:
            if isinstance(item, dict):
                records.append(item)

    by_field: Dict[str, Dict[str, Any]] = {}
    for item in records:
        field_name = _candidate_field_name(item)
        value = _candidate_value(item)
        if not field_name or _is_missing_value(value):
            continue
        key = normalize_field(field_name)
        confidence = _as_float(item.get("confidence"), 0.0)
        relevance = _as_float(item.get("relevance_score"), 0.0)
        provenance_bonus = 0.1 if _candidate_has_provenance(item) else 0.0
        score = confidence + relevance * 0.1 + provenance_bonus
        prior = by_field.get(key)
        if not prior or score > _as_float(prior.get("_auto_repair_rank"), 0.0):
            candidate = dict(item)
            candidate["_auto_repair_rank"] = score
            by_field[key] = candidate
    return by_field


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


def _requirement_bool(requirement: str) -> bool:
    return str(requirement or "").strip().upper() == "MANDATORY"


def _patch_field_payload(
    *,
    info: Dict[str, Any],
    candidate: Dict[str, Any],
    existing: Dict[str, Any],
) -> Dict[str, Any]:
    value = _candidate_value(candidate)
    confidence = min(0.95, max(_as_float(candidate.get("confidence"), 0.0), 0.65))
    raw = info.get("raw") if isinstance(info.get("raw"), dict) else {}
    raw_metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    requirement = str(info.get("requirement") or "OPTIONAL").upper()
    payload = deepcopy(existing) if existing else {}
    payload.update(
        {
            "field_name": existing.get("field_name") or info["field"],
            "value": str(value).strip(),
            "evidence": _candidate_evidence(candidate),
            "confidence": round(confidence, 4),
            "origin": "auto_repair",
            "status": "confirmed" if confidence >= 0.75 else "provisional",
            "status_reason": "auto_repaired_from_exact_section_candidate",
            "isa_sheet": info.get("isa_sheet") or existing.get("isa_sheet") or "study",
            "isa_level": info.get("isa_sheet") or existing.get("isa_level") or "study",
            "required": _requirement_bool(requirement),
            "requirement": requirement,
        }
    )
    if raw_metadata.get("package") or raw_metadata.get("package_source"):
        payload["package_source"] = raw_metadata.get("package_source") or raw_metadata.get(
            "package"
        )
    if existing.get("entity_id"):
        payload["entity_id"] = existing.get("entity_id")
    return payload


def _patch_fields_list(
    metadata_fields: List[Dict[str, Any]],
    *,
    field_name: str,
    patch_payload: Dict[str, Any],
) -> str:
    key = normalize_field(field_name)
    best_idx: Optional[int] = None
    best_confidence = -1.0
    for idx, field in enumerate(metadata_fields):
        if not isinstance(field, dict):
            continue
        if normalize_field(_metadata_field_name(field)) != key:
            continue
        confidence = _as_float(field.get("confidence"), 0.0)
        if best_idx is None or confidence > best_confidence:
            best_idx = idx
            best_confidence = confidence
    if best_idx is None:
        metadata_fields.append(patch_payload)
        return "appended"
    metadata_fields[best_idx].update(patch_payload)
    return "updated"


def _ensure_sheet_payload(isa_structure: Dict[str, Any], sheet: str) -> Any:
    if sheet not in isa_structure:
        isa_structure[sheet] = {"description": "", "fields": [], "columns": [], "rows": []}
    return isa_structure[sheet]


def _patch_flat_sheet_field(sheet_payload: Any, field_payload: Dict[str, Any]) -> bool:
    key = normalize_field(str(field_payload.get("field_name") or ""))
    if not key:
        return False
    if isinstance(sheet_payload, list):
        fields = sheet_payload
    elif isinstance(sheet_payload, dict):
        fields = sheet_payload.setdefault("fields", [])
    else:
        return False
    if not isinstance(fields, list):
        return False
    clean_payload = deepcopy(field_payload)
    clean_payload.pop("value", None)
    for idx, field in enumerate(fields):
        if isinstance(field, dict) and normalize_field(_metadata_field_name(field)) == key:
            merged = deepcopy(field)
            merged.update(clean_payload)
            merged.pop("value", None)
            fields[idx] = merged
            return True
    fields.append(clean_payload)
    return True


def _patch_matrix_sheet(sheet_payload: Any, field_payload: Dict[str, Any], sheet: str) -> bool:
    if not isinstance(sheet_payload, dict):
        return False
    field_name = str(field_payload.get("field_name") or "").strip()
    key = normalize_field(field_name)
    if not key:
        return False
    columns = sheet_payload.setdefault("columns", [])
    rows = sheet_payload.setdefault("rows", [])
    if not isinstance(columns, list) or not isinstance(rows, list):
        return False
    if key not in [normalize_field(col) for col in columns]:
        columns.append(key)
    if not rows and sheet in SINGLE_ROW_SHEETS:
        rows.append({})
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return False
    rows[0][key] = field_payload.get("value")
    return True


def _recompute_statistics(payload: Dict[str, Any]) -> None:
    isa_structure = payload.get("isa_structure")
    if not isinstance(isa_structure, dict):
        return
    total_fields = 0
    study_fields = 0
    confirmed_fields = 0
    provisional_fields = 0
    for sheet_name, sheet_data in isa_structure.items():
        if not isinstance(sheet_data, dict):
            continue
        fields = sheet_data.get("fields", [])
        if not isinstance(fields, list):
            continue
        for field in fields:
            if not isinstance(field, dict):
                continue
            total_fields += 1
            if sheet_name == "study":
                study_fields += 1
            conf = field.get("confidence")
            if isinstance(conf, (int, float)) and conf >= 0.8:
                confirmed_fields += 1
            else:
                provisional_fields += 1
    payload["statistics"] = {
        "total_fields": total_fields,
        "study_fields": study_fields,
        "confirmed_fields": confirmed_fields,
        "provisional_fields": provisional_fields,
    }


def _apply_auto_repair_patch(
    state: Dict[str, Any],
    field_payload: Dict[str, Any],
) -> Dict[str, Any]:
    artifacts = state.setdefault("artifacts", {})
    metadata_json = artifacts.get("metadata_json")
    if not metadata_json:
        return {"metadata_json_patched": False, "reason": "no_metadata_json"}
    try:
        payload = (
            json.loads(metadata_json)
            if isinstance(metadata_json, str)
            else deepcopy(metadata_json)
        )
    except (TypeError, json.JSONDecodeError):
        return {"metadata_json_patched": False, "reason": "metadata_json_parse_error"}
    if not isinstance(payload, dict):
        return {"metadata_json_patched": False, "reason": "metadata_json_not_object"}

    sheet = normalize_field(field_payload.get("isa_sheet") or "study").replace(" ", "")
    if sheet not in {"investigation", "study", "observationunit", "sample", "assay"}:
        sheet = "study"
    isa_structure = payload.setdefault("isa_structure", {})
    if not isinstance(isa_structure, dict):
        return {"metadata_json_patched": False, "reason": "isa_structure_not_object"}
    sheet_payload = _ensure_sheet_payload(isa_structure, sheet)
    flat_patched = _patch_flat_sheet_field(sheet_payload, field_payload)
    structure_matrix_patched = _patch_matrix_sheet(sheet_payload, field_payload, sheet)

    isa_values_patched = False
    isa_values = payload.get("isa_values")
    if isinstance(isa_values, dict):
        isa_values_sheet = isa_values.get(sheet)
        if isinstance(isa_values_sheet, dict):
            isa_values_patched = _patch_matrix_sheet(isa_values_sheet, field_payload, sheet)

    _recompute_statistics(payload)
    artifacts["metadata_json"] = json.dumps(payload, indent=2, ensure_ascii=False)

    isa_values_json = artifacts.get("isa_values") or artifacts.get("isa_values_json")
    if isa_values_json:
        try:
            values_payload = (
                json.loads(isa_values_json)
                if isinstance(isa_values_json, str)
                else deepcopy(isa_values_json)
            )
            if isinstance(values_payload, dict) and isinstance(
                values_payload.get(sheet),
                dict,
            ):
                if _patch_matrix_sheet(values_payload[sheet], field_payload, sheet):
                    values_str = json.dumps(
                        values_payload,
                        indent=2,
                        ensure_ascii=False,
                    )
                    artifacts["isa_values"] = values_str
                    artifacts["isa_values_json"] = values_str
                    isa_values_patched = True
        except (TypeError, json.JSONDecodeError):
            pass

    return {
        "metadata_json_patched": bool(flat_patched),
        "isa_structure_matrix_patched": bool(structure_matrix_patched),
        "isa_values_patched": bool(isa_values_patched),
    }


def _validate_patch_integrity(
    state: Dict[str, Any],
    field_payload: Dict[str, Any],
) -> Tuple[bool, List[str], Dict[str, Any]]:
    artifacts = state.get("artifacts") or {}
    metadata_json = artifacts.get("metadata_json")
    failures: List[str] = []
    details: Dict[str, Any] = {}

    try:
        payload = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
    except (TypeError, json.JSONDecodeError) as exc:
        return False, [f"metadata_json_parse_error:{exc}"], {}
    if not isinstance(payload, dict):
        return False, ["metadata_json_not_object"], {}

    errors: List[str] = []
    warnings: List[str] = []
    validate_json_structure(payload, errors, warnings)
    validate_field_datatypes(payload, errors, warnings)
    validate_value_formats(payload, errors, warnings)
    grounding = validate_source_grounding(payload, errors, warnings)

    sheet = normalize_field(field_payload.get("isa_sheet") or "study").replace(" ", "")
    field_name = str(field_payload.get("field_name") or "").strip()
    normalized_field = normalize_field(field_name)
    isa_structure = payload.get("isa_structure")
    if not isinstance(isa_structure, dict):
        errors.append("isa_structure_not_object")
    else:
        sheet_payload = isa_structure.get(sheet)
        if not isinstance(sheet_payload, dict):
            errors.append(f"patched_sheet_missing:{sheet}")
        else:
            fields = sheet_payload.get("fields")
            if not isinstance(fields, list):
                errors.append(f"patched_sheet_fields_not_array:{sheet}")
            elif not any(
                isinstance(item, dict)
                and normalize_field(_metadata_field_name(item)) == normalized_field
                for item in fields
            ):
                errors.append(f"patched_field_missing:{field_name}")
            rows = sheet_payload.get("rows")
            columns = sheet_payload.get("columns")
            if sheet in SINGLE_ROW_SHEETS:
                if not isinstance(columns, list) or normalized_field not in [
                    normalize_field(column) for column in columns
                ]:
                    errors.append(f"patched_matrix_column_missing:{field_name}")
                if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                    errors.append(f"patched_matrix_row_invalid:{sheet}")
                elif normalized_field not in rows[0]:
                    errors.append(f"patched_matrix_value_missing:{field_name}")

    isa_values_json = artifacts.get("isa_values_json")
    if isa_values_json:
        try:
            values_payload = (
                json.loads(isa_values_json)
                if isinstance(isa_values_json, str)
                else isa_values_json
            )
            if not isinstance(values_payload, dict):
                errors.append("isa_values_json_not_object")
        except (TypeError, json.JSONDecodeError) as exc:
            errors.append(f"isa_values_json_parse_error:{exc}")

    details.update(
        {
            "errors": errors,
            "warnings": warnings[:20],
            "source_grounding": grounding,
        }
    )
    failures.extend(errors)
    return not failures, failures, details


def _restore_patch_snapshot(
    state: Dict[str, Any],
    *,
    fields_snapshot: List[Any],
    artifact_snapshot: Dict[str, Any],
) -> None:
    state["metadata_fields"] = fields_snapshot
    artifacts = state.setdefault("artifacts", {})
    for key, value in artifact_snapshot.items():
        if value is None:
            artifacts.pop(key, None)
        else:
            artifacts[key] = value


def _deterministic_acceptance(
    *,
    field_name: str,
    isa_sheet: str,
    reason: str,
    candidate: Optional[Dict[str, Any]],
    existing: Dict[str, Any],
    min_candidate_confidence: float = DETERMINISTIC_PATCH_MIN_CONFIDENCE,
) -> Tuple[bool, List[str]]:
    failures: List[str] = []
    if is_linkage_field(field_name):
        failures.append("linkage_field_guard")
    sheet = normalize_field(isa_sheet).replace(" ", "")
    if sheet not in SINGLE_ROW_SHEETS:
        failures.append("multi_row_sheet_guard")
    if not isinstance(candidate, dict):
        failures.append("no_exact_field_candidate")
        return False, failures
    candidate_confidence = _as_float(candidate.get("confidence"), 0.0)
    if candidate_confidence < min_candidate_confidence:
        failures.append("weak_candidate_confidence")
    if _is_missing_value(_candidate_value(candidate)):
        failures.append("empty_candidate_value")
    if not _candidate_has_provenance(candidate):
        failures.append("missing_candidate_provenance")
    if not _candidate_evidence(candidate):
        failures.append("missing_candidate_evidence")
    if reason not in {
        "missing_field",
        "missing_value",
        "low_confidence",
        "missing_source_reference",
    }:
        failures.append("field_not_repairable")
    existing_confidence = _as_float(existing.get("confidence"), 0.0)
    if reason == "low_confidence" and existing_confidence >= candidate_confidence:
        failures.append("candidate_not_stronger_than_existing")

    guard_ok, guard_failures = guard_patch_acceptance(
        {
            "field": field_name,
            "value_score": candidate_confidence,
        }
    )
    if not guard_ok:
        failures.extend(guard_failures)
    return not failures, failures


def generate_auto_repair_trace(
    state: Dict[str, Any],
    *,
    apply_patches: bool = True,
    min_candidate_confidence: float = DETERMINISTIC_PATCH_MIN_CONFIDENCE,
    classifier_shadow_predictions: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build a deterministic repair trace and apply narrow exact-match patches."""
    retrieved_knowledge = [
        item for item in (state.get("retrieved_knowledge") or [])
        if isinstance(item, dict)
    ]
    raw_metadata_fields = state.setdefault("metadata_fields", [])
    metadata_fields = [item for item in raw_metadata_fields if isinstance(item, dict)]
    retrieval_telemetry = state.get("retrieval_telemetry") or {}
    knowledge_index = _build_knowledge_index(retrieved_knowledge)
    exact_candidates = _candidate_index(state)

    candidates: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    accepted_patches: List[Dict[str, Any]] = []
    rejected_patches: List[Dict[str, Any]] = []
    metadata_mutated = False

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
        exact_candidate = exact_candidates.get(key)
        patch_ok, patch_failures = _deterministic_acceptance(
            field_name=field_name,
            isa_sheet=info.get("isa_sheet", ""),
            reason=reason,
            candidate=exact_candidate,
            existing=existing,
            min_candidate_confidence=min_candidate_confidence,
        )
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
            "exact_candidate": _candidate_summary(exact_candidate),
            "patch_guard_ok": patch_ok,
            "patch_guard_failures": patch_failures,
        }
        classifier_prediction = _classifier_shadow_prediction(
            classifier_shadow_predictions,
            field_name,
        )
        if classifier_prediction:
            record["classifier_shadow_prediction"] = classifier_prediction
        if should_consider and (decision["decision"] == "semantic_repair" or exact_candidate):
            if patch_ok and exact_candidate:
                if apply_patches:
                    patch_payload = _patch_field_payload(
                        info=info,
                        candidate=exact_candidate,
                        existing=existing,
                    )
                    fields_snapshot = deepcopy(raw_metadata_fields)
                    artifact_snapshot = {
                        "metadata_json": state.setdefault("artifacts", {}).get(
                            "metadata_json"
                        ),
                        "isa_values_json": state.setdefault("artifacts", {}).get(
                            "isa_values_json"
                        ),
                    }
                    field_action = _patch_fields_list(
                        raw_metadata_fields,
                        field_name=field_name,
                        patch_payload=patch_payload,
                    )
                    metadata_fields = [
                        item for item in raw_metadata_fields if isinstance(item, dict)
                    ]
                    json_result = _patch_metadata_json(state, patch_payload)
                    validation_ok, validation_failures, validation_details = (
                        _validate_patch_integrity(state, patch_payload)
                    )
                    if validation_ok:
                        record.update(
                            {
                                "decision": "deterministic_patch",
                                "accept_patch": True,
                                "field_action": field_action,
                                "post_patch_validation": "passed",
                                **json_result,
                            }
                        )
                        accepted_patches.append(record)
                        metadata_mutated = True
                    else:
                        _restore_patch_snapshot(
                            state,
                            fields_snapshot=fields_snapshot,
                            artifact_snapshot=artifact_snapshot,
                        )
                        raw_metadata_fields = state["metadata_fields"]
                        metadata_fields = [
                            item for item in raw_metadata_fields if isinstance(item, dict)
                        ]
                        record.update(
                            {
                                "decision": "reject_deterministic_patch",
                                "accept_patch": False,
                                "field_action": field_action,
                                "post_patch_validation": "failed",
                                "patch_guard_ok": False,
                                "patch_guard_failures": validation_failures,
                                "post_patch_validation_details": validation_details,
                                **json_result,
                            }
                        )
                        rejected_patches.append(record)
                else:
                    record.update(
                        {
                            "decision": "trace_only_candidate",
                            "accept_patch": False,
                            "patch_guard_failures": ["trace_only_mode"],
                        }
                    )
            elif exact_candidate:
                record.update(
                    {
                        "decision": "reject_deterministic_patch",
                        "accept_patch": False,
                    }
                )
                rejected_patches.append(record)
            else:
                record["accept_patch"] = False
            candidates.append(record)
        elif should_consider:
            skipped.append(record)

    # §12.1: after accepted patches, recompile from one matrix and re-project
    # so metadata.json / sidecar share a single matrix_id.
    recompile_info: Dict[str, Any] = {"recompiled": False}
    if metadata_mutated and apply_patches:
        try:
            from ..utils.isa_matrix_projection import (
                extract_matrix_from_metadata,
                sync_compiled_matrix_to_state,
            )

            artifacts = state.setdefault("artifacts", {})
            matrix: Dict[str, Any] = {}
            sidecar = artifacts.get("isa_values_json")
            if sidecar:
                parsed = json.loads(sidecar) if isinstance(sidecar, str) else sidecar
                if isinstance(parsed, dict):
                    matrix = {
                        sheet: {
                            "columns": list((block or {}).get("columns") or []),
                            "rows": list((block or {}).get("rows") or []),
                        }
                        for sheet, block in parsed.items()
                        if isinstance(block, dict)
                    }
            if not matrix:
                meta = artifacts.get("metadata_json")
                payload = json.loads(meta) if isinstance(meta, str) else meta
                if isinstance(payload, dict):
                    matrix = extract_matrix_from_metadata(payload)
            if matrix:
                projected = sync_compiled_matrix_to_state(
                    state,
                    matrix,
                    recompile=True,
                    compiler_tag="auto_repair",
                )
                recompile_info = {
                    "recompiled": True,
                    "matrix_id": projected.get("matrix_id"),
                }
        except Exception as exc:  # noqa: BLE001 — repair must not fail closed on sync
            recompile_info = {"recompiled": False, "error": str(exc)}

    trace = {
        "generated_at": datetime.now().isoformat(),
        "mode": "deterministic_exact_patch",
        "summary": {
            "knowledge_fields": len(knowledge_index),
            "metadata_fields": len(metadata_fields),
            "candidate_count": len(candidates),
            "skipped_gap_count": len(skipped),
            "accepted_patch_count": len(accepted_patches),
            "rejected_patch_count": len(rejected_patches),
            "metadata_mutated": metadata_mutated,
            "apply_patches": apply_patches,
            "min_candidate_confidence": min_candidate_confidence,
            "classifier_shadow_prediction_count": sum(
                1 for item in candidates
                if isinstance(item, dict) and item.get("classifier_shadow_prediction")
            ),
            **recompile_info,
        },
        "candidates": candidates,
        "accepted_patches": accepted_patches,
        "rejected_patches": rejected_patches[:100],
        "skipped_gaps": skipped[:100],
        "notes": [
            (
                "Only exact FAIR-DS field-name candidates with source provenance "
                "are eligible for deterministic patching."
            ),
            (
                "Deterministic patches are limited to single-row sheets; "
                "linkage/id fields and multi-row sheets are guarded to avoid "
                "row-alignment regressions."
            ),
            (
                "After accepted patches, matrices are recompiled and projected "
                "so metadata.json and isa_values_json share one matrix_id."
            ),
            (
                "Targeted semantic LLM patching must pass FAIR-DS/ISA guards "
                "before future acceptance."
            ),
        ],
    }
    return trace


def serialize_auto_repair_trace(trace: Dict[str, Any]) -> str:
    return json.dumps(trace, indent=2, ensure_ascii=False)


def inject_auto_repair_summary(
    state: Dict[str, Any],
    trace: Dict[str, Any],
) -> bool:
    """Add a compact repair summary to metadata.json after accepted patches."""
    summary = trace.get("summary") if isinstance(trace.get("summary"), dict) else {}
    if int(summary.get("accepted_patch_count") or 0) <= 0:
        return False

    artifacts = state.setdefault("artifacts", {})
    metadata_json = artifacts.get("metadata_json")
    if not metadata_json:
        return False
    try:
        payload = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False

    accepted_fields = [
        {
            "field": item.get("field"),
            "isa_sheet": item.get("isa_sheet"),
            "field_action": item.get("field_action"),
            "post_patch_validation": item.get("post_patch_validation"),
        }
        for item in trace.get("accepted_patches", [])
        if isinstance(item, dict)
    ]
    payload["auto_repair_summary"] = {
        "mode": trace.get("mode"),
        "generated_at": trace.get("generated_at"),
        "accepted_patch_count": int(summary.get("accepted_patch_count") or 0),
        "rejected_patch_count": int(summary.get("rejected_patch_count") or 0),
        "candidate_count": int(summary.get("candidate_count") or 0),
        "metadata_mutated": bool(summary.get("metadata_mutated")),
        "apply_patches": bool(summary.get("apply_patches")),
        "accepted_fields": accepted_fields,
        "trace_artifact": "auto_repair_trace.json",
    }
    artifacts["metadata_json"] = json.dumps(payload, indent=2, ensure_ascii=False)
    return True
