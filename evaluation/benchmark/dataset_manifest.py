"""Materialize a benchmark manifest only after explicit dataset decisions.

This module deliberately does not infer a development/held-out split.  The
caller must provide a complete instance-to-split map and an explicit model
panel.  It is therefore safe to use while a release is still being designed:
the same function can validate a proposed manifest without silently freezing
one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from .assets import collect_asset_checksums, resolve_manifest_path
from .contracts import load_manifest, validate_manifest


ALLOWED_SPLITS = {
    "development",
    "held_out",
    "core",
    "operational",
    "generalization",
    "stress",
    "verified",
}
ALLOWED_REPORTING_ROLES = {"core", "supplemental", "stress"}


class DatasetManifestError(ValueError):
    """Raised when explicit dataset/materialization inputs are incomplete."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetManifestError("Unable to read JSON: %s" % path) from exc


def _normalise_source_path(
    source_value: str,
    *,
    ground_truth_path: Path,
    project_root: Path,
) -> str:
    """Return a file path, resolving legacy PETase paper directories."""

    path = resolve_manifest_path(source_value, ground_truth_path, project_root)
    if path.is_file():
        return str(path)
    if path.is_dir():
        candidates = [
            candidate
            for candidate in (path / "paper.pdf", path / "paper.md", path / "paper.txt")
            if candidate.is_file()
        ]
        if len(candidates) == 1:
            return str(candidates[0])
        if not candidates:
            raise DatasetManifestError(
                "source path is a directory without paper.pdf/paper.md/paper.txt: %s" % path
            )
        raise DatasetManifestError(
            "source path has multiple canonical document candidates: %s" % path
        )
    raise DatasetManifestError("source path does not exist: %s" % path)


def _normalise_asset_path(
    value: str,
    *,
    collection_path: Path,
    project_root: Path,
    label: str,
) -> str:
    """Resolve one declared auxiliary asset and require a regular file."""

    path = resolve_manifest_path(value, collection_path, project_root)
    if not path.is_file():
        raise DatasetManifestError("%s does not exist: %s" % (label, path))
    return str(path)


def _collection_documents(path: Path) -> List[Mapping[str, Any]]:
    value = _read_json(path)
    documents = value.get("documents") if isinstance(value, Mapping) else None
    if not isinstance(documents, list) or not documents:
        raise DatasetManifestError("ground-truth collection has no documents: %s" % path)
    result: List[Mapping[str, Any]] = []
    for index, document in enumerate(documents):
        if not isinstance(document, Mapping):
            raise DatasetManifestError("document %d is not an object in %s" % (index, path))
        document_id = document.get("document_id")
        source_path = document.get("document_path")
        if not isinstance(document_id, str) or not document_id.strip():
            raise DatasetManifestError("document %d has no document_id in %s" % (index, path))
        if not isinstance(source_path, str) or not source_path.strip():
            raise DatasetManifestError("%s has no document_path" % document_id)
        result.append(document)
    return result


def _load_split_map(path: Path) -> Dict[str, str]:
    value = _read_json(path)
    mapping = value.get("instances") if isinstance(value, Mapping) and "instances" in value else value
    if not isinstance(mapping, Mapping):
        raise DatasetManifestError("split map must be a JSON object mapping instance_id to split")
    result: Dict[str, str] = {}
    for instance_id, split in mapping.items():
        if not isinstance(instance_id, str) or not isinstance(split, str):
            raise DatasetManifestError("split map keys and values must be strings")
        if split not in ALLOWED_SPLITS:
            raise DatasetManifestError(
                "unsupported split %r for %s; choose one of %s"
                % (split, instance_id, sorted(ALLOWED_SPLITS))
            )
        result[instance_id] = split
    return result


def _load_reporting_roles(path: Path) -> Dict[str, str]:
    value = _read_json(path)
    if isinstance(value, Mapping) and isinstance(value.get("reporting_roles"), Mapping):
        mapping = value["reporting_roles"]
    else:
        mapping = value.get("instances") if isinstance(value, Mapping) and "instances" in value else value
    if not isinstance(mapping, Mapping):
        raise DatasetManifestError(
            "reporting roles must be a JSON object mapping instance_id to role"
        )
    result: Dict[str, str] = {}
    for instance_id, role in mapping.items():
        if not isinstance(instance_id, str) or not isinstance(role, str):
            raise DatasetManifestError("reporting role keys and values must be strings")
        result[instance_id] = role
    return result


def _load_models(path: Path) -> List[Dict[str, Any]]:
    value = _read_json(path)
    models = value.get("models") if isinstance(value, Mapping) and "models" in value else value
    if not isinstance(models, list) or not models:
        raise DatasetManifestError("model panel must be a non-empty JSON list")
    result: List[Dict[str, Any]] = []
    for index, model in enumerate(models):
        if not isinstance(model, Mapping):
            raise DatasetManifestError("model panel item %d is not an object" % index)
        required = ("model_id", "provider", "model_name", "endpoint_class", "configuration_hash")
        missing = [key for key in required if not isinstance(model.get(key), str) or not model.get(key).strip()]
        if missing:
            raise DatasetManifestError("model panel item %d missing: %s" % (index, ", ".join(missing)))
        result.append(dict(model))
    return result


def _repository_commit(project_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unresolved"
    commit = completed.stdout.strip()
    return commit or "unresolved"


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def materialize_manifest(
    ground_truth_paths: Sequence[Path],
    *,
    project_root: Path,
    split_map: Mapping[str, str],
    model_panel: Sequence[Mapping[str, Any]],
    package_id: str,
    package_version: str,
    package_path: str | None = None,
    conditions: Sequence[Mapping[str, Any]],
    benchmark_release: str,
    evaluator_version: str,
    repetitions: int = 1,
    repetitions_by_split: Mapping[str, int] | None = None,
    reporting_roles: Mapping[str, str] | None = None,
    created_at: str | None = None,
    repository_commit: str | None = None,
    freeze_confirmation: str | None = None,
) -> Dict[str, Any]:
    """Build and validate a complete manifest from explicit release inputs.

    ``freeze_confirmation`` is intentionally required.  It should be a short
    human-authored statement such as ``"researcher-approved: split-v2"`` and
    is recorded in provenance; no default split is ever selected.
    """

    if not freeze_confirmation or not freeze_confirmation.strip():
        raise DatasetManifestError(
            "freeze_confirmation is required; dataset roles must be explicitly approved"
        )
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
        raise DatasetManifestError("repetitions must be a positive integer")
    if repetitions_by_split is not None and not isinstance(repetitions_by_split, Mapping):
        raise DatasetManifestError("repetitions_by_split must be a JSON object")
    if not ground_truth_paths:
        raise DatasetManifestError("at least one ground-truth collection is required")
    split_repetitions = dict(repetitions_by_split or {})
    for split, count in split_repetitions.items():
        if split not in ALLOWED_SPLITS:
            raise DatasetManifestError("unsupported repetition split: %s" % split)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise DatasetManifestError("repetitions_by_split values must be positive integers")
    if not package_id.strip() or not package_version.strip():
        raise DatasetManifestError("package_id and package_version are required")
    resolved_package_path: str | None = None
    if package_path:
        package_file = resolve_manifest_path(package_path, Path(ground_truth_paths[0]), project_root)
        if not package_file.is_file():
            raise DatasetManifestError("package_path does not exist: %s" % package_file)
        resolved_package_path = str(package_file)
    if not benchmark_release.strip() or not evaluator_version.strip():
        raise DatasetManifestError("benchmark_release and evaluator_version are required")
    if not conditions:
        raise DatasetManifestError("at least one publication condition is required")

    all_documents: Dict[str, Dict[str, Any]] = {}
    source_collections: Dict[str, str] = {}
    for collection_path in ground_truth_paths:
        collection_path = Path(collection_path)
        for document in _collection_documents(collection_path):
            instance_id = str(document["document_id"])
            if instance_id in all_documents:
                raise DatasetManifestError(
                    "duplicate document across ground-truth collections: %s" % instance_id
                )
            all_documents[instance_id] = dict(document)
            source_collections[instance_id] = str(collection_path)

    expected_ids = set(all_documents)
    supplied_ids = set(split_map)
    missing = sorted(expected_ids - supplied_ids)
    extra = sorted(supplied_ids - expected_ids)
    if missing or extra:
        parts = []
        if missing:
            parts.append("missing split assignments: " + ", ".join(missing))
        if extra:
            parts.append("split assignments for unknown instances: " + ", ".join(extra))
        raise DatasetManifestError("; ".join(parts))

    role_map = dict(reporting_roles or {})
    unknown_roles = sorted(set(role_map) - expected_ids)
    missing_roles = sorted(expected_ids - set(role_map)) if reporting_roles is not None else []
    invalid_roles = sorted(
        "%s=%s" % (instance_id, role)
        for instance_id, role in role_map.items()
        if not isinstance(role, str) or role not in ALLOWED_REPORTING_ROLES
    )
    if unknown_roles or missing_roles or invalid_roles:
        problems = []
        if unknown_roles:
            problems.append("reporting roles for unknown instances: " + ", ".join(unknown_roles))
        if missing_roles:
            problems.append("missing reporting roles: " + ", ".join(missing_roles))
        if invalid_roles:
            problems.append("unsupported reporting roles: " + ", ".join(invalid_roles))
        raise DatasetManifestError("; ".join(problems))

    instances: List[Dict[str, Any]] = []
    for instance_id in sorted(all_documents):
        document = all_documents[instance_id]
        collection_path = Path(source_collections[instance_id])
        source_path = _normalise_source_path(
            str(document["document_path"]),
            ground_truth_path=collection_path,
            project_root=project_root,
        )
        metadata = document.get("metadata") if isinstance(document.get("metadata"), Mapping) else {}
        domain = metadata.get("domain") if isinstance(metadata, Mapping) else None
        domain_source = "metadata.domain"
        if not isinstance(domain, str) or not domain.strip():
            extensions = metadata.get("schema_extensions") if isinstance(metadata, Mapping) else None
            if isinstance(extensions, list) and extensions and all(
                isinstance(extension, str) and extension.strip() for extension in extensions
            ):
                domain = "schema_extension:" + "+".join(sorted(set(extensions)))
                domain_source = "metadata.schema_extensions"
            else:
                raise DatasetManifestError("%s has no metadata.domain or schema_extensions stratum" % instance_id)
        strata: Dict[str, Any] = {}
        allowed_strata = {
            "domain",
            "experiment_type",
            "layout",
            "length",
            "ocr_quality",
            "table_density",
            "supplementary_material",
            "reporting_completeness",
        }
        for key in allowed_strata:
            value = metadata.get(key)
            if isinstance(value, (str, int, float, bool)) and (not isinstance(value, str) or value.strip()):
                strata[key] = value
        strata.setdefault("domain", domain)
        instance_record = {
            "instance_id": instance_id,
            "source_path": source_path,
            "ground_truth_path": str(collection_path),
            "package_id": package_id,
            "package_version": package_version,
            "split": split_map[instance_id],
            "strata": {**strata, "ground_truth_collection": collection_path.stem},
            "provenance": {
                "ground_truth_collection": str(collection_path),
                "annotation_schema_version": document.get("annotation_schema_version"),
                "annotation_policy": "human_annotation_converted_without_evidence_requirement",
                "domain_source": domain_source,
            },
        }
        if reporting_roles is not None:
            instance_record["reporting_role"] = role_map[instance_id]
        for group_key in ("project_id", "study_family_id"):
            group_value = document.get(group_key) or metadata.get(group_key)
            if isinstance(group_value, (str, int)) and str(group_value).strip():
                instance_record[group_key] = str(group_value)

        for optional_key in ("standards_context_path", "retrieved_context_path"):
            declared = document.get(optional_key)
            if isinstance(declared, str) and declared.strip():
                instance_record[optional_key] = _normalise_asset_path(
                    declared,
                    collection_path=collection_path,
                    project_root=project_root,
                    label="%s.%s" % (instance_id, optional_key),
                )

        declared_supplementary = document.get("supplementary_paths")
        if declared_supplementary is not None:
            if not isinstance(declared_supplementary, list):
                raise DatasetManifestError("%s.supplementary_paths must be a list" % instance_id)
            instance_record["supplementary_paths"] = [
                _normalise_asset_path(
                    value,
                    collection_path=collection_path,
                    project_root=project_root,
                    label="%s.supplementary_paths[%d]" % (instance_id, index),
                )
                for index, value in enumerate(declared_supplementary)
                if isinstance(value, str) and value.strip()
            ]
            if len(instance_record["supplementary_paths"]) != len(declared_supplementary):
                raise DatasetManifestError("%s.supplementary_paths contains an invalid path" % instance_id)
        declared_values_path = document.get("ground_truth_values_path")
        if isinstance(declared_values_path, str) and declared_values_path.strip():
            values_path = resolve_manifest_path(declared_values_path, collection_path, project_root)
            if not values_path.is_file():
                raise DatasetManifestError(
                    "declared ground_truth_values_path does not exist: %s" % values_path
                )
            instance_record["ground_truth_values_path"] = str(values_path)
        else:
            inferred_values_path = collection_path.parent / "values" / (
                "ground_truth_%s_values.json" % instance_id
            )
            if inferred_values_path.is_file():
                instance_record["ground_truth_values_path"] = str(inferred_values_path)
        instances.append(instance_record)
        if resolved_package_path:
            instances[-1]["package_path"] = resolved_package_path

    condition_rows = [dict(condition) for condition in conditions]
    model_rows = [dict(model) for model in model_panel]
    if split_repetitions:
        missing_split_repetitions = sorted(
            {instance["split"] for instance in instances} - set(split_repetitions)
        )
        if missing_split_repetitions:
            raise DatasetManifestError(
                "repetitions_by_split is missing: " + ", ".join(missing_split_repetitions)
            )
    scheduled_runs: List[Dict[str, Any]] = []
    for instance in instances:
        for condition in condition_rows:
            for model in model_rows:
                repetition_count = split_repetitions.get(instance["split"], repetitions)
                for repetition in range(1, repetition_count + 1):
                    scheduled_runs.append(
                        {
                            "run_id": "%s__%s__%s__r%02d"
                            % (
                                instance["instance_id"],
                                condition["condition_id"],
                                model["model_id"],
                                repetition,
                            ),
                            "instance_id": instance["instance_id"],
                            "condition_id": condition["condition_id"],
                            "model_id": model["model_id"],
                            "repetition": repetition,
                        }
                    )

    provenance: Dict[str, Any] = {
        "repository_commit": repository_commit or _repository_commit(project_root),
        "evaluator_version": evaluator_version,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "split_freeze_confirmation": freeze_confirmation.strip(),
        "split_map_sha256": _sha256_json(dict(sorted(split_map.items()))),
        "ground_truth_collections": sorted(set(source_collections.values())),
        "evidence_annotation_required": False,
        "repetitions_by_split": split_repetitions or {"all": repetitions},
        "model_panel_sha256": _sha256_json(model_rows),
        "model_or_api_calls_performed": False,
    }
    if reporting_roles is not None:
        provenance["reporting_role_map_sha256"] = _sha256_json(dict(sorted(role_map.items())))
    manifest: Dict[str, Any] = {
        "schema_version": "fairiagent.benchmark_manifest.v2",
        "benchmark_release": benchmark_release,
        "instances": instances,
        "conditions": condition_rows,
        "models": model_rows,
        "scheduled_runs": scheduled_runs,
        "provenance": provenance,
    }
    # Validate all structural references before callers persist the release.
    errors = validate_manifest(manifest)
    if errors:
        raise DatasetManifestError("Materialized manifest is invalid:\n- " + "\n- ".join(errors))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a v2 manifest from explicit split and model decisions")
    parser.add_argument("--ground-truth", type=Path, action="append", required=True)
    parser.add_argument("--split-map", type=Path, required=True)
    parser.add_argument("--model-panel", type=Path, required=True)
    parser.add_argument("--conditions", type=Path, required=True, help="JSON condition list or condition registry")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--package-version", required=True)
    parser.add_argument("--package-path")
    parser.add_argument("--benchmark-release", required=True)
    parser.add_argument("--evaluator-version", required=True)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--repetitions-by-split", type=Path)
    parser.add_argument("--reporting-roles", type=Path, help="JSON object mapping instance_id to core/supplemental/stress")
    parser.add_argument(
        "--context-report",
        type=Path,
        help="Token-free context snapshot report used to wire standards/retrieval assets",
    )
    parser.add_argument("--freeze-confirmation", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    split_map = _load_split_map(args.split_map)
    model_panel = _load_models(args.model_panel)
    condition_value = _read_json(args.conditions)
    conditions = condition_value.get("conditions") if isinstance(condition_value, Mapping) else condition_value
    if not isinstance(conditions, list):
        raise DatasetManifestError("conditions must be a JSON list or registry object")
    repetitions_by_split = _read_json(args.repetitions_by_split) if args.repetitions_by_split else None
    reporting_roles = _load_reporting_roles(args.reporting_roles) if args.reporting_roles else None
    manifest = materialize_manifest(
        args.ground_truth,
        project_root=args.project_root,
        split_map=split_map,
        model_panel=model_panel,
        package_id=args.package_id,
        package_version=args.package_version,
        package_path=args.package_path,
        conditions=conditions,
        benchmark_release=args.benchmark_release,
        evaluator_version=args.evaluator_version,
        repetitions=args.repetitions,
        repetitions_by_split=repetitions_by_split,
        reporting_roles=reporting_roles,
        freeze_confirmation=args.freeze_confirmation,
    )
    manifest["provenance"]["model_panel_path"] = str(args.model_panel)
    manifest["provenance"]["model_panel_file_sha256"] = hashlib.sha256(
        args.model_panel.read_bytes()
    ).hexdigest()
    if args.context_report:
        from .context_snapshots import manifest_with_context_paths

        context_report = _read_json(args.context_report)
        manifest = manifest_with_context_paths(manifest, context_report)
        context_errors = validate_manifest(manifest)
        if context_errors:
            raise DatasetManifestError(
                "Manifest with context snapshots is invalid:\n- "
                + "\n- ".join(context_errors)
            )
    assets = collect_asset_checksums(
        manifest,
        args.output,
        project_root=args.project_root,
        require_ground_truth=True,
    )
    manifest["provenance"]["asset_checksums"] = assets
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    # Re-load from disk so the exact serialized artifact is validated too.
    load_manifest(args.output)
    print(
        json.dumps(
            {
                "status": "materialized",
                "output": str(args.output),
                "instance_count": len(manifest["instances"]),
                "scheduled_run_count": len(manifest["scheduled_runs"]),
                "model_or_api_calls_performed": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
