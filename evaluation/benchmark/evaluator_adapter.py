"""Adapt the existing Layer 1--4 evaluator records to result envelope v2.

The legacy evaluator returns rich per-document dictionaries, while the v2
benchmark needs one explicit envelope for every scheduled document-run.  This
module only performs a lossless metric mapping; it never turns an aggregate or
an omitted evaluator section into evidence of quality.  Missing Layer 2/3
ground truth is therefore represented by a zero axis and an explicit
``missing_metrics`` diagnostic, which keeps the hard-gated score fail-closed.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from .contracts import RESULT_SCHEMA_VERSION, validate_result


class EvaluatorAdapterError(ValueError):
    """Raised when evaluator output is ambiguous or cannot be mapped safely."""


_SECTIONS = ("correctness", "value_accuracy", "structural", "schema_validation")


def _metrics(section: Any) -> Mapping[str, Any]:
    """Return a document section's summary metrics without guessing shape."""

    if not isinstance(section, Mapping):
        return {}
    summary = section.get("summary_metrics")
    if isinstance(summary, Mapping):
        return summary
    # Schema validation stores metrics at the section root.  Supporting this
    # shape is explicit and limited to known scalar keys below.
    return section


def _bounded_number(metrics: Mapping[str, Any], keys: Sequence[str]) -> Optional[float]:
    for key in keys:
        value = metrics.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, min(1.0, float(value)))
    return None


def _document_sections(
    batch_record: Mapping[str, Any], document_id: str
) -> Dict[str, Mapping[str, Any]]:
    """Extract one document from the existing batch evaluator result.

    The caller must provide the document identifier.  An aggregate-only
    record is rejected rather than broadcasting a model-level mean to every
    run, which was a source of misleading historical comparisons.
    """

    sections: Dict[str, Mapping[str, Any]] = {}
    for name in _SECTIONS:
        section = batch_record.get(name)
        if not isinstance(section, Mapping):
            continue
        per_document = section.get("per_document")
        if not isinstance(per_document, Mapping):
            continue
        document_section = per_document.get(document_id)
        if isinstance(document_section, Mapping):
            sections[name] = document_section
    if not sections:
        raise EvaluatorAdapterError(
            "No per-document evaluator records found for %s; aggregate metrics "
            "cannot be adapted to a document-run envelope" % document_id
        )
    return sections


def adapt_evaluator_record(
    run_spec: Mapping[str, Any],
    evaluator_record: Mapping[str, Any],
    *,
    artifact: Mapping[str, Any],
    validation: Mapping[str, Any],
    status: str = "success",
    resources: Optional[Mapping[str, Any]] = None,
    provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Create one canonical result from one document's evaluator record.

    ``artifact`` and ``validation`` are required deliberately: schema and
    round-trip checks belong to the benchmark gate, not to the metric adapter.
    The caller must have run those checks for this exact ``run_id``.
    """

    required = ("run_id", "instance_id", "condition_id", "model_id", "repetition")
    missing = [key for key in required if key not in run_spec]
    if missing:
        raise EvaluatorAdapterError("run_spec is missing: %s" % ", ".join(missing))
    if status not in {"success", "failed", "timeout", "infrastructure_error", "not_observed"}:
        raise EvaluatorAdapterError("Unsupported canonical status: %s" % status)

    sections = evaluator_record
    if "per_document" in evaluator_record:
        raise EvaluatorAdapterError(
            "Pass a document-level record, not a batch record containing per_document"
        )

    correctness = _metrics(sections.get("correctness"))
    values = _metrics(sections.get("value_accuracy"))
    structural = _metrics(sections.get("structural"))
    schema = _metrics(sections.get("schema_validation"))

    missing_metrics = []
    information_coverage = _bounded_number(
        correctness, ("field_coverage_recall", "information_coverage")
    )
    # Public curated GT is values-first: Layer-1 field lists are often empty
    # (total_ground_truth_fields==0 → recall forced to 0). Prefer values-GT
    # presence coverage in that case so the axis is not degenerate.
    gt_field_n = correctness.get("total_ground_truth_fields")
    if (information_coverage is None or gt_field_n == 0) and values:
        total_v = values.get("n_gt_populated_fields")
        missing_v = values.get("missing_count")
        if isinstance(total_v, int) and total_v > 0 and isinstance(missing_v, (int, float)):
            information_coverage = max(0.0, min(1.0, 1.0 - float(missing_v) / float(total_v)))
    if information_coverage is None:
        missing_metrics.append("information_coverage")
        information_coverage = 0.0

    value_accuracy = _bounded_number(
        values, ("value_partial_credit_score", "value_mean_score", "value_accuracy")
    )
    if value_accuracy is None:
        missing_metrics.append("value_accuracy")
        value_accuracy = 0.0

    structural_fidelity = _bounded_number(structural, ("structural_fidelity",))
    if structural_fidelity is None:
        placement = _bounded_number(structural, ("sheet_placement_accuracy",))
        alignment = _bounded_number(structural, ("row_alignment_f1",))
        if placement is not None and alignment is not None:
            structural_fidelity = (placement + alignment) / 2.0
        else:
            missing_metrics.append("structural_fidelity")
            structural_fidelity = 0.0

    interoperability = _bounded_number(
        schema, ("schema_compliance_rate", "mean_compliance_rate", "interoperability")
    )
    if interoperability is None:
        missing_metrics.append("interoperability")
        interoperability = 0.0

    artifact_data = dict(artifact)
    validation_data = dict(validation)
    result: Dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "run_id": run_spec["run_id"],
        "instance_id": run_spec["instance_id"],
        "condition_id": run_spec["condition_id"],
        "model_id": run_spec["model_id"],
        "repetition": run_spec["repetition"],
        "status": status,
        "artifact": {
            "exists": bool(artifact_data.get("exists", False)),
            "parseable": bool(artifact_data.get("parseable", False)),
            **{key: value for key, value in artifact_data.items() if key not in {"exists", "parseable"}},
        },
        "validation": {
            "fairds_valid": bool(validation_data.get("fairds_valid", False)),
            "isa_round_trip_valid": bool(validation_data.get("isa_round_trip_valid", False)),
            "critical_errors": int(validation_data.get("critical_errors", 0) or 0),
            "warnings": int(validation_data.get("warnings", 0) or 0),
        },
        "axes": {
            "information_coverage": information_coverage,
            "value_accuracy": value_accuracy,
            "structural_fidelity": structural_fidelity,
            "interoperability": interoperability,
        },
        "resources": dict(resources or {}),
        "failure": {"category": "missing_evaluator_metrics", "missing_metrics": missing_metrics}
        if missing_metrics
        else {},
        "provenance": {
            "evaluator_adapter": "layer1_4_to_result_envelope_v2",
            **dict(provenance or {}),
        },
    }
    errors = validate_result(result)
    if errors:
        raise EvaluatorAdapterError("Adapted result is invalid:\n- " + "\n- ".join(errors))
    return result


def adapt_evaluator_batch_record(
    run_spec: Mapping[str, Any],
    batch_record: Mapping[str, Any],
    document_id: str,
    *,
    artifact: Mapping[str, Any],
    validation: Mapping[str, Any],
    status: str = "success",
    resources: Optional[Mapping[str, Any]] = None,
    provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Adapt one document from ``evaluate_outputs.py``'s batch result."""

    return adapt_evaluator_record(
        run_spec,
        _document_sections(batch_record, document_id),
        artifact=artifact,
        validation=validation,
        status=status,
        resources=resources,
        provenance=provenance,
    )
