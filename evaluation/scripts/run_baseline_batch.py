#!/usr/bin/env python3
"""
Batch runner for baseline single-prompt evaluations.

Runs baseline extractions on multiple documents with multiple repeats,
matching the structure used for agentic workflow evaluations.
"""

import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add project root to path
sys.path.insert(0, str(Path(__file__).parents[2]))


class BaselineBatchRunner:
    """Batch runner for baseline evaluations."""
    
    def __init__(
        self,
        config_file: Path,
        config_name: str,
        ground_truth: Path,
        output_dir: Path,
        workers: int = 3,
        n_runs: int = 10
    ):
        self.config_file = config_file
        self.config_name = config_name
        self.ground_truth = ground_truth
        self.output_dir = output_dir
        self.workers = workers
        self.n_runs = n_runs
        
        # Load ground truth
        with open(ground_truth, 'r') as f:
            self.gt_data = json.load(f)
        
        self.documents = self.gt_data.get("documents", [])
        
    def run_single_extraction(
        self,
        document: Dict[str, Any],
        run_idx: int
    ) -> Dict[str, Any]:
        """Run a single baseline extraction."""
        doc_id = document["document_id"]
        doc_path = Path(document["document_path"])
        
        # Create output directory
        run_output_dir = (
            self.output_dir / "outputs" / self.config_name / 
            doc_id / f"run_{run_idx}"
        )
        run_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create CLI output log
        cli_output_path = run_output_dir / "cli_output.txt"
        
        # Build command
        cmd = [
            sys.executable,
            "evaluation/scripts/baseline_single_prompt.py",
            str(doc_path),
            "--output-dir", str(run_output_dir),
            "--config-file", str(self.config_file),
            "--run-idx", str(run_idx)
        ]
        
        # Run extraction
        print(f"   Run {run_idx}: Starting...")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout
            )
            
            # Save CLI output
            with open(cli_output_path, 'w') as f:
                f.write(f"Command: {' '.join(cmd)}\n")
                f.write(f"Return code: {result.returncode}\n\n")
                f.write("=== STDOUT ===\n")
                f.write(result.stdout)
                f.write("\n\n=== STDERR ===\n")
                f.write(result.stderr)
            
            if result.returncode == 0:
                print(f"   Run {run_idx}: ✅ SUCCESS")
                return {"run_idx": run_idx, "status": "success"}
            else:
                print(f"   Run {run_idx}: ❌ FAILED")
                # Try to read error from eval_result.json
                eval_result_path = run_output_dir / "eval_result.json"
                error_msg = "Unknown error"
                if eval_result_path.exists():
                    with open(eval_result_path, 'r') as f:
                        eval_data = json.load(f)
                        error_msg = eval_data.get("error", "Unknown error")
                print(f"      Error: {error_msg}")
                return {"run_idx": run_idx, "status": "failed", "error": error_msg}
                
        except subprocess.TimeoutExpired:
            print(f"   Run {run_idx}: ⏱️  TIMEOUT")
            return {"run_idx": run_idx, "status": "timeout"}
        except Exception as e:
            print(f"   Run {run_idx}: ❌ EXCEPTION: {e}")
            return {"run_idx": run_idx, "status": "error", "error": str(e)}
    
    def run_document(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """Run all repeats for a single document."""
        doc_id = document["document_id"]
        
        print(f"\n{'='*70}")
        print(f"📄 Document: {doc_id}")
        print(f"   Repeats: {self.n_runs}")
        print(f"   Workers: {self.workers}")
        print(f"{'='*70}")
        
        results = []
        
        # Run with thread pool
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self.run_single_extraction, document, i): i
                for i in range(1, self.n_runs + 1)
            }
            
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
        
        # Summary
        success_count = sum(1 for r in results if r["status"] == "success")
        fail_count = sum(1 for r in results if r["status"] == "failed")
        timeout_count = sum(1 for r in results if r["status"] == "timeout")
        
        print(f"\n📊 Summary for {doc_id}:")
        print(f"   ✅ Success: {success_count}/{self.n_runs}")
        print(f"   ❌ Failed:  {fail_count}/{self.n_runs}")
        print(f"   ⏱️  Timeout: {timeout_count}/{self.n_runs}")
        
        return {
            "document_id": doc_id,
            "total_runs": self.n_runs,
            "success": success_count,
            "failed": fail_count,
            "timeout": timeout_count,
            "results": results
        }
    
    def run(self) -> Dict[str, Any]:
        """Run all baseline evaluations."""
        print("\n" + "="*70)
        print("🔬 Baseline Single-Prompt Evaluation")
        print("="*70)
        print(f"📋 Config: {self.config_name}")
        print(f"📁 Output: {self.output_dir}")
        print(f"🔧 Workers: {self.workers}")
        print(f"🔁 Runs per document: {self.n_runs}")
        print(f"📄 Documents: {len(self.documents)}")
        print("="*70)
        
        start_time = datetime.now()
        
        # Run each document
        document_results = []
        for doc in self.documents:
            doc_result = self.run_document(doc)
            document_results.append(doc_result)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Save run metadata
        run_metadata = {
            "config_name": self.config_name,
            "config_file": str(self.config_file),
            "ground_truth": str(self.ground_truth),
            "output_dir": str(self.output_dir),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "n_documents": len(self.documents),
            "n_runs_per_document": self.n_runs,
            "workers": self.workers,
            "baseline_method": "single_prompt",
            "document_results": document_results
        }
        
        metadata_path = self.output_dir / "run_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(run_metadata, f, indent=2)
        
        # Print final summary
        print("\n" + "="*70)
        print("✅ Baseline evaluation complete!")
        print("="*70)
        print(f"⏱️  Total duration: {duration:.1f}s")
        print(f"📄 Metadata saved: {metadata_path}")
        
        total_success = sum(r["success"] for r in document_results)
        total_runs = sum(r["total_runs"] for r in document_results)
        print(f"📊 Overall success: {total_success}/{total_runs} ({100*total_success/total_runs:.1f}%)")
        print("="*70)
        
        return run_metadata


def main():
    parser = argparse.ArgumentParser(
        description="Run baseline single-prompt batch evaluation"
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        required=True,
        help="Model configuration file"
    )
    parser.add_argument(
        "--config-name",
        type=str,
        required=True,
        help="Configuration name (e.g., 'baseline_gpt4')"
    )
    parser.add_argument(
        "--ground-truth",
        type=Path,
        required=True,
        help="Ground truth JSON file"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Number of parallel workers (default: 3)"
    )
    parser.add_argument(
        "--n-runs",
        type=int,
        default=10,
        help="Number of runs per document (default: 10)"
    )
    
    args = parser.parse_args()
    
    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Run batch evaluation
    runner = BaselineBatchRunner(
        config_file=args.config_file,
        config_name=args.config_name,
        ground_truth=args.ground_truth,
        output_dir=args.output_dir,
        workers=args.workers,
        n_runs=args.n_runs
    )
    
    runner.run()


if __name__ == "__main__":
    main()

