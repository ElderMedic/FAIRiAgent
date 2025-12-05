# Evaluation Archive

This directory contains archived files that are no longer actively used but kept for reference.

## Structure

- **docs/**: Old documentation files (superseded by current README.md)
- **scripts/**: One-time or deprecated scripts
- **logs/**: Old log files from analysis runs
- **runs/**: Old run directories (rerun, baseline batches)

## Contents

### Documentation
- `ANALYSIS_FAILURE_CLASSIFICATION.md`: Failure classification documentation
- `ANALYSIS_REFACTORING.md`: Refactoring notes
- `BASELINE_EVALUATION.md`: Baseline evaluation documentation
- `BASELINE_VS_AGENTIC_COMPARISON.md`: Comparison documentation
- `EVALUATION_CHANGES.md`: Change log
- `EVALUATION_STATUS_SUMMARY.md`: Status summaries
- `RERUN_GUIDE.md`: Rerun guide (now in main README)
- `FINAL_ANALYSIS_RESULTS.md`: Old analysis results

### Scripts
- `aggregate_evaluation_results.py`: Superseded by `analysis/run_analysis.py`
- `generate_report.py`: Superseded by `analysis/reports/report_generator.py`
- `rerun_missing_runs.sh`: Duplicate of `rerun_failed.sh`
- `monitor_parallel.sh`, `show_full_logs.sh`, `tail_all_logs.sh`, `test_baseline.sh`: Temporary monitoring scripts
- `add_biorem_to_ground_truth.py`, `clean_ground_truth.py`, `convert_excel_to_ground_truth.py`: One-time data preparation scripts

### Data
- Old ground truth files (v1, v2, rerun, template versions)
- Old run directories (rerun batches, baseline batches)

## Note

Files in this archive are kept for historical reference but should not be used for new analyses. Always use the current files in the main evaluation directory.

