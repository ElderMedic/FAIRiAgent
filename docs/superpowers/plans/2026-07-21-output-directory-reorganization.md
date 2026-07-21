# Output Directory Reorganization & Values Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize output directory into functional subdirectories (`deliverables/`, `logs/`, `reports/`, `workspace/`), rename `isa_values_json.json` to `isa_values.json`, and strip filled values from `metadata.json` so it contains only metadata schema & field definitions.

**Architecture:** Update `fairifier/output_paths.py` with subdirectory constants and backward-compatible path resolution functions. Update state/artifact projections in `isa_matrix_projection.py` and output handlers in CLI/API runners.

**Tech Stack:** Python 3.9+, Pytest, FAIRiAgent Core.

---

### Task 1: Update Output Path Constants and Resolution Helpers

**Files:**
- Modify: `fairifier/output_paths.py`
- Modify: `tests/test_output_paths.py` (or create if not present)

- [ ] **Step 1: Write unit test for backward-compatible path resolution**

```python
import pytest
from pathlib import Path
from fairifier.output_paths import (
    metadata_output_write_path,
    resolve_metadata_output_read_path,
    isa_values_output_write_path,
    resolve_isa_values_read_path,
    artifact_output_path
)

def test_resolve_metadata_and_isa_paths(tmp_path: Path):
    # Test new subdirectory paths
    deliv_dir = tmp_path / "deliverables"
    deliv_dir.mkdir()
    (deliv_dir / "metadata.json").write_text("{}")
    (deliv_dir / "isa_values.json").write_text("{}")

    assert resolve_metadata_output_read_path(tmp_path) == deliv_dir / "metadata.json"
    assert resolve_isa_values_read_path(tmp_path) == deliv_dir / "isa_values.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_output_paths.py -v`
Expected: FAIL due to missing functions/constants.

- [ ] **Step 3: Update `fairifier/output_paths.py`**

Add constants and updated helpers:
```python
DELIVERABLES_DIRNAME = "deliverables"
LOGS_DIRNAME = "logs"
REPORTS_DIRNAME = "reports"
WORKSPACE_DIRNAME = "workspace"

METADATA_OUTPUT_FILENAME = "metadata.json"
ISA_VALUES_OUTPUT_FILENAME = "isa_values.json"
LEGACY_ISA_VALUES_FILENAME = "isa_values_json.json"

def metadata_output_write_path(output_dir: Path) -> Path:
    return Path(output_dir) / DELIVERABLES_DIRNAME / METADATA_OUTPUT_FILENAME

def resolve_metadata_output_read_path(output_dir: Path) -> Optional[Path]:
    d = Path(output_dir)
    primary = d / DELIVERABLES_DIRNAME / METADATA_OUTPUT_FILENAME
    if primary.exists():
        return primary
    flat_primary = d / METADATA_OUTPUT_FILENAME
    if flat_primary.exists():
        return flat_primary
    return None

def isa_values_output_write_path(output_dir: Path) -> Path:
    return Path(output_dir) / DELIVERABLES_DIRNAME / ISA_VALUES_OUTPUT_FILENAME

def resolve_isa_values_read_path(output_dir: Path) -> Optional[Path]:
    d = Path(output_dir)
    primary = d / DELIVERABLES_DIRNAME / ISA_VALUES_OUTPUT_FILENAME
    if primary.exists():
        return primary
    flat_primary = d / ISA_VALUES_OUTPUT_FILENAME
    if flat_primary.exists():
        return flat_primary
    legacy = d / LEGACY_ISA_VALUES_FILENAME
    if legacy.exists():
        return legacy
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_output_paths.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fairifier/output_paths.py tests/test_output_paths.py
git commit -m "feat: add subdirectory constants and updated path resolvers in output_paths.py"
```

---

### Task 2: Separate Concrete Values into `isa_values.json` and Strip Values from `metadata.json`

**Files:**
- Modify: `fairifier/utils/isa_matrix_projection.py`
- Modify: `fairifier/agents/isa_value_mapper.py`
- Test: `tests/test_isa_matrix_projection.py`

- [ ] **Step 1: Write test for values separation and renaming**

```python
def test_sync_compiled_matrix_strips_values_from_metadata():
    # Verify metadata_json has schema fields without values, and isa_values has matrix
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_isa_matrix_projection.py -v`
Expected: FAIL

- [ ] **Step 3: Implement values separation in `isa_matrix_projection.py`**

Rename artifact key from `isa_values_json` to `isa_values`, and strip concrete values (`rows` / filled `value`) from `metadata.json.isa_structure`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_isa_matrix_projection.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fairifier/utils/isa_matrix_projection.py fairifier/agents/isa_value_mapper.py tests/test_isa_matrix_projection.py
git commit -m "feat: separate concrete values into isa_values.json and strip values from metadata.json"
```

---

### Task 3: Update CLI & API Runners to Write to Subdirectories

**Files:**
- Modify: `fairifier/cli.py`
- Modify: `fairifier/apps/api/services/runner.py`
- Modify: `fairifier/graph/excel.py`
- Modify: `fairifier/utils/json_logger.py`

- [ ] **Step 1: Update directory creation in CLI and API runner**

Ensure `deliverables/`, `logs/`, `reports/`, and `workspace/` directories are created.

- [ ] **Step 2: Update artifact saving logic to route files into subdirectories**

- Deliverables: `metadata.json`, `isa_values.json`, `metadata_fairds.xlsx` -> `deliverables/`
- Logs: `processing_log.jsonl`, `llm_responses.json`, `full_output.log` -> `logs/`
- Reports: `workflow_report.json`, `workflow_report.txt`, `auto_repair_trace.json`, `runtime_config.json` -> `reports/`
- Workspace: `extracted_document_content.txt`, `source_workspace/` -> `workspace/`

- [ ] **Step 3: Run fast regression tests**

Run: `mamba run -n FAIRiAgent python run_tests.py fast`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add fairifier/cli.py fairifier/apps/api/services/runner.py fairifier/graph/excel.py fairifier/utils/json_logger.py
git commit -m "refactor: save artifacts into functional subdirectories (deliverables, logs, reports, workspace)"
```

---

### Task 4: Final End-to-End Verification and Clean Cleanup

- [ ] **Step 1: Run fast test suite**

Run: `mamba run -n FAIRiAgent python run_tests.py fast`
Expected: All tests pass cleanly.

- [ ] **Step 2: Commit all remaining changes**

```bash
git commit -m "chore: complete output directory reorganization and values separation"
```
