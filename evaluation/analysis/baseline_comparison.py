"""
Baseline Comparison Module

Handles comparison between baseline (single-prompt) and agentic workflow runs.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
import numpy as np

from .config import (
    EXCLUDED_MODELS, EXCLUDED_DOCUMENTS, EXCLUDED_DIRECTORIES,
    normalize_model_name, normalize_document_id, get_model_display_name,
    get_model_color, is_baseline_run
)


def count_actual_fields(metadata: dict) -> int:
    """
    Count actual populated metadata fields.
    
    For agentic output: counts fields with non-empty 'value' in isa_structure
    For baseline output: counts leaf values in the flat structure
    
    Args:
        metadata: Metadata dictionary from metadata_json.json
        
    Returns:
        Number of populated fields
    """
    if 'isa_structure' in metadata:
        return count_isa_fields(metadata['isa_structure'])
    else:
        return count_baseline_fields(metadata)


def count_isa_fields(isa_structure: dict) -> int:
    """Count populated fields in ISA structure (agentic output)."""
    count = 0
    for section_name in ['investigation', 'study', 'assay', 'sample', 'observationunit']:
        section = isa_structure.get(section_name, {})
        if not section or 'fields' not in section:
            continue
        
        fields = section['fields']
        if not isinstance(fields, list):
            continue
        
        for field in fields:
            if isinstance(field, dict):
                value = field.get('value')
                if value and value not in [None, "", "Not specified", [], {}, "N/A"]:
                    count += 1
    return count


def count_baseline_fields(data: dict) -> int:
    """Count leaf values in baseline output."""
    count = 0
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                count += count_baseline_fields(value)
            elif value and value not in [None, "", "Not specified", "N/A"]:
                count += 1
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                count += count_baseline_fields(item)
            elif item and item not in [None, "", "Not specified", "N/A"]:
                count += 1
    return count


def load_run_data(run_dir: Path) -> Dict[str, Any]:
    """
    Load run data from a directory.
    
    Args:
        run_dir: Path to run directory
        
    Returns:
        Dictionary with run statistics and per-document data
    """
    data = {
        'runs': [],
        'documents': set(),
        'n_fields': [],
        'runtimes': [],
        'success_count': 0,
        'fail_count': 0,
        'critic_scores': [],
        'by_document': {},  # Store data by document
        'seen_runs': set()  # Track seen (document_id, run_idx) pairs to avoid duplicates
    }
    
    # Find all eval_result.json files
    # Support both old structure (outputs/model_name/document/run_X/) 
    # and new structure (model_name/document/run_X/)
    eval_files = list(run_dir.rglob("eval_result.json"))
    
    # Group by (document_id, run_idx) and keep only one file per pair
    # Prefer files in the canonical model name directory
    seen_keys = {}
    for eval_file in eval_files:
        # Skip if in results/ directory (those are aggregated results, not individual runs)
        if '/results/' in str(eval_file):
            continue
        
        try:
            with open(eval_file, 'r') as f:
                eval_data = json.load(f)
            doc_id = normalize_document_id(eval_data.get('document_id', 'unknown'))
            run_idx = eval_data.get('run_idx')
            key = (doc_id, run_idx)
            
            # Keep the first file we see for each key, or prefer canonical model name directory
            if key not in seen_keys:
                seen_keys[key] = eval_file
            else:
                # Prefer canonical model name (e.g., anthropic_sonnet over sonnet)
                current_path = str(eval_file)
                existing_path = str(seen_keys[key])
                # Priority: canonical model names > generic names
                # If new file is in a more specific/canonical directory, use it
                current_is_canonical = 'anthropic_sonnet' in current_path or 'openai_' in current_path
                existing_is_canonical = 'anthropic_sonnet' in existing_path or 'openai_' in existing_path
                
                if current_is_canonical and not existing_is_canonical:
                    seen_keys[key] = eval_file
                elif current_is_canonical and existing_is_canonical:
                    # Both are canonical, prefer the one with more specific path
                    if 'anthropic_sonnet' in current_path and 'anthropic_sonnet' not in existing_path:
                        seen_keys[key] = eval_file
                    elif 'openai_' in current_path and 'openai_' not in existing_path:
                        seen_keys[key] = eval_file
        except:
            continue
    
    # Process only the deduplicated files
    for eval_file in seen_keys.values():
        try:
            with open(eval_file, 'r') as f:
                eval_data = json.load(f)
            
            doc_id = eval_data.get('document_id', 'unknown')
            doc_id = normalize_document_id(doc_id)
            run_idx = eval_data.get('run_idx', None)
            
            # Skip excluded documents
            if doc_id in EXCLUDED_DOCUMENTS:
                continue
            
            # Check for duplicates: same (document_id, run_idx) pair
            run_key = (doc_id, run_idx)
            if run_key in data['seen_runs']:
                # Skip duplicate run
                continue
            data['seen_runs'].add(run_key)
            
            data['documents'].add(doc_id)
            
            # Initialize document entry if needed
            if doc_id not in data['by_document']:
                data['by_document'][doc_id] = {
                    'n_fields': [],
                    'runtimes': [],
                    'critic_scores': [],
                    'success_count': 0,
                    'fail_count': 0
                }
            
            if eval_data.get('success'):
                data['success_count'] += 1
                data['by_document'][doc_id]['success_count'] += 1
                
                runtime = eval_data.get('runtime_seconds', 0)
                data['runtimes'].append(runtime)
                data['by_document'][doc_id]['runtimes'].append(runtime)
                
                # Count actual fields from metadata_json.json
                metadata_file = eval_file.parent / "metadata_json.json"
                if metadata_file.exists():
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                        actual_fields = count_actual_fields(metadata)
                        data['n_fields'].append(actual_fields)
                        data['by_document'][doc_id]['n_fields'].append(actual_fields)
                else:
                    fields = eval_data.get('n_fields_extracted', 0)
                    data['n_fields'].append(fields)
                    data['by_document'][doc_id]['n_fields'].append(fields)
            else:
                data['fail_count'] += 1
                data['by_document'][doc_id]['fail_count'] += 1
            
            data['runs'].append(eval_data)
            
            # Try to get critic score from workflow_report
            workflow_report = eval_file.parent / "workflow_report.json"
            if workflow_report.exists():
                with open(workflow_report, 'r') as f:
                    report = json.load(f)
                    critic_conf = report.get('quality_metrics', {}).get('critic_confidence')
                    if critic_conf is not None:
                        data['critic_scores'].append(critic_conf)
                        data['by_document'][doc_id]['critic_scores'].append(critic_conf)
        except Exception:
            continue
    
    data['documents'] = list(data['documents'])
    return data


def load_agentic_data(runs_dir: Path) -> Dict[str, Dict[str, Any]]:
    """
    Load all agentic workflow data, merging runs from same model.
    
    Args:
        runs_dir: Path to evaluation/runs directory
        
    Returns:
        Dictionary mapping canonical model names to run data
    """
    agentic_data = {}
    runs_dir = Path(runs_dir)
    
    # Support both old structure (batch_dir/model_dir/) and new structure (model_dir/)
    # Check if we have new structure (model directories directly in runs_dir)
    has_new_structure = any(
        item.is_dir() and 
        item.name not in EXCLUDED_DIRECTORIES and
        not is_baseline_run(item) and
        not item.name.startswith('rerun_') and
        not item.name.startswith('baseline_') and
        # Check if it's a model directory (has document subdirectories with run_*)
        any((item / doc_dir / run_dir).exists() 
            for doc_dir in item.iterdir() if doc_dir.is_dir()
            for run_dir in (item / doc_dir).iterdir() if run_dir.is_dir() and run_dir.name.startswith('run_'))
        for item in runs_dir.iterdir()
    )
    
    if has_new_structure:
        # New structure: model directories directly in runs_dir
        for model_dir in runs_dir.iterdir():
            if not model_dir.is_dir():
                continue
            # Exclude archive, baseline, rerun directories
            if (model_dir.name in EXCLUDED_DIRECTORIES or 
                is_baseline_run(model_dir) or 
                model_dir.name.startswith('rerun_') or
                model_dir.name.startswith('baseline_')):
                continue
            
            model_name = model_dir.name
            
            # Skip excluded models
            if any(excl in model_name.lower() for excl in EXCLUDED_MODELS):
                continue
            
            # Map to canonical model name for merging
            canonical_name = normalize_model_name(model_name)
            
            data = load_run_data(model_dir)
            
            if data['success_count'] > 0:
                if canonical_name not in agentic_data:
                    # First time seeing this model - initialize
                    agentic_data[canonical_name] = data
                    # Initialize seen_runs from the loaded data
                    agentic_data[canonical_name]['seen_runs'] = data.get('seen_runs', set())
                else:
                    # Merge with existing data, avoiding duplicates
                    # Get existing run keys
                    existing_run_keys = agentic_data[canonical_name].get('seen_runs', set())
                    if not existing_run_keys:
                        # Build from existing runs
                        existing_run_keys = {
                            (normalize_document_id(r.get('document_id', 'unknown')), r.get('run_idx'))
                            for r in agentic_data[canonical_name]['runs']
                        }
                    
                    # Filter new data to only include runs not already seen
                    new_run_keys = data.get('seen_runs', set())
                    if not new_run_keys:
                        new_run_keys = {
                            (normalize_document_id(r.get('document_id', 'unknown')), r.get('run_idx'))
                            for r in data['runs']
                        }
                    
                    # Find truly new runs
                    truly_new_keys = new_run_keys - existing_run_keys
                    
                    if truly_new_keys:
                        # Filter data to only include new runs
                        new_runs = [
                            r for r in data['runs']
                            if (normalize_document_id(r.get('document_id', 'unknown')), r.get('run_idx')) in truly_new_keys
                        ]
                        
                        # Match fields, runtimes, critic_scores to new runs
                        # We need to match by index in original data
                        new_indices = [
                            i for i, r in enumerate(data['runs'])
                            if (normalize_document_id(r.get('document_id', 'unknown')), r.get('run_idx')) in truly_new_keys
                        ]
                        
                        new_fields = [data['n_fields'][i] for i in new_indices if i < len(data['n_fields'])]
                        new_runtimes = [data['runtimes'][i] for i in new_indices if i < len(data['runtimes'])]
                        new_critic_scores = [
                            data['critic_scores'][i] for i in new_indices 
                            if i < len(data['critic_scores'])
                        ]
                        
                        # Count new successes/failures
                        new_success = sum(1 for r in new_runs if r.get('success'))
                        new_fail = len(new_runs) - new_success
                        
                        # Merge
                        agentic_data[canonical_name]['runs'].extend(new_runs)
                        agentic_data[canonical_name]['n_fields'].extend(new_fields)
                        agentic_data[canonical_name]['runtimes'].extend(new_runtimes)
                        agentic_data[canonical_name]['success_count'] += new_success
                        agentic_data[canonical_name]['fail_count'] += new_fail
                        agentic_data[canonical_name]['critic_scores'].extend(new_critic_scores)
                        agentic_data[canonical_name]['documents'] = list(
                            set(agentic_data[canonical_name]['documents'] + data['documents'])
                        )
                        agentic_data[canonical_name]['seen_runs'] = existing_run_keys | truly_new_keys
                        
                        # Merge by_document data for new runs only
                        for doc_id, doc_data in data['by_document'].items():
                            # Count how many new runs for this document
                            new_doc_runs = [
                                r for r in new_runs
                                if normalize_document_id(r.get('document_id')) == doc_id
                            ]
                            n_new = len(new_doc_runs)
                            
                            if n_new == 0:
                                continue  # No new runs for this document
                            
                            if doc_id not in agentic_data[canonical_name]['by_document']:
                                # New document - take only the new runs' data
                                # Match indices in doc_data to new runs
                                doc_indices = [
                                    i for i, r in enumerate(data['runs'])
                                    if normalize_document_id(r.get('document_id')) == doc_id
                                    and (normalize_document_id(r.get('document_id')), r.get('run_idx')) in truly_new_keys
                                ]
                                
                                agentic_data[canonical_name]['by_document'][doc_id] = {
                                    'n_fields': [doc_data['n_fields'][i] for i in doc_indices if i < len(doc_data['n_fields'])],
                                    'runtimes': [doc_data['runtimes'][i] for i in doc_indices if i < len(doc_data['runtimes'])],
                                    'critic_scores': [doc_data['critic_scores'][i] for i in doc_indices if i < len(doc_data['critic_scores'])],
                                    'success_count': new_success if doc_id in [normalize_document_id(r.get('document_id')) for r in new_runs] else 0,
                                    'fail_count': new_fail if doc_id in [normalize_document_id(r.get('document_id')) for r in new_runs] else 0
                                }
                            else:
                                # Existing document - append only new runs' data
                                doc_indices = [
                                    i for i, r in enumerate(data['runs'])
                                    if normalize_document_id(r.get('document_id')) == doc_id
                                    and (normalize_document_id(r.get('document_id')), r.get('run_idx')) in truly_new_keys
                                ]
                                
                                agentic_data[canonical_name]['by_document'][doc_id]['n_fields'].extend(
                                    [doc_data['n_fields'][i] for i in doc_indices if i < len(doc_data['n_fields'])]
                                )
                                agentic_data[canonical_name]['by_document'][doc_id]['runtimes'].extend(
                                    [doc_data['runtimes'][i] for i in doc_indices if i < len(doc_data['runtimes'])]
                                )
                                agentic_data[canonical_name]['by_document'][doc_id]['critic_scores'].extend(
                                    [doc_data['critic_scores'][i] for i in doc_indices if i < len(doc_data['critic_scores'])]
                                )
                                
                                # Update counts for this document
                                doc_new_success = sum(1 for r in new_doc_runs if r.get('success'))
                                doc_new_fail = len(new_doc_runs) - doc_new_success
                                agentic_data[canonical_name]['by_document'][doc_id]['success_count'] += doc_new_success
                                agentic_data[canonical_name]['by_document'][doc_id]['fail_count'] += doc_new_fail
    else:
        # Old structure: batch_dir/model_dir/
        for run_dir in runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            # Exclude archive, baseline, and rerun directories (reruns contain duplicate data)
            if (run_dir.name in EXCLUDED_DIRECTORIES or 
                is_baseline_run(run_dir) or 
                run_dir.name.startswith('rerun_')):
                continue
            
            for model_dir in run_dir.iterdir():
                if not model_dir.is_dir():
                    continue
                
                model_name = model_dir.name
                
                # Skip excluded models
                if any(excl in model_name.lower() for excl in EXCLUDED_MODELS):
                    continue
                
                # Map to canonical model name for merging
                canonical_name = normalize_model_name(model_name)
                
                data = load_run_data(model_dir)
                
                if data['success_count'] > 0:
                    if canonical_name not in agentic_data:
                        # First time seeing this model - initialize
                        agentic_data[canonical_name] = data
                        # Initialize seen_runs from the loaded data
                        agentic_data[canonical_name]['seen_runs'] = data.get('seen_runs', set())
                    else:
                        # Merge with existing data, avoiding duplicates
                        # Get existing run keys
                        existing_run_keys = agentic_data[canonical_name].get('seen_runs', set())
                        if not existing_run_keys:
                            # Build from existing runs
                            existing_run_keys = {
                                (normalize_document_id(r.get('document_id', 'unknown')), r.get('run_idx'))
                                for r in agentic_data[canonical_name]['runs']
                            }
                        
                        # Filter new data to only include runs not already seen
                        new_run_keys = data.get('seen_runs', set())
                        if not new_run_keys:
                            new_run_keys = {
                                (normalize_document_id(r.get('document_id', 'unknown')), r.get('run_idx'))
                                for r in data['runs']
                            }
                        
                        # Find truly new runs
                        truly_new_keys = new_run_keys - existing_run_keys
                        
                        if truly_new_keys:
                            # Filter data to only include new runs
                            new_runs = [
                                r for r in data['runs']
                                if (normalize_document_id(r.get('document_id', 'unknown')), r.get('run_idx')) in truly_new_keys
                            ]
                            
                            # Match fields, runtimes, critic_scores to new runs
                            # We need to match by index in original data
                            new_indices = [
                                i for i, r in enumerate(data['runs'])
                                if (normalize_document_id(r.get('document_id', 'unknown')), r.get('run_idx')) in truly_new_keys
                            ]
                            
                            new_fields = [data['n_fields'][i] for i in new_indices if i < len(data['n_fields'])]
                            new_runtimes = [data['runtimes'][i] for i in new_indices if i < len(data['runtimes'])]
                            new_critic_scores = [
                                data['critic_scores'][i] for i in new_indices 
                                if i < len(data['critic_scores'])
                            ]
                            
                            # Count new successes/failures
                            new_success = sum(1 for r in new_runs if r.get('success'))
                            new_fail = len(new_runs) - new_success
                            
                            # Merge
                            agentic_data[canonical_name]['runs'].extend(new_runs)
                            agentic_data[canonical_name]['n_fields'].extend(new_fields)
                            agentic_data[canonical_name]['runtimes'].extend(new_runtimes)
                            agentic_data[canonical_name]['success_count'] += new_success
                            agentic_data[canonical_name]['fail_count'] += new_fail
                            agentic_data[canonical_name]['critic_scores'].extend(new_critic_scores)
                            agentic_data[canonical_name]['documents'] = list(
                                set(agentic_data[canonical_name]['documents'] + data['documents'])
                            )
                            agentic_data[canonical_name]['seen_runs'] = existing_run_keys | truly_new_keys
                            
                            # Merge by_document data for new runs only
                            for doc_id, doc_data in data['by_document'].items():
                                # Count how many new runs for this document
                                new_doc_runs = [
                                    r for r in new_runs
                                    if normalize_document_id(r.get('document_id')) == doc_id
                                ]
                                n_new = len(new_doc_runs)
                                
                                if n_new == 0:
                                    continue  # No new runs for this document
                                
                                if doc_id not in agentic_data[canonical_name]['by_document']:
                                    # New document - take only the new runs' data
                                    # Match indices in doc_data to new runs
                                    doc_indices = [
                                        i for i, r in enumerate(data['runs'])
                                        if normalize_document_id(r.get('document_id')) == doc_id
                                        and (normalize_document_id(r.get('document_id')), r.get('run_idx')) in truly_new_keys
                                    ]
                                    
                                    agentic_data[canonical_name]['by_document'][doc_id] = {
                                        'n_fields': [doc_data['n_fields'][i] for i in doc_indices if i < len(doc_data['n_fields'])],
                                        'runtimes': [doc_data['runtimes'][i] for i in doc_indices if i < len(doc_data['runtimes'])],
                                        'critic_scores': [doc_data['critic_scores'][i] for i in doc_indices if i < len(doc_data['critic_scores'])],
                                        'success_count': new_success if doc_id in [normalize_document_id(r.get('document_id')) for r in new_runs] else 0,
                                        'fail_count': new_fail if doc_id in [normalize_document_id(r.get('document_id')) for r in new_runs] else 0
                                    }
                                else:
                                    # Existing document - append only new runs' data
                                    doc_indices = [
                                        i for i, r in enumerate(data['runs'])
                                        if normalize_document_id(r.get('document_id')) == doc_id
                                        and (normalize_document_id(r.get('document_id')), r.get('run_idx')) in truly_new_keys
                                    ]
                                    
                                    agentic_data[canonical_name]['by_document'][doc_id]['n_fields'].extend(
                                        [doc_data['n_fields'][i] for i in doc_indices if i < len(doc_data['n_fields'])]
                                    )
                                    agentic_data[canonical_name]['by_document'][doc_id]['runtimes'].extend(
                                        [doc_data['runtimes'][i] for i in doc_indices if i < len(doc_data['runtimes'])]
                                    )
                                    agentic_data[canonical_name]['by_document'][doc_id]['critic_scores'].extend(
                                        [doc_data['critic_scores'][i] for i in doc_indices if i < len(doc_data['critic_scores'])]
                                    )
                                    
                                    # Update counts for this document
                                    doc_new_success = sum(1 for r in new_doc_runs if r.get('success'))
                                    doc_new_fail = len(new_doc_runs) - doc_new_success
                                    agentic_data[canonical_name]['by_document'][doc_id]['success_count'] += doc_new_success
                                    agentic_data[canonical_name]['by_document'][doc_id]['fail_count'] += doc_new_fail
    
    return agentic_data


def load_baseline_data(runs_dir: Path) -> Dict[str, Dict[str, Any]]:
    """
    Load baseline data.
    
    Args:
        runs_dir: Path to evaluation/runs directory
        
    Returns:
        Dictionary mapping baseline model names to run data
    """
    baseline_data = {}
    runs_dir = Path(runs_dir)
    
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        if not is_baseline_run(run_dir):
            continue
        
        for model_dir in run_dir.iterdir():
            if not model_dir.is_dir():
                continue
            
            model_name = model_dir.name
            data = load_run_data(model_dir)
            
            if data['success_count'] > 0:
                baseline_data[model_name] = data
    
    return baseline_data

