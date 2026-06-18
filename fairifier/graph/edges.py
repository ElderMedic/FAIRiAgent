"""Routing edges for the FAIRifier LangGraph workflow."""

import logging
from typing import Any, Dict
from fairifier.graph.state import FAIRifierState

logger = logging.getLogger(__name__)


def route_after_critic(state: FAIRifierState) -> str:
    """Determine the next step based on the critic's decision in the state.

    Args:
        state: The current FAIRifierState.

    Returns:
        The name of the next node/step to execute:
        - "finalize" if the critic decision is "ACCEPT"
        - "orchestrate" if the critic decision is "REJECT" or "RETRY"
        - "finalize" as a fallback.
    """
    execution_history = state.get("execution_history")
    if not execution_history:
        logger.info("No execution history found, defaulting route to 'finalize'.")
        return "finalize"

    # Get the last execution from history
    last_execution = execution_history[-1]
    critic_eval = last_execution.get("critic_evaluation") or {}
    decision = critic_eval.get("decision", "ACCEPT")

    if isinstance(decision, str):
        decision_upper = decision.upper()
        if decision_upper == "ACCEPT":
            return "finalize"
        elif decision_upper in ("REJECT", "RETRY"):
            return "orchestrate"

    return "finalize"


def route_after_parser(state: FAIRifierState) -> str:
    """Determine the next step after parsing the document.

    Args:
        state: The current FAIRifierState.

    Returns:
        The next node to execute.
    """
    errors = state.get("errors", [])
    if errors:
        return "finalize"
    return "orchestrate"
