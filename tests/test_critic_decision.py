"""Unit tests for Critic agent decision logic."""

import json
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

    def test_retrieval_context_is_compact(self, critic_agent, base_state):
        base_state["document_info"] = {
            "document_type": "research_paper",
            "title": "Earthworm response to nanomaterials",
            "research_domain": "ecotoxicology",
            "keywords": ["earthworm", "soil", "RNA-seq"],
            "variables": ["time", "dose", "gene expression"],
        }
        base_state["retrieved_knowledge"] = [
            {
                "term": f"term-{idx}",
                "metadata": {
                    "package": "soil" if idx % 2 == 0 else "Illumina",
                    "isa_sheet": "sample" if idx % 2 == 0 else "assay",
                    "required": idx % 3 == 0,
                },
            }
            for idx in range(40)
        ]
        base_state["api_capabilities"] = {
            "available_packages": [f"pkg-{i}" for i in range(30)],
            "candidate_packages_considered": ["default", "soil", "Illumina"],
        }

        context = critic_agent._build_retrieval_context(base_state)

        assert "complete_terms_list" not in context
        assert len(context) < 6000

    def test_generation_context_is_compact(self, critic_agent, base_state):
        base_state["document_info"] = {
            "document_type": "research_paper",
            "title": "Earthworm response to nanomaterials",
            "research_domain": "ecotoxicology",
        }
        base_state["metadata_fields"] = [
            {
                "field_name": f"field-{idx}",
                "isa_level": "sample" if idx % 2 == 0 else "assay",
                "confidence": 0.9 if idx % 3 == 0 else 0.7,
                "evidence": "evidence" if idx % 4 == 0 else "",
            }
            for idx in range(50)
        ]

        context = critic_agent._build_generation_context(base_state)

        assert '"field_summary"' in context
        assert len(context) < 5000

    def test_generation_context_includes_metadata_json_summary(self, critic_agent, base_state):
        base_state["metadata_fields"] = [
            {
                "field_name": "study title",
                "isa_level": "study",
                "confidence": 0.91,
                "evidence": "Title",
            }
        ]
        base_state["artifacts"] = {
            "metadata_json": json.dumps(
                {
                    "packages_used": ["default"],
                    "overall_confidence": 0.91,
                    "needs_review": False,
                    "isa_structure": {
                        "study": {"fields": [{"field_name": "study title"}]},
                    },
                    "statistics": {
                        "total_fields": 1,
                        "confirmed_fields": 1,
                        "provisional_fields": 0,
                        "inferred_extension_fields": 0,
                    },
                }
            )
        }

        context = critic_agent._build_generation_context(base_state)

        assert '"generator_contract"' in context
        assert '"metadata_json_summary"' in context
        assert '"parseable": true' in context.lower()

    def test_postprocess_accepts_api_constrained_gap_handling_for_retrieval(self, critic_agent, base_state):
        base_state["selected_packages"] = ["default", "Illumina"]
        base_state["retrieved_knowledge"] = [{"term": "study title", "metadata": {"package": "default"}}]
        base_state["metadata_gap_hints"] = [
            {"label": "transcriptomics", "source": "package_request", "status": "unmapped_to_fairds"}
        ]
        base_state["api_capabilities"] = {
            "unavailable_requested_packages": ["transcriptomics"],
        }

        evaluation = critic_agent._postprocess_api_constrained_evaluation(
            "knowledge_retriever",
            {
                "decision": "RETRY",
                "score": 0.55,
                "critique": "Use a transcriptomics FAIR-DS package instead of Illumina.",
                "issues": ["Missing transcriptomics package"],
                "improvement_ops": ["Add transcriptomics package"],
            },
            base_state,
        )

        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["score"] >= config.critic_accept_threshold_knowledge_retriever
        assert evaluation["issues"] == []
        assert "metadata gaps" in evaluation["critique"].lower()

    def test_postprocess_accepts_api_constrained_gap_handling_for_json_generator(self, critic_agent, base_state):
        base_state["selected_packages"] = ["default"]
        base_state["metadata_fields"] = [{"field_name": "study title", "confidence": 0.9, "evidence": "Title"}]
        base_state["metadata_gap_hints"] = [
            {"label": "transcriptomics", "source": "term_search", "status": "unmapped_to_fairds"}
        ]
        base_state["inferred_metadata_extensions"] = [
            {"field_name": "transcriptomics", "value": "RNA-seq", "confidence": 0.72}
        ]
        base_state["api_capabilities"] = {
            "unavailable_requested_packages": ["transcriptomics"],
        }

        evaluation = critic_agent._postprocess_api_constrained_evaluation(
            "json_generator",
            {
                "decision": "RETRY",
                "score": 0.6,
                "critique": "Missing transcriptomics package and corresponding JSON block.",
                "issues": ["Missing transcriptomics package"],
                "improvement_ops": ["Add transcriptomics package"],
            },
            base_state,
        )

        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["issues"] == []

    def test_postprocess_accepts_generated_metadata_when_only_jsonld_stretch_goals_are_missing(
        self,
        critic_agent,
        base_state,
    ):
        base_state["metadata_fields"] = [
            {"field_name": "study title", "confidence": 0.9, "evidence": "Title"}
        ]
        base_state["artifacts"] = {
            "metadata_json": json.dumps(
                {
                    "packages_used": ["default", "miappe"],
                    "isa_structure": {"study": {"fields": [{"field_name": "study title"}]}},
                    "statistics": {"total_fields": 1},
                }
            )
        }

        evaluation = critic_agent._postprocess_api_constrained_evaluation(
            "json_generator",
            {
                "decision": "ESCALATE",
                "score": 0.35,
                "critique": "No actual JSON-LD output was produced. Only field summaries exist.",
                "issues": ["Missing JSON-LD ResearchProject block"],
                "improvement_ops": ["Add @context and DCAT Dataset nodes"],
            },
            base_state,
        )

        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["score"] >= config.critic_accept_threshold_json_generator
        assert evaluation["issues"] == []
        assert "isa-structured metadata json" in evaluation["critique"].lower()

    def test_invalid_critic_output_is_softened_for_usable_retrieval_output(self, critic_agent, base_state):
        base_state["retrieved_knowledge"] = [
            {"term": "study title", "metadata": {"package": "default"}}
        ]
        base_state["selected_packages"] = ["default"]

        evaluation = critic_agent._stabilize_invalid_critic_output(
            "knowledge_retriever",
            {
                "decision": "ESCALATE",
                "score": 0.0,
                "critique": "Critic failure: Unable to parse critic JSON response",
                "issues": ["Unable to parse critic JSON response"],
                "improvement_ops": ["Human review required due to critic failure."],
            },
            base_state,
        )

        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["score"] >= config.critic_accept_threshold_knowledge_retriever
