# Provenance Logging Design

## Overview
Improve run tracing by ensuring complete `critic_evaluation` records are written to `processing_log.jsonl` before in-memory compaction, and implement a unified logging utility to safely merge and chronologically sort all dynamically and memory-buffered log events during finalization.

## Architecture & Data Flow

### 1. Critic Event Logging
- **Location:** `fairifier/graph/nodes.py` (inside `_execute_agent_with_retry`)
- **Behavior:** 
  - After Critic and hard-gate evaluations complete (or immediately if an agent exception occurs), a new event of type `critic_evaluation` is appended to `processing_log.jsonl`.
  - This ensures the full record (including uncompacted `critique`, `issues`, etc.) is safely captured on disk before the `compact_prior_attempts_for_agent` function strips verbose fields from the live state.
- **Event Schema:**
  ```json
  {
    "event": "critic_evaluation",
    "timestamp": "ISO_8601_TIMESTAMP",
    "agent_name": "AgentName",
    "attempt": 1,
    "start_time": "ISO_8601_TIMESTAMP",
    "end_time": "ISO_8601_TIMESTAMP",
    "success": true,
    "error": null,
    "critic_evaluation": { ... }
  }
  ```

### 2. Unified Log Saver
- **Location:** `fairifier/utils/json_logger.py`
- **Behavior:** A new utility function `save_processing_log(log_path: Path, json_logger: JSONLogger) -> None` will be introduced.
- **Workflow:**
  1. Read all existing entries from `log_path` (if it exists). These include dynamically written events like `context_usage`, `agent_message`, and `critic_evaluation`.
  2. Combine these with the memory-buffered entries from the current run via `json_logger.get_logs()`.
  3. Deduplicate exact duplicate JSON strings to ensure idempotency.
  4. Sort the unified list chronologically using the `timestamp` field.
  5. Overwrite the file with the complete, sorted log stream.

### 3. Runner Unification
- **Location:** `fairifier/cli.py` and `fairifier/apps/api/services/runner.py`
- **Behavior:** Replace custom overwrite/append logic in the CLI and API runners with calls to `save_processing_log()`. This guarantees that no dynamically written events are lost when memory logs are finalized.
