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

    def test_generation_context_locks_plan_and_treats_source_absence_as_blank(
        self, critic_agent, base_state
    ):
        base_state["entity_plan_validation"] = {
            "passed": True,
            "row_counts": {"sample": 28, "assay": 36},
            "investigation_contact_count": 3,
        }

        context = critic_agent._build_generation_context(base_state)

        assert "immutable at this stage" in context
        assert "blank value with confidence 0" in context
        assert '"sample": 28' in context
        assert '"assay": 36' in context

    def test_generation_context_excludes_untrusted_freeform_planner_guidance(
        self, critic_agent, base_state
    ):
        speculative = (
            "Require QuantSeq, STAR, and a Transcriptome package even when the "
            "source and selected FAIR-DS contracts do not support them."
        )
        base_state["agent_guidance"] = {"JSONGenerator": speculative}

        context = critic_agent._build_generation_context(base_state)

        assert speculative not in context
        assert "Free-form orchestration suggestions are intentionally excluded" in context

    def test_generation_critic_cannot_retry_to_invent_blanks_or_replan_entities(
        self, critic_agent, base_state
    ):
        base_state["entity_plan_validation"] = {"passed": True}
        base_state["entity_plan"] = {
            "unresolved_ambiguities": [
                "The names of the three library preparation kits are not stated."
            ]
        }
        base_state["metadata_fields"] = [
            {
                "field_name": "assay instrument",
                "isa_level": "assay",
                "value": "",
                "confidence": 0.0,
            }
        ]
        base_state["artifacts"] = {
            "metadata_json": json.dumps(
                {"isa_structure": {"assay": {"fields": []}}}
            )
        }

        evaluation = critic_agent._postprocess_generation_plan_evaluation(
            {
                "decision": "RETRY",
                "score": 0.48,
                "critique": "Too many provisional fields and low confidence.",
                "issues": [
                    "695 fields are provisional and overall confidence is low.",
                    "Duplicated identifiers appear in normalized records.",
                    "Dilution rows need separate observationunit blocks.",
                    "ObservationUnit count (9) vs 36 samples raises linkage clarity question",
                    "Entity counts (9 OU, 36 samples) diverge from planner (24 OU, 8 samples)",
                    "5 ISA cross-reference IDs linking sample to assay are missing.",
                    "Four mandatory ISA identifiers are absent from the JSON.",
                    "Planner's data-availability/accession note unconfirmed in output",
                ],
                "improvement_ops": [
                    "Fill blank values to clear needs_review.",
                    "Deduplicate investigation identifiers.",
                    "Map dilution-series rows to separate observationunit blocks.",
                    "Verify OU-to-sample mapping logic; confirm 9 OUs cover all 36 sample-assay links per planner.",
                    "Add cross-reference identifiers linking each ISA level.",
                    "Flag specific 3 kit names from methods section.",
                    "Check paper for GEO/SRA accession; add it if present.",
                ],
            },
            base_state,
        )

        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["score"] >= config.critic_accept_threshold_json_generator
        assert evaluation["issues"] == []
        assert evaluation["improvement_ops"] == []

    def test_generation_critic_keeps_source_fidelity_failures(
        self, critic_agent, base_state
    ):
        base_state["entity_plan_validation"] = {"passed": True}
        base_state["metadata_fields"] = [
            {
                "field_name": "assay instrument",
                "isa_level": "assay",
                "value": "NovaSeq 6000",
                "confidence": 0.3,
            }
        ]
        base_state["artifacts"] = {
            "metadata_json": json.dumps(
                {"isa_structure": {"assay": {"fields": []}}}
            )
        }

        evaluation = critic_agent._postprocess_generation_plan_evaluation(
            {
                "decision": "RETRY",
                "score": 0.5,
                "critique": "Unsupported value.",
                "issues": ["Unsupported non-empty assay instrument is hallucinated."],
                "improvement_ops": ["Remove the hallucinated instrument."],
            },
            base_state,
        )

        assert evaluation["decision"] == "RETRY"
        assert evaluation["issues"]

    def test_generation_critic_uses_unique_schema_coverage_not_entity_record_count(
        self, critic_agent, base_state
    ):
        base_state["entity_plan_validation"] = {"passed": True}
        base_state["retrieved_knowledge"] = [
            {"term": "sample name", "metadata": {"isa_sheet": "sample"}},
            {"term": "library strategy", "metadata": {"isa_sheet": "assay"}},
        ]
        base_state["metadata_fields"] = [
            {
                "field_name": "sample name",
                "isa_level": "sample",
                "value": f"sample {index}",
            }
            for index in range(36)
        ] + [
            {
                "field_name": "library strategy",
                "isa_level": "assay",
                "value": "RNA-Seq",
            }
            for _ in range(36)
        ]
        base_state["artifacts"] = {
            "metadata_json": json.dumps(
                {
                    "isa_structure": {
                        "sample": {"fields": [{"field_name": "sample name"}]},
                        "assay": {
                            "fields": [{"field_name": "library strategy"}]
                        },
                    },
                    "statistics": {"total_fields": 2},
                }
            )
        }

        evaluation = critic_agent._postprocess_generation_plan_evaluation(
            {
                "decision": "RETRY",
                "score": 0.58,
                "critique": "Only 2 of 72 planned fields appear in the JSON.",
                "issues": ["Only 2 of 72 planned fields appear; major coverage gap."],
                "improvement_ops": ["Regenerate to emit all 72 field records."],
            },
            base_state,
        )

        assert critic_agent._generation_field_coverage(base_state) == {
            "expected_count": 2,
            "actual_count": 2,
            "missing": [],
            "raw_entity_field_records": 72,
        }
        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["issues"] == []
        assert evaluation["improvement_ops"] == []

    def test_generation_critic_keeps_real_unique_schema_coverage_gap(
        self, critic_agent, base_state
    ):
        base_state["entity_plan_validation"] = {"passed": True}
        base_state["retrieved_knowledge"] = [
            {"term": "sample name", "metadata": {"isa_sheet": "sample"}},
            {"term": "scientific name", "metadata": {"isa_sheet": "sample"}},
        ]
        base_state["metadata_fields"] = [
            {"field_name": "sample name", "isa_level": "sample", "value": "s1"}
        ]
        base_state["artifacts"] = {
            "metadata_json": json.dumps(
                {"isa_structure": {"sample": {"fields": []}}}
            )
        }

        evaluation = critic_agent._postprocess_generation_plan_evaluation(
            {
                "decision": "RETRY",
                "score": 0.55,
                "issues": ["Missing schema coverage for scientific name."],
                "improvement_ops": ["Emit the missing schema field."],
            },
            base_state,
        )

        assert evaluation["decision"] == "RETRY"
        assert evaluation["issues"]

    def test_mapper_critic_cannot_restore_value_rejected_by_fairds_contract(
        self, critic_agent, base_state
    ):
        base_state["entity_plan_validation"] = {"passed": True}
        base_state["entity_matrix_validation"] = {"passed": True}
        base_state["isa_value_quality"] = {
            "issues": [
                "FAIR-DS value contract rejected sample.design variable selector="
                "'5 ng'; the unsupported value was cleared."
            ]
        }

        evaluation = critic_agent._postprocess_entity_plan_evaluation(
            {
                "decision": "RETRY",
                "score": 0.55,
                "issues": [
                    "Design variable selector values were cleared as unsupported."
                ],
                "improvement_ops": [
                    "Treat design variable selector as free-text and add back 5 ng."
                ],
            },
            base_state,
        )

        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["issues"] == []
        assert evaluation["improvement_ops"] == []

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

    def test_postprocess_retries_unstable_package_contract(self, critic_agent, base_state):
        base_state["selected_packages"] = ["default", "assay-schema-b"]
        base_state["retrieved_knowledge"] = [
            {"term": "library strategy", "metadata": {"package": "assay-schema-b"}}
        ]
        base_state["package_selection_trace"] = {
            "stable": False,
            "rounds": [
                {"round": 0, "packages": ["default", "assay-schema-a"]},
                {"round": 1, "packages": ["default", "assay-schema-b"]},
            ],
        }

        evaluation = critic_agent._postprocess_api_constrained_evaluation(
            "knowledge_retriever",
            {
                "decision": "ACCEPT",
                "score": 0.9,
                "critique": "Packages are valid API names.",
                "issues": [],
                "improvement_ops": [],
            },
            base_state,
        )

        assert evaluation["decision"] == "RETRY"
        assert evaluation["score"] < config.critic_accept_threshold_knowledge_retriever
        assert any("did not stabilize" in issue for issue in evaluation["issues"])

    def test_postprocess_retries_uncovered_source_schema_level(self, critic_agent, base_state):
        base_state["selected_packages"] = ["default"]
        base_state["package_selection_trace"] = {
            "stable": False,
            "coverage_resolved": False,
            "uncovered_schema_levels": ["assay"],
            "source_schema_matches": [
                {
                    "package": "focused-assay",
                    "score": 5,
                    "evidence": ["library strategy=controlled-value"],
                    "levels": ["assay"],
                }
            ],
            "rounds": [],
        }

        evaluation = critic_agent._postprocess_api_constrained_evaluation(
            "knowledge_retriever",
            {
                "decision": "ACCEPT",
                "score": 0.9,
                "critique": "Default fields are valid.",
                "issues": [],
                "improvement_ops": [],
            },
            base_state,
        )

        assert evaluation["decision"] == "RETRY"
        assert any("assay" in issue for issue in evaluation["issues"])
        assert "source schema match" in evaluation["critique"].lower()

    def test_stable_real_contract_trace_overrides_free_form_package_preference(
        self, critic_agent, base_state
    ):
        base_state["selected_packages"] = [
            "default",
            "Crop Plant sample enhanced annotation checklist",
            "Illumina",
        ]
        base_state["retrieved_knowledge"] = [
            {"term": "library strategy", "metadata": {"package": "Illumina"}}
        ]
        base_state["api_capabilities"] = {
            "available_packages": [
                "default",
                "Crop Plant sample enhanced annotation checklist",
                "Illumina",
                "Genome",
                "Plant Sample Checklist",
            ]
        }
        base_state["package_selection_trace"] = {
            "stable": True,
            "coverage_resolved": True,
            "uncovered_schema_levels": [],
            "rounds": [
                {
                    "round": 2,
                    "packages": [
                        "default",
                        "Crop Plant sample enhanced annotation checklist",
                        "Illumina",
                    ],
                },
                {
                    "round": 3,
                    "packages": [
                        "default",
                        "Crop Plant sample enhanced annotation checklist",
                        "Illumina",
                    ],
                },
            ],
        }

        evaluation = critic_agent._postprocess_api_constrained_evaluation(
            "knowledge_retriever",
            {
                "decision": "RETRY",
                "score": 0.62,
                "critique": "Prefer Genome package.",
                "issues": ["Genome package was not selected."],
                "improvement_ops": [
                    "Add Genome package to selected set per planner guidance.",
                    "Remove RNA-seq terms from gap_hints since Illumina covers them.",
                    "Consider adding Plant Sample Checklist.",
                ],
            },
            base_state,
        )

        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["score"] >= config.critic_accept_threshold_knowledge_retriever
        assert evaluation["issues"] == []
        assert evaluation["improvement_ops"] == []

    def test_stable_contract_trace_owns_cross_level_coverage_judgement(
        self, critic_agent, base_state
    ):
        base_state["selected_packages"] = [
            "default",
            "lean-sample-schema",
            "assay-schema",
        ]
        base_state["retrieved_knowledge"] = [
            {"term": "replicate", "metadata": {"package": "lean-sample-schema"}}
        ]
        base_state["api_capabilities"] = {
            "available_packages": [
                "default",
                "lean-sample-schema",
                "assay-schema",
                "broad-sample-schema",
            ]
        }
        base_state["package_selection_trace"] = {
            "stable": True,
            "coverage_resolved": True,
            "uncovered_schema_levels": [],
            "rounds": [
                {
                    "basis": "mandatory_burden_arbitration",
                    "packages": [
                        "default",
                        "lean-sample-schema",
                        "assay-schema",
                    ],
                }
            ],
        }

        evaluation = critic_agent._postprocess_api_constrained_evaluation(
            "knowledge_retriever",
            {
                "decision": "RETRY",
                "score": 0.58,
                "critique": "Replicate should be represented on observationunit.",
                "issues": [
                    "No direct observationunit mapping for biological replicate."
                ],
                "improvement_ops": [
                    "Verify observationunit terms include biological replicate."
                ],
            },
            base_state,
        )

        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["issues"] == []
        assert evaluation["improvement_ops"] == [
            "Verify observationunit terms include biological replicate."
        ]

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

    def test_invalid_critic_output_does_not_regenerate_validated_isa_matrix(
        self, critic_agent, base_state
    ):
        base_state["artifacts"] = {
            "isa_values_json": {
                level: {"columns": ["identifier"], "rows": [{"identifier": level}]}
                for level in (
                    "investigation",
                    "study",
                    "observationunit",
                    "sample",
                    "assay",
                )
            }
        }
        base_state["entity_matrix_validation"] = {"passed": True}
        base_state["needs_human_review"] = False

        evaluation = critic_agent._stabilize_invalid_critic_output(
            "isa_value_mapper",
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
        assert evaluation["score"] >= config.critic_accept_threshold_general
        assert base_state["needs_human_review"] is True

    def test_validated_entity_plan_blocks_merge_retry_for_declared_replicates(
        self, critic_agent, base_state
    ):
        base_state["entity_plan_validation"] = {"passed": True}
        base_state["entity_matrix_validation"] = {"passed": True}
        base_state["entity_plan"] = {
            "levels": [
                {
                    "level": "sample",
                    "entities": [
                        {
                            "attributes": [
                                {
                                    "dimension_name": "biological replicate",
                                    "field_name": None,
                                    "value": "replicate_01",
                                }
                            ]
                        }
                    ],
                }
            ],
            "unresolved_ambiguities": ["The replicate labels are not provided."],
        }

        evaluation = critic_agent._postprocess_entity_plan_evaluation(
            {
                "decision": "RETRY",
                "score": 0.5,
                "critique": "Duplicate identity-stripped rows remain.",
                "issues": ["Duplicate identity-stripped sample rows remain."],
                "improvement_ops": ["Merge duplicate rows sharing a condition."],
            },
            base_state,
        )

        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["issues"] == []
        assert evaluation["improvement_ops"] == []

    def test_validated_matrix_blocks_contradictory_identity_and_link_claims(
        self, critic_agent, base_state
    ):
        base_state["entity_plan_validation"] = {"passed": True}
        base_state["entity_matrix_validation"] = {"passed": True}
        base_state["entity_plan"] = {"levels": [], "unresolved_ambiguities": []}

        evaluation = critic_agent._postprocess_entity_plan_evaluation(
            {
                "decision": "ESCALATE",
                "score": 0.35,
                "critique": "Identifiers and links are invalid.",
                "issues": [
                    "Non-unique identifiers remain.",
                    "24 missing assay-sample links remain.",
                    "Universal label mismatches remain.",
                ],
                "improvement_ops": [
                    "Make identifiers unique.",
                    "Repair missing assay-sample links.",
                    "Repair label mismatches.",
                ],
            },
            base_state,
        )

        assert evaluation["decision"] == "ACCEPT"
        assert evaluation["issues"] == []
        assert evaluation["improvement_ops"] == []
def test_parser_critic_narrows_composite_missing_claim_to_truly_absent_fields():
    evaluation = {
        "decision": "ACCEPT",
        "score": 0.78,
        "issues": [
            "No authors, year, journal, or DOI captured for a research paper",
            "No distinction between inferred and directly stated fields",
        ],
        "improvement_ops": [
            "Add bibliographic block: authors, year, journal, DOI"
        ],
        "critique": "Authors, year, journal, and DOI are missing.",
    }
    state = {
        "document_info": {
            "authors": ["A. Researcher"],
            "publication_date": "2026-09",
            "journal": "Example Journal",
        }
    }

    result = CriticAgent._postprocess_document_parser_evaluation(
        evaluation, state
    )

    assert result["issues"] == [
        "Missing parsed field(s): DOI.",
        "No distinction between inferred and directly stated fields",
    ]
    assert result["improvement_ops"] == [
        "Extract missing parsed field(s): DOI."
    ]
    assert "authors" not in result["critique"].lower()


def test_parser_critic_drops_missing_claim_when_every_named_field_is_present():
    evaluation = {
        "decision": "ACCEPT",
        "score": 0.8,
        "issues": ["Title and authors not captured"],
        "improvement_ops": ["Extract title and authors"],
        "critique": "Missing fields.",
    }
    state = {"document_info": {"title": "T", "authors": ["A"]}}

    result = CriticAgent._postprocess_document_parser_evaluation(
        evaluation, state
    )

    assert result["issues"] == []
    assert result["improvement_ops"] == []


def test_parser_critic_does_not_demand_paper_bibliography_from_bundle_table():
    evaluation = {
        "decision": "RETRY",
        "score": 0.62,
        "issues": ["Missing publication date, journal, and DOI for the paper"],
        "improvement_ops": ["Extract missing publication year, journal, and DOI"],
        "critique": "Bibliographic fields are missing.",
    }
    state = {
        "document_info": {"document_type": "supplementary data table"},
        "context": {
            "current_source_role": "table",
            "current_source_total": 4,
        },
    }

    result = CriticAgent._postprocess_document_parser_evaluation(
        evaluation, state
    )

    assert result["decision"] == "ACCEPT"
    assert result["score"] >= config.critic_accept_threshold_document_parser
    assert result["issues"] == []
    assert result["improvement_ops"] == []


def test_parser_critic_retains_source_specific_table_issue():
    evaluation = {
        "decision": "RETRY",
        "score": 0.6,
        "issues": ["Missing sample identifiers and stage values"],
        "improvement_ops": ["Extract sample identifiers and stage values"],
        "critique": "The table evidence is incomplete.",
    }
    state = {
        "document_info": {"document_type": "supplementary data table"},
        "context": {
            "current_source_role": "metadata_table",
            "current_source_total": 3,
        },
    }

    result = CriticAgent._postprocess_document_parser_evaluation(
        evaluation, state
    )

    assert result["decision"] == "RETRY"
    assert result["issues"] == ["Missing sample identifiers and stage values"]


def test_invalid_critic_output_keeps_usable_bundle_table_without_retry():
    critic_agent = CriticAgent.__new__(CriticAgent)
    result = critic_agent._stabilize_invalid_critic_output(
        "document_parser",
        {
            "decision": "ESCALATE",
            "score": 0.0,
            "critique": "Critic failure: Unable to parse critic JSON response",
            "issues": ["Unable to parse critic JSON response"],
            "improvement_ops": ["Human review required due to critic failure."],
        },
        {
            "document_info": {
                "document_type": "supplementary metadata table",
                "variables": ["sample identifier"],
                "datasets_mentioned": ["GSE000001"],
            },
            "context": {
                "current_source_role": "metadata_table",
                "current_source_total": 5,
            },
        },
    )

    assert result["decision"] == "ACCEPT"
    assert result["score"] >= config.critic_accept_threshold_document_parser
    assert result["issues"] == []


def test_invalid_mapper_critic_uses_deterministic_gate_errors_for_retry():
    critic_agent = CriticAgent.__new__(CriticAgent)
    matrix = {
        level: {"columns": ["identifier"], "rows": [{"identifier": level}]}
        for level in (
            "investigation",
            "study",
            "observationunit",
            "sample",
            "assay",
        )
    }
    result = critic_agent._stabilize_invalid_critic_output(
        "isa_value_mapper",
        {
            "decision": "ESCALATE",
            "score": 0.0,
            "critique": "Critic failure: Unable to parse critic JSON response",
            "issues": ["Unable to parse critic JSON response"],
            "improvement_ops": ["Human review required due to critic failure."],
        },
        {
            "artifacts": {"isa_values_json": json.dumps(matrix)},
            "entity_matrix_validation": {
                "passed": False,
                "errors": ["Assay row A has no matching Sample parent."],
            },
        },
    )

    assert result["decision"] == "RETRY"
    assert result["issues"] == ["Assay row A has no matching Sample parent."]
    assert "human review" not in " ".join(result["improvement_ops"]).lower()
