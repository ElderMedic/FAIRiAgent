"""Confidence aggregation helpers for FAIRifier workflow."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Dict, Any, List, Optional

from ..models import FAIRifierState
from ..config import FAIRifierConfig


@dataclass
class ConfidenceBreakdown:
    critic: float
    structural: float
    validation: float
    overall: float
    details: Dict[str, Any]


def aggregate_confidence(state: FAIRifierState, cfg: FAIRifierConfig) -> ConfidenceBreakdown:
    """Combine critic scores, structural metrics, and validation signal into one score."""
    critic_score, critic_details = _critic_component(state)
    structural_score, structural_details = _structural_component(state)
    validation_score, validation_details = _validation_component(state, cfg)
    
    overall = (
        critic_score * cfg.confidence_weight_critic
        + structural_score * cfg.confidence_weight_structural
        + validation_score * cfg.confidence_weight_validation
    )
    overall = max(0.0, min(1.0, overall))
    
    details = {
        "critic_scores": critic_details.get("critic_scores"),
        "field_completion_ratio": structural_details.get("field_completion_ratio"),
        "evidence_coverage_ratio": structural_details.get("evidence_coverage_ratio"),
        "avg_field_confidence": structural_details.get("avg_field_confidence"),
        "validation_errors": validation_details.get("errors"),
        "validation_warnings": validation_details.get("warnings"),
    }
    
    components = ConfidenceBreakdown(
        critic=critic_score,
        structural=structural_score,
        validation=validation_score,
        overall=overall,
        details=details,
    )
    return components


def _critic_component(state: FAIRifierState) -> (float, Dict[str, Any]):
    scores: List[float] = []
    for execution in state.get("execution_history", []):
        evaluation = execution.get("critic_evaluation")
        if not evaluation:
            continue
        score = evaluation.get("score")
        if score is not None:
            scores.append(float(score))
    if not scores:
        return 0.0, {"critic_scores": []}
    score = max(0.0, min(1.0, mean(scores)))
    return score, {"critic_scores": scores}


def _structural_component(state: FAIRifierState) -> (float, Dict[str, Any]):
    metadata_fields = state.get("metadata_fields", [])
    total_fields = len(metadata_fields)
    if total_fields == 0:
        return 0.0, {
            "field_completion_ratio": 0.0,
            "evidence_coverage_ratio": 0.0,
            "avg_field_confidence": 0.0,
        }
    
    fields_with_values = sum(
        1 for f in metadata_fields if f.get("value") not in (None, "", f.get("field_name"))
    )
    fields_with_evidence = sum(1 for f in metadata_fields if bool(f.get("evidence")))
    avg_field_confidence = sum(f.get("confidence", 0.0) for f in metadata_fields) / total_fields
    
    field_completion_ratio = fields_with_values / total_fields
    evidence_ratio = fields_with_evidence / total_fields
    
    structural_score = (field_completion_ratio + evidence_ratio + avg_field_confidence) / 3
    structural_score = max(0.0, min(1.0, structural_score))
    
    return structural_score, {
        "critic_scores": [],
        "field_completion_ratio": field_completion_ratio,
        "evidence_coverage_ratio": evidence_ratio,
        "avg_field_confidence": avg_field_confidence,
    }


def _validation_component(
    state: FAIRifierState,
    cfg: FAIRifierConfig,
) -> (float, Dict[str, Any]):
    validation = state.get("validation_results", {}) or {}
    errors = validation.get("errors", []) or []
    warnings = validation.get("warnings", []) or []
    
    if not errors and not warnings:
        score = 1.0
    elif not errors:
        score = max(0.0, 1.0 - 0.05 * len(warnings))
    else:
        score = max(0.0, cfg.validation_pass_target - 0.2 * len(errors))
    
    score = max(0.0, min(1.0, score))
    return score, {"errors": len(errors), "warnings": len(warnings)}

