#!/usr/bin/env python3
"""
Full-Pipeline Runner for Phase-0 paper experiments
====================================================
Wraps the FAIRiAgent full pipeline (LangGraph + Critic + FAIR-DS API) for
a single document and model, storing artifacts in the same directory tree as
the baseline scripts so phase0_broad_n1.sh can treat all four conditions
uniformly.

Output path:
    runs/full_pipeline/<config_name>/<doc_id>/run_<N>/

Compatible with:
    evaluation/scripts/run_batch_evaluation.py  (BatchEvaluationRunner)
    evaluation/scripts/evaluate_outputs.py

Usage:
    python evaluation/paper_experiments_v1/run_full_pipeline.py \\
        --doc earthworm --model qwen3.6-27b [--repeats 1] [--run-start 1]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

PAPER_ROOT = PROJECT_ROOT / "evaluation" / "paper_experiments_v1"
CONFIG_DIR = PROJECT_ROOT / "evaluation" / "config" / "model_configs"
GT_PATH = PROJECT_ROOT / "evaluation" / "datasets" / "annotated" / "ground_truth_filtered.json"
BASE_ENV = PROJECT_ROOT / "evaluation" / "config" / "env.evaluation"

MODEL_CONFIGS = {
    "qwen3.5-9b":  CONFIG_DIR / "ollama_qwen3.5-9b_v1.4.0.env",
    "qwen3.6-27b": CONFIG_DIR / "ollama_qwen3.6-27b_v1.4.0.env",
    "qwen3.6-35b": CONFIG_DIR / "ollama_qwen3.6-35b_v1.4.0.env",
    "gemma4-31b":  CONFIG_DIR / "ollama_gemma4-31b_v1.4.0.env",
    "gpt-oss-20b": CONFIG_DIR / "ollama_gpt-oss-20b_v1.5.0.env",
    "deepseek-v4-pro": CONFIG_DIR / "deepseek_v4-pro_v1.4.0.env",
}

MAIN_DOCS = [
    "aetherobacter_fasciculatus_genome",
    "arabidopsis_vacuolar_srna",
    "biorem",
    "biosensor",
    "earthworm",
    "human_gut_microbiome_temporal",
    "pea_cold_stress",
    "pomato",
    "pseudomonas_recombinase_screen",
    "sea_cucumber_gut_metagenome",
]


def load_doc_path(doc_id: str) -> Path:
    """Return the document file path registered in the ground truth."""
    with open(GT_PATH) as f:
        gt = json.load(f)
    for doc in gt.get("documents", []):
        if doc["document_id"] == doc_id:
            rel = doc.get("document_path", "")
            if not rel:
                raise FileNotFoundError(f"No document_path for '{doc_id}' in ground truth")
            p = PROJECT_ROOT / rel
            if not p.exists():
                raise FileNotFoundError(f"Document not found: {p}")
            return p
    raise KeyError(f"doc_id '{doc_id}' not in ground truth")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Full-pipeline single-doc runner for Phase-0 paper experiments"
    )
    p.add_argument(
        "--doc", required=True, choices=MAIN_DOCS,
        help="Document ID (must be in the 8-document main benchmark)",
    )
    p.add_argument(
        "--model", required=True, choices=sorted(MODEL_CONFIGS.keys()),
        help="Model preset key",
    )
    p.add_argument("--repeats", type=int, default=1,
                   help="Number of independent runs to execute")
    p.add_argument("--run-start", type=int, default=1,
                   help="Index of the first run (default 1); useful for adding extra reps)")
    p.add_argument(
        "--output-dir", type=Path,
        default=PAPER_ROOT / "runs" / "full_pipeline",
        help="Parent output directory (a <config_name>/<doc>/<run_N> subtree is created)",
    )
    p.add_argument("--timeout", type=int, default=7200,
                   help="Per-run timeout in seconds (default 7200 = 2 h)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be run without executing")
    return p.parse_args()


def run_one(
    doc_id: str,
    doc_path: Path,
    model_key: str,
    config_path: Path,
    run_dir: Path,
    run_idx: int,
    timeout: int,
    dry_run: bool,
) -> bool:
    """Run the FAIRiAgent pipeline for one (doc, model, run_idx) cell."""
    config_name = config_path.stem

    if dry_run:
        print(f"  [DRY-RUN] would run: fairifier.cli process {doc_id}  →  {run_dir}")
        return True

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / ".running").touch()

    pid = f"full_{model_key}_{doc_id}_run{run_idx}"
    cmd = [
        sys.executable, "-m", "fairifier.cli",
        "process", str(doc_path),
        "--output-dir", str(run_dir),
        "--env-file", str(config_path),
        "--project-id", pid,
    ]

    env = os.environ.copy()
    cli_log = run_dir / "cli_output.txt"
    start = time.time()

    print(f"  CMD: {' '.join(cmd)}")
    try:
        with open(cli_log, "w") as fout:
            result = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                env=env,
                timeout=timeout,
                stdout=fout,
                stderr=subprocess.STDOUT,
            )
        elapsed = time.time() - start
        success = result.returncode == 0

        # BatchEvaluationRunner searches for metadata.json recursively; check the same way.
        meta_candidates = list(run_dir.rglob("metadata.json"))
        metadata_path = meta_candidates[0] if meta_candidates else None
        if not success and metadata_path is None:
            print(f"  [FAIL] exit={result.returncode}  elapsed={elapsed:.0f}s")
        else:
            found = str(metadata_path.relative_to(run_dir)) if metadata_path else "(none)"
            print(f"  [OK]   exit={result.returncode}  elapsed={elapsed:.0f}s  meta={found}")

        eval_result = {
            "success": success and metadata_path is not None,
            "project_id": pid,
            "document_id": doc_id,
            "config_name": config_name,
            "condition": "full_pipeline",
            "run_idx": run_idx,
            "runtime_seconds": round(elapsed, 1),
            "start_time": datetime.fromtimestamp(start, tz=timezone.utc).isoformat(),
            "end_time": datetime.now(timezone.utc).isoformat(),
            "output_dir": str(run_dir),
            "metadata_json_path": str(metadata_path) if metadata_path else None,
            "cli_log": str(cli_log),
            "returncode": result.returncode,
            "error": None if success else f"returncode={result.returncode}",
        }
        with open(run_dir / "eval_result.json", "w") as f:
            json.dump(eval_result, f, indent=2)

        return eval_result["success"]

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        print(f"  [TIMEOUT] after {elapsed:.0f}s")
        eval_result = {
            "success": False,
            "project_id": pid,
            "document_id": doc_id,
            "config_name": config_name,
            "condition": "full_pipeline",
            "run_idx": run_idx,
            "runtime_seconds": round(elapsed, 1),
            "error": f"timeout after {timeout}s",
        }
        with open(run_dir / "eval_result.json", "w") as f:
            json.dump(eval_result, f, indent=2)
        return False

    except Exception as exc:
        elapsed = time.time() - start
        print(f"  [ERROR] {exc}")
        eval_result = {
            "success": False,
            "project_id": pid,
            "document_id": doc_id,
            "config_name": config_name,
            "condition": "full_pipeline",
            "run_idx": run_idx,
            "runtime_seconds": round(elapsed, 1),
            "error": str(exc),
        }
        with open(run_dir / "eval_result.json", "w") as f:
            json.dump(eval_result, f, indent=2)
        return False

    finally:
        (run_dir / ".running").unlink(missing_ok=True)


def main() -> None:
    args = parse_args()
    config_path = MODEL_CONFIGS[args.model]
    config_name = config_path.stem

    print("=== Full-Pipeline Runner (Phase-0) ===")
    print(f"  Document : {args.doc}")
    print(f"  Model    : {args.model}  ({config_name})")
    print(f"  Repeats  : {args.repeats}  (starting at run_{args.run_start})")
    print(f"  Output   : {args.output_dir / config_name / args.doc}")
    if args.dry_run:
        print("  [DRY-RUN MODE]")

    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}")
        sys.exit(1)

    try:
        doc_path = load_doc_path(args.doc)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print(f"  Doc path : {doc_path}")

    n_ok = 0
    for i in range(args.repeats):
        run_idx = args.run_start + i
        run_dir = args.output_dir / config_name / args.doc / f"run_{run_idx}"
        print(f"\n--- Run {run_idx} ({i + 1}/{args.repeats}) ---")
        ok = run_one(args.doc, doc_path, args.model, config_path,
                     run_dir, run_idx, args.timeout, args.dry_run)
        if ok:
            n_ok += 1

    print(f"\nDone: {n_ok}/{args.repeats} runs succeeded.")
    if n_ok < args.repeats:
        sys.exit(1)


if __name__ == "__main__":
    main()
