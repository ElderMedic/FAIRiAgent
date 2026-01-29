"""Thread-safe run control for interrupting long-running workflows (e.g. WebUI)."""

import threading

_lock = threading.Lock()
_stop_requested = False


def run_stop_requested() -> bool:
    """Return True if the current run should stop (e.g. user clicked Stop)."""
    with _lock:
        return _stop_requested


def set_run_stop_requested(value: bool = True) -> None:
    """Set the stop flag so the workflow can exit at the next step."""
    global _stop_requested
    with _lock:
        _stop_requested = value


def reset_run_stop_requested() -> None:
    """Reset the stop flag before starting a new run."""
    set_run_stop_requested(False)
