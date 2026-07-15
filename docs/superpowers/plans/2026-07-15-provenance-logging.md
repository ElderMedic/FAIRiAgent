# Provenance Logging Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure `critic_evaluation` records are safely captured in `processing_log.jsonl` before compaction, and implement a unified log writing utility to safely merge disk and memory logs across runners.

**Architecture:** Append `critic_evaluation` directly to disk during the retry loop. Replace the disjoint log-saving implementations in `cli.py` and `runner.py` with a new `save_processing_log` utility that merges, deduplicates, and chronologically sorts all logs.

**Tech Stack:** Python, JSON

---

### Task 1: Add Unified Log Saver

**Files:**
- Modify: `fairifier/utils/json_logger.py`

- [ ] **Step 1: Write `save_processing_log` utility**

Append the new function at the end of the file.

```python
def save_processing_log(log_path: "Path", json_logger: JSONLogger) -> None:
    """Safely merge dynamically written events and memory-buffered logs, sort chronologically, and overwrite file."""
    import json
    from pathlib import Path
    
    events = []
    seen = set()

    # 1. Read existing events from disk (e.g., dynamically written context_usage, critic_evaluation)
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            # Parse to ensure it's valid JSON
                            ev = json.loads(line)
                            # Re-serialize to canonical string for deduplication
                            str_ev = json.dumps(ev, ensure_ascii=False)
                            if str_ev not in seen:
                                seen.add(str_ev)
                                events.append(ev)
                        except json.JSONDecodeError:
                            pass
        except OSError:
            pass

    # 2. Combine with memory-buffered events
    for ev in json_logger.get_logs():
        str_ev = json.dumps(ev, ensure_ascii=False)
        if str_ev not in seen:
            seen.add(str_ev)
            events.append(ev)
            
    # 3. Sort chronologically by timestamp
    events.sort(key=lambda x: x.get("timestamp", ""))

    # 4. Overwrite file with unified, sorted list
    with open(log_path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
```

- [ ] **Step 2: Commit**

```bash
git add fairifier/utils/json_logger.py
git commit -m "feat: add save_processing_log utility for unified log merging"
```

### Task 2: Append Critic Evaluation Event to Disk

**Files:**
- Modify: `fairifier/graph/nodes.py`

- [ ] **Step 1: Write to disk right after Critic and hard gate evaluations**

In `_execute_agent_with_retry`, add the disk-write logic just before the `# Handle decision` section (around line 1474). We also include a helper to write the `execution_record` if it fails earlier (we'll capture it in the `except` block).

Find the `# Handle decision` comment (around line 1474). Insert the following code just **before** it:

```python
            # --- START NEW DISK APPEND ---
            if log_path:
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            "event": "critic_evaluation",
                            "timestamp": datetime.now().isoformat(),
                            "agent_name": agent_name,
                            "attempt": attempt,
                            "start_time": last_execution.get("start_time"),
                            "end_time": last_execution.get("end_time"),
                            "success": last_execution.get("success"),
                            "error": last_execution.get("error"),
                            "critic_evaluation": critic_eval
                        }, ensure_ascii=False) + "\n")
                except Exception as exc:
                    logger.warning("Failed to append critic_evaluation to log: %s", exc)
            # --- END NEW DISK APPEND ---

            # Handle decision
            if decision == "ACCEPT":
```

- [ ] **Step 2: Append failed attempts**

In `_execute_agent_with_retry`, find the `except Exception as e:` block inside the retry loop (around line 1355). Just before it decides whether to `continue` or `break` (around line 1362), add the logging logic:

```python
                # --- START NEW DISK APPEND ---
                if log_path:
                    try:
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(json.dumps({
                                "event": "critic_evaluation",
                                "timestamp": datetime.now().isoformat(),
                                "agent_name": agent_name,
                                "attempt": attempt,
                                "start_time": execution_record.get("start_time"),
                                "end_time": execution_record.get("end_time"),
                                "success": False,
                                "error": execution_record.get("error"),
                                "critic_evaluation": None
                            }, ensure_ascii=False) + "\n")
                    except Exception as exc:
                        logger.warning("Failed to append failed attempt to log: %s", exc)
                # --- END NEW DISK APPEND ---
                
                # On error, try next attempt if available
                if attempt <= self.max_step_retries:
```

- [ ] **Step 3: Commit**

```bash
git add fairifier/graph/nodes.py
git commit -m "feat: persist critic_evaluation to processing_log.jsonl dynamically"
```

### Task 3: Unify CLI Runner Log Saving

**Files:**
- Modify: `fairifier/cli.py`

- [ ] **Step 1: Replace custom saving logic**

Find the block saving `processing_log.jsonl` (around line 616-636) inside `_run_workflow`:

Replace this:
```python
        # Save processing log — preserve context_usage events written inline
        # during the run by log_context_usage (context observability §6).
        log_file = output_path / "processing_log.jsonl"
        existing_context_events: list = []
        if log_file.exists():
            try:
                for raw_line in log_file.read_text(encoding="utf-8").splitlines():
                    raw_line = raw_line.strip()
                    if raw_line:
                        ev = json.loads(raw_line)
                        if ev.get("event") == "context_usage":
                            existing_context_events.append(ev)
            except Exception:
                pass
        with open(log_file, "w", encoding="utf-8") as f:
            for log_entry in json_logger.get_logs():
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            for ev in existing_context_events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        click.echo(f"  ✓ processing_log.jsonl")
```

With this:
```python
        # Save processing log using unified utility to safely merge disk and memory logs
        from fairifier.utils.json_logger import save_processing_log
        log_file = output_path / "processing_log.jsonl"
        try:
            save_processing_log(log_file, json_logger)
            click.echo(f"  ✓ processing_log.jsonl")
        except Exception as exc:
            click.echo(f"  ⚠️  Failed to save processing_log.jsonl: {exc}", err=True)
```

- [ ] **Step 2: Commit**

```bash
git add fairifier/cli.py
git commit -m "refactor: use unified save_processing_log in CLI runner"
```

### Task 4: Unify API Runner Log Saving

**Files:**
- Modify: `fairifier/apps/api/services/runner.py`

- [ ] **Step 1: Replace custom saving logic**

Find the block saving `processing_log.jsonl` (around line 627-641) inside `_persist_run_outputs`:

Replace this:
```python
    log_path = output_path / "processing_log.jsonl"
    try:
        with log_path.open("w", encoding="utf-8") as fh:
            for log_entry in json_logger.get_logs():
                fh.write(
                    json.dumps(
                        log_entry, ensure_ascii=False
                    )
                    + "\n"
                )
    except Exception as exc:
        msg = f"Failed to save processing_log.jsonl: {exc}"
        logger.warning(msg)
        errors.append(msg)
```

With this:
```python
    log_path = output_path / "processing_log.jsonl"
    try:
        from fairifier.utils.json_logger import save_processing_log
        save_processing_log(log_path, json_logger)
    except Exception as exc:
        msg = f"Failed to save processing_log.jsonl: {exc}"
        logger.warning(msg)
        errors.append(msg)
```

- [ ] **Step 2: Commit**

```bash
git add fairifier/apps/api/services/runner.py
git commit -m "refactor: use unified save_processing_log in API runner"
```
