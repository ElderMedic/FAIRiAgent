"""Base agent class for FAIRifier agents."""

from abc import ABC, abstractmethod
from typing import Dict, Any
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
    
    def get_context_feedback(self, state: FAIRifierState) -> Dict[str, Any]:
        """
        Extract feedback from context (critic feedback, human feedback, previous attempts)
        This allows agents to adapt based on reflective feedback
        """
        context = state.get("context", {})
        planner_guidance = state.get("agent_guidance", {})
        critic_feedback = context.get("critic_feedback")
        if critic_feedback:
            critic_feedback = critic_feedback.copy()
            history = context.get("critic_guidance_history", {}).get(self.name, [])
            if history:
                critic_feedback["history"] = history
        feedback = {
            "critic_feedback": critic_feedback,
            "human_feedback": context.get("human_feedback", None),
            "previous_attempt": context.get("previous_attempt", None),
            "retry_count": context.get("retry_count", 0),
            "planner_instruction": planner_guidance.get(self.name),
            "guidance_history": context.get("critic_guidance_history", {}).get(self.name, [])
        }
        
        return feedback
    
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
