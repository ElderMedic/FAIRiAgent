#!/usr/bin/env python3
"""
Full Evaluation Analysis Script

Integrates results from both API models and Ollama models,
computes confidence-aware metrics, and generates comprehensive reports.

Usage:
    python run_full_analysis.py --api-runs evaluation/runs/api_results --ollama-runs evaluation/runs/ollama_20260116
    python run_full_analysis.py --runs-dir evaluation/runs  # Auto-detect all runs
"""

import sys
import argparse
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import statistics
from typing import Dict, List, Any, Optional, Tuple

# Project paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
EVAL_DIR = PROJECT_ROOT / "evaluation"

# Confidence threshold for high-confidence excess fields
HIGH_CONFIDENCE_THRESHOLD = 0.8


def load_ground_truth(gt_path: Path) -> Dict:
    """Load ground truth data."""
    with open(gt_path, 'r') as f:
        return json.load(f)


def get_gt_fields_for_document(ground_truth: Dict, doc_id: str) -> set:
    """Get ground truth field names for a specific document."""
    for doc in ground_truth.get("documents", []):
        if doc.get("document_id") == doc_id:
            return set(f.get("field_name", "") for f in doc.get("fields", []))
    return set()


def extract_run_results(runs_dir: Path) -> List[Dict]:
    """Extract all run results from a directory structure."""
    results = []
    
    # Handle different directory structures
    # Structure 1: runs_dir/model_name/outputs/config/doc_id/run_N/
    # Structure 2: runs_dir/outputs/config/doc_id/run_N/
    
    for path in runs_dir.rglob("eval_result.json"):
        try:
            with open(path, 'r') as f:
                result = json.load(f)
            
            # Try to load metadata_json.json from same directory
            metadata_path = path.parent / "metadata_json.json"
            if metadata_path.exists():
                with open(metadata_path, 'r') as f:
                    result["extracted_metadata"] = json.load(f)
            
            # Infer model name from path
            parts = path.parts
            if "outputs" in parts:
                outputs_idx = parts.index("outputs")
                if outputs_idx > 0:
                    result["inferred_model"] = parts[outputs_idx - 1]
            
            results.append(result)
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️  Failed to load {path}: {e}")
    
    return results


def calculate_metrics_for_run(
    run_result: Dict,
    gt_fields: set,
    confidence_threshold: float = HIGH_CONFIDENCE_THRESHOLD
) -> Dict:
    """Calculate confidence-aware metrics for a single run."""
    metadata = run_result.get("extracted_metadata", {})
    
    if not metadata:
        return {"error": "No metadata found"}
    
    extracted_fields = set(metadata.keys())
    
    # Basic metrics
    tp = extracted_fields & gt_fields
    fp = extracted_fields - gt_fields
    fn = gt_fields - extracted_fields
    
    # Confidence-aware: separate high/low confidence excess fields
    high_conf_excess = set()
    low_conf_excess = set()
    
    for field in fp:
        field_data = metadata.get(field, {})
        if isinstance(field_data, dict):
            conf = field_data.get("confidence", 0)
            if isinstance(conf, (int, float)) and conf >= confidence_threshold:
                high_conf_excess.add(field)
            else:
                low_conf_excess.add(field)
        else:
            low_conf_excess.add(field)
    
    # Standard metrics
    precision = len(tp) / (len(tp) + len(fp)) if (len(tp) + len(fp)) > 0 else 0
    recall = len(tp) / (len(tp) + len(fn)) if (len(tp) + len(fn)) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    # Adjusted metrics (only penalize low-confidence excess)
    adj_precision = len(tp) / (len(tp) + len(low_conf_excess)) if (len(tp) + len(low_conf_excess)) > 0 else 0
    adj_f1 = 2 * adj_precision * recall / (adj_precision + recall) if (adj_precision + recall) > 0 else 0
    
    # Discovery bonus
    discovery_bonus = len(high_conf_excess) / len(gt_fields) if gt_fields else 0
    
    # Overall confidence
    confidences = []
    for field, data in metadata.items():
        if isinstance(data, dict) and "confidence" in data:
            conf = data.get("confidence")
            if isinstance(conf, (int, float)):
                confidences.append(conf)
    
    overall_confidence = statistics.mean(confidences) if confidences else 0
    
    # Completeness (same as recall)
    completeness = recall
    
    # Aggregate scores
    original_score = 0.4 * completeness + 0.4 * f1 + 0.2 * overall_confidence
    adjusted_score = 0.4 * completeness + 0.4 * adj_f1 + 0.2 * overall_confidence
    
    return {
        "tp": len(tp),
        "fp": len(fp),
        "fn": len(fn),
        "high_conf_excess": len(high_conf_excess),
        "low_conf_excess": len(low_conf_excess),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "adj_precision": adj_precision,
        "adj_f1": adj_f1,
        "completeness": completeness,
        "discovery_bonus": discovery_bonus,
        "overall_confidence": overall_confidence,
        "original_score": original_score,
        "adjusted_score": adjusted_score,
        "n_fields_extracted": len(extracted_fields),
        "n_gt_fields": len(gt_fields),
    }


def aggregate_model_metrics(run_metrics: List[Dict]) -> Dict:
    """Aggregate metrics across multiple runs for a model."""
    if not run_metrics:
        return {"error": "No metrics to aggregate"}
    
    # Filter out error results
    valid_metrics = [m for m in run_metrics if "error" not in m]
    
    if not valid_metrics:
        return {"error": "All runs failed"}
    
    aggregated = {}
    metric_keys = [
        "precision", "recall", "f1", "adj_precision", "adj_f1",
        "completeness", "discovery_bonus", "overall_confidence",
        "original_score", "adjusted_score", "n_fields_extracted",
        "high_conf_excess", "low_conf_excess"
    ]
    
    for key in metric_keys:
        values = [m[key] for m in valid_metrics if key in m]
        if values:
            aggregated[key] = {
                "mean": statistics.mean(values),
                "std": statistics.stdev(values) if len(values) > 1 else 0,
                "min": min(values),
                "max": max(values),
            }
    
    aggregated["n_runs"] = len(valid_metrics)
    aggregated["n_failed"] = len(run_metrics) - len(valid_metrics)
    
    return aggregated


def group_results_by_model(all_results: List[Dict]) -> Dict[str, List[Dict]]:
    """Group results by model name."""
    grouped = defaultdict(list)
    
    for result in all_results:
        model = result.get("config_name") or result.get("inferred_model") or "unknown"
        grouped[model].append(result)
    
    return dict(grouped)


def generate_ranking_table(model_aggregates: Dict[str, Dict], sort_by: str = "adjusted_score") -> str:
    """Generate a ranking table sorted by specified metric."""
    lines = []
    
    # Sort models by the specified metric
    sorted_models = sorted(
        model_aggregates.items(),
        key=lambda x: x[1].get(sort_by, {}).get("mean", 0) if isinstance(x[1].get(sort_by), dict) else 0,
        reverse=True
    )
    
    lines.append(f"## Model Rankings (by {sort_by})\n")
    lines.append("| Rank | Model | Adj Score | Orig Score | Completeness | Adj F1 | F1 | Discovery | Runtime |")
    lines.append("|------|-------|-----------|------------|--------------|--------|-----|-----------|---------|")
    
    medals = ["🥇", "🥈", "🥉"]
    
    for idx, (model, metrics) in enumerate(sorted_models):
        rank = medals[idx] if idx < 3 else str(idx + 1)
        
        adj_score = metrics.get("adjusted_score", {}).get("mean", 0)
        orig_score = metrics.get("original_score", {}).get("mean", 0)
        completeness = metrics.get("completeness", {}).get("mean", 0) * 100
        adj_f1 = metrics.get("adj_f1", {}).get("mean", 0)
        f1 = metrics.get("f1", {}).get("mean", 0)
        discovery = metrics.get("discovery_bonus", {}).get("mean", 0)
        
        # Try to get runtime if available
        runtime = "N/A"
        
        lines.append(
            f"| {rank} | **{model}** | {adj_score:.3f} | {orig_score:.3f} | "
            f"{completeness:.1f}% | {adj_f1:.3f} | {f1:.3f} | {discovery:.2f} | {runtime} |"
        )
    
    return "\n".join(lines)


def generate_full_report(
    model_aggregates: Dict[str, Dict],
    output_dir: Path
) -> str:
    """Generate a full analysis report."""
    lines = []
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    lines.append("# FAIRiAgent Comprehensive Evaluation Report\n")
    lines.append(f"**Generated**: {timestamp}\n")
    lines.append(f"**Models Evaluated**: {len(model_aggregates)}\n")
    
    # Separate API and Ollama models
    api_models = {k: v for k, v in model_aggregates.items() if not k.startswith("ollama_")}
    ollama_models = {k: v for k, v in model_aggregates.items() if k.startswith("ollama_")}
    
    lines.append("---\n")
    
    # Overall ranking
    lines.append(generate_ranking_table(model_aggregates, "adjusted_score"))
    lines.append("\n---\n")
    
    # API Models section
    if api_models:
        lines.append("## API Models Performance\n")
        lines.append(generate_ranking_table(api_models, "adjusted_score"))
        lines.append("\n")
    
    # Ollama Models section
    if ollama_models:
        lines.append("## Ollama Models Performance\n")
        lines.append(generate_ranking_table(ollama_models, "adjusted_score"))
        lines.append("\n")
    
    # Detailed metrics table
    lines.append("---\n")
    lines.append("## Detailed Metrics\n")
    lines.append("| Model | Precision | Adj Prec | Recall | High Conf Excess | Low Conf Excess | Runs |")
    lines.append("|-------|-----------|----------|--------|------------------|-----------------|------|")
    
    for model, metrics in sorted(model_aggregates.items()):
        prec = metrics.get("precision", {}).get("mean", 0)
        adj_prec = metrics.get("adj_precision", {}).get("mean", 0)
        recall = metrics.get("recall", {}).get("mean", 0)
        high_conf = metrics.get("high_conf_excess", {}).get("mean", 0)
        low_conf = metrics.get("low_conf_excess", {}).get("mean", 0)
        n_runs = metrics.get("n_runs", 0)
        
        lines.append(
            f"| {model} | {prec:.3f} | {adj_prec:.3f} | {recall:.3f} | "
            f"{high_conf:.1f} | {low_conf:.1f} | {n_runs} |"
        )
    
    lines.append("\n---\n")
    
    # Key findings
    lines.append("## Key Findings\n")
    
    # Best overall
    if model_aggregates:
        best_model = max(
            model_aggregates.items(),
            key=lambda x: x[1].get("adjusted_score", {}).get("mean", 0) if isinstance(x[1].get("adjusted_score"), dict) else 0
        )
        lines.append(f"- **Best Overall**: {best_model[0]} (adjusted score: {best_model[1].get('adjusted_score', {}).get('mean', 0):.3f})\n")
        
        # Best discovery
        best_discovery = max(
            model_aggregates.items(),
            key=lambda x: x[1].get("discovery_bonus", {}).get("mean", 0) if isinstance(x[1].get("discovery_bonus"), dict) else 0
        )
        lines.append(f"- **Highest Discovery**: {best_discovery[0]} (discovery bonus: {best_discovery[1].get('discovery_bonus', {}).get('mean', 0):.2f})\n")
        
        # Best completeness
        best_completeness = max(
            model_aggregates.items(),
            key=lambda x: x[1].get("completeness", {}).get("mean", 0) if isinstance(x[1].get("completeness"), dict) else 0
        )
        lines.append(f"- **Highest Completeness**: {best_completeness[0]} ({best_completeness[1].get('completeness', {}).get('mean', 0)*100:.1f}%)\n")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Run full analysis on all evaluation results",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("--runs-dir", type=Path, default=None,
                       help="Single directory containing all runs (auto-detect structure)")
    parser.add_argument("--api-runs", type=Path, default=None,
                       help="Directory containing API model runs")
    parser.add_argument("--ollama-runs", type=Path, default=None,
                       help="Directory containing Ollama model runs")
    parser.add_argument("--ground-truth", type=Path,
                       default=EVAL_DIR / "datasets/annotated/ground_truth_filtered.json",
                       help="Ground truth JSON file")
    parser.add_argument("--output-dir", type=Path, default=None,
                       help="Output directory for reports (default: same as runs-dir)")
    parser.add_argument("--confidence-threshold", type=float, default=HIGH_CONFIDENCE_THRESHOLD,
                       help=f"Confidence threshold for high-confidence fields (default: {HIGH_CONFIDENCE_THRESHOLD})")
    
    args = parser.parse_args()
    
    # Determine runs directories
    runs_dirs = []
    if args.runs_dir:
        runs_dirs.append(args.runs_dir)
    if args.api_runs:
        runs_dirs.append(args.api_runs)
    if args.ollama_runs:
        runs_dirs.append(args.ollama_runs)
    
    if not runs_dirs:
        # Default to evaluation/runs
        runs_dirs = [EVAL_DIR / "runs"]
    
    # Load ground truth
    if not args.ground_truth.exists():
        print(f"❌ Ground truth not found: {args.ground_truth}")
        return 1
    
    ground_truth = load_ground_truth(args.ground_truth)
    print(f"📋 Loaded ground truth with {len(ground_truth.get('documents', []))} documents")
    
    # Load all results
    all_results = []
    for runs_dir in runs_dirs:
        if runs_dir.exists():
            print(f"📁 Loading results from: {runs_dir}")
            results = extract_run_results(runs_dir)
            all_results.extend(results)
            print(f"   Found {len(results)} run results")
    
    if not all_results:
        print("❌ No results found")
        return 1
    
    print(f"\n📊 Total runs loaded: {len(all_results)}")
    
    # Group by model
    grouped = group_results_by_model(all_results)
    print(f"📋 Models found: {list(grouped.keys())}")
    
    # Calculate metrics for each run
    model_metrics = {}
    for model, runs in grouped.items():
        run_metrics = []
        for run in runs:
            doc_id = run.get("document_id", "unknown")
            gt_fields = get_gt_fields_for_document(ground_truth, doc_id)
            
            if gt_fields:
                metrics = calculate_metrics_for_run(run, gt_fields, args.confidence_threshold)
                run_metrics.append(metrics)
        
        model_metrics[model] = aggregate_model_metrics(run_metrics)
    
    # Generate report
    output_dir = args.output_dir or (runs_dirs[0] if len(runs_dirs) == 1 else EVAL_DIR / "analysis" / "output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    report = generate_full_report(model_metrics, output_dir)
    
    # Save report
    report_file = output_dir / f"full_analysis_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(report_file, 'w') as f:
        f.write(report)
    print(f"\n📄 Report saved to: {report_file}")
    
    # Save metrics JSON
    metrics_file = output_dir / "full_analysis_metrics.json"
    with open(metrics_file, 'w') as f:
        json.dump(model_metrics, f, indent=2)
    print(f"📊 Metrics saved to: {metrics_file}")
    
    # Print summary to console
    print("\n" + "="*70)
    print(report)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
