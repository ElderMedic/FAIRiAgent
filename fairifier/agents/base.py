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
    
    def get_context_feedback(self, state: FAIRifierState) -> Dict[str, Any]:
        """
        Extract feedback from context (critic feedback, human feedback, previous attempts, memories)
        This allows agents to adapt based on reflective feedback and retrieved memories.
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
            "guidance_history": context.get("critic_guidance_history", {}).get(self.name, []),
            # Include retrieved memories from mem0 (if available)
            "retrieved_memories": context.get("retrieved_memories", [])
        }
        
        return feedback
    
    def format_retrieved_memories_for_prompt(
        self,
        retrieved_memories: list,
        max_facts: int = 10,
        max_chars: int = 1500,
        dynamic_budget: bool = False,
        current_prompt_size: int = 0,
        max_total_prompt_tokens: int = 8000
    ) -> str:
        """
        Format mem0 memories for prompt injection.

        Features:
        - Dynamic budget adjustment based on prompt size
        - De-duplication of identical facts
        - Relevance-based sorting (if score available)
        - Token-aware compression

        Args:
            retrieved_memories: List of memory dicts from search
            max_facts: Maximum number of facts (default limit)
            max_chars: Maximum characters (default limit)
            dynamic_budget: Enable dynamic adjustment
            current_prompt_size: Estimated tokens in prompt
            max_total_prompt_tokens: Maximum allowed tokens

        Returns:
            Formatted string, or empty string if no memories
        """
        if not retrieved_memories:
            return ""

        # Dynamic adjustment: reduce budget if prompt is large
        if dynamic_budget and current_prompt_size > 0:
            remaining = max_total_prompt_tokens - current_prompt_size
            if remaining < 1000:  # Less than 1k tokens left
                max_chars = min(max_chars, 500)
                max_facts = min(max_facts, 3)
            elif remaining < 2000:  # Less than 2k tokens left
                max_chars = min(max_chars, 1000)
                max_facts = min(max_facts, 5)

        # De-duplicate facts (exact match)
        seen = set()
        unique_memories = []
        for m in retrieved_memories:
            text = m.get("memory", m) if isinstance(m, dict) else str(m)
            if isinstance(text, str) and text.strip():
                text_normalized = text.strip()
                if text_normalized not in seen:
                    seen.add(text_normalized)
                    unique_memories.append((text_normalized, m))

        # Sort by relevance score if available
        has_scores = (
            unique_memories
            and isinstance(retrieved_memories[0], dict)
            and "score" in retrieved_memories[0]
        )
        if has_scores:
            # Sort by score descending (most relevant first)
            unique_memories.sort(
                key=lambda x: (
                    x[1].get("score", 0.0)
                    if isinstance(x[1], dict)
                    else 0.0
                ),
                reverse=True
            )

        # Extract text only after sorting
        unique_texts = [text for text, _ in unique_memories]

        # Trim to budget
        facts = []
        total = 0
        for text in unique_texts[:max_facts]:
            if total + len(text) <= max_chars:
                facts.append(text)
                total += len(text)
            else:
                # Try to fit partial text if first fact
                if not facts and len(text) > 100:
                    facts.append(text[:max_chars] + "...")
                break

        if not facts:
            return ""

        prefix = (
            "Prior context from memory "
            "(use to avoid repeating; compress when possible):\n"
        )
        return prefix + "\n".join(f"- {f}" for f in facts)
    
    def get_memory_query_hint(
        self, state: FAIRifierState
    ) -> Optional[str]:
        """
        Return a custom query hint for memory retrieval.

        Override in subclasses for agent-specific memory queries.
        The hint is used to search for relevant memories.

        Args:
            state: Current workflow state

        Returns:
            Custom query string, or None for default query.
        """
        return None
    
    def log_execution(
        self, state: FAIRifierState, message: str, level: str = "info"
    ):
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

    def update_confidence(
        self, state: FAIRifierState, component: str, score: float
    ):
        """Update confidence score for a component."""
        if "confidence_scores" not in state:
            state["confidence_scores"] = {}
        state["confidence_scores"][component] = score

        # Check if human review is needed
        if score < config.min_confidence_threshold:
            state["needs_human_review"] = True
            msg = (
                f"Low confidence score ({score:.2f}) for {component}, "
                f"flagging for human review"
            )
            self.log_execution(state, msg)
