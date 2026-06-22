import os
import json
import shutil
from pathlib import Path

def main():
    base_dir = Path("/Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent/evaluation/runs/petase_full_run_20260619/deepseek_v4-pro_v1.4.0")
    if not base_dir.exists():
        print(f"Base directory {base_dir} does not exist.")
        return

    failed_runs = []
    successful_runs = []

    # Iterate through all document directories
    for doc_dir in sorted(base_dir.iterdir()):
        if not doc_dir.is_dir():
            continue
        
        # Iterate through run directories (run_1, run_2, run_3)
        for run_dir in doc_dir.iterdir():
            if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
                continue
            
            metadata_path = run_dir / "metadata.json"
            eval_result_path = run_dir / "eval_result.json"
            
            is_success = False
            error_reason = "Missing files"
            
            if metadata_path.exists() and eval_result_path.exists():
                try:
                    with open(eval_result_path, "r", encoding="utf-8") as f:
                        eval_data = json.load(f)
                    if eval_data.get("success", False):
                        is_success = True
                    else:
                        error_reason = eval_data.get("error", "Flagged unsuccessful in eval_result")
                except Exception as e:
                    error_reason = f"Error reading result file: {e}"
            else:
                if not metadata_path.exists():
                    error_reason = "Missing metadata.json"
                elif not eval_result_path.exists():
                    error_reason = "Missing eval_result.json"

            run_info = {
                "doc_id": doc_dir.name,
                "run_name": run_dir.name,
                "path": run_dir,
                "reason": error_reason
            }
            
            if is_success:
                successful_runs.append(run_info)
            else:
                failed_runs.append(run_info)

    print(f"Found {len(successful_runs)} successful runs and {len(failed_runs)} failed/incomplete runs.")
    
    if failed_runs:
        print("\nFailed runs:")
        for r in failed_runs:
            print(f"  - {r['doc_id']}/{r['run_name']}: {r['reason']}")
            
        print("\nCleaning up failed run folders...")
        for r in failed_runs:
            run_path = r["path"]
            if run_path.exists():
                print(f"    Deleting {run_path}")
                shutil.rmtree(run_path)
        print("Cleanup complete!")
    else:
        print("\nNo failed runs to clean up.")

if __name__ == "__main__":
    main()
