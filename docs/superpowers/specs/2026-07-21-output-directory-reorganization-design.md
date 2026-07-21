# Design Spec: Output Directory Reorganization & Values Separation

## Overview

This specification defines the reorganization of run output directories in FAIRiAgent and the separation of schema metadata (`metadata.json`) from concrete extracted values (`isa_values.json`).

## Requirements & Goals

1. **Subdirectory Categorization**: Organize flat files inside `output/<run_id>/` into functional subdirectories (`deliverables/`, `logs/`, `reports/`, `workspace/`).
2. **Data Separation**:
   - `metadata.json`: Holds metadata schema, field definitions, requirements, evidence, confidence, package sources, and status, omitting concrete extracted field values.
   - `isa_values.json`: Renamed from legacy `isa_values_json.json`, stores the compiled concrete values across ISA levels (`investigation`, `study`, `observationunit`, `sample`, `assay`).
3. **Backward Compatibility**: Provide helper resolution routines (`resolve_isa_values_path`, `resolve_metadata_output_read_path`) so evaluation scripts, WebUI, and tools can seamlessly read both old flat output structures and new subdirectory structures.

## Directory Layout Specification

```text
output/<run_id>/
├── deliverables/               # Core user outputs
│   ├── metadata.json           # Schema & field metadata (without values)
│   ├── isa_values.json         # Extracted concrete ISA matrix values
│   └── metadata_fairds.xlsx    # Excel export format
├── logs/                       # Tracing & execution logs
│   ├── processing_log.jsonl    # LangGraph execution & Critic event log
│   ├── llm_responses.json      # LLM raw prompts, responses & token usage
│   └── full_output.log         # Optional raw stdout stream
├── reports/                    # Execution & quality reports
│   ├── workflow_report.json    # Machine-readable telemetry & metrics
│   ├── workflow_report.txt     # Human-readable summary
│   ├── auto_repair_trace.json  # Critic & auto-repair trace
│   └── runtime_config.json     # Execution configuration snapshot
└── workspace/                  # Intermediate extraction workspace
    ├── extracted_document_content.txt
    └── source_workspace/       # Chunking, tables, & evidence store
```

## Affected Modules & Utility Updates

1. `fairifier/output_paths.py`:
   - Define subfolders `DELIVERABLES_DIR`, `LOGS_DIR`, `REPORTS_DIR`, `WORKSPACE_DIR`.
   - Update `METADATA_OUTPUT_FILENAME` path resolver to check `deliverables/metadata.json` (falling back to flat `metadata.json`).
   - Define `ISA_VALUES_OUTPUT_FILENAME = "isa_values.json"` (legacy `isa_values_json.json`).
   - Add helper functions to compute output paths for all artifacts.

2. `fairifier/utils/isa_matrix_projection.py`:
   - Update state artifact key & filename references to `isa_values.json`.
   - Strip concrete `value` properties when writing `metadata.json` or maintain clean schema representation.

3. `fairifier/cli.py` & `fairifier/apps/api/services/runner.py`:
   - Ensure directory creation creates necessary subdirectories (`deliverables/`, `logs/`, `reports/`, `workspace/`).
   - Write files to their designated subdirectories.

4. `fairifier/graph/excel.py`, `fairifier/utils/json_logger.py`, & Evaluation Scripts:
   - Use updated resolution helpers to read artifacts from subdirectories or flat fallbacks.

## Backward Compatibility & Testing Plan

- Existing runs with flat structure will remain readable by all path resolution helpers.
- Run regression tests (`python run_tests.py fast`) to confirm all unit tests pass with updated path helpers and file names.
