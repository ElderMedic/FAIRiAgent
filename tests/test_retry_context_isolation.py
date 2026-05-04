"""Tests for retry context isolation (P0 §2 of architecture refactor).

These verify that on retry, the LLM prompt does NOT see:
- The previous attempt's failed output (anchoring effect)
- The Critic's verbose prose ``critique`` field (anchoring/sycophancy)

It SHOULD see:
- Structured ``issues`` (what was wrong)
- Structured ``suggestions`` (what to do, distilled improvement ops)
- ``score`` (so the agent knows whether it's improving)
"""

import pytest

from fairifier.utils.retry_context import clean_critic_feedback_for_prompt


class TestCleanCriticFeedbackForPrompt:
    def _full_feedback(self):
        return {
            "decision": "RETRY",
            "score": 0.6,
            "critique": (
                "The output is partially correct but the model has hallucinated "
                "the assay type and missed several mandatory sample fields. "
                "Specifically, sample.organism is empty even though the document "
                "clearly mentions Eisenia fetida..."
                * 5
            ),
            "issues": [
                "Missing sample.organism",
                "Wrong assay_type inference",
            ],
            "suggestions": [
                "Re-extract sample.organism from evidence_packets",
                "Use methodology field to infer assay_type correctly",
            ],
            "timestamp": "2026-05-04T10:00:00",
            "target_agent": "JSONGenerator",
        }

    def test_keeps_issues(self):
        cleaned = clean_critic_feedback_for_prompt(self._full_feedback())
        assert cleaned["issues"] == [
            "Missing sample.organism",
            "Wrong assay_type inference",
        ]

    def test_keeps_suggestions(self):
        cleaned = clean_critic_feedback_for_prompt(self._full_feedback())
        assert len(cleaned["suggestions"]) == 2

    def test_keeps_score(self):
        cleaned = clean_critic_feedback_for_prompt(self._full_feedback())
        assert cleaned["score"] == 0.6

    def test_drops_critique_prose(self):
        """The verbose prose critique anchors the LLM to its own past mistakes."""
        cleaned = clean_critic_feedback_for_prompt(self._full_feedback())
        assert "critique" not in cleaned

    def test_handles_none_input(self):
        assert clean_critic_feedback_for_prompt(None) is None

    def test_handles_missing_optional_fields(self):
        cleaned = clean_critic_feedback_for_prompt(
            {"issues": ["x"], "suggestions": ["y"]}
        )
        assert cleaned["issues"] == ["x"]
        assert cleaned["suggestions"] == ["y"]

    def test_substantial_size_reduction(self):
        import json

        full = self._full_feedback()
        full_size = len(json.dumps(full))
        cleaned_size = len(json.dumps(clean_critic_feedback_for_prompt(full)))
        # Cleaned form must be substantially smaller (verbose prose dropped).
        assert cleaned_size < full_size / 2


class TestGetContextFeedbackStripsRetryNoise:
    """Verify base agent feedback view drops echo-chamber-inducing fields."""

    def _make_agent(self):
        from fairifier.agents.base import BaseAgent

        class _DummyAgent(BaseAgent):
            async def execute(self, state):
                return state

        return _DummyAgent("DocumentParser")

    def test_returns_no_critique_prose(self):
        agent = self._make_agent()
        state = {
            "context": {
                "critic_feedback": {
                    "target_agent": "DocumentParser",
                    "decision": "RETRY",
                    "score": 0.5,
                    "critique": "verbose prose explaining what went wrong",
                    "issues": ["a", "b"],
                    "suggestions": ["fix a", "fix b"],
                },
                "retry_count": 1,
            },
            "agent_guidance": {},
        }
        feedback = agent.get_context_feedback(state)
        cf = feedback["critic_feedback"]
        assert cf is not None
        assert "critique" not in cf, (
            "critique prose must be stripped to prevent echo-chamber anchoring"
        )

    def test_returns_no_previous_attempt(self):
        agent = self._make_agent()
        state = {
            "context": {
                "critic_feedback": {
                    "target_agent": "DocumentParser",
                    "decision": "RETRY",
                    "score": 0.5,
                    "issues": ["x"],
                    "suggestions": ["y"],
                },
                "previous_attempt": {"title": "wrong title", "abstract": "wrong"},
                "retry_count": 1,
            },
            "agent_guidance": {},
        }
        feedback = agent.get_context_feedback(state)
        # previous_attempt (the failed output) must not be exposed to retry prompts
        assert feedback["previous_attempt"] is None, (
            "previous_attempt must be stripped — exposing the failed output "
            "anchors the LLM to its own mistake"
        )

    def test_keeps_structured_issues_and_suggestions(self):
        agent = self._make_agent()
        state = {
            "context": {
                "critic_feedback": {
                    "target_agent": "DocumentParser",
                    "decision": "RETRY",
                    "score": 0.5,
                    "critique": "blah",
                    "issues": ["x"],
                    "suggestions": ["y"],
                },
                "retry_count": 1,
            },
            "agent_guidance": {},
        }
        feedback = agent.get_context_feedback(state)
        cf = feedback["critic_feedback"]
        assert cf["issues"] == ["x"]
        assert cf["suggestions"] == ["y"]

    def test_keeps_score_for_retry_awareness(self):
        agent = self._make_agent()
        state = {
            "context": {
                "critic_feedback": {
                    "target_agent": "DocumentParser",
                    "score": 0.5,
                    "issues": ["x"],
                    "suggestions": ["y"],
                },
                "retry_count": 1,
            },
            "agent_guidance": {},
        }
        feedback = agent.get_context_feedback(state)
        cf = feedback["critic_feedback"]
        assert cf.get("score") == 0.5
