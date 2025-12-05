#!/usr/bin/env python3
"""
Aggregate evaluation results from multiple model runs into a single comprehensive report.

This script is useful when running multiple models in parallel (e.g., via run_openai_evaluation.sh)
and you want to combine all results into one evaluation_results.json file.
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime


def aggregate_results(base_dir: Path, output_file: Path = None):
    """
    Aggregate evaluation results from multiple model subdirectories.
    
    Args:
        base_dir: Base directory containing model subdirectories (e.g., gpt5, gpt4.1, o3)
        output_file: Output file path (default: base_dir/evaluation_results_aggregated.json)
    """
    if not base_dir.exists():
        print(f"❌ Error: Base directory not found: {base_dir}")
        return
    
    # Find all model subdirectories
    model_dirs = [d for d in base_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]
    
    print(f"📊 Aggregating results from {len(model_dirs)} model directories...")
    
    aggregated = {
        'aggregation_metadata': {
            'base_dir': str(base_dir),
            'aggregation_time': datetime.now().isoformat(),
            'n_models': len(model_dirs)
        },
        'per_model_results': {},
        'model_comparison': {}
    }
    
    # Load results from each model directory
    for model_dir in model_dirs:
        model_name = model_dir.name
        print(f"\n📁 Processing: {model_name}")
        
        # Try to find evaluation_results.json in different locations
        possible_locations = [
            model_dir / 'evaluation_results.json',
            model_dir / 'results' / 'evaluation_results.json',
            model_dir / 'outputs' / model_name / 'results' / 'evaluation_results.json'
        ]
        
        eval_file = None
        for loc in possible_locations:
            if loc.exists():
                eval_file = loc
                break
        
        if not eval_file:
            print(f"  ⚠️  No evaluation_results.json found in {model_name}")
            continue
        
        try:
            with open(eval_file, 'r', encoding='utf-8') as f:
                model_data = json.load(f)
            
            # Extract per_model_results if available
            if 'per_model_results' in model_data:
                # This is a full evaluation_results.json
                for config_name, config_results in model_data['per_model_results'].items():
                    aggregated['per_model_results'][config_name] = config_results
                print(f"  ✅ Loaded evaluation results for {model_name}")
            elif 'per_document' in model_data or 'aggregated' in model_data:
                # This might be a partial result, try to reconstruct
                aggregated['per_model_results'][model_name] = model_data
                print(f"  ✅ Loaded partial results for {model_name}")
            else:
                print(f"  ⚠️  Unknown format in {eval_file}")
                
        except Exception as e:
            print(f"  ❌ Failed to load {eval_file}: {e}")
            continue
    
    # Compute model comparison if we have multiple models
    if len(aggregated['per_model_results']) > 1:
        print(f"\n📈 Computing model comparison...")
        aggregated['model_comparison'] = compute_model_comparison(aggregated['per_model_results'])
    
    # Save aggregated results
    if output_file is None:
        output_file = base_dir / 'evaluation_results_aggregated.json'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(aggregated, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Aggregated results saved to: {output_file}")
    print(f"   Total models: {len(aggregated['per_model_results'])}")
    
    return aggregated


def compute_model_comparison(per_model_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Compute comparison metrics across models."""
    comparison = {
        'models': list(per_model_results.keys()),
        'metrics': {}
    }
    
    for model_name, model_data in per_model_results.items():
        metrics = {}
        
        # Extract completeness
        if 'completeness' in model_data and 'aggregated' in model_data['completeness']:
            comp = model_data['completeness']['aggregated']
            metrics['completeness'] = comp.get('mean_overall_completeness', 0.0)
        
        # Extract correctness (field presence)
        if 'correctness' in model_data and 'aggregated' in model_data['correctness']:
            corr = model_data['correctness']['aggregated']
            metrics['correctness_f1'] = corr.get('mean_f1_score', 0.0)
            metrics['field_presence_rate'] = corr.get('mean_field_presence_rate', 0.0)
        
        # Extract schema compliance
        if 'schema_validation' in model_data and 'aggregated' in model_data['schema_validation']:
            schema = model_data['schema_validation']['aggregated']
            metrics['schema_compliance'] = schema.get('mean_compliance_rate', 0.0)
        
        # Extract LLM judge score
        if 'llm_judge' in model_data and 'aggregated' in model_data['llm_judge']:
            judge = model_data['llm_judge']['aggregated']
            metrics['llm_judge_score'] = judge.get('mean_overall_score', 0.0)
        
        # Extract aggregate score if available
        if 'aggregate_score' in model_data:
            metrics['aggregate_score'] = model_data['aggregate_score']
        
        comparison['metrics'][model_name] = metrics
    
    # Rank models by aggregate score
    if comparison['metrics']:
        ranked = sorted(
            comparison['metrics'].items(),
            key=lambda x: x[1].get('aggregate_score', 0.0),
            reverse=True
        )
        comparison['ranking'] = [model for model, _ in ranked]
    
    return comparison


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Aggregate evaluation results from multiple model runs'
    )
    parser.add_argument(
        'base_dir',
        type=Path,
        help='Base directory containing model subdirectories (e.g., evaluation/runs/openai_parallel_TIMESTAMP)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Output file path (default: base_dir/evaluation_results_aggregated.json)'
    )
    
    args = parser.parse_args()
    
    aggregate_results(args.base_dir, args.output)

