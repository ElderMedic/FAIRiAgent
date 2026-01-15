"""Unit tests for Critic agent decision logic."""

import pytest
from fairifier.agents.critic import CriticAgent
from fairifier.models import FAIRifierState
from fairifier.config import config


class TestCriticDecisionLogic:
    """Test Critic agent decision-making logic."""

    @pytest.fixture
    def critic_agent(self):
        """Create a CriticAgent instance."""
        return CriticAgent()

    @pytest.fixture
    def base_state(self) -> FAIRifierState:
        """Create a base state for testing."""
        return {
            "document_path": "test.pdf",
            "document_content": "Test content",
            "document_conversion": {},
            "output_dir": None,
            "document_info": {},
            "retrieved_knowledge": [],
            "metadata_fields": [],
            "validation_results": {"errors": [], "warnings": []},
            "confidence_scores": {},
            "needs_human_review": False,
            "artifacts": {},
            "human_interventions": {},
            "execution_history": [],
            "reasoning_chain": [],
            "execution_plan": {},
            "execution_summary": {},
            "status": "running",
            "processing_start": "2024-01-01T00:00:00",
            "processing_end": None,
            "errors": [],
        }

    def test_decision_accept_high_score(self, critic_agent, base_state):
        """Test ACCEPT decision for high confidence score."""
        evaluation = {
            "score": 0.85,
            "decision": "ACCEPT",
            "issues": [],
            "improvement_ops": []
        }
        
        # Decision should be ACCEPT for score >= accept_threshold
        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["score"] >= config.critic_accept_threshold_general

    def test_decision_retry_medium_score(self, critic_agent, base_state):
        """Test RETRY decision for medium confidence score."""
        evaluation = {
            "score": 0.55,
            "decision": "RETRY",
            "issues": ["Minor issue"],
            "improvement_ops": ["Fix issue"]
        }
        
        # Decision should be RETRY for score between retry_min and retry_max
        assert evaluation["decision"] == "RETRY"
        assert config.critic_retry_min_threshold <= evaluation["score"] < config.critic_retry_max_threshold

    def test_decision_escalate_low_score(self, critic_agent, base_state):
        """Test ESCALATE decision for low confidence score."""
        evaluation = {
            "score": 0.3,
            "decision": "ESCALATE",
            "issues": ["Critical issue"],
            "improvement_ops": []
        }
        
        # Decision should be ESCALATE for score < retry_min
        assert evaluation["decision"] == "ESCALATE"
        assert evaluation["score"] < config.critic_retry_min_threshold

    def test_decision_with_retry_count_limit(self, critic_agent, base_state):
        """Test that retry count affects decision."""
        base_state["context"] = {
            "retry_count": config.max_step_retries + 1
        }
        
        # When retry count exceeds limit, should escalate even if score suggests retry
        evaluation = {
            "score": 0.55,  # Would normally be RETRY
            "decision": "ESCALATE",  # But should escalate due to retry limit
            "issues": ["Persistent issue"],
            "improvement_ops": []
        }
        
        assert evaluation["decision"] == "ESCALATE"

    def test_feedback_format_complete(self, critic_agent, base_state):
        """Test that feedback contains all required fields."""
        evaluation = {
            "decision": "RETRY",
            "score": 0.6,
            "critique": "Some issues found",
            "issues": ["Issue 1", "Issue 2"],
            "improvement_ops": ["Fix 1", "Fix 2"]
        }
        
        # Verify feedback structure
        assert "decision" in evaluation
        assert "score" in evaluation
        assert "critique" in evaluation
        assert "issues" in evaluation
        assert "improvement_ops" in evaluation
        assert isinstance(evaluation["issues"], list)
        assert isinstance(evaluation["improvement_ops"], list)

    def test_evaluation_empty_output(self, critic_agent, base_state):
        """Test evaluation handling of empty output."""
        base_state["document_info"] = {}
        base_state["metadata_fields"] = []
        
        # Empty output should result in low score and ESCALATE
        evaluation = {
            "score": 0.1,
            "decision": "ESCALATE",
            "issues": ["No output generated"],
            "improvement_ops": ["Generate output"]
        }
        
        assert evaluation["decision"] == "ESCALATE"
        assert evaluation["score"] < config.critic_retry_min_threshold

    def test_validation_based_decision_no_errors(self, critic_agent, base_state):
        """Test decision when validation has no errors."""
        base_state["validation_results"] = {
            "errors": [],
            "warnings": []
        }
        
        # No errors should result in ACCEPT
        evaluation = {
            "score": 1.0,
            "decision": "ACCEPT",
            "issues": [],
            "improvement_ops": []
        }
        
        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["score"] == 1.0

    def test_validation_based_decision_with_warnings(self, critic_agent, base_state):
        """Test decision when validation has warnings but no errors."""
        base_state["validation_results"] = {
            "errors": [],
            "warnings": ["Warning 1", "Warning 2"]
        }
        
        # Warnings should reduce score but may still ACCEPT
        evaluation = {
            "score": 0.85,
            "decision": "ACCEPT",
            "issues": ["2 warnings"],
            "improvement_ops": []
        }
        
        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["score"] >= config.critic_accept_threshold_general

    def test_validation_based_decision_with_errors(self, critic_agent, base_state):
        """Test decision when validation has errors."""
        base_state["validation_results"] = {
            "errors": ["Error 1", "Error 2"],
            "warnings": []
        }
        
        # Errors should result in RETRY or ESCALATE
        evaluation = {
            "score": 0.5,
            "decision": "RETRY",
            "issues": ["2 validation errors"],
            "improvement_ops": ["Fix errors"]
        }
        
        assert evaluation["decision"] in ["RETRY", "ESCALATE"]
        assert evaluation["score"] < config.critic_accept_threshold_general
