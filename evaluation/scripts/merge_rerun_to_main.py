#!/usr/bin/env python3
"""
Merge rerun results into main runs directory with correct run_idx mapping.

This script:
1. Reads rerun results from rerun directory
2. Maps them to the correct run_idx based on what's missing in the main directory
3. Copies successful runs to the main directory structure
"""

import json
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Set
import argparse
from collections import defaultdict


def get_existing_run_indices(model_dir: Path, document: str) -> Set[int]:
    """
    Get existing run indices for a model-document pair.
    
    Args:
        model_dir: Path to model directory (e.g., evaluation/runs/gpt5)
        document: Document ID (e.g., 'biosensor')
        
    Returns:
        Set of existing run indices
    """
    doc_dir = model_dir / document
    if not doc_dir.exists():
        return set()
    
    existing = set()
    for run_dir in doc_dir.iterdir():
        if run_dir.is_dir() and run_dir.name.startswith('run_'):
            try:
                run_idx = int(run_dir.name.split('_')[1])
                # Check if it's a complete run
                if (run_dir / "metadata_json.json").exists():
                    existing.add(run_idx)
            except:
                pass
    
    return existing


def find_missing_run_indices(existing: Set[int], target_count: int = 10) -> List[int]:
    """
    Find missing run indices.
    
    Args:
        existing: Set of existing run indices
        target_count: Target number of runs (default: 10)
        
    Returns:
        List of missing run indices (sorted)
    """
    all_needed = set(range(1, target_count + 1))
    missing = sorted(all_needed - existing)
    return missing


def get_rerun_results(rerun_dir: Path) -> Dict[Tuple[str, str], List[Path]]:
    """
    Collect rerun results organized by (model, document).
    
    Args:
        rerun_dir: Path to rerun directory
        
    Returns:
        Dictionary mapping (model, document) to list of run directories
    """
    results = defaultdict(list)
    
    # Look for structure: rerun_dir/model_document/outputs/model_name/document/run_X/
    for output_dir in rerun_dir.rglob("outputs"):
        for model_dir in output_dir.iterdir():
            if not model_dir.is_dir():
                continue
            
            model_name = model_dir.name
            # Normalize model name
            if model_name.startswith('openai_'):
                model_name = model_name.replace('openai_', '')
            elif model_name.startswith('anthropic_'):
                model_name = model_name.replace('anthropic_', '')
            
            for doc_dir in model_dir.iterdir():
                if not doc_dir.is_dir():
                    continue
                
                document = doc_dir.name
                if document == 'biorem':
                    continue
                
                # Find all run directories
                for run_dir in doc_dir.iterdir():
                    if run_dir.is_dir() and run_dir.name.startswith('run_'):
                        # Check if complete
                        if (run_dir / "metadata_json.json").exists():
                            key = (model_name, document)
                            results[key].append(run_dir)
    
    return results


def merge_rerun_results(
    rerun_dir: Path,
    main_runs_dir: Path = None,
    dry_run: bool = True
) -> Dict[str, int]:
    """
    Merge rerun results into main runs directory.
    
    Args:
        rerun_dir: Path to rerun directory
        main_runs_dir: Path to main runs directory (default: evaluation/runs)
        dry_run: If True, only report what would be done
        
    Returns:
        Statistics dictionary
    """
    if main_runs_dir is None:
        main_runs_dir = Path("evaluation/runs")
    
    stats = {
        'runs_merged': 0,
        'runs_skipped': 0,
        'models_processed': 0
    }
    
    # Get rerun results
    rerun_results = get_rerun_results(rerun_dir)
    
    print(f"Found rerun results for {len(rerun_results)} model-document pairs")
    
    # Process each model-document pair
    for (model_name, document), rerun_runs in rerun_results.items():
        print(f"\n处理 {model_name}/{document}: {len(rerun_runs)} 个补跑结果")
        
        # Get existing run indices in main directory
        model_dir = main_runs_dir / model_name
        existing_indices = get_existing_run_indices(model_dir, document)
        missing_indices = find_missing_run_indices(existing_indices)
        
        print(f"  已有运行索引: {sorted(existing_indices)}")
        print(f"  缺失运行索引: {missing_indices}")
        
        if not missing_indices:
            print(f"  ⚠️  无需合并（已有 10 次运行）")
            continue
        
        # Sort rerun runs by their run_idx (from eval_result.json if available)
        rerun_runs_with_idx = []
        for run_dir in rerun_runs:
            run_idx = None
            eval_file = run_dir / "eval_result.json"
            if eval_file.exists():
                try:
                    with open(eval_file, 'r') as f:
                        eval_data = json.load(f)
                    run_idx = eval_data.get('run_idx')
                except:
                    pass
            
            if run_idx is None:
                # Try to extract from directory name
                try:
                    run_idx = int(run_dir.name.split('_')[1])
                except:
                    run_idx = 999  # Put at end if can't determine
            
            rerun_runs_with_idx.append((run_idx, run_dir))
        
        # Sort by original run_idx
        rerun_runs_with_idx.sort(key=lambda x: x[0])
        
        # Map rerun runs to missing indices
        doc_dir = model_dir / document
        doc_dir.mkdir(parents=True, exist_ok=True)
        
        for i, missing_idx in enumerate(missing_indices):
            if i >= len(rerun_runs_with_idx):
                print(f"  ⚠️  补跑结果不足，无法补齐 run_{missing_idx}")
                break
            
            _, rerun_run_dir = rerun_runs_with_idx[i]
            target_run_dir = doc_dir / f"run_{missing_idx}"
            
            if dry_run:
                print(f"  [DRY RUN] 将合并: {rerun_run_dir.name} -> run_{missing_idx}")
            else:
                if target_run_dir.exists():
                    # Remove existing if it exists
                    shutil.rmtree(target_run_dir)
                
                # Copy run directory
                shutil.copytree(rerun_run_dir, target_run_dir)
                
                # Update run_idx in eval_result.json
                eval_file = target_run_dir / "eval_result.json"
                if eval_file.exists():
                    try:
                        with open(eval_file, 'r') as f:
                            eval_data = json.load(f)
                        eval_data['run_idx'] = missing_idx
                        with open(eval_file, 'w') as f:
                            json.dump(eval_data, f, indent=2)
                    except:
                        pass
                
                print(f"  ✅ 已合并: run_{missing_idx}")
                stats['runs_merged'] += 1
        
        stats['models_processed'] += 1
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Merge rerun results into main runs directory"
    )
    parser.add_argument(
        '--rerun-dir',
        type=Path,
        required=True,
        help='Path to rerun directory (e.g., evaluation/runs/rerun_20251205_123456)'
    )
    parser.add_argument(
        '--main-runs-dir',
        type=Path,
        default=Path('evaluation/runs'),
        help='Path to main runs directory (default: evaluation/runs)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=True,
        help='Dry run mode: only report what would be done (default: True)'
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually merge files (overrides --dry-run)'
    )
    
    args = parser.parse_args()
    
    dry_run = not args.execute
    
    if dry_run:
        print("=" * 80)
        print("DRY RUN MODE - No files will be copied")
        print("Use --execute to actually merge files")
        print("=" * 80)
    else:
        print("=" * 80)
        print("EXECUTION MODE - Files will be COPIED")
        print("=" * 80)
    
    print(f"\nRerun directory: {args.rerun_dir}")
    print(f"Main runs directory: {args.main_runs_dir}")
    
    stats = merge_rerun_results(
        args.rerun_dir,
        args.main_runs_dir,
        dry_run=dry_run
    )
    
    print("\n" + "=" * 80)
    print("Summary:")
    print(f"  Models processed: {stats['models_processed']}")
    print(f"  Runs merged: {stats['runs_merged']}")
    print(f"  Runs skipped: {stats['runs_skipped']}")
    print("=" * 80)


if __name__ == '__main__':
    main()


