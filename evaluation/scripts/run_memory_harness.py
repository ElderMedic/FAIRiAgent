#!/usr/bin/env python3
"""Run a focused memory harness benchmark for FAIRiAgent.

This runner is designed to answer one question:
does mem0 improve repeat runs through within-run memory and cross-run reuse?

It keeps normal workflow/checkpoint project IDs unique, while optionally sharing
mem0 scope IDs across runs to simulate persistent user/project memory.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from dotenv import dotenv_values


def _slug(value: str) -> str:
    cleaned = []
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
        else:
            cleaned.append("_")
    text = "".join(cleaned).strip("_")
    while "__" in text:
        text = text.replace("__", "_")
    return text or "run"


def _load_env_file(path: Path) -> Dict[str, str]:
    values = dotenv_values(path)
    return {str(k): str(v) for k, v in values.items() if v is not None}


def _pick_doc_id(document_path: str) -> str:
    return Path(document_path).stem


def _build_memory_scope_id(
    experiment_name: str,
    config_name: str,
    doc_id: str,
    mode: str,
    run_idx: int,
    shared_scope_level: str,
) -> Optional[str]:
    if mode == "stateless":
        return None
    if mode == "fresh_mem0":
        return _slug(f"{experiment_name}_{config_name}_{doc_id}_{mode}_run{run_idx}")
    if shared_scope_level == "project":
        return _slug(f"{experiment_name}_{config_name}_project_memory")
    return _slug(f"{experiment_name}_{config_name}_{doc_id}_shared_memory")


def _summarize_run_output(run_dir: Path) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "workflow_status": None,
        "overall_confidence": None,
        "needs_human_review": None,
        "total_fields": 0,
        "packages_used": [],
        "total_steps": None,
        "failed_steps": None,
        "steps_requiring_retry": None,
        "retry_agents": [],
        "metadata_json_exists": (run_dir / "metadata_json.json").exists(),
    }
    report_path = run_dir / "workflow_report.json"
    if not report_path.exists():
        return summary

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return summary

    exec_summary = report.get("execution_summary", {}) or {}
    field_analysis = report.get("field_analysis", {}) or {}
    quality = report.get("quality_metrics", {}) or {}
    retry = report.get("retry_analysis", {}) or {}

    summary.update(
        {
            "workflow_status": report.get("workflow_status"),
            "overall_confidence": quality.get("overall_confidence"),
            "needs_human_review": exec_summary.get("needs_human_review"),
            "total_fields": field_analysis.get("total_fields", 0),
            "packages_used": field_analysis.get("packages_used", []),
            "total_steps": exec_summary.get("total_steps"),
            "failed_steps": exec_summary.get("failed_steps"),
            "steps_requiring_retry": exec_summary.get("steps_requiring_retry"),
            "retry_agents": retry.get("agents_with_retries", []),
        }
    )
    return summary


def _mean(values: Iterable[float]) -> Optional[float]:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_single(
    *,
    document_path: str,
    doc_id: str,
    config_path: Path,
    config_name: str,
    mode: str,
    run_idx: int,
    experiment_name: str,
    shared_scope_level: str,
    output_root: Path,
    timeout_seconds: int,
) -> Dict[str, Any]:
    run_dir = (
        output_root
        / "outputs"
        / config_name
        / mode
        / doc_id
        / f"run_{run_idx}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    project_id = _slug(
        f"{experiment_name}_{config_name}_{doc_id}_{mode}_run{run_idx}"
    )
    memory_scope_id = _build_memory_scope_id(
        experiment_name,
        config_name,
        doc_id,
        mode,
        run_idx,
        shared_scope_level,
    )
    collection_name = _slug(f"memh_{experiment_name}_{config_name}_{mode}")

    env = os.environ.copy()
    env.update(_load_env_file(config_path))
    env["MEM0_COLLECTION_NAME"] = collection_name
    env["LANGSMITH_PROJECT"] = _slug(f"fairifier-{experiment_name}-{config_name}-{mode}")
    if mode == "stateless":
        env["MEM0_ENABLED"] = "false"
        env.pop("FAIRIFIER_MEMORY_SCOPE_ID", None)
    else:
        env["MEM0_ENABLED"] = "true"
        env["FAIRIFIER_MEMORY_SCOPE_ID"] = memory_scope_id or project_id

    cmd = [
        sys.executable,
        "-m",
        "fairifier.cli",
        "process",
        document_path,
        "--output-dir",
        str(run_dir),
        "--env-file",
        str(config_path),
        "--project-id",
        project_id,
    ]

    started = time.time()
    result = subprocess.run(
        cmd,
        cwd=str(Path(__file__).parents[2]),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    runtime_seconds = time.time() - started

    cli_output_path = run_dir / "cli_output.txt"
    cli_output_path.write_text(
        "\n".join(
            [
                f"Command: {' '.join(cmd)}",
                f"Return code: {result.returncode}",
                "",
                "=== STDOUT ===",
                result.stdout or "",
                "",
                "=== STDERR ===",
                result.stderr or "",
            ]
        ),
        encoding="utf-8",
    )

    run_summary = _summarize_run_output(run_dir)
    success = bool(run_summary["metadata_json_exists"] and result.returncode == 0)

    return {
        "experiment_name": experiment_name,
        "config_name": config_name,
        "document_id": doc_id,
        "document_path": document_path,
        "mode": mode,
        "run_idx": run_idx,
        "project_id": project_id,
        "memory_scope_id": memory_scope_id,
        "mem0_enabled": mode != "stateless",
        "shared_scope_level": shared_scope_level if mode == "shared_mem0" else None,
        "collection_name": collection_name,
        "runtime_seconds": round(runtime_seconds, 3),
        "return_code": result.returncode,
        "success": success,
        **run_summary,
        "output_dir": str(run_dir),
    }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Focused memory benchmark harness for FAIRiAgent."
    )
    parser.add_argument(
        "--model-config",
        dest="model_configs",
        action="append",
        required=True,
        help="Path to a model .env config. Repeat for multiple models.",
    )
    parser.add_argument(
        "--document",
        dest="documents",
        action="append",
        required=True,
        help="Document path. Repeat for multiple documents.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Benchmark output directory.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Sequential repeats per condition/document/model.",
    )
    parser.add_argument(
        "--mode",
        dest="modes",
        action="append",
        choices=["stateless", "fresh_mem0", "shared_mem0"],
        help="Run mode. Defaults to all three.",
    )
    parser.add_argument(
        "--shared-scope-level",
        choices=["document", "project"],
        default="document",
        help="Scope sharing level for shared_mem0 mode.",
    )
    parser.add_argument(
        "--experiment-name",
        default=f"memory_harness_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Stable experiment name used in run IDs and mem0 scopes.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=5400,
        help="Timeout per run.",
    )
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    modes = args.modes or ["stateless", "fresh_mem0", "shared_mem0"]
    config_paths = [Path(path) for path in args.model_configs]
    rows: List[Dict[str, Any]] = []

    for config_path in config_paths:
        config_name = config_path.stem
        for document_path in args.documents:
            doc_id = _pick_doc_id(document_path)
            for mode in modes:
                print(
                    f"[memory-harness] config={config_name} doc={doc_id} mode={mode} "
                    f"repeats={args.repeats}"
                )
                for run_idx in range(1, args.repeats + 1):
                    row = run_single(
                        document_path=document_path,
                        doc_id=doc_id,
                        config_path=config_path,
                        config_name=config_name,
                        mode=mode,
                        run_idx=run_idx,
                        experiment_name=args.experiment_name,
                        shared_scope_level=args.shared_scope_level,
                        output_root=output_dir,
                        timeout_seconds=args.timeout_seconds,
                    )
                    rows.append(row)
                    print(
                        f"  run={run_idx} success={row['success']} "
                        f"status={row['workflow_status']} runtime={row['runtime_seconds']:.1f}s "
                        f"fields={row['total_fields']} confidence={row['overall_confidence']}"
                    )

    grouped: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["config_name"], row["document_id"], row["mode"])
        grouped[key].append(row)

    aggregate_rows: List[Dict[str, Any]] = []
    for (config_name, document_id, mode), items in sorted(grouped.items()):
        aggregate_rows.append(
            {
                "config_name": config_name,
                "document_id": document_id,
                "mode": mode,
                "runs": len(items),
                "success_rate": round(
                    sum(1 for item in items if item["success"]) / len(items), 3
                ),
                "mean_runtime_seconds": round(
                    _mean(item["runtime_seconds"] for item in items) or 0.0, 3
                ),
                "mean_overall_confidence": round(
                    _mean(item["overall_confidence"] for item in items) or 0.0, 4
                ),
                "mean_total_fields": round(
                    _mean(item["total_fields"] for item in items) or 0.0, 2
                ),
                "mean_steps_requiring_retry": round(
                    _mean(item["steps_requiring_retry"] for item in items) or 0.0, 2
                ),
                "shared_scope_level": items[0].get("shared_scope_level"),
                "memory_scope_id_example": items[0].get("memory_scope_id"),
            }
        )

    summary = {
        "experiment_name": args.experiment_name,
        "generated_at": datetime.now().isoformat(),
        "model_configs": [str(path) for path in config_paths],
        "documents": args.documents,
        "modes": modes,
        "shared_scope_level": args.shared_scope_level,
        "repeats": args.repeats,
        "runs": rows,
        "aggregates": aggregate_rows,
    }

    (output_dir / "memory_harness_results.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_csv(
        output_dir / "memory_harness_runs.csv",
        rows,
        [
            "experiment_name",
            "config_name",
            "document_id",
            "mode",
            "run_idx",
            "project_id",
            "memory_scope_id",
            "mem0_enabled",
            "shared_scope_level",
            "runtime_seconds",
            "success",
            "workflow_status",
            "overall_confidence",
            "total_fields",
            "steps_requiring_retry",
            "needs_human_review",
            "output_dir",
        ],
    )
    _write_csv(
        output_dir / "memory_harness_aggregates.csv",
        aggregate_rows,
        [
            "config_name",
            "document_id",
            "mode",
            "runs",
            "success_rate",
            "mean_runtime_seconds",
            "mean_overall_confidence",
            "mean_total_fields",
            "mean_steps_requiring_retry",
            "shared_scope_level",
            "memory_scope_id_example",
        ],
    )

    print(f"\nSaved summary to: {output_dir / 'memory_harness_results.json'}")


if __name__ == "__main__":
    main()
