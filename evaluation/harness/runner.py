"""Minimal runner skeleton for private FAIRiAgent evaluation harnesses."""

from __future__ import annotations

import json
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from evaluation.benchmark.contracts import load_manifest as load_benchmark_manifest
from evaluation.benchmark.assets import collect_asset_checksums
from evaluation.benchmark.dataset_inventory import validate_split_leakage


@dataclass
class HarnessCase:
    """Single evaluation case definition."""

    case_id: str
    document_path: str
    gold_path: str | None = None
    notes: str | None = None


def load_manifest(path: str | Path) -> List[HarnessCase]:
    """Load a simple case manifest."""
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    return [HarnessCase(**case) for case in manifest.get("cases", [])]


def summarize_cases(cases: List[HarnessCase]) -> Dict[str, Any]:
    """Return a lightweight manifest summary for local harness runs."""
    return {
        "case_count": len(cases),
        "case_ids": [case.case_id for case in cases],
    }


def summarize_benchmark_manifest(
    manifest: Dict[str, Any],
    *,
    manifest_path: Path | None = None,
    project_root: Path | None = None,
) -> Dict[str, Any]:
    """Summarize and validate a version 2 matrix without executing a model.

    Asset checksums and split-leakage checks are part of the dry-run contract.
    This keeps a scheduled matrix from being executed against silently changed
    documents or references.
    """

    if manifest_path is None or project_root is None:
        raise ValueError("manifest_path and project_root are required for benchmark dry-runs")
    assets = collect_asset_checksums(
        manifest,
        manifest_path,
        project_root=project_root,
        require_ground_truth=True,
    )
    leakage_errors = validate_split_leakage(manifest["instances"], assets)
    if leakage_errors:
        raise ValueError("Benchmark split leakage detected:\n- " + "\n- ".join(leakage_errors))

    return {
        "schema_version": manifest["schema_version"],
        "benchmark_release": manifest["benchmark_release"],
        "instance_count": len(manifest["instances"]),
        "condition_count": len(manifest["conditions"]),
        "model_count": len(manifest["models"]),
        "scheduled_run_count": len(manifest["scheduled_runs"]),
        "run_ids": [run["run_id"] for run in manifest["scheduled_runs"]],
        "asset_checksums": assets,
        "asset_count": sum(len(values) for values in assets.values()),
        "split_leakage_errors": leakage_errors,
        "model_or_api_calls_performed": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FAIRiAgent evaluation harness")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("example_manifest.json"),
        help="A version 2 benchmark manifest, or the legacy case manifest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and expand the scheduled matrix without executing a model.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Root used for manifest-relative source and ground-truth paths.",
    )
    args = parser.parse_args()
    raw_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if raw_manifest.get("schema_version") == "fairiagent.benchmark_manifest.v2":
        benchmark_manifest = load_benchmark_manifest(args.manifest)
        print(
            json.dumps(
                summarize_benchmark_manifest(
                    benchmark_manifest,
                    manifest_path=args.manifest,
                    project_root=args.project_root,
                ),
                indent=2,
            )
        )
    else:
        cases = load_manifest(args.manifest)
        print(json.dumps(summarize_cases(cases), indent=2))
