#!/usr/bin/env python3
"""Prepare or execute MinerU preconversion for auto eval target documents.

The auto merge gate expects full-run artifacts to be reproducible. For PDF-like
inputs, the main pipeline reuses preconverted MinerU output at
``<source_parent>/mineru_<source_stem>/`` before attempting a live MinerU run.
This helper makes that preconversion step explicit and auditable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fairifier.services.mineru_health import (
    dependency_errors_for_backend,
    dependency_install_hint_for_backend,
)

import run_auto_eval


DEFAULT_REPORT = run_auto_eval.ARTIFACTS_DIR / "mineru_preconvert_report.json"


@dataclass(frozen=True)
class PreconvertTask:
    document_id: str
    source_path: Path
    output_dir: Path
    command: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_path": str(self.source_path),
            "output_dir": str(self.output_dir),
            "command": self.command,
        }


def build_mineru_command(
    *,
    cli: str,
    source_path: Path,
    output_dir: Path,
    backend: str,
    method: str,
    lang: str,
    url: Optional[str],
) -> List[str]:
    cmd = [
        cli,
        "-p",
        str(source_path),
        "-o",
        str(output_dir),
        "-b",
        backend,
    ]
    if backend == "pipeline":
        cmd.extend(["-m", method, "-l", lang])
    if "http-client" in backend and url:
        cmd.extend(["-u", url])
    return cmd


def build_preconvert_tasks(
    *,
    ground_truth: Path,
    documents: List[str],
    cli: str = "mineru",
    backend: str = "pipeline",
    method: str = "auto",
    lang: str = "en",
    url: Optional[str] = None,
) -> List[PreconvertTask]:
    doc_index = run_auto_eval.build_document_path_index(ground_truth)
    tasks: List[PreconvertTask] = []
    for doc_id in documents:
        doc_path = doc_index.get(doc_id)
        if doc_path is None:
            continue
        readiness = run_auto_eval.mineru_readiness_for_document(doc_path)
        for raw_source in readiness.get("missing_sources") or []:
            source_path = Path(raw_source)
            output_dir = source_path.parent / f"mineru_{source_path.stem}"
            tasks.append(
                PreconvertTask(
                    document_id=doc_id,
                    source_path=source_path,
                    output_dir=output_dir,
                    command=build_mineru_command(
                        cli=cli,
                        source_path=source_path,
                        output_dir=output_dir,
                        backend=backend,
                        method=method,
                        lang=lang,
                        url=url,
                    ),
                )
            )
    return tasks


def skipped_results_for_dependency_errors(
    tasks: List[PreconvertTask],
    dependency_errors: List[str],
) -> List[Dict[str, Any]]:
    now = datetime.now().isoformat()
    detail = "; ".join(dependency_errors)
    return [
        {
            **task.to_dict(),
            "status": "skipped_missing_dependency",
            "returncode": None,
            "started_at": now,
            "ended_at": now,
            "runtime_seconds": 0.0,
            "stdout_tail": "",
            "stderr_tail": detail,
            "preconverted_after": False,
            "missing_sources_after": [str(task.source_path)],
        }
        for task in tasks
    ]


def run_tasks(tasks: List[PreconvertTask], *, timeout: int) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for task in tasks:
        started = datetime.now()
        status = "pending"
        task.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run(
                task.command,
                cwd=str(run_auto_eval.PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            error = completed.stderr[-4000:] if completed.returncode != 0 else ""
            stdout = completed.stdout[-4000:] if completed.stdout else ""
        except subprocess.TimeoutExpired as exc:
            completed = None
            status = "timeout"
            error = f"timed out after {timeout}s"
            stdout = (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else ""
        ended = datetime.now()
        post = run_auto_eval.mineru_readiness_for_document(task.source_path)
        results.append(
            {
                **task.to_dict(),
                "status": status,
                "returncode": completed.returncode if completed else None,
                "started_at": started.isoformat(),
                "ended_at": ended.isoformat(),
                "runtime_seconds": (ended - started).total_seconds(),
                "stdout_tail": stdout,
                "stderr_tail": error,
                "preconverted_after": bool(post.get("preconverted")),
                "missing_sources_after": post.get("missing_sources", []),
            }
        )
        if completed is not None:
            preconverted = bool(post.get("preconverted"))
            if completed.returncode == 0 and preconverted:
                results[-1]["status"] = "success"
            elif completed.returncode == 0:
                results[-1]["status"] = "failed_missing_markdown"
                results[-1]["stderr_tail"] = (
                    results[-1].get("stderr_tail") or ""
                )[-3500:] + "\nMinerU returned 0 but no reusable Markdown was found."
            else:
                results[-1]["status"] = "failed"
    return results


def build_report(
    *,
    tasks: List[PreconvertTask],
    executed: bool,
    results: Optional[List[Dict[str, Any]]] = None,
    dependency_errors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    results = results or []
    dependency_errors = dependency_errors or []
    install_hint = (
        dependency_install_hint_for_backend("pipeline")
        if dependency_errors
        else None
    )
    success_count = sum(1 for item in results if item.get("status") == "success")
    failed_count = len(results) - success_count if executed else 0
    return {
        "generated_at": datetime.now().isoformat(),
        "executed": executed,
        "task_count": len(tasks),
        "success_count": success_count,
        "failed_count": failed_count,
        "dependency_errors": dependency_errors,
        "dependency_install_hint": install_hint,
        "tasks": [task.to_dict() for task in tasks],
        "results": results,
        "next_action": (
            "No missing MinerU preconversions were found."
            if not tasks
            else (
                "Install missing MinerU pipeline dependencies before executing preconversion"
                + (f": {install_hint}" if install_hint else ".")
                if dependency_errors
                else
                "Inspect failed results and rerun preconversion before readiness."
                if executed and failed_count
                else "Rerun readiness_report.py after successful conversion."
                if executed
                else "Review the commands, then rerun with --execute to create MinerU output."
            )
        ),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# MinerU Preconversion Report",
        "",
        f"- Executed: `{report.get('executed')}`",
        f"- Tasks: `{report.get('task_count', 0)}`",
        f"- Successes: `{report.get('success_count', 0)}`",
        f"- Failures: `{report.get('failed_count', 0)}`",
        f"- Next action: {report.get('next_action')}",
        "",
    ]
    dependency_errors = report.get("dependency_errors") or []
    if dependency_errors:
        lines.extend(["## Dependency Errors", ""])
        for error in dependency_errors:
            lines.append(f"- `{error}`")
        if report.get("dependency_install_hint"):
            lines.append(f"- Install: `{report.get('dependency_install_hint')}`")
        lines.append("")
    lines.extend(["## Tasks", ""])
    tasks = report.get("tasks") or []
    if not tasks:
        lines.append("- None")
    else:
        for task in tasks:
            lines.append(f"- `{task.get('document_id')}`: `{task.get('source_path')}`")
            lines.append(f"  - Output: `{task.get('output_dir')}`")
            lines.append(f"  - Command: `{' '.join(task.get('command') or [])}`")
    results = report.get("results") or []
    if results:
        lines.extend(["", "## Results", ""])
        for item in results:
            lines.append(
                f"- `{item.get('document_id')}`: `{item.get('status')}` "
                f"(preconverted_after=`{item.get('preconverted_after')}`)"
            )
    lines.append("")
    return "\n".join(lines)


def write_report(report: Dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    output.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ground-truth", type=Path, default=run_auto_eval.DEFAULT_GROUND_TRUTH)
    parser.add_argument("--baseline-metadata", type=Path, default=run_auto_eval.DEFAULT_BASELINE_METADATA)
    parser.add_argument("--include-documents", nargs="+")
    parser.add_argument("--cli", default="mineru")
    parser.add_argument("--backend", default="pipeline")
    parser.add_argument("--method", default="auto")
    parser.add_argument("--lang", default="en")
    parser.add_argument("--url")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    docs = args.include_documents or run_auto_eval.read_target_documents(
        args.baseline_metadata
    )
    tasks = build_preconvert_tasks(
        ground_truth=args.ground_truth,
        documents=docs,
        cli=args.cli,
        backend=args.backend,
        method=args.method,
        lang=args.lang,
        url=args.url,
    )
    dependency_errors = dependency_errors_for_backend(args.backend)
    if args.execute and dependency_errors:
        results = skipped_results_for_dependency_errors(tasks, dependency_errors)
    else:
        results = run_tasks(tasks, timeout=args.timeout) if args.execute else []
    report = build_report(
        tasks=tasks,
        executed=args.execute,
        results=results,
        dependency_errors=dependency_errors,
    )
    write_report(report, args.output)

    print(f"MinerU preconversion report: {args.output}")
    print(f"Tasks: {len(tasks)}")
    for task in tasks:
        print(f"- {task.document_id}: {' '.join(task.command)}")
    if args.execute and (
        dependency_errors or any(item.get("status") != "success" for item in results)
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
