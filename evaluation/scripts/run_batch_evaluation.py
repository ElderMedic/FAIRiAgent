#!/usr/bin/env python3
"""
Batch Evaluation Runner for FAIRiAgent

Runs FAIRiAgent on multiple documents with different model configurations.
All runs are tracked in LangSmith with appropriate metadata.
"""

import sys
import argparse
import json
import asyncio
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime
import os
import dotenv
from dotenv import load_dotenv
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path to import FAIRiAgent
sys.path.insert(0, str(Path(__file__).parents[2]))

# Patch dotenv to prevent crashes from malformed .env files in root
# This is necessary because fairifier/config.py loads .env on import
original_load_dotenv = dotenv.load_dotenv

def safe_load_dotenv(*args, **kwargs):
    try:
        return original_load_dotenv(*args, **kwargs)
    except Exception as e:
        print(f"⚠️ Warning: load_dotenv failed (ignoring): {e}")
        return False

dotenv.load_dotenv = safe_load_dotenv

class BatchEvaluationRunner:
    """Run FAIRiAgent on multiple documents with different configurations."""
    
    def __init__(
        self,
        ground_truth_path: Path,
        model_configs: List[Path],
        output_dir: Path,
        env_file: Path,
        exclude_documents: List[str] = None
    ):
        """
        Initialize batch runner.
        
        Args:
            ground_truth_path: Path to ground truth JSON
            model_configs: List of model config .env files
            output_dir: Output directory for all runs
            env_file: Main evaluation env file
            exclude_documents: List of document IDs to exclude (default: None)
        """
        self.ground_truth_path = ground_truth_path
        self.model_configs = model_configs
        self.output_dir = output_dir
        self.env_file = env_file
        
        # Load ground truth
        with open(ground_truth_path, 'r', encoding='utf-8') as f:
            gt_data = json.load(f)
            all_documents = gt_data.get('documents', [])
        
        # Filter documents if exclude list is provided
        if exclude_documents:
            self.documents = [
                doc for doc in all_documents 
                if doc.get('document_id') not in exclude_documents
            ]
            excluded = [doc.get('document_id') for doc in all_documents if doc.get('document_id') in exclude_documents]
            if excluded:
                print(f"🚫 Excluding documents: {', '.join(excluded)}")
        else:
            self.documents = all_documents
        
        print(f"📊 Loaded {len(self.documents)} documents from ground truth")
        print(f"🔧 Testing {len(model_configs)} model configurations")
    
    async def run_all(self, repeats: int = 1, max_workers: int = 1):
        """
        Run all evaluations.
        
        Args:
            repeats: Number of times to repeat each document evaluation
            max_workers: Maximum number of parallel runs (default: 1, sequential)
        """
        results = {
            'run_metadata': {
                'start_time': datetime.now().isoformat(),
                'ground_truth_path': str(self.ground_truth_path),
                'n_documents': len(self.documents),
                'n_model_configs': len(self.model_configs),
                'model_configs': [str(c) for c in self.model_configs],
                'repeats': repeats
            },
            'per_model_per_document': {}
        }
        
        # Run each model config
        for config_path in self.model_configs:
            config_name = config_path.stem  # e.g., "anthropic" from "anthropic.env"
            print(f"\n{'='*70}")
            print(f"🚀 Running with config: {config_name} (Repeats: {repeats})")
            print(f"{'='*70}\n")
            
            model_results = await self._run_with_config(config_path, config_name, repeats, max_workers)
            results['per_model_per_document'][config_name] = model_results
        
        results['run_metadata']['end_time'] = datetime.now().isoformat()
        
        # Save run metadata
        metadata_file = self.output_dir / 'run_metadata.json'
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        
        print(f"\n✅ Batch evaluation complete!")
        print(f"📄 Run metadata saved to: {metadata_file}")
        
        # Run evaluators to compute detailed metrics
        print(f"\n📊 Running evaluators to compute detailed metrics...")
        try:
            eval_results = self._run_evaluators()
            if eval_results:
                eval_file = self.output_dir / 'evaluation_results.json'
                with open(eval_file, 'w', encoding='utf-8') as f:
                    json.dump(eval_results, f, indent=2)
                print(f"✅ Evaluation results saved to: {eval_file}")
        except Exception as e:
            print(f"⚠️  Failed to run evaluators: {e}")
            print(f"   You can manually run: python evaluation/scripts/evaluate_outputs.py --run-dir {self.output_dir} --ground-truth {self.ground_truth_path} --env-file {self.env_file}")
        
        return results
    
    def _run_evaluators(self) -> Dict[str, Any]:
        """
        Run evaluators on batch outputs to compute detailed metrics.
        
        Returns:
            Evaluation results dict
        """
        try:
            # Import evaluator orchestrator
            eval_script_path = Path(__file__).parent / 'evaluate_outputs.py'
            if not eval_script_path.exists():
                print(f"⚠️  Evaluation script not found: {eval_script_path}")
                return None
            
            # Run evaluation script as subprocess to avoid import conflicts
            python_exe = sys.executable
            cmd = [
                python_exe,
                str(eval_script_path),
                '--run-dir', str(self.output_dir),
                '--ground-truth', str(self.ground_truth_path),
                '--env-file', str(self.env_file)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,
                check=False
            )
            
            if result.returncode == 0:
                # Try to load evaluation results
                eval_file = self.output_dir / 'evaluation_results.json'
                if eval_file.exists():
                    with open(eval_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
                return {'status': 'completed', 'output': result.stdout}
            else:
                print(f"⚠️  Evaluator script returned code {result.returncode}")
                if result.stderr:
                    print(f"   Error: {result.stderr[:500]}")
                return None
                
        except Exception as e:
            print(f"⚠️  Error running evaluators: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _run_with_config(
        self,
        config_path: Path,
        config_name: str,
        repeats: int = 1,
        max_workers: int = 1
    ) -> Dict[str, Any]:
        """
        Run all documents with a specific model config.
        
        Args:
            config_path: Path to model config .env file
            config_name: Name identifier for this config
            repeats: Number of repetitions
            max_workers: Maximum number of parallel runs (default: 1, sequential)
            
        Returns:
            Dict mapping document_id -> list of results (one per repeat)
        """
        # Get model info for LangSmith project naming (before loading env)
        # Load env files to get model info
        load_dotenv(config_path, override=True)
        load_dotenv(self.env_file, override=True)
        
        provider = os.getenv('LLM_PROVIDER', 'unknown')
        model = os.getenv('FAIRIFIER_LLM_MODEL', 'unknown')
        
        print(f"📊 Config: {config_name}")
        print(f"🤖 Model: {provider}/{model}")
        print(f"⚡ Parallel workers: {max_workers}\n")
        
        # Create output directory for this config
        config_output_dir = self.output_dir / 'outputs' / config_name
        config_output_dir.mkdir(parents=True, exist_ok=True)
        
        model_results = {}
        
        # Run each document
        for doc_idx, doc in enumerate(self.documents, 1):
            doc_id = doc['document_id']
            doc_path = doc['document_path']
            
            print(f"[{doc_idx}/{len(self.documents)}] Processing: {doc_id}")
            
            # Prepare all run tasks
            run_tasks = [
                (doc_id, doc_path, config_name, config_path, config_output_dir, run_idx)
                for run_idx in range(1, repeats + 1)
            ]
            
            # Run in parallel if max_workers > 1
            if max_workers > 1 and len(run_tasks) > 1:
                print(f"   Running {len(run_tasks)} runs in parallel (max {max_workers} workers)...")
                doc_results = self._run_parallel(run_tasks, max_workers)
            else:
                # Sequential execution
                doc_results = []
                for task in run_tasks:
                    doc_id, doc_path, config_name, config_path, config_output_dir, run_idx = task
                    print(f"   Running repeat {run_idx}/{repeats}...")
                    
                    try:
                        result = self._run_single_document(
                            doc_id=doc_id,
                            doc_path=doc_path,
                            config_name=config_name,
                            config_path=config_path,
                            config_output_dir=config_output_dir,
                            run_idx=run_idx
                        )
                        doc_results.append(result)
                        
                        status = "✅ SUCCESS" if result['success'] else "❌ FAILED"
                        print(f"   Run {run_idx}: {status}")
                        
                        # CRITICAL: If JSON parsing failed, stop all further runs for this document
                        if not result['success'] and result.get('error') and 'JSON parsing failure' in result.get('error', ''):
                            print(f"   ⛔ JSON parsing failure detected - stopping all remaining runs for {doc_id}")
                            # Fill remaining runs with failure status
                            for remaining_idx in range(run_idx + 1, repeats + 1):
                                doc_results.append({
                                    'success': False,
                                    'error': 'Skipped due to JSON parsing failure in previous run',
                                    'document_id': doc_id,
                                    'config_name': config_name,
                                    'run_idx': remaining_idx
                                })
                            break  # Exit the repeat loop
                        
                    except Exception as e:
                        print(f"   Run {run_idx}: ❌ ERROR: {e}")
                        doc_results.append({
                            'success': False,
                            'error': str(e),
                            'document_id': doc_id,
                            'config_name': config_name,
                            'run_idx': run_idx
                        })
                        
                        # If it's a JSON parsing error, stop remaining runs
                        if 'JSON' in str(e) and 'parse' in str(e).lower():
                            print(f"   ⛔ JSON parsing error detected - stopping all remaining runs for {doc_id}")
                            for remaining_idx in range(run_idx + 1, repeats + 1):
                                doc_results.append({
                                    'success': False,
                                    'error': 'Skipped due to JSON parsing error in previous run',
                                    'document_id': doc_id,
                                    'config_name': config_name,
                                    'run_idx': remaining_idx
                                })
                            break
            
            # Sort results by run_idx to maintain order
            doc_results.sort(key=lambda x: x.get('run_idx', 0))
            model_results[doc_id] = doc_results
        
        return model_results
    
    def _run_parallel(self, run_tasks: List[tuple], max_workers: int) -> List[Dict[str, Any]]:
        """
        Run multiple document runs in parallel.
        
        Args:
            run_tasks: List of (doc_id, doc_path, config_name, config_path, config_output_dir, run_idx) tuples
            max_workers: Maximum number of parallel workers
            
        Returns:
            List of result dictionaries
        """
        results = []
        json_parse_failed = False
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_task = {
                executor.submit(
                    self._run_single_document,
                    doc_id=task[0],
                    doc_path=task[1],
                    config_name=task[2],
                    config_path=task[3],
                    config_output_dir=task[4],
                    run_idx=task[5]
                ): task
                for task in run_tasks
            }
            
            # Collect results as they complete
            completed_results = {}
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                run_idx = task[5]
                
                try:
                    result = future.result()
                    completed_results[run_idx] = result
                    
                    status = "✅ SUCCESS" if result['success'] else "❌ FAILED"
                    print(f"   Run {run_idx}: {status}")
                    
                    # Check for JSON parsing failure
                    if not result['success'] and result.get('error') and 'JSON parsing failure' in result.get('error', ''):
                        json_parse_failed = True
                        print(f"   ⛔ JSON parsing failure detected in run {run_idx} - will skip remaining runs")
                        
                except Exception as e:
                    print(f"   Run {run_idx}: ❌ ERROR: {e}")
                    completed_results[run_idx] = {
                        'success': False,
                        'error': str(e),
                        'document_id': task[0],
                        'config_name': task[2],
                        'run_idx': run_idx
                    }
                    
                    if 'JSON' in str(e) and 'parse' in str(e).lower():
                        json_parse_failed = True
                        print(f"   ⛔ JSON parsing error detected in run {run_idx} - will skip remaining runs")
        
        # Sort by run_idx and fill in skipped runs if JSON parsing failed
        sorted_run_indices = sorted(completed_results.keys())
        for run_idx in sorted_run_indices:
            results.append(completed_results[run_idx])
        
        # If JSON parsing failed, mark remaining incomplete runs as skipped
        if json_parse_failed:
            max_run_idx = max([task[5] for task in run_tasks])
            completed_run_indices = set(completed_results.keys())
            for run_idx in range(1, max_run_idx + 1):
                if run_idx not in completed_run_indices:
                    results.append({
                        'success': False,
                        'error': 'Skipped due to JSON parsing failure in another run',
                        'document_id': run_tasks[0][0],
                        'config_name': run_tasks[0][2],
                        'run_idx': run_idx
                    })
            # Sort again after adding skipped runs
            results.sort(key=lambda x: x.get('run_idx', 0))
        
        return results
    
    def _run_single_document(
        self,
        doc_id: str,
        doc_path: str,
        config_name: str,
        config_path: Path,
        config_output_dir: Path,
        run_idx: int = 1
    ) -> Dict[str, Any]:
        """
        Run FAIRiAgent on a single document using CLI (same as manual execution).
        
        Returns:
            Result dict with success status and file paths
        """
        # Create document-specific output directory for this run
        doc_output_dir = config_output_dir / doc_id / f"run_{run_idx}"
        doc_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Resolve document path (might be relative to evaluation dir)
        project_root = Path(__file__).parents[2]
        if not Path(doc_path).is_absolute():
            # Try relative to project root
            resolved_doc_path = project_root / doc_path
            if not resolved_doc_path.exists():
                # Try relative to evaluation dir
                resolved_doc_path = Path(__file__).parents[1] / doc_path
        else:
            resolved_doc_path = Path(doc_path)
        
        if not resolved_doc_path.exists():
            raise FileNotFoundError(f"Document not found: {doc_path}")
        
        # Run FAIRiAgent CLI exactly like manual execution
        # This ensures all configuration loading happens the same way
        start_time = datetime.now()
        
        # Build command: python -m fairifier.cli process <doc> --output-dir <out> --env-file <config>
        python_exe = sys.executable
        cmd = [
            python_exe,
            '-m', 'fairifier.cli',
            'process',
            str(resolved_doc_path),
            '--output-dir', str(doc_output_dir),
            '--env-file', str(config_path),
            '--project-id', f"eval_{config_name}_{doc_id}_run{run_idx}"
        ]
        
        # Run CLI command with full environment (preserve PATH and other env vars)
        # This ensures MinerU and other tools are accessible
        env = os.environ.copy()
        
        # Run CLI command
        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                env=env,  # Pass full environment
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout
                check=False  # Don't raise on non-zero exit
            )
            
            end_time = datetime.now()
            runtime = (end_time - start_time).total_seconds()
            
            # Save CLI output for debugging
            cli_output_path = doc_output_dir / 'cli_output.txt'
            with open(cli_output_path, 'w', encoding='utf-8') as f:
                f.write(f"Command: {' '.join(cmd)}\n")
                f.write(f"Return code: {result.returncode}\n")
                f.write(f"\n=== STDOUT ===\n{result.stdout}\n")
                f.write(f"\n=== STDERR ===\n{result.stderr}\n")
            
            # CRITICAL: Check for JSON parsing failures - if found, immediately fail
            combined_output = (result.stdout or "") + (result.stderr or "")
            json_parse_error_patterns = [
                "Failed to parse LLM response as JSON",
                "Failed to parse LLM response as JSON after all fallback strategies",
                "❌ Failed to parse LLM response"
            ]
            
            json_parse_failed = False
            for pattern in json_parse_error_patterns:
                if pattern in combined_output:
                    json_parse_failed = True
                    print(f"   ❌ CRITICAL: JSON parsing failure detected: {pattern}")
                    print(f"   ⛔ Terminating workflow immediately")
                    break
            
            if json_parse_failed:
                success = False
                error_msg = f"JSON parsing failure detected - workflow terminated immediately"
                metadata_json_path = None
            else:
                success = result.returncode == 0
                
                # Check if metadata_json.json was created
                metadata_json_path = doc_output_dir / 'metadata_json.json'
                if not metadata_json_path.exists():
                    # Try to find it in subdirectories (FAIRiAgent might create nested dirs)
                    found_metadata = list(doc_output_dir.rglob('metadata_json.json'))
                    if found_metadata:
                        metadata_json_path = found_metadata[0]
                
                if not metadata_json_path.exists():
                    success = False
                    error_msg = "metadata_json.json not found after workflow completion"
                else:
                    error_msg = None
                
                if not success and error_msg:
                    print(f"   ⚠️  CLI returned code {result.returncode}: {error_msg}")
                    if result.stderr:
                        print(f"   Error: {result.stderr[:200]}")
            
        except subprocess.TimeoutExpired:
            end_time = datetime.now()
            runtime = (end_time - start_time).total_seconds()
            success = False
            error_msg = f"Workflow timed out after {runtime:.1f} seconds"
            metadata_json_path = None
            cli_output_path = doc_output_dir / 'cli_output.txt'
            with open(cli_output_path, 'w', encoding='utf-8') as f:
                f.write(f"Command: {' '.join(cmd)}\n")
                f.write(f"Error: {error_msg}\n")
        
        # Extract metadata from JSON if available
        metadata_fields = []
        confidence_scores = {}
        if metadata_json_path and metadata_json_path.exists():
            try:
                with open(metadata_json_path, 'r', encoding='utf-8') as f:
                    metadata_json = json.load(f)
                    # Extract field count and confidence scores
                    if isinstance(metadata_json, dict):
                        metadata_fields = list(metadata_json.keys())
                        # Try to extract confidence if available
                        if 'confidence' in metadata_json:
                            confidence_scores = metadata_json.get('confidence', {})
            except Exception as e:
                print(f"   ⚠️  Could not parse metadata_json: {e}")
        
        result = {
            'success': success,
            'document_id': doc_id,
            'config_name': config_name,
            'run_idx': run_idx,
            'runtime_seconds': runtime,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'output_dir': str(doc_output_dir),
            'metadata_json_path': str(metadata_json_path) if metadata_json_path else None,
            'n_fields_extracted': len(metadata_fields),
            'confidence_scores': confidence_scores,
            'error': error_msg
        }
        
        # Save individual result
        result_file = doc_output_dir / 'eval_result.json'
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        
        return result


async def main():
    parser = argparse.ArgumentParser(
        description="Batch Evaluation Runner for FAIRiAgent",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--env-file', type=Path, required=True,
                       help='Main evaluation env file')
    parser.add_argument('--model-configs', type=Path, nargs='+', required=True,
                       help='Model config .env files')
    parser.add_argument('--ground-truth', type=Path, required=True,
                       help='Ground truth JSON file')
    parser.add_argument('--output-dir', type=Path, required=True,
                       help='Output directory for all runs')
    parser.add_argument('--repeats', type=int, default=1,
                       help='Number of repeats per document (default: 1)')
    parser.add_argument('--workers', type=int, default=1,
                       help='Number of parallel workers for running multiple repeats (default: 1, sequential)')
    parser.add_argument('--exclude-documents', type=str, nargs='+', default=None,
                       help='Document IDs to exclude from evaluation (e.g., --exclude-documents biorem)')
    
    args = parser.parse_args()
    
    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize runner
    runner = BatchEvaluationRunner(
        ground_truth_path=args.ground_truth,
        model_configs=args.model_configs,
        output_dir=args.output_dir,
        env_file=args.env_file,
        exclude_documents=args.exclude_documents
    )
    
    # Run all evaluations
    await runner.run_all(repeats=args.repeats, max_workers=args.workers)
    
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))

