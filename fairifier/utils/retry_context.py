"""Retry context isolation utilities (P0 §2 of architecture refactor).

When a Critic-driven retry happens, naively re-injecting the agent's previous
failed output and the Critic's verbose prose ``critique`` into the next prompt
causes "correction paralysis": the LLM is anchored to its own earlier mistake
and tends to repeat it (the echo-chamber effect).

The right approach — based on Anthropic's "Building Effective Agents" guidance
and the JetBrains 2025 finding that LLM-based summarization smooths away
failure signals — is **observation masking**: keep raw structured signals
(``issues``, ``suggestions``) and discard verbose prose (``critique``, the
failed output snapshot itself). No LLM is used to summarize.

This module provides ``clean_critic_feedback_for_prompt`` which produces the
lean view exposed to retry prompts. The full ``critic_feedback`` is still
stored in state for audit/logging — only the LLM-facing view is trimmed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# Fields preserved in the prompt-facing view of critic feedback.
# Everything else (notably ``critique`` prose) is dropped on retry.
_PROMPT_KEPT_FIELDS = (
    "decision",
    "score",
    "issues",
    "suggestions",
    "target_agent",
)


def clean_critic_feedback_for_prompt(
    critic_feedback: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return a lean copy of ``critic_feedback`` safe for retry prompts.

    Drops:
    - ``critique`` (verbose prose; anchoring effect)
    - ``timestamp`` (LLM does not need it; reduces noise)
    - any other LLM-generated commentary fields

    Keeps:
    - ``issues`` (structured: what was wrong)
    - ``suggestions`` (structured: what to do)
    - ``score`` (so the agent knows whether it's improving)
    - ``decision`` and ``target_agent`` (routing context)

    Returns ``None`` when input is ``None`` (no retry context yet).
    """
    if critic_feedback is None:
        return None
    if not isinstance(critic_feedback, dict):
        return critic_feedback

    return {
        key: critic_feedback[key]
        for key in _PROMPT_KEPT_FIELDS
        if key in critic_feedback
    }
