#!/usr/bin/env python3
"""
Clean up incomplete and timeout runs from evaluation results.

This script:
1. Identifies runs without metadata_json.json (incomplete/timeout)
2. Deletes these incomplete runs
3. Ensures each model-document pair has exactly 10 successful runs
"""

import json
import shutil
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple
import argparse


def is_complete_run(run_dir: Path) -> bool:
    """
    Check if a run is complete (has metadata_json.json).
    
    Args:
        run_dir: Path to run directory (e.g., run_1, run_2)
        
    Returns:
        True if run is complete, False otherwise
    """
    metadata_file = run_dir / "metadata_json.json"
    return metadata_file.exists()


def is_timeout_run(run_dir: Path) -> bool:
    """
    Check if a run timed out.
    
    Args:
        run_dir: Path to run directory
        
    Returns:
        True if run timed out, False otherwise
    """
    eval_result_file = run_dir / "eval_result.json"
    if not eval_result_file.exists():
        return False
    
    try:
        with open(eval_result_file, 'r', encoding='utf-8') as f:
            eval_data = json.load(f)
        error_msg = eval_data.get('error', '').lower()
        return 'timeout' in error_msg or 'timed out' in error_msg
    except:
        return False


def find_incomplete_runs(runs_dir: Path, exclude_patterns: List[str] = None) -> List[Path]:
    """
    Find all incomplete or timeout runs.
    
    Args:
        runs_dir: Path to evaluation/runs directory
        exclude_patterns: List of patterns to exclude (e.g., ['archive', 'rerun_', 'baseline_'])
        
    Returns:
        List of run directories to delete
    """
    if exclude_patterns is None:
        exclude_patterns = ['archive', 'rerun_', 'baseline_', 'results']
    
    incomplete_runs = []
    
    for run_dir in runs_dir.rglob("run_*"):
        # Skip if in excluded directories
        if any(pattern in str(run_dir) for pattern in exclude_patterns):
            continue
        
        # Check if it's a run directory (contains eval_result.json)
        if not (run_dir / "eval_result.json").exists():
            continue
        
        # Check if incomplete or timeout
        if not is_complete_run(run_dir) or is_timeout_run(run_dir):
            incomplete_runs.append(run_dir)
    
    return incomplete_runs


def find_runs_to_keep(runs_dir: Path, exclude_patterns: List[str] = None) -> Dict[Tuple[str, str], List[Path]]:
    """
    Find successful runs and group by (model, document).
    Keep only 10 runs per model-document pair.
    
    Args:
        runs_dir: Path to evaluation/runs directory
        exclude_patterns: List of patterns to exclude
        
    Returns:
        Dictionary mapping (model, document) to list of run directories to keep
    """
    if exclude_patterns is None:
        exclude_patterns = ['archive', 'rerun_', 'baseline_', 'results']
    
    runs_by_model_doc = defaultdict(list)
    
    for run_dir in runs_dir.rglob("run_*"):
        # Skip if in excluded directories
        if any(pattern in str(run_dir) for pattern in exclude_patterns):
            continue
        
        # Check if it's a run directory
        eval_result_file = run_dir / "eval_result.json"
        if not eval_result_file.exists():
            continue
        
        # Check if complete
        if not is_complete_run(run_dir):
            continue
        
        # Check if timeout
        if is_timeout_run(run_dir):
            continue
        
        # Extract model and document from path
        # Path structure: .../model_dir/outputs/model_name/document/run_X/
        try:
            parts = run_dir.parts
            # Find 'outputs' in path
            outputs_idx = None
            for i, part in enumerate(parts):
                if part == 'outputs':
                    outputs_idx = i
                    break
            
            if outputs_idx is None:
                continue
            
            # Model name is at outputs_idx + 1
            # Document is at outputs_idx + 2
            if outputs_idx + 2 >= len(parts):
                continue
            
            model_name = parts[outputs_idx + 1]
            document = parts[outputs_idx + 2]
            
            # Read run_idx from eval_result.json
            try:
                with open(eval_result_file, 'r', encoding='utf-8') as f:
                    eval_data = json.load(f)
                run_idx = eval_data.get('run_idx')
                if run_idx is None:
                    continue
            except:
                continue
            
            key = (model_name, document)
            runs_by_model_doc[key].append((run_dir, run_idx))
        except Exception as e:
            continue
    
    # Sort by run_idx and keep only first 10 per model-document pair
    runs_to_keep = {}
    for (model, doc), runs_with_idx in runs_by_model_doc.items():
        # Sort by run_idx
        runs_with_idx.sort(key=lambda x: x[1])
        # Keep only first 10
        runs_to_keep[(model, doc)] = [run_dir for run_dir, _ in runs_with_idx[:10]]
    
    return runs_to_keep


def cleanup_runs(
    runs_dir: Path,
    dry_run: bool = True,
    keep_only_10: bool = True
) -> Dict[str, int]:
    """
    Clean up incomplete runs.
    
    Args:
        runs_dir: Path to evaluation/runs directory
        dry_run: If True, only report what would be deleted without actually deleting
        keep_only_10: If True, keep only 10 runs per model-document pair
        
    Returns:
        Dictionary with statistics
    """
    stats = {
        'incomplete_deleted': 0,
        'excess_deleted': 0,
        'total_deleted': 0
    }
    
    # Find incomplete runs
    incomplete_runs = find_incomplete_runs(runs_dir)
    print(f"Found {len(incomplete_runs)} incomplete/timeout runs")
    
    # Delete incomplete runs
    for run_dir in incomplete_runs:
        if dry_run:
            print(f"  [DRY RUN] Would delete: {run_dir}")
        else:
            try:
                shutil.rmtree(run_dir)
                print(f"  ✅ Deleted: {run_dir}")
                stats['incomplete_deleted'] += 1
            except Exception as e:
                print(f"  ❌ Failed to delete {run_dir}: {e}")
    
    if keep_only_10:
        # Find runs to keep (10 per model-document)
        runs_to_keep = find_runs_to_keep(runs_dir)
        
        print(f"\nFound {len(runs_to_keep)} model-document pairs")
        for (model, doc), runs in runs_to_keep.items():
            print(f"  {model}/{doc}: {len(runs)} runs to keep")
        
        # Find all successful runs
        all_successful_runs = []
        for run_dir in runs_dir.rglob("run_*"):
            if any(pattern in str(run_dir) for pattern in ['archive', 'rerun_', 'baseline_', 'results']):
                continue
            if is_complete_run(run_dir) and not is_timeout_run(run_dir):
                all_successful_runs.append(run_dir)
        
        # Find runs to delete (excess runs beyond 10 per model-document)
        runs_to_delete = []
        keep_set = set()
        for runs in runs_to_keep.values():
            keep_set.update(runs)
        
        for run_dir in all_successful_runs:
            if run_dir not in keep_set:
                runs_to_delete.append(run_dir)
        
        print(f"\nFound {len(runs_to_delete)} excess runs to delete (beyond 10 per model-document)")
        
        # Delete excess runs
        for run_dir in runs_to_delete:
            if dry_run:
                print(f"  [DRY RUN] Would delete excess: {run_dir}")
            else:
                try:
                    shutil.rmtree(run_dir)
                    print(f"  ✅ Deleted excess: {run_dir}")
                    stats['excess_deleted'] += 1
                except Exception as e:
                    print(f"  ❌ Failed to delete {run_dir}: {e}")
    
    stats['total_deleted'] = stats['incomplete_deleted'] + stats['excess_deleted']
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Clean up incomplete and timeout runs from evaluation results"
    )
    parser.add_argument(
        '--runs-dir',
        type=Path,
        default=Path('evaluation/runs'),
        help='Path to evaluation/runs directory (default: evaluation/runs)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=True,
        help='Dry run mode: only report what would be deleted (default: True)'
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually delete files (overrides --dry-run)'
    )
    parser.add_argument(
        '--keep-only-10',
        action='store_true',
        default=True,
        help='Keep only 10 runs per model-document pair (default: True)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompt (use with --execute)'
    )
    
    args = parser.parse_args()
    
    dry_run = not args.execute
    
    if dry_run:
        print("=" * 80)
        print("DRY RUN MODE - No files will be deleted")
        print("Use --execute to actually delete files")
        print("=" * 80)
    else:
        print("=" * 80)
        print("EXECUTION MODE - Files will be DELETED")
        print("=" * 80)
        if not args.force:
            try:
                response = input("Are you sure you want to delete files? (yes/no): ")
                if response.lower() != 'yes':
                    print("Aborted.")
                    return
            except EOFError:
                print("No input available. Use --force to skip confirmation.")
                return
    
    print(f"\nScanning runs directory: {args.runs_dir}")
    stats = cleanup_runs(
        args.runs_dir,
        dry_run=dry_run,
        keep_only_10=args.keep_only_10
    )
    
    print("\n" + "=" * 80)
    print("Summary:")
    print(f"  Incomplete/timeout runs deleted: {stats['incomplete_deleted']}")
    print(f"  Excess runs deleted: {stats['excess_deleted']}")
    print(f"  Total runs deleted: {stats['total_deleted']}")
    print("=" * 80)


if __name__ == '__main__':
    main()

