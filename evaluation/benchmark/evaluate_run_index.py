"""Evaluate and score a persisted v2 run index without selecting a best run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from .attach_evaluator import attach_evaluator_results
from .contracts import load_manifest
from .reporting import write_score_report
from .scorer import score_batch


def evaluate_run_index(
    manifest_path: Path,
    run_index_path: Path,
    *,
    project_root: Path,
    scope: str | None = None,
) -> Dict[str, Any]:
    """Attach per-run evaluator records and score every scheduled cell."""

    manifest = load_manifest(manifest_path)
    evaluated_index = attach_evaluator_results(
        manifest_path,
        run_index_path,
        project_root=project_root,
    )
    score = score_batch(manifest, evaluated_index.get("results") or [], scope=scope)
    score["evaluated_run_index"] = evaluated_index
    return score


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate and score every run in a v2 run index")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-index", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--scope", choices=("core", "supplemental", "stress"))
    args = parser.parse_args()
    score = evaluate_run_index(
        args.manifest,
        args.run_index,
        project_root=args.project_root,
        scope=args.scope,
    )
    output = args.output
    if output:
        output.write_text(json.dumps(score, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.report_dir:
        write_score_report(score, args.report_dir)
    rendered = {key: value for key, value in score.items() if key != "evaluated_run_index"}
    print(json.dumps(rendered, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
