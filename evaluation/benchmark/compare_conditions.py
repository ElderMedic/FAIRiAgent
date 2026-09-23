"""Compare two persisted v2 score files without rerunning evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from .statistics import paired_comparison


def compare_score_files(
    baseline_path: Path,
    treatment_path: Path,
    *,
    resamples: int = 2000,
    seed: int = 0,
) -> Dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    treatment = json.loads(treatment_path.read_text(encoding="utf-8"))
    return paired_comparison(
        baseline.get("standard_runs") or [],
        treatment.get("standard_runs") or [],
        resamples=resamples,
        seed=seed,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two FAIRiAgent v2 score files")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--treatment", type=Path, required=True)
    parser.add_argument("--resamples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare_score_files(
        args.baseline,
        args.treatment,
        resamples=args.resamples,
        seed=args.seed,
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
