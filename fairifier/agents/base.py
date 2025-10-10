"""Base agent class for FAIRifier agents."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging
from datetime import datetime

from ..models import FAIRifierState
from ..config import config

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for all FAIRifier agents."""
    
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"fairifier.agents.{name}")
        
    @abstractmethod
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """Execute the agent's main functionality."""
        pass
    
    def log_execution(self, state: FAIRifierState, message: str, level: str = "info"):
        """Log agent execution with context."""
        timestamp = datetime.now().isoformat()
        log_entry = f"[{timestamp}] {self.name}: {message}"
        
        if level == "error":
            self.logger.error(log_entry)
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(log_entry)
        elif level == "warning":
            self.logger.warning(log_entry)
        else:
            self.logger.info(log_entry)
    
    def update_confidence(self, state: FAIRifierState, component: str, score: float):
        """Update confidence score for a component."""
        if "confidence_scores" not in state:
            state["confidence_scores"] = {}
        state["confidence_scores"][component] = score
        
        # Check if human review is needed
        if score < config.min_confidence_threshold:
            state["needs_human_review"] = True
            self.log_execution(
                state, 
                f"Low confidence score ({score:.2f}) for {component}, flagging for human review"
            )
