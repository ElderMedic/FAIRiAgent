"""Merge denominator-preserving benchmark execution partitions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .run_index import merge_run_indices


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge disjoint v2 run-index partitions without dropping runs"
    )
    parser.add_argument("--run-index", action="append", required=True, help="Partition JSON path")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    indices = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.run_index]
    merged = merge_run_indices(indices)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "scheduled_count": merged["scheduled_count"],
                "observed_count": merged["observed_count"],
                "missing_count": merged["missing_count"],
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
