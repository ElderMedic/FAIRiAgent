#!/usr/bin/env python3
"""
Reorganize evaluation runs by model and document.

Current structure:
  evaluation/runs/
    batch_timestamp/
      model_name/
        outputs/
          model_name/
            document/
              run_X/

Target structure:
  evaluation/runs/
    model_name/
      document/
        run_X/
"""

import json
import shutil
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple
import argparse


def get_model_document_from_path(run_dir: Path) -> Tuple[str, str, int]:
    """
    Extract model name, document name, and run_idx from run directory path.
    
    Args:
        run_dir: Path to run directory (e.g., .../outputs/model_name/document/run_X/)
        
    Returns:
        (model_name, document_name, run_idx) or None if cannot parse
    """
    parts = run_dir.parts
    
    # Find 'outputs' in path
    outputs_idx = None
    for i, part in enumerate(parts):
        if part == 'outputs':
            outputs_idx = i
            break
    
    if outputs_idx is None or outputs_idx + 3 >= len(parts):
        return None
    
    # Structure: .../outputs/model_name/document/run_X/
    model_name = parts[outputs_idx + 1]
    document = parts[outputs_idx + 2]
    run_name = parts[outputs_idx + 3]
    
    # Extract run_idx from run_X
    if not run_name.startswith('run_'):
        return None
    
    try:
        run_idx = int(run_name.split('_')[1])
    except:
        return None
    
    return (model_name, document, run_idx)


def is_complete_run(run_dir: Path) -> bool:
    """Check if run is complete (has metadata_json.json)."""
    return (run_dir / "metadata_json.json").exists()


def is_timeout_run(run_dir: Path) -> bool:
    """Check if run timed out."""
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


def collect_runs(runs_dir: Path, exclude_patterns: List[str] = None) -> Dict[Tuple[str, str], List[Tuple[Path, int]]]:
    """
    Collect all runs organized by (model, document).
    
    Returns:
        Dictionary mapping (model, document) to list of (run_dir, run_idx) tuples
    """
    if exclude_patterns is None:
        exclude_patterns = ['archive', 'rerun_', 'baseline_', 'results']
    
    runs_by_model_doc = defaultdict(list)
    
    for run_dir in runs_dir.rglob("run_*"):
        # Skip excluded directories
        if any(pattern in str(run_dir) for pattern in exclude_patterns):
            continue
        
        # Check if complete and not timeout
        if not is_complete_run(run_dir):
            continue
        
        if is_timeout_run(run_dir):
            continue
        
        # Extract model, document, run_idx
        result = get_model_document_from_path(run_dir)
        if result is None:
            continue
        
        model_name, document, run_idx = result
        
        # Skip biorem
        if document == 'biorem':
            continue
        
        key = (model_name, document)
        runs_by_model_doc[key].append((run_dir, run_idx))
    
    # Sort by run_idx and keep only first 10 per model-document pair
    organized_runs = {}
    for (model, doc), runs in runs_by_model_doc.items():
        # Sort by run_idx
        runs.sort(key=lambda x: x[1])
        # Keep only first 10
        organized_runs[(model, doc)] = runs[:10]
    
    return organized_runs


def normalize_model_name(model_name: str) -> str:
    """
    Normalize model name to canonical form.
    
    Examples:
        openai_gpt4.1 -> gpt4.1
        anthropic_sonnet -> sonnet
        openai_gpt5 -> gpt5
        openai_o3 -> o3
        anthropic_haiku -> haiku
    """
    # Remove provider prefix
    if model_name.startswith('openai_'):
        return model_name.replace('openai_', '')
    elif model_name.startswith('anthropic_'):
        return model_name.replace('anthropic_', '')
    return model_name


def reorganize_runs(
    runs_dir: Path,
    target_dir: Path = None,
    dry_run: bool = True
) -> Dict[str, int]:
    """
    Reorganize runs by model and document.
    
    Args:
        runs_dir: Source runs directory
        target_dir: Target directory (default: same as runs_dir)
        dry_run: If True, only report what would be done
        
    Returns:
        Statistics dictionary
    """
    if target_dir is None:
        target_dir = runs_dir
    
    stats = {
        'models': 0,
        'documents': 0,
        'runs_moved': 0,
        'runs_skipped': 0
    }
    
    # Collect all runs
    print("Collecting runs...")
    organized_runs = collect_runs(runs_dir)
    
    print(f"Found {len(organized_runs)} model-document pairs")
    
    # Create new structure
    for (model_name, document), runs in sorted(organized_runs.items()):
        # Normalize model name
        canonical_model = normalize_model_name(model_name)
        
        # Create target directory
        target_model_dir = target_dir / canonical_model / document
        target_model_dir.mkdir(parents=True, exist_ok=True)
        
        if dry_run:
            print(f"\n[DRY RUN] {canonical_model}/{document}: {len(runs)} runs")
        else:
            print(f"\n{canonical_model}/{document}: {len(runs)} runs")
        
        # Move runs
        for run_dir, run_idx in runs:
            target_run_dir = target_model_dir / f"run_{run_idx}"
            
            if dry_run:
                print(f"  Would move: {run_dir} -> {target_run_dir}")
            else:
                if target_run_dir.exists():
                    # Remove existing if it exists
                    shutil.rmtree(target_run_dir)
                
                # Move run directory
                shutil.move(str(run_dir), str(target_run_dir))
                print(f"  ✅ Moved: run_{run_idx}")
                stats['runs_moved'] += 1
        
        if not dry_run:
            stats['models'] = len(set(normalize_model_name(m) for m, _ in organized_runs.keys()))
            stats['documents'] = len(set(d for _, d in organized_runs.keys()))
    
    return stats


def cleanup_old_structure(runs_dir: Path, dry_run: bool = True):
    """
    Clean up old batch-based directory structure after reorganization.
    
    Args:
        runs_dir: Runs directory
        dry_run: If True, only report what would be deleted
    """
    exclude_patterns = ['archive', 'rerun_', 'baseline_']
    
    # Find all batch directories
    batch_dirs = []
    for item in runs_dir.iterdir():
        if not item.is_dir():
            continue
        if item.name in exclude_patterns or item.name.startswith('baseline_'):
            continue
        # Check if it's a batch directory (contains model subdirectories)
        has_models = any(
            subdir.is_dir() and (subdir / 'outputs').exists()
            for subdir in item.iterdir()
        )
        if has_models:
            batch_dirs.append(item)
    
    if not batch_dirs:
        print("No old batch directories found to clean up.")
        return
    
    print(f"\nFound {len(batch_dirs)} old batch directories:")
    for batch_dir in batch_dirs:
        if dry_run:
            print(f"  [DRY RUN] Would delete: {batch_dir}")
        else:
            try:
                shutil.rmtree(batch_dir)
                print(f"  ✅ Deleted: {batch_dir}")
            except Exception as e:
                print(f"  ❌ Failed to delete {batch_dir}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Reorganize evaluation runs by model and document"
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
        help='Dry run mode: only report what would be done (default: True)'
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually reorganize files (overrides --dry-run)'
    )
    parser.add_argument(
        '--cleanup',
        action='store_true',
        help='Clean up old batch-based directories after reorganization'
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
        print("DRY RUN MODE - No files will be moved")
        print("Use --execute to actually reorganize files")
        print("=" * 80)
    else:
        print("=" * 80)
        print("EXECUTION MODE - Files will be MOVED")
        print("=" * 80)
        if not args.force:
            try:
                response = input("Are you sure you want to reorganize files? (yes/no): ")
                if response.lower() != 'yes':
                    print("Aborted.")
                    return
            except EOFError:
                print("No input available. Use --force to skip confirmation.")
                return
    
    print(f"\nScanning runs directory: {args.runs_dir}")
    stats = reorganize_runs(args.runs_dir, dry_run=dry_run)
    
    print("\n" + "=" * 80)
    print("Summary:")
    print(f"  Models: {stats.get('models', 'N/A')}")
    print(f"  Documents: {stats.get('documents', 'N/A')}")
    print(f"  Runs moved: {stats['runs_moved']}")
    print("=" * 80)
    
    if args.cleanup and not dry_run:
        print("\nCleaning up old batch directories...")
        cleanup_old_structure(args.runs_dir, dry_run=False)


if __name__ == '__main__':
    main()

