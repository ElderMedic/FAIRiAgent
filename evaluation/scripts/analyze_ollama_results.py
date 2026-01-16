#!/usr/bin/env python3
"""
Ollama Evaluation Results Analyzer

Analyzes and compares Ollama model evaluation results.
Can also compare with API model results for comprehensive analysis.

Usage:
    python analyze_ollama_results.py --runs-dir evaluation/runs/ollama_20260116
    python analyze_ollama_results.py --runs-dir evaluation/runs/ollama_20260116 --compare-api-runs evaluation/runs/api_results
    python analyze_ollama_results.py --runs-dir evaluation/runs/ollama_20260116 --output-format csv
"""

import sys
import argparse
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import statistics

# Project paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
EVAL_DIR = PROJECT_ROOT / "evaluation"


def load_evaluation_results(runs_dir: Path) -> dict:
    """Load evaluation results from a runs directory."""
    results = {}
    
    # Try to load from ollama_evaluation_results.json first
    summary_file = runs_dir / "ollama_evaluation_results.json"
    if summary_file.exists():
        with open(summary_file, 'r') as f:
            results["summary"] = json.load(f)
    
    # Load individual model results
    for model_dir in runs_dir.iterdir():
        if not model_dir.is_dir() or model_dir.name.startswith("."):
            continue
        
        model_name = model_dir.name
        results[model_name] = {
            "runs": [],
            "metadata": None
        }
        
        # Look for outputs directory
        outputs_dir = model_dir / "outputs"
        if outputs_dir.exists():
            # New structure: model_dir/outputs/config_name/doc_id/run_N/
            for config_dir in outputs_dir.iterdir():
                if not config_dir.is_dir():
                    continue
                for doc_dir in config_dir.iterdir():
                    if not doc_dir.is_dir():
                        continue
                    for run_dir in doc_dir.iterdir():
                        if not run_dir.is_dir():
                            continue
                        
                        # Load eval_result.json
                        eval_result = run_dir / "eval_result.json"
                        if eval_result.exists():
                            with open(eval_result, 'r') as f:
                                results[model_name]["runs"].append(json.load(f))
                        
                        # Load metadata_json.json for metrics
                        metadata_file = run_dir / "metadata_json.json"
                        if metadata_file.exists():
                            try:
                                with open(metadata_file, 'r') as f:
                                    metadata = json.load(f)
                                    results[model_name]["runs"][-1]["metadata"] = metadata
                            except (json.JSONDecodeError, IndexError):
                                pass
        
        # Load run_metadata.json if exists
        metadata_file = model_dir / "run_metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                results[model_name]["metadata"] = json.load(f)
    
    return results


def calculate_model_metrics(model_results: dict, ground_truth: dict = None) -> dict:
    """Calculate metrics for a single model."""
    runs = model_results.get("runs", [])
    
    if not runs:
        return {"error": "No runs found"}
    
    # Basic metrics
    successful_runs = [r for r in runs if r.get("success", False)]
    failed_runs = [r for r in runs if not r.get("success", False)]
    
    metrics = {
        "total_runs": len(runs),
        "successful_runs": len(successful_runs),
        "failed_runs": len(failed_runs),
        "success_rate": len(successful_runs) / len(runs) if runs else 0,
    }
    
    # Runtime statistics
    runtimes = [r.get("runtime_seconds", 0) for r in successful_runs if r.get("runtime_seconds")]
    if runtimes:
        metrics["runtime"] = {
            "mean": statistics.mean(runtimes),
            "std": statistics.stdev(runtimes) if len(runtimes) > 1 else 0,
            "min": min(runtimes),
            "max": max(runtimes),
        }
    
    # Fields extracted statistics
    fields = [r.get("n_fields_extracted", 0) for r in successful_runs]
    if fields:
        metrics["fields_extracted"] = {
            "mean": statistics.mean(fields),
            "std": statistics.stdev(fields) if len(fields) > 1 else 0,
            "min": min(fields),
            "max": max(fields),
        }
    
    # Confidence statistics (if available)
    confidences = []
    for r in successful_runs:
        if "metadata" in r and isinstance(r["metadata"], dict):
            for field, value in r["metadata"].items():
                if isinstance(value, dict) and "confidence" in value:
                    conf = value.get("confidence")
                    if isinstance(conf, (int, float)):
                        confidences.append(conf)
    
    if confidences:
        metrics["confidence"] = {
            "mean": statistics.mean(confidences),
            "std": statistics.stdev(confidences) if len(confidences) > 1 else 0,
        }
    
    return metrics


def compare_with_ground_truth(model_results: dict, ground_truth: dict) -> dict:
    """Calculate precision, recall, F1 against ground truth."""
    if not ground_truth:
        return {}
    
    runs = model_results.get("runs", [])
    successful_runs = [r for r in runs if r.get("success", False)]
    
    if not successful_runs:
        return {"error": "No successful runs"}
    
    gt_fields = set()
    for doc in ground_truth.get("documents", []):
        for field in doc.get("fields", []):
            gt_fields.add(field.get("field_name", ""))
    
    metrics_per_run = []
    
    for run in successful_runs:
        if "metadata" not in run or not isinstance(run["metadata"], dict):
            continue
        
        extracted_fields = set(run["metadata"].keys())
        
        # Calculate TP, FP, FN
        tp = len(extracted_fields & gt_fields)
        fp = len(extracted_fields - gt_fields)
        fn = len(gt_fields - extracted_fields)
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        
        metrics_per_run.append({
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "completeness": recall  # Same as recall in this context
        })
    
    if not metrics_per_run:
        return {}
    
    return {
        "precision": {
            "mean": statistics.mean([m["precision"] for m in metrics_per_run]),
            "std": statistics.stdev([m["precision"] for m in metrics_per_run]) if len(metrics_per_run) > 1 else 0,
        },
        "recall": {
            "mean": statistics.mean([m["recall"] for m in metrics_per_run]),
            "std": statistics.stdev([m["recall"] for m in metrics_per_run]) if len(metrics_per_run) > 1 else 0,
        },
        "f1": {
            "mean": statistics.mean([m["f1"] for m in metrics_per_run]),
            "std": statistics.stdev([m["f1"] for m in metrics_per_run]) if len(metrics_per_run) > 1 else 0,
        },
    }


def generate_comparison_table(all_results: dict, ground_truth: dict = None) -> str:
    """Generate a markdown comparison table."""
    lines = []
    lines.append("# Ollama Model Evaluation Results\n")
    lines.append(f"Generated: {datetime.now().isoformat()}\n")
    
    # Summary table
    lines.append("## Model Performance Summary\n")
    lines.append("| Model | Success Rate | Avg Runtime (s) | Avg Fields | Avg Confidence |")
    lines.append("|-------|-------------|-----------------|------------|----------------|")
    
    model_metrics = {}
    for model_name, model_data in all_results.items():
        if model_name in ["summary"] or not isinstance(model_data, dict):
            continue
        
        metrics = calculate_model_metrics(model_data, ground_truth)
        model_metrics[model_name] = metrics
        
        success_rate = f"{metrics.get('success_rate', 0)*100:.1f}%"
        runtime = metrics.get("runtime", {})
        runtime_str = f"{runtime.get('mean', 0):.1f} ± {runtime.get('std', 0):.1f}" if runtime else "N/A"
        fields = metrics.get("fields_extracted", {})
        fields_str = f"{fields.get('mean', 0):.1f} ± {fields.get('std', 0):.1f}" if fields else "N/A"
        conf = metrics.get("confidence", {})
        conf_str = f"{conf.get('mean', 0):.2f}" if conf else "N/A"
        
        lines.append(f"| {model_name} | {success_rate} | {runtime_str} | {fields_str} | {conf_str} |")
    
    lines.append("")
    
    # Detailed metrics if ground truth available
    if ground_truth:
        lines.append("## Quality Metrics (vs Ground Truth)\n")
        lines.append("| Model | Precision | Recall | F1 Score |")
        lines.append("|-------|-----------|--------|----------|")
        
        for model_name, model_data in all_results.items():
            if model_name in ["summary"] or not isinstance(model_data, dict):
                continue
            
            gt_metrics = compare_with_ground_truth(model_data, ground_truth)
            if "error" in gt_metrics:
                continue
            
            precision = gt_metrics.get("precision", {})
            recall = gt_metrics.get("recall", {})
            f1 = gt_metrics.get("f1", {})
            
            prec_str = f"{precision.get('mean', 0):.3f} ± {precision.get('std', 0):.3f}" if precision else "N/A"
            rec_str = f"{recall.get('mean', 0):.3f} ± {recall.get('std', 0):.3f}" if recall else "N/A"
            f1_str = f"{f1.get('mean', 0):.3f} ± {f1.get('std', 0):.3f}" if f1 else "N/A"
            
            lines.append(f"| {model_name} | {prec_str} | {rec_str} | {f1_str} |")
        
        lines.append("")
    
    # Runtime comparison
    lines.append("## Runtime Analysis\n")
    lines.append("| Model | Min (s) | Max (s) | Mean (s) | Std (s) |")
    lines.append("|-------|---------|---------|----------|---------|")
    
    for model_name, metrics in model_metrics.items():
        runtime = metrics.get("runtime", {})
        if runtime:
            lines.append(f"| {model_name} | {runtime.get('min', 0):.1f} | {runtime.get('max', 0):.1f} | {runtime.get('mean', 0):.1f} | {runtime.get('std', 0):.1f} |")
    
    return "\n".join(lines)


def generate_csv_output(all_results: dict, ground_truth: dict = None) -> str:
    """Generate CSV output for further analysis."""
    lines = []
    lines.append("model,success_rate,runtime_mean,runtime_std,fields_mean,fields_std,confidence_mean,precision,recall,f1")
    
    for model_name, model_data in all_results.items():
        if model_name in ["summary"] or not isinstance(model_data, dict):
            continue
        
        metrics = calculate_model_metrics(model_data, ground_truth)
        gt_metrics = compare_with_ground_truth(model_data, ground_truth) if ground_truth else {}
        
        row = [
            model_name,
            f"{metrics.get('success_rate', 0):.4f}",
            f"{metrics.get('runtime', {}).get('mean', 0):.2f}",
            f"{metrics.get('runtime', {}).get('std', 0):.2f}",
            f"{metrics.get('fields_extracted', {}).get('mean', 0):.2f}",
            f"{metrics.get('fields_extracted', {}).get('std', 0):.2f}",
            f"{metrics.get('confidence', {}).get('mean', 0):.4f}",
            f"{gt_metrics.get('precision', {}).get('mean', 0):.4f}",
            f"{gt_metrics.get('recall', {}).get('mean', 0):.4f}",
            f"{gt_metrics.get('f1', {}).get('mean', 0):.4f}",
        ]
        lines.append(",".join(row))
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Ollama model evaluation results",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("--runs-dir", type=Path, required=True,
                       help="Directory containing Ollama evaluation runs")
    parser.add_argument("--ground-truth", type=Path,
                       default=EVAL_DIR / "datasets/annotated/ground_truth_filtered.json",
                       help="Ground truth JSON file for quality metrics")
    parser.add_argument("--compare-api-runs", type=Path, default=None,
                       help="Directory containing API model runs for comparison")
    parser.add_argument("--output-format", choices=["markdown", "csv", "json"], default="markdown",
                       help="Output format (default: markdown)")
    parser.add_argument("--output-file", type=Path, default=None,
                       help="Output file path (default: stdout)")
    
    args = parser.parse_args()
    
    if not args.runs_dir.exists():
        print(f"❌ Runs directory not found: {args.runs_dir}")
        return 1
    
    print(f"📁 Loading results from: {args.runs_dir}")
    
    # Load Ollama results
    results = load_evaluation_results(args.runs_dir)
    
    # Load ground truth
    ground_truth = None
    if args.ground_truth.exists():
        with open(args.ground_truth, 'r') as f:
            ground_truth = json.load(f)
        print(f"📋 Loaded ground truth: {args.ground_truth}")
    
    # Load API results for comparison if specified
    if args.compare_api_runs and args.compare_api_runs.exists():
        api_results = load_evaluation_results(args.compare_api_runs)
        results.update({f"api_{k}": v for k, v in api_results.items() if k != "summary"})
        print(f"📊 Loaded API results for comparison: {args.compare_api_runs}")
    
    # Generate output
    if args.output_format == "markdown":
        output = generate_comparison_table(results, ground_truth)
    elif args.output_format == "csv":
        output = generate_csv_output(results, ground_truth)
    else:  # json
        output = json.dumps({
            model: calculate_model_metrics(data, ground_truth)
            for model, data in results.items()
            if model != "summary" and isinstance(data, dict)
        }, indent=2)
    
    # Write output
    if args.output_file:
        with open(args.output_file, 'w') as f:
            f.write(output)
        print(f"✅ Results saved to: {args.output_file}")
    else:
        print("\n" + output)
    
    # Save JSON metrics regardless
    metrics_file = args.runs_dir / "analysis_metrics.json"
    metrics = {
        model: calculate_model_metrics(data, ground_truth)
        for model, data in results.items()
        if model != "summary" and isinstance(data, dict)
    }
    with open(metrics_file, 'w') as f:
        json.dump(metrics, f, indent=2)
    print(f"📊 Metrics saved to: {metrics_file}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
