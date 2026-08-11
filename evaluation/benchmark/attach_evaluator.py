"""Attach deterministic evaluator results to an existing v2 run index.

This is the missing boundary between the current evaluator implementation and
the benchmark scorer.  It consumes already-produced artifacts only; it never
starts a workflow or calls a model/judge.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .assets import resolve_manifest_path
from .contracts import load_manifest
from .current_evaluator import evaluate_current_run
from .output_validation import validate_output_payload
from .run_index import validate_run_index
from fairifier.output_paths import resolve_metadata_output_read_path


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_ground_truth(path: Path, instance_id: str) -> Dict[str, Any]:
    value = _load_json(path)
    if isinstance(value, Mapping) and isinstance(value.get("documents"), list):
        for document in value["documents"]:
            if isinstance(document, Mapping) and document.get("document_id") == instance_id:
                return dict(document)
        raise ValueError("ground truth has no document %s: %s" % (instance_id, path))
    if isinstance(value, Mapping) and value.get("document_id") in {None, instance_id}:
        return dict(value)
    raise ValueError("unsupported ground-truth shape for %s" % path)


def _values_path(
    instance: Mapping[str, Any],
    ground_truth_path: Path,
    manifest_path: Path,
    project_root: Path,
) -> Optional[Path]:
    declared = instance.get("ground_truth_values_path")
    if isinstance(declared, str) and declared:
        path = resolve_manifest_path(declared, manifest_path, project_root)
        return path if path.is_file() else None
    inferred = ground_truth_path.parent / "values" / (
        "ground_truth_%s_values.json" % instance["instance_id"]
    )
    return inferred if inferred.is_file() else None


def _run_directory(result: Mapping[str, Any], run_index_path: Path) -> Path:
    provenance = result.get("provenance")
    if isinstance(provenance, Mapping) and provenance.get("run_dir"):
        return Path(str(provenance["run_dir"]))
    artifact = result.get("artifact")
    if isinstance(artifact, Mapping) and artifact.get("path"):
        path = Path(str(artifact["path"]))
        if not path.is_absolute():
            path = run_index_path.parent / path
        return path.parent
    raise ValueError("result has neither provenance.run_dir nor artifact.path")


def attach_evaluator_results(
    manifest_path: Path,
    run_index_path: Path,
    *,
    project_root: Path,
) -> Dict[str, Any]:
    """Return a copy of a run index with exact per-run evaluation attached."""

    manifest = load_manifest(manifest_path)
    run_index = _load_json(run_index_path)
    run_index_errors = validate_run_index(run_index)
    if run_index_errors:
        raise ValueError("Invalid v2 run index:\n- " + "\n- ".join(run_index_errors))
    instances = {item["instance_id"]: item for item in manifest["instances"]}
    scheduled = {item["run_id"]: item for item in manifest["scheduled_runs"]}
    updated_index = dict(run_index)
    updated_results = []
    for original in run_index.get("results") or []:
        run_id = original.get("run_id")
        if run_id not in scheduled:
            raise ValueError("run index result is not scheduled: %s" % run_id)
        run_spec = scheduled[run_id]
        instance = instances[run_spec["instance_id"]]
        ground_truth_path = resolve_manifest_path(
            instance["ground_truth_path"], manifest_path, project_root
        )
        ground_truth_doc = _load_ground_truth(ground_truth_path, run_spec["instance_id"])
        values_path = _values_path(instance, ground_truth_path, manifest_path, project_root)
        values_doc = _load_json(values_path) if values_path else None

        run_dir = _run_directory(original, run_index_path)
        output_path = resolve_metadata_output_read_path(run_dir) or (run_dir / "metadata.json")
        artifact = original.get("artifact")
        if isinstance(artifact, Mapping) and artifact.get("path"):
            candidate = Path(str(artifact["path"]))
            output_path = candidate if candidate.is_absolute() else run_index_path.parent / candidate
        validation = {"fairds_valid": False, "isa_round_trip_valid": False, "critical_errors": 0}
        if output_path.is_file():
            try:
                payload = _load_json(output_path)
                if isinstance(payload, Mapping):
                    validation = validate_output_payload(payload)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass

        adapted = evaluate_current_run(
            run_spec,
            run_dir,
            ground_truth_doc,
            validation=validation,
            ground_truth_values_doc=values_doc,
            status=str(original.get("status") or "failed"),
        )
        adapted["resources"] = {
            **dict(original.get("resources") or {}),
            **dict(adapted.get("resources") or {}),
        }
        adapted["provenance"] = {
            **dict(original.get("provenance") or {}),
            **dict(adapted.get("provenance") or {}),
            "output_validation": {
                "fairds_valid": validation["fairds_valid"],
                "isa_round_trip_valid": validation["isa_round_trip_valid"],
                "critical_errors": validation["critical_errors"],
                "warnings": validation.get("warnings", 0),
            },
        }
        updated_results.append(adapted)
    updated_index["results"] = updated_results
    updated_index["evaluated_with"] = "evaluation.benchmark.attach_evaluator"
    return updated_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Attach deterministic evaluator results to a v2 run index")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-index", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = attach_evaluator_results(
        args.manifest,
        args.run_index,
        project_root=args.project_root,
    )
    output = args.output or args.run_index.with_name(args.run_index.stem + "_evaluated.json")
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(output), "observed_count": len(result.get("results") or [])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
