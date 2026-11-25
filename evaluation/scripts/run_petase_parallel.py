#!/usr/bin/env python3
"""Run FAIRiAgent on many PETase papers in parallel, one isolated run per paper.

Each paper gets its own input directory holding only the manifest's main PDF
and supplementary files (never the expert annotation that sits next to the PDF
in the raw batch folders), its own output directory, and a per-run env file:
the base env plus overrides that keep runs independent (no shared memory layer,
in-memory checkpoints). Wall time and exit status are written to
``<out>/run_status.jsonl`` so a long batch can be resumed with --skip-done.

Example:
  python evaluation/scripts/run_petase_parallel.py \
      --env path/to/deepseek.env --out evaluation/runs/petase_batch_X \
      --split held_out --papers 8 --workers 4 --set FAIRIFIER_LLM_BATCH_CONCURRENCY=6
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "evaluation/datasets/petase_benchmark_manifest.json"

# Keep paper runs independent and parallel-safe.
ISOLATION = {
    "MEM0_ENABLED": "false",
    "CHECKPOINTER_BACKEND": "memory",
}


def select(instances, split, ids, n):
    chosen = [i for i in instances if (not split or i["split"] == split)]
    if ids:
        wanted = set(ids)
        chosen = [i for i in instances if i["instance_id"] in wanted]
    return chosen[:n] if n else chosen


def prepare_input(instance, inputs_dir: Path) -> Path:
    folder = inputs_dir / instance["instance_id"]
    folder.mkdir(parents=True, exist_ok=True)
    for rel in [instance["source_path"], *instance.get("supplementary_paths", [])]:
        src = ROOT / rel
        if not src.is_file():
            raise FileNotFoundError(src)
        link = folder / src.name
        if not link.exists():
            link.symlink_to(src)
    return folder


def run_one(instance, args, env_file: Path, status_path: Path):
    paper_out = args.out / instance["instance_id"]
    inputs = prepare_input(instance, args.out / "_inputs")
    # A single main file is passed directly so its name stays the source name.
    target = inputs if instance.get("supplementary_paths") else inputs / Path(instance["source_path"]).name
    cmd = [
        sys.executable, "run_fairifier.py", "process", str(target),
        "-o", str(paper_out), "-p", instance["instance_id"], "-e", str(env_file),
    ]
    log = args.out / f"{instance['instance_id']}.log"
    # A rerun keeps the earlier attempt's outputs and log as traces.
    if paper_out.exists() or log.exists():
        keep = args.out / "_attempts" / instance["instance_id"] / time.strftime("%Y%m%d-%H%M%S")
        keep.mkdir(parents=True, exist_ok=True)
        for old in (paper_out, log):
            if old.exists():
                shutil.move(str(old), str(keep / old.name))
    started = time.time()
    with open(log, "w") as handle:
        try:
            code = subprocess.run(
                cmd, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
                timeout=args.timeout, env={**os.environ, "PATH": os.environ.get("PATH", "")},
            ).returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
    # A run that lost its model mid-way still exits 0 with a degraded record;
    # mark it so --skip-done runs it again.
    failed_calls = sum(1 for line in log.read_text(errors="ignore").splitlines() if "call failed" in line)
    if code == 0 and failed_calls >= args.degraded_after:
        code = "degraded"
    record = {
        "instance_id": instance["instance_id"], "split": instance["split"],
        "exit": code, "minutes": round((time.time() - started) / 60, 1),
        "metadata": str(next(paper_out.rglob("metadata.json"), "")) if paper_out.exists() else "",
        "failed_llm_calls": failed_calls,
    }
    with open(status_path, "a") as handle:
        handle.write(json.dumps(record) + "\n")
    print(json.dumps(record), flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--split", choices=["held_out", "development"], default=None)
    parser.add_argument("--ids", nargs="*", default=None)
    parser.add_argument("--papers", type=int, default=0, help="0 = all selected")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=12 * 3600)
    parser.add_argument("--overlay", type=Path, action="append", default=[],
                        help="env file applied after --env (e.g. evaluation/config/production/*.overlay.env)")
    parser.add_argument("--set", action="append", default=[], help="KEY=VALUE env override")
    parser.add_argument("--skip-done", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print how many papers would run, then exit")
    parser.add_argument("--degraded-after", type=int, default=3,
                        help="mark a run degraded (rerun by --skip-done) after this many failed LLM calls")
    args = parser.parse_args()
    if args.ids is not None and not args.ids:
        parser.error("--ids was given without any instance id (it would select every paper)")
    args.out = args.out if args.out.is_absolute() else ROOT / args.out
    args.out.mkdir(parents=True, exist_ok=True)

    overrides = dict(ISOLATION)
    overrides.update(item.split("=", 1) for item in args.set)
    overlays = "".join(
        f"\n# --- overlay {path} ---\n" + (path if path.is_absolute() else ROOT / path).read_text()
        for path in args.overlay
    )
    env_text = (args.env.read_text() + overlays + "\n# --- run_petase_parallel overrides ---\n"
                + "".join(f"{k}={v}\n" for k, v in overrides.items()))
    # Named by content: two runners sharing --out with different envs (e.g. one
    # Ollama per GPU) must not overwrite each other's settings.
    env_file = args.out / f"run_{hashlib.sha256(env_text.encode()).hexdigest()[:8]}.env"
    env_file.write_text(env_text)
    os.chmod(env_file, 0o600)  # holds API keys from the base env

    instances = select(json.loads(MANIFEST.read_text())["instances"], args.split, args.ids, args.papers)
    status_path = args.out / "run_status.jsonl"
    if args.skip_done and status_path.exists():
        done = {json.loads(line)["instance_id"] for line in status_path.read_text().splitlines()
                if line.strip() and json.loads(line)["exit"] in (0, "skipped")}
        instances = [i for i in instances if i["instance_id"] not in done]
    print(f"{len(instances)} papers, {args.workers} workers -> {args.out}", flush=True)
    if args.dry_run:
        return 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(lambda inst: run_one(inst, args, env_file, status_path), instances))


if __name__ == "__main__":
    main()
