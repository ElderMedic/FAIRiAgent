"""Conservative adapter from legacy per-run records to result envelope v2.

Legacy ``eval_result.json`` files generally contain execution status but not
executable FAIR-DS/ISA validation or all Layer 1–4 values. Missing information
is therefore represented as an unmet gate, never guessed from ``success`` or
``n_fields_extracted``.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from .contracts import RESULT_SCHEMA_VERSION


def _number(metrics: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        value = metrics.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, min(1.0, float(value)))
    return 0.0


def adapt_legacy_run(
    legacy_result: Mapping[str, Any],
    run_spec: Mapping[str, Any],
    *,
    layer_metrics: Mapping[str, Any] | None = None,
    artifact: Mapping[str, Any] | None = None,
    validation: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Map one legacy run into v2 without inventing missing quality evidence.

    ``layer_metrics``, ``artifact``, and ``validation`` are optional because a
    legacy result may not contain them. Omitting them produces a valid v2
    envelope whose hard gates fail until the missing checks are supplied.
    """

    expected_keys = ("run_id", "instance_id", "condition_id", "model_id", "repetition")
    for key in expected_keys:
        if key not in run_spec:
            raise ValueError("run_spec is missing %s" % key)
    metrics = layer_metrics or {}
    validation_data = dict(validation or {})
    artifact_data = dict(artifact or {})

    success = bool(legacy_result.get("success"))
    error_text = str(legacy_result.get("error") or "").lower()
    if success:
        status = "success"
    elif "timeout" in error_text or "timed out" in error_text:
        status = "timeout"
    else:
        status = "failed"

    structural_explicit = _number(metrics, "structural_fidelity")
    if "structural_fidelity" not in metrics:
        placement = _number(metrics, "sheet_placement_accuracy")
        alignment = _number(metrics, "row_alignment_f1")
        structural_explicit = (placement + alignment) / 2 if placement or alignment else 0.0

    return {
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
            "information_coverage": _number(metrics, "information_coverage", "field_coverage_recall", "overall_completeness"),
            "value_accuracy": _number(metrics, "value_accuracy", "value_partial_credit_score", "value_mean_score"),
            "structural_fidelity": structural_explicit,
            "interoperability": _number(metrics, "interoperability", "schema_compliance", "fairds_compliance"),
            **({"efficiency": _number(metrics, "efficiency")} if "efficiency" in metrics else {}),
        },
        "resources": {
            "latency_seconds": legacy_result.get("runtime_seconds"),
            "input_tokens": legacy_result.get("input_tokens"),
            "output_tokens": legacy_result.get("output_tokens"),
        },
        "failure": {"category": legacy_result.get("error")} if not success else {},
        "provenance": {
            "legacy_adapter": True,
            "legacy_config_name": legacy_result.get("config_name"),
            "legacy_output_dir": legacy_result.get("output_dir"),
        },
    }
