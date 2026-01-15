"""Unit tests for confidence aggregation functionality."""

from fairifier.services.confidence_aggregator import aggregate_confidence, ConfidenceBreakdown
from fairifier.config import FAIRifierConfig
from fairifier.models import FAIRifierState


class TestConfidenceAggregation:
    """Test confidence aggregation from multiple components."""

    def test_aggregate_confidence_combines_components(self):
        """Test that aggregate_confidence combines critic, structural, and validation scores."""
        state: FAIRifierState = {
            "execution_history": [
                {"critic_evaluation": {"score": 0.8}},
                {"critic_evaluation": {"score": 0.6}},
            ],
            "metadata_fields": [
                {
                    "field_name": "title",
                    "value": "Sample project",
                    "evidence": "Title section",
                    "confidence": 0.95,
                },
                {
                    "field_name": "description",
                    "value": "Demo abstract",
                    "evidence": "Abstract",
                    "confidence": 0.9,
                },
            ],
            "validation_results": {"errors": [], "warnings": []},
            # Required FAIRifierState fields
            "document_path": "test.pdf",
            "document_content": "",
            "document_conversion": {},
            "output_dir": None,
            "document_info": {},
            "retrieved_knowledge": [],
            "confidence_scores": {},
            "needs_human_review": False,
            "artifacts": {},
            "human_interventions": {},
            "reasoning_chain": [],
            "execution_plan": {},
            "execution_summary": {},
            "status": "running",
            "processing_start": "2024-01-01T00:00:00",
            "processing_end": None,
            "errors": [],
        }
        cfg = FAIRifierConfig()
        breakdown = aggregate_confidence(state, cfg)
        
        assert isinstance(breakdown, ConfidenceBreakdown)
        assert round(breakdown.critic, 2) == 0.7
        assert 0.9 <= breakdown.validation <= 1.0
        assert breakdown.structural > 0
        assert 0.0 <= breakdown.overall <= 1.0
        assert breakdown.overall >= 0.0
        assert breakdown.overall <= 1.0

    def test_aggregate_confidence_empty_state(self):
        """Test confidence aggregation with empty state."""
        state: FAIRifierState = {
            "execution_history": [],
            "metadata_fields": [],
            "validation_results": {"errors": [], "warnings": []},
            # Required FAIRifierState fields
            "document_path": "test.pdf",
            "document_content": "",
            "document_conversion": {},
            "output_dir": None,
            "document_info": {},
            "retrieved_knowledge": [],
            "confidence_scores": {},
            "needs_human_review": False,
            "artifacts": {},
            "human_interventions": {},
            "reasoning_chain": [],
            "execution_plan": {},
            "execution_summary": {},
            "status": "running",
            "processing_start": "2024-01-01T00:00:00",
            "processing_end": None,
            "errors": [],
        }
        cfg = FAIRifierConfig()
        breakdown = aggregate_confidence(state, cfg)
        
        assert breakdown.critic == 0.0
        assert breakdown.structural == 0.0
        assert breakdown.validation == 1.0  # No errors or warnings
        assert breakdown.overall >= 0.0
        assert breakdown.overall <= 1.0

    def test_aggregate_confidence_with_validation_errors(self):
        """Test confidence aggregation when validation has errors."""
        state: FAIRifierState = {
            "execution_history": [
                {"critic_evaluation": {"score": 0.8}},
            ],
            "metadata_fields": [
                {
                    "field_name": "title",
                    "value": "Sample",
                    "evidence": "Title",
                    "confidence": 0.9,
                },
            ],
            "validation_results": {"errors": ["Error 1", "Error 2"], "warnings": ["Warning 1"]},
            # Required FAIRifierState fields
            "document_path": "test.pdf",
            "document_content": "",
            "document_conversion": {},
            "output_dir": None,
            "document_info": {},
            "retrieved_knowledge": [],
            "confidence_scores": {},
            "needs_human_review": False,
            "artifacts": {},
            "human_interventions": {},
            "reasoning_chain": [],
            "execution_plan": {},
            "execution_summary": {},
            "status": "running",
            "processing_start": "2024-01-01T00:00:00",
            "processing_end": None,
            "errors": [],
        }
        cfg = FAIRifierConfig()
        breakdown = aggregate_confidence(state, cfg)
        
        assert breakdown.critic == 0.8
        assert breakdown.validation < 1.0  # Should be reduced due to errors
        assert breakdown.overall >= 0.0
        assert breakdown.overall <= 1.0
        assert "validation_errors" in breakdown.details

