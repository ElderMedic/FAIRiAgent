#!/usr/bin/env python3
"""Run a local-ollama smoke evaluation for the paper bundle."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from evaluation.scripts.run_batch_evaluation import BatchEvaluationRunner


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAPER_ROOT = PROJECT_ROOT / "evaluation" / "paper_experiments_v1"
GROUND_TRUTH = PROJECT_ROOT / "evaluation" / "datasets" / "annotated" / "ground_truth_filtered.json"
DEFAULT_ENV = PROJECT_ROOT / "evaluation" / "config" / "env.evaluation"
CONFIG_DIR = PROJECT_ROOT / "evaluation" / "config" / "model_configs"

MODEL_CONFIGS = {
    "qwen3.5-9b":  CONFIG_DIR / "ollama_qwen3.5-9b_v1.4.0.env",
    "qwen3.6-27b": CONFIG_DIR / "ollama_qwen3.6-27b_v1.4.0.env",
    "qwen3.6-35b": CONFIG_DIR / "ollama_qwen3.6-35b_v1.4.0.env",
    "gemma4-31b":  CONFIG_DIR / "ollama_gemma4-31b_v1.4.0.env",
    "gpt-oss-20b": CONFIG_DIR / "ollama_gpt-oss-20b_v1.5.0.env",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local Ollama smoke evaluation for FAIRiAgent paper bundle")
    parser.add_argument("--doc", default="earthworm", help="Document ID to keep in the smoke run")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["qwen3.5-9b"],
        choices=sorted(MODEL_CONFIGS.keys()),
        help="Local ollama model presets to run",
    )
    parser.add_argument("--repeats", type=int, default=1, help="Number of repeats per selected document")
    parser.add_argument("--workers", type=int, default=1, help="Parallel workers per document")
    parser.add_argument("--timeout", type=int, default=3600, help="Per-document timeout in seconds")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PAPER_ROOT / "runs" / "local_smoke",
        help="Output directory under paper_experiments_v1",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    model_configs = [MODEL_CONFIGS[name] for name in args.models]
    exclude_documents = [
        doc_id
        for doc_id in [
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
        if doc_id != args.doc
    ]

    runner = BatchEvaluationRunner(
        ground_truth_path=GROUND_TRUTH,
        model_configs=model_configs,
        output_dir=args.output_dir,
        env_file=DEFAULT_ENV,
        exclude_documents=exclude_documents,
        timeout=args.timeout,
    )
    await runner.run_all(repeats=args.repeats, max_workers=args.workers)


if __name__ == "__main__":
    asyncio.run(main())
