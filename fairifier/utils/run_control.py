"""Thread-safe run control for interrupting long-running workflows."""

import threading
from typing import Optional

_lock = threading.Lock()
_global_stop_requested = False
_run_stop_requests: dict[str, bool] = {}


def run_stop_requested(run_id: Optional[str] = None) -> bool:
    """Return True if the current run should stop."""
    with _lock:
        if _global_stop_requested:
            return True
        if run_id is None:
            return False
        return _run_stop_requests.get(run_id, False)


def set_run_stop_requested(
    value: bool = True, run_id: Optional[str] = None
) -> None:
    """Set the stop flag so the workflow can exit at the next checkpoint."""
    global _global_stop_requested
    with _lock:
        if run_id is None:
            _global_stop_requested = value
            return
        if value:
            _run_stop_requests[run_id] = True
        else:
            _run_stop_requests.pop(run_id, None)


def reset_run_stop_requested(run_id: Optional[str] = None) -> None:
    """Reset the stop flag before starting a new run."""
    set_run_stop_requested(False, run_id=run_id)
