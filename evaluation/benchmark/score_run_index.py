#!/usr/bin/env python3
"""Score a production run index with the benchmark version 2 scorer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from .contracts import load_manifest
from .reporting import write_score_report
from .run_index import validate_run_index
from .scorer import score_batch


def score_run_index(
    manifest_path: Path,
    run_index_path: Path,
    *,
    scope: str | None = None,
) -> Dict[str, Any]:
    manifest = load_manifest(manifest_path)
    run_index = json.loads(run_index_path.read_text(encoding="utf-8"))
    run_index_errors = validate_run_index(run_index)
    if run_index_errors:
        raise ValueError("Invalid v2 run index:\n- " + "\n- ".join(run_index_errors))
    results = run_index.get("results") or []
    score = score_batch(manifest, results, scope=scope)
    score["run_index_path"] = str(run_index_path)
    score["run_index_observed_count"] = run_index.get("observed_count")
    score["run_index_missing_count"] = run_index.get("missing_count")
    return score


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a FAIRiAgent v2 run index")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-index", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--scope", choices=("core", "supplemental", "stress"))
    args = parser.parse_args()
    score = score_run_index(args.manifest, args.run_index, scope=args.scope)
    rendered = json.dumps(score, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    if args.report_dir:
        write_score_report(score, args.report_dir)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
