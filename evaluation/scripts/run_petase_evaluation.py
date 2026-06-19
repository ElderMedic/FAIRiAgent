#!/usr/bin/env python3
"""Run FAIRiAgent batch evaluation on the PETase benchmark only."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).resolve().parent

DEFAULT_GT = PROJECT_ROOT / "evaluation/datasets/annotated/ground_truth_petase_only.json"
DEFAULT_ENV = PROJECT_ROOT / "evaluation/config/env.evaluation"
DEFAULT_MODEL = PROJECT_ROOT / "evaluation/config/model_configs/deepseek_v4-pro_v1.4.0.env"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FAIRiAgent on PETase benchmark papers")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--model-config", type=Path, default=DEFAULT_MODEL)
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=DEFAULT_GT,
        help="Default: ground_truth_petase_only.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Default: evaluation/runs/petase_YYYYMMDD_HHMMSS",
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument(
        "--include-documents",
        type=str,
        nargs="+",
        default=None,
        help="Run only these document IDs (e.g. petase_10_1038_s41586-020-2149-4)",
    )
    args = parser.parse_args()

    if not args.ground_truth.exists():
        raise SystemExit(
            f"Ground truth not found: {args.ground_truth}\n"
            "Run: mamba run -n FAIRiAgent python evaluation/scripts/prepare_petase_benchmark.py"
        )

    output_dir = args.output_dir or (
        PROJECT_ROOT / "evaluation/runs" / f"petase_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    cmd = [
        sys.executable,
        str(SCRIPTS / "run_batch_evaluation.py"),
        "--env-file",
        str(args.env_file),
        "--model-configs",
        str(args.model_config),
        "--ground-truth",
        str(args.ground_truth),
        "--output-dir",
        str(output_dir),
        "--repeats",
        str(args.repeats),
        "--workers",
        str(args.workers),
        "--timeout",
        str(args.timeout),
    ]
    if args.include_documents:
        cmd.extend(["--include-documents", *args.include_documents])
    raise SystemExit(subprocess.run(cmd, cwd=str(PROJECT_ROOT)).returncode)


if __name__ == "__main__":
    main()
