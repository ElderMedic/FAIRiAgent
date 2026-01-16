#!/usr/bin/env python3
"""
External API Models Evaluation Runner

Runs FAIRiAgent evaluation on all external API models (OpenAI, Anthropic, Qwen).
Models can run in parallel since they use different API endpoints.

Usage:
    python run_api_evaluation.py --repeats 10
    python run_api_evaluation.py --repeats 10 --models anthropic_sonnet openai_gpt4.1
    python run_api_evaluation.py --list-models
"""

import sys
import argparse
import json
import subprocess
from pathlib import Path
from datetime import datetime
import os
import time

# Force unbuffered output
os.environ['PYTHONUNBUFFERED'] = '1'

# Project paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
EVAL_DIR = PROJECT_ROOT / "evaluation"
CONFIG_DIR = EVAL_DIR / "config"
MODEL_CONFIGS_DIR = CONFIG_DIR / "model_configs"

# Default API model configs (in order of evaluation)
DEFAULT_API_MODELS = [
    "anthropic_sonnet",
    "anthropic_haiku",
    "openai_gpt4.1",
    "openai_gpt5",
    "openai_o3",
    "qwen_max",
    "qwen_plus",
    "qwen_flash",
]


def log(message: str):
    """Print with timestamp and flush."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def get_available_api_configs() -> list:
    """Get all available API model configs (excluding ollama)."""
    configs = []
    for f in MODEL_CONFIGS_DIR.glob("*.env"):
        if not f.stem.startswith("ollama") and not f.stem.endswith(".template"):
            configs.append(f.stem)
    return sorted(configs)


def run_single_model_evaluation(
    config_name: str,
    output_dir: Path,
    ground_truth: Path,
    env_file: Path,
    repeats: int = 10,
    workers: int = 4,
    exclude_documents: list = None
) -> dict:
    """Run evaluation for a single model."""
    config_path = MODEL_CONFIGS_DIR / f"{config_name}.env"
    
    if not config_path.exists():
        log(f"   ❌ Config not found: {config_path}")
        return {"success": False, "error": f"Config not found: {config_path}"}
    
    # Extract model info from config
    provider = None
    model_name = None
    with open(config_path, 'r') as f:
        for line in f:
            if line.startswith("LLM_PROVIDER="):
                provider = line.split("=", 1)[1].strip()
            elif line.startswith("FAIRIFIER_LLM_MODEL="):
                model_name = line.split("=", 1)[1].strip()
    
    log(f"   📦 Provider: {provider}, Model: {model_name}")
    log(f"   📄 Config: {config_path}")
    
    # Create model-specific output directory
    model_output_dir = output_dir / config_name
    model_output_dir.mkdir(parents=True, exist_ok=True)
    log(f"   📁 Output: {model_output_dir}")
    
    start_time = datetime.now()
    log(f"   📊 Starting evaluation (repeats={repeats}, workers={workers})...")
    
    # Run batch evaluation
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "run_batch_evaluation.py"),
        "--env-file", str(env_file),
        "--model-configs", str(config_path),
        "--ground-truth", str(ground_truth),
        "--output-dir", str(model_output_dir),
        "--repeats", str(repeats),
        "--workers", str(workers)  # Parallel runs for API models
    ]
    
    # Add exclude documents if specified
    if exclude_documents:
        cmd.extend(["--exclude-documents"] + exclude_documents)
    
    log(f"   🖥️  Running: {' '.join(cmd[:4])}...")
    
    try:
        # Use Popen to stream output in real-time
        process = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Stream output
        output_lines = []
        for line in process.stdout:
            output_lines.append(line)
            # Print progress indicators
            if any(x in line for x in ['Processing:', 'Run ', '✅', '❌', 'SUCCESS', 'FAILED', 'Loaded']):
                log(f"      {line.strip()}")
        
        process.wait(timeout=7200 * repeats)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        success = process.returncode == 0
        
        # Save run log
        log_file = model_output_dir / "run_log.txt"
        with open(log_file, 'w') as f:
            f.write(f"Command: {' '.join(cmd)}\n")
            f.write(f"Return code: {process.returncode}\n")
            f.write(f"Duration: {duration:.1f}s\n")
            f.write(f"\n=== OUTPUT ===\n{''.join(output_lines)}\n")
        
        return {
            "success": success,
            "config_name": config_name,
            "provider": provider,
            "model_name": model_name,
            "output_dir": str(model_output_dir),
            "duration_seconds": duration,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "return_code": process.returncode,
            "error": None if success else "See run_log.txt for details"
        }
        
    except subprocess.TimeoutExpired:
        log(f"   ❌ TIMEOUT after {7200 * repeats}s")
        return {
            "success": False,
            "config_name": config_name,
            "error": "Timeout expired"
        }
    except Exception as e:
        log(f"   ❌ ERROR: {e}")
        return {
            "success": False,
            "config_name": config_name,
            "error": str(e)
        }


def run_all_evaluations(
    models: list,
    output_dir: Path,
    ground_truth: Path,
    env_file: Path,
    repeats: int = 10,
    workers: int = 4,
    exclude_documents: list = None
) -> dict:
    """Run evaluation for all specified models sequentially."""
    results = {
        "run_metadata": {
            "start_time": datetime.now().isoformat(),
            "models": models,
            "repeats": repeats,
            "workers": workers,
            "output_dir": str(output_dir),
            "exclude_documents": exclude_documents,
        },
        "model_results": {}
    }
    
    total_models = len(models)
    
    for idx, model in enumerate(models, 1):
        log("")
        log("=" * 70)
        log(f"🚀 [{idx}/{total_models}] Running evaluation for: {model}")
        log("=" * 70)
        
        result = run_single_model_evaluation(
            config_name=model,
            output_dir=output_dir,
            ground_truth=ground_truth,
            env_file=env_file,
            repeats=repeats,
            workers=workers,
            exclude_documents=exclude_documents
        )
        
        results["model_results"][model] = result
        
        status = "✅ SUCCESS" if result["success"] else "❌ FAILED"
        duration = result.get("duration_seconds", 0)
        log(f"")
        log(f"   {status} - Duration: {duration/60:.1f} minutes")
        
        # Save intermediate results
        results_file = output_dir / "api_evaluation_results.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        log(f"   💾 Results saved to: {results_file}")
        
        # Small delay between models
        if idx < total_models:
            log(f"")
            log(f"   ⏳ Waiting 10 seconds before next model...")
            time.sleep(10)
    
    results["run_metadata"]["end_time"] = datetime.now().isoformat()
    
    # Final save
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    return results


def main():
    log("=" * 70)
    log("🏁 FAIRiAgent External API Evaluation Runner Started")
    log("=" * 70)
    
    parser = argparse.ArgumentParser(
        description="Run FAIRiAgent evaluation on external API models",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("--models", nargs="+", default=None,
                       help="Model config names to evaluate (without .env extension)")
    parser.add_argument("--repeats", type=int, default=10,
                       help="Number of repeats per document (default: 10)")
    parser.add_argument("--workers", type=int, default=4,
                       help="Number of parallel workers for runs (default: 4)")
    parser.add_argument("--output-dir", type=Path, default=None,
                       help="Output directory (default: evaluation/runs/api_YYYYMMDD_HHMMSS)")
    parser.add_argument("--ground-truth", type=Path, 
                       default=EVAL_DIR / "datasets/annotated/ground_truth_filtered.json",
                       help="Ground truth JSON file")
    parser.add_argument("--env-file", type=Path,
                       default=CONFIG_DIR / "env.evaluation",
                       help="Main evaluation env file")
    parser.add_argument("--exclude-documents", type=str, nargs="+", default=None,
                       help="Document IDs to exclude (e.g., --exclude-documents biorem pomato)")
    parser.add_argument("--list-models", action="store_true",
                       help="List available API model configs and exit")
    
    args = parser.parse_args()
    
    # List models mode
    if args.list_models:
        log("Available API model configs:")
        for config in get_available_api_configs():
            log(f"  - {config}")
        return 0
    
    # Determine models to evaluate
    models = args.models if args.models else DEFAULT_API_MODELS
    
    # Filter to only existing configs
    available = get_available_api_configs()
    models = [m for m in models if m in available]
    
    if not models:
        log("❌ No valid model configs found")
        log(f"   Available configs: {available}")
        return 1
    
    log(f"")
    log(f"📋 Models to evaluate ({len(models)}):")
    for m in models:
        log(f"   - {m}")
    
    # Setup output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = EVAL_DIR / "runs" / f"api_{timestamp}"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    log(f"")
    log(f"📁 Output directory: {output_dir}")
    log(f"📄 Ground truth: {args.ground_truth}")
    log(f"🔁 Repeats per document: {args.repeats}")
    log(f"⚡ Parallel workers: {args.workers}")
    if args.exclude_documents:
        log(f"🚫 Excluding documents: {', '.join(args.exclude_documents)}")
    
    # Run evaluations
    results = run_all_evaluations(
        models=models,
        output_dir=output_dir,
        ground_truth=args.ground_truth,
        env_file=args.env_file,
        repeats=args.repeats,
        workers=args.workers,
        exclude_documents=args.exclude_documents
    )
    
    # Summary
    log("")
    log("=" * 70)
    log("📊 EVALUATION SUMMARY")
    log("=" * 70)
    
    successful = sum(1 for r in results["model_results"].values() if r.get("success"))
    total = len(results["model_results"])
    
    log(f"   Total models: {total}")
    log(f"   Successful: {successful}")
    log(f"   Failed: {total - successful}")
    log(f"")
    log(f"   Results saved to: {output_dir / 'api_evaluation_results.json'}")
    
    # Per-model summary
    log("")
    log("Per-model results:")
    for model, result in results["model_results"].items():
        status = "✅" if result.get("success") else "❌"
        duration = result.get("duration_seconds", 0)
        log(f"   {status} {model}: {duration/60:.1f} min")
    
    log("")
    log("🏁 Evaluation runner finished!")
    
    return 0 if successful == total else 1


if __name__ == "__main__":
    sys.exit(main())
