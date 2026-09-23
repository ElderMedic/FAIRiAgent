"""Validation and loading for the canonical benchmark version 2 contract.

The repository deliberately keeps this validator dependency-free. The JSON
Schema files are the interchange contract; this module provides actionable
validation for the local harness and tests without requiring an optional
``jsonschema`` installation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


MANIFEST_SCHEMA_VERSION = "fairiagent.benchmark_manifest.v2"
RESULT_SCHEMA_VERSION = "fairiagent.result_envelope.v2"
_CONDITION_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "schemas" / "condition_registry.json"
_ALLOWED_SPLITS = {
    "development",
    "held_out",
    "core",
    "operational",
    "generalization",
    "stress",
    "verified",
}
_ALLOWED_ENDPOINT_CLASSES = {"hosted", "local", "snapshot"}
_ALLOWED_REPORTING_ROLES = {"core", "supplemental", "stress"}


class ManifestValidationError(ValueError):
    """Raised when a benchmark manifest cannot define a reproducible matrix."""


class ResultValidationError(ValueError):
    """Raised when a document-run result violates the canonical envelope."""


def _read_json(path: str | Path) -> Dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to load JSON: %s" % source) from exc
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object: %s" % source)
    return value


def _require_strings(container: Mapping[str, Any], keys: Iterable[str], prefix: str) -> List[str]:
    errors: List[str] = []
    for key in keys:
        value = container.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append("%s.%s must be a non-empty string" % (prefix, key))
    return errors


def validate_manifest(manifest: Mapping[str, Any]) -> List[str]:
    """Return actionable validation errors for a benchmark manifest.

    The function does not silently repair duplicate or dangling matrix entries.
    Callers should fail before scheduling when the returned list is non-empty.
    """

    errors: List[str] = []
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append("schema_version must be %s" % MANIFEST_SCHEMA_VERSION)

    errors.extend(_require_strings(manifest, ("benchmark_release",), "manifest"))
    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        errors.append("manifest.provenance must be an object")
    else:
        errors.extend(
            _require_strings(
                provenance,
                ("repository_commit", "evaluator_version", "created_at"),
                "manifest.provenance",
            )
        )

    instances = manifest.get("instances")
    conditions = manifest.get("conditions")
    models = manifest.get("models")
    scheduled = manifest.get("scheduled_runs")
    for name, value in (
        ("instances", instances),
        ("conditions", conditions),
        ("models", models),
        ("scheduled_runs", scheduled),
    ):
        if not isinstance(value, list) or not value:
            errors.append("%s must be a non-empty list" % name)

    def collect_unique(items: Any, key: str, prefix: str) -> Dict[str, Mapping[str, Any]]:
        collected: Dict[str, Mapping[str, Any]] = {}
        if not isinstance(items, list):
            return collected
        for index, item in enumerate(items):
            item_prefix = "%s[%d]" % (prefix, index)
            if not isinstance(item, Mapping):
                errors.append("%s must be an object" % item_prefix)
                continue
            errors.extend(_require_strings(item, (key,), item_prefix))
            identifier = item.get(key)
            if isinstance(identifier, str) and identifier:
                if identifier in collected:
                    errors.append("duplicate %s: %s" % (key, identifier))
                collected[identifier] = item
        return collected

    instance_map = collect_unique(instances, "instance_id", "instances")
    condition_map = collect_unique(conditions, "condition_id", "conditions")
    model_map = collect_unique(models, "model_id", "models")

    if isinstance(instances, list):
        for index, instance in enumerate(instances):
            if isinstance(instance, Mapping):
                errors.extend(
                    _require_strings(
                        instance,
                        (
                            "source_path",
                            "ground_truth_path",
                            "package_id",
                            "package_version",
                            "split",
                        ),
                        "instances[%d]" % index,
                    )
                )
                split = instance.get("split")
                if isinstance(split, str) and split not in _ALLOWED_SPLITS:
                    errors.append(
                        "instances[%d].split is not a supported benchmark split: %s"
                        % (index, split)
                    )
                reporting_role = instance.get("reporting_role")
                if reporting_role is not None and (
                    not isinstance(reporting_role, str)
                    or reporting_role not in _ALLOWED_REPORTING_ROLES
                ):
                    errors.append(
                        "instances[%d].reporting_role must be one of %s"
                        % (index, sorted(_ALLOWED_REPORTING_ROLES))
                    )
                strata = instance.get("strata")
                if not isinstance(strata, Mapping):
                    errors.append("instances[%d].strata must be an object" % index)
                else:
                    errors.extend(_require_strings(strata, ("domain",), "instances[%d].strata" % index))
                for optional_path_key in (
                    "standards_context_path",
                    "retrieved_context_path",
                ):
                    if optional_path_key in instance and (
                        not isinstance(instance.get(optional_path_key), str)
                        or not str(instance.get(optional_path_key)).strip()
                    ):
                        errors.append(
                            "instances[%d].%s must be a non-empty string when supplied"
                            % (index, optional_path_key)
                        )
                supplementary = instance.get("supplementary_paths")
                if supplementary is not None:
                    if not isinstance(supplementary, list):
                        errors.append("instances[%d].supplementary_paths must be a list" % index)
                    else:
                        for path_index, value in enumerate(supplementary):
                            if not isinstance(value, str) or not value.strip():
                                errors.append(
                                    "instances[%d].supplementary_paths[%d] must be a non-empty string"
                                    % (index, path_index)
                                )
    if isinstance(models, list):
        for index, model in enumerate(models):
            if isinstance(model, Mapping):
                errors.extend(
                    _require_strings(
                        model,
                        ("provider", "model_name", "endpoint_class", "configuration_hash"),
                        "models[%d]" % index,
                    )
                )
                endpoint_class = model.get("endpoint_class")
                if isinstance(endpoint_class, str) and endpoint_class not in _ALLOWED_ENDPOINT_CLASSES:
                    errors.append(
                        "models[%d].endpoint_class is not supported: %s"
                        % (index, endpoint_class)
                    )

    if isinstance(conditions, list):
        try:
            registry = json.loads(_CONDITION_REGISTRY_PATH.read_text(encoding="utf-8"))
            known_condition_ids = {
                item.get("condition_id")
                for item in registry.get("conditions", [])
                if isinstance(item, Mapping)
            }
        except (OSError, json.JSONDecodeError, AttributeError):
            known_condition_ids = set()
        for index, condition in enumerate(conditions):
            if not isinstance(condition, Mapping):
                continue
            condition_id = condition.get("condition_id")
            if isinstance(condition_id, str) and not all(
                character.islower() or character.isdigit() or character == "_"
                for character in condition_id
            ):
                errors.append("conditions[%d].condition_id must be lowercase snake_case" % index)
            if not isinstance(condition.get("publication_name"), str):
                errors.append("conditions[%d].publication_name must be a string" % index)
            if not isinstance(condition.get("component_settings"), Mapping):
                errors.append("conditions[%d].component_settings must be an object" % index)
            if known_condition_ids and condition_id not in known_condition_ids:
                errors.append(
                    "conditions[%d].condition_id is not in condition_registry.json: %s"
                    % (index, condition_id)
                )

    scheduled_ids: set[str] = set()
    cell_repetitions: Dict[tuple[str, str, str], List[int]] = {}
    if isinstance(scheduled, list):
        for index, run in enumerate(scheduled):
            prefix = "scheduled_runs[%d]" % index
            if not isinstance(run, Mapping):
                errors.append("%s must be an object" % prefix)
                continue
            errors.extend(
                _require_strings(
                    run,
                    ("run_id", "instance_id", "condition_id", "model_id"),
                    prefix,
                )
            )
            repetition = run.get("repetition")
            if not isinstance(repetition, int) or isinstance(repetition, bool) or repetition < 1:
                errors.append("%s.repetition must be a positive integer" % prefix)
            elif all(isinstance(run.get(key), str) and run.get(key) for key in ("instance_id", "condition_id", "model_id")):
                cell = (run["instance_id"], run["condition_id"], run["model_id"])
                cell_repetitions.setdefault(cell, []).append(repetition)
            run_id = run.get("run_id")
            if isinstance(run_id, str) and run_id:
                if run_id in scheduled_ids:
                    errors.append("duplicate run_id: %s" % run_id)
                scheduled_ids.add(run_id)
            for key, values in (
                ("instance_id", instance_map),
                ("condition_id", condition_map),
                ("model_id", model_map),
            ):
                identifier = run.get(key)
                if isinstance(identifier, str) and identifier and identifier not in values:
                    errors.append("%s.%s references unknown %s: %s" % (prefix, key, key, identifier))

    for cell, repetitions in cell_repetitions.items():
        ordered = sorted(repetitions)
        if len(ordered) != len(set(ordered)):
            errors.append("duplicate repetition for %s" % ("/".join(cell),))
        elif ordered != list(range(1, len(ordered) + 1)):
            errors.append(
                "repetitions for %s must be contiguous from 1: %s"
                % ("/".join(cell), ordered)
            )

    return errors


def load_manifest(path: str | Path) -> Dict[str, Any]:
    """Load and validate a canonical benchmark manifest."""

    manifest = _read_json(path)
    errors = validate_manifest(manifest)
    if errors:
        raise ManifestValidationError("Invalid benchmark manifest:\n- " + "\n- ".join(errors))
    return manifest


def validate_result(result: Mapping[str, Any]) -> List[str]:
    """Return errors for one canonical document-run result."""

    errors: List[str] = []
    if result.get("schema_version") != RESULT_SCHEMA_VERSION:
        errors.append("schema_version must be %s" % RESULT_SCHEMA_VERSION)
    errors.extend(
        _require_strings(
            result,
            ("run_id", "instance_id", "condition_id", "model_id"),
            "result",
        )
    )
    repetition = result.get("repetition")
    if not isinstance(repetition, int) or isinstance(repetition, bool) or repetition < 1:
        errors.append("result.repetition must be a positive integer")
    if result.get("status") not in {
        "success",
        "failed",
        "timeout",
        "infrastructure_error",
        "not_observed",
    }:
        errors.append("result.status is not a canonical status")

    artifact = result.get("artifact")
    if not isinstance(artifact, Mapping):
        errors.append("result.artifact must be an object")
    else:
        for key in ("exists", "parseable"):
            if not isinstance(artifact.get(key), bool):
                errors.append("result.artifact.%s must be boolean" % key)

    validation = result.get("validation")
    if not isinstance(validation, Mapping):
        errors.append("result.validation must be an object")
    else:
        for key in ("fairds_valid", "isa_round_trip_valid"):
            if not isinstance(validation.get(key), bool):
                errors.append("result.validation.%s must be boolean" % key)
        critical_errors = validation.get("critical_errors")
        if not isinstance(critical_errors, int) or isinstance(critical_errors, bool) or critical_errors < 0:
            errors.append("result.validation.critical_errors must be a non-negative integer")

    axes = result.get("axes")
    if not isinstance(axes, Mapping):
        errors.append("result.axes must be an object")
    else:
        for key in ("information_coverage", "value_accuracy", "structural_fidelity", "interoperability"):
            value = axes.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                errors.append("result.axes.%s must be a number in [0, 1]" % key)

    return errors


def load_result(path: str | Path) -> Dict[str, Any]:
    """Load and validate one canonical result envelope."""

    result = _read_json(path)
    errors = validate_result(result)
    if errors:
        raise ResultValidationError("Invalid result envelope:\n- " + "\n- ".join(errors))
    return result
