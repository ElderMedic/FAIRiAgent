#!/usr/bin/env python3
"""Remove failed or incomplete evaluation run folders under a model run directory."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _collect_runs(base_dir: Path) -> tuple[list[dict], list[dict]]:
    successful_runs: list[dict] = []
    failed_runs: list[dict] = []

    for doc_dir in sorted(base_dir.iterdir()):
        if not doc_dir.is_dir():
            continue

        for run_dir in doc_dir.iterdir():
            if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
                continue

            metadata_path = run_dir / "metadata.json"
            eval_result_path = run_dir / "eval_result.json"

            is_success = False
            error_reason = "Missing files"

            if metadata_path.exists() and eval_result_path.exists():
                try:
                    with open(eval_result_path, "r", encoding="utf-8") as f:
                        eval_data = json.load(f)
                    if eval_data.get("success", False):
                        is_success = True
                    else:
                        error_reason = eval_data.get(
                            "error", "Flagged unsuccessful in eval_result"
                        )
                except Exception as exc:
                    error_reason = f"Error reading result file: {exc}"
            elif not metadata_path.exists():
                error_reason = "Missing metadata.json"
            elif not eval_result_path.exists():
                error_reason = "Missing eval_result.json"

            run_info = {
                "doc_id": doc_dir.name,
                "run_name": run_dir.name,
                "path": run_dir,
                "reason": error_reason,
            }

            if is_success:
                successful_runs.append(run_info)
            else:
                failed_runs.append(run_info)

    return successful_runs, failed_runs


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Delete failed or incomplete evaluation run folders under a model run root."
        )
    )
    parser.add_argument(
        "base_dir",
        nargs="?",
        type=Path,
        help=(
            "Model run directory containing per-document folders "
            "(default: evaluation/runs under repo root)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List failed runs without deleting them",
    )
    args = parser.parse_args()

    base_dir = (args.base_dir or (_repo_root() / "evaluation" / "runs")).expanduser()
    base_dir = base_dir.resolve()
    if not base_dir.exists():
        raise SystemExit(f"Base directory does not exist: {base_dir}")

    successful_runs, failed_runs = _collect_runs(base_dir)
    print(
        f"Found {len(successful_runs)} successful runs and "
        f"{len(failed_runs)} failed/incomplete runs under {base_dir}."
    )

    if not failed_runs:
        print("No failed runs to clean up.")
        return

    print("\nFailed runs:")
    for run in failed_runs:
        print(f"  - {run['doc_id']}/{run['run_name']}: {run['reason']}")

    if args.dry_run:
        print("\nDry run only — no folders deleted.")
        return

    print("\nCleaning up failed run folders...")
    for run in failed_runs:
        run_path = run["path"]
        if run_path.exists():
            print(f"    Deleting {run_path}")
            shutil.rmtree(run_path)
    print("Cleanup complete!")


if __name__ == "__main__":
    main()
