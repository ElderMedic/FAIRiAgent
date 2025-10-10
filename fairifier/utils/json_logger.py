"""JSON line-based logging utility for FAIR-DS compatibility."""

import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from enum import Enum


class LogLevel(Enum):
    """Log levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class JSONLogger:
    """JSON line-based logger that outputs to stdout."""
    
    def __init__(self, component: str = "fairifier", enable_stdout: bool = True):
        self.component = component
        self.enable_stdout = enable_stdout
        self.logs = []  # Store logs for later retrieval
    
    def _log(self, level: LogLevel, event: str, **kwargs) -> None:
        """Internal logging method."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level.value,
            "component": self.component,
            "event": event,
            **kwargs
        }
        
        # Store log
        self.logs.append(log_entry)
        
        # Output to stdout
        if self.enable_stdout:
            print(json.dumps(log_entry, ensure_ascii=False), file=sys.stdout, flush=True)
    
    def debug(self, event: str, **kwargs) -> None:
        """Log debug message."""
        self._log(LogLevel.DEBUG, event, **kwargs)
    
    def info(self, event: str, **kwargs) -> None:
        """Log info message."""
        self._log(LogLevel.INFO, event, **kwargs)
    
    def warning(self, event: str, **kwargs) -> None:
        """Log warning message."""
        self._log(LogLevel.WARNING, event, **kwargs)
    
    def error(self, event: str, **kwargs) -> None:
        """Log error message."""
        self._log(LogLevel.ERROR, event, **kwargs)
    
    def critical(self, event: str, **kwargs) -> None:
        """Log critical message."""
        self._log(LogLevel.CRITICAL, event, **kwargs)
    
    def log_processing_start(self, document_path: str, project_id: str) -> None:
        """Log processing start."""
        self.info(
            "processing_started",
            document_path=document_path,
            project_id=project_id
        )
    
    def log_processing_end(self, project_id: str, status: str, duration_seconds: float) -> None:
        """Log processing end."""
        self.info(
            "processing_completed",
            project_id=project_id,
            status=status,
            duration_seconds=round(duration_seconds, 2)
        )
    
    def log_agent_execution(self, agent_name: str, action: str, **kwargs) -> None:
        """Log agent execution."""
        self.info(
            "agent_execution",
            agent=agent_name,
            action=action,
            **kwargs
        )
    
    def log_field_extracted(
        self, 
        field_name: str, 
        value: Optional[str], 
        confidence: float,
        origin: str
    ) -> None:
        """Log metadata field extraction."""
        self.info(
            "field_extracted",
            field_name=field_name,
            value=value,
            confidence=round(confidence, 3),
            origin=origin
        )
    
    def log_validation_result(
        self, 
        is_valid: bool, 
        error_count: int, 
        warning_count: int
    ) -> None:
        """Log validation results."""
        self.info(
            "validation_completed",
            is_valid=is_valid,
            error_count=error_count,
            warning_count=warning_count
        )
    
    def log_confidence_score(self, component: str, score: float) -> None:
        """Log confidence score."""
        self.info(
            "confidence_score",
            component=component,
            score=round(score, 3)
        )
    
    def get_logs(self) -> list:
        """Get all stored logs."""
        return self.logs
    
    def get_logs_json(self) -> str:
        """Get all logs as JSON string."""
        return json.dumps(self.logs, ensure_ascii=False, indent=2)
    
    def clear_logs(self) -> None:
        """Clear stored logs."""
        self.logs = []


# Global logger instance
_global_logger: Optional[JSONLogger] = None


def get_logger(component: str = "fairifier") -> JSONLogger:
    """Get or create global JSON logger."""
    global _global_logger
    if _global_logger is None:
        _global_logger = JSONLogger(component=component)
    return _global_logger


def set_logger(logger: JSONLogger) -> None:
    """Set global logger instance."""
    global _global_logger
    _global_logger = logger

