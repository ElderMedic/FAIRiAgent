#!/usr/bin/env python3
"""Progress of a PETase batch: done papers, where each running paper is, and an ETA.

    python evaluation/scripts/petase_batch_progress.py evaluation/runs/petase_batch48_v2_20261122/ollama_qwen3.8-27b

Stage progress of a running paper is read from its log (which agent runs, which
mapping batch it is on), so it is an estimate; finished papers are exact.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "evaluation/datasets/petase_benchmark_manifest.json"

# (log marker, fraction of the paper done when it is seen, stage name)
STAGES = [
    ("DocumentParser", 0.03, "parsing"),
    ("Indexed", 0.08, "indexing"),
    ("KnowledgeRetriever", 0.12, "package lookup"),
    ("Generating metadata batch", 0.20, "JSON generation"),
    ("EntityStructurePlanner", 0.35, "entity planning"),
    ("ISAValueMapper", 0.50, "value mapping"),
    ("Saved ", 1.00, "finished"),
]


def bar(fraction: float, width: int = 40) -> str:
    filled = int(round(width * fraction))
    return "█" * filled + "░" * (width - filled)


def paper_progress(log: Path) -> tuple[float, str]:
    """Estimated fraction and stage of a running paper from its log."""
    if not log.exists():
        return 0.0, "queued"
    fraction, stage = 0.0, "starting"
    for line in log.read_text(errors="ignore").splitlines():
        if "ISA mapping batch" in line:
            m = re.search(r"batch (\d+)/(\d+)", line)
            if m and int(m[2]):
                fraction = max(fraction, 0.50 + 0.40 * int(m[1]) / int(m[2]))
                stage = f"mapping {m[1]}/{m[2]}"
            continue
        if "Record-level review" in line:
            fraction, stage = max(fraction, 0.92), "record review"
            continue
        m = re.search(r"Generating metadata batch (\d+)/(\d+)", line)
        if m:
            fraction = max(fraction, 0.20 + 0.15 * int(m[1]) / int(m[2]))
            stage = f"JSON generation {m[1]}/{m[2]}"
            continue
        for marker, value, name in STAGES:
            if marker in line and value > fraction and value < 1.0:
                fraction, stage = value, name
    return fraction, stage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path, help="batch output folder (holds run_status.jsonl)")
    parser.add_argument("--workers", type=int, default=4, help="papers running at once, for the ETA")
    args = parser.parse_args()

    ids = [i["instance_id"] for i in json.loads(MANIFEST.read_text())["instances"]]
    # Same rule as --skip-done: one record that succeeded (or set the paper aside)
    # settles it, whatever was appended later (e.g. the exit of a stopped process).
    records: dict = {}
    status = args.out / "run_status.jsonl"
    if status.exists():
        for line in status.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                records.setdefault(record["instance_id"], []).append(record)
    done = [i for i in ids if any(r["exit"] == 0 for r in records.get(i, []))]
    skipped = [i for i in ids if i not in done and any(r["exit"] == "skipped" for r in records.get(i, []))]
    minutes = [next(r["minutes"] for r in records[i] if r["exit"] == 0) for i in done]

    running = []
    for i in ids:
        log = args.out / f"{i}.log"
        if i in done or i in skipped or not log.exists():
            continue
        if time.time() - log.stat().st_mtime < 1800:  # written to in the last 30 min
            running.append((i, *paper_progress(log)))

    total = len(ids) - len(skipped)
    fraction = (len(done) + sum(f for _, f, _ in running)) / total if total else 0
    print(f"\n  [{bar(fraction)}] {100 * fraction:4.1f}%   {len(done)}/{total} papers done"
          + (f"  ({len(skipped)} set aside)" if skipped else ""))
    print()
    for i, f, stage in running:
        print(f"  {i[8:42]:34s} [{bar(f, 20)}] {100 * f:3.0f}%  {stage}")
    if minutes:
        median = statistics.median(minutes)
        left = total - len(done) - sum(f for _, f, _ in running)
        hours = left * median / 60 / max(args.workers, 1)
        print(f"\n  median {median:.0f} min/paper, {args.workers} at a time: about {hours:.0f} h left"
              f" (~{time.strftime('%m-%d %H:%M', time.localtime(time.time() + hours * 3600))})")
    for i in skipped:
        reason = next(r.get("reason", "") for r in records[i] if r["exit"] == "skipped")
        print(f"  set aside: {i[8:]} - {reason[:90]}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
