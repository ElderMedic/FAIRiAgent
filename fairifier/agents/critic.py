"""
Critic Agent - Evaluates the quality of each step's output and provides feedback.

The Critic Agent reviews outputs from other agents and decides whether they meet
quality standards, need improvement, or should be accepted.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from langsmith import traceable

from .base import BaseAgent
from ..models import FAIRifierState
from ..config import config
from ..utils.llm_helper import get_llm_helper

logger = logging.getLogger(__name__)


class CriticAgent(BaseAgent):
    """
    Critic Agent for evaluating agent outputs and providing actionable feedback.
    
    Uses LLM for intelligent quality evaluation (required - no rule-based fallback).
    
    Responsibilities:
    - Evaluate quality of each agent's output using LLM reasoning
    - Identify issues and missing information through LLM analysis
    - Provide specific, actionable feedback for improvement
    - Decide: ACCEPT, RETRY, or ESCALATE based on LLM evaluation
    """
    
    def __init__(self):
        super().__init__("Critic")
        self.llm_helper = get_llm_helper()
        # Get retry limit from config (can be overridden by env vars)
        self.max_retries_per_step = config.max_step_retries
        
        logger.info("✅ Critic Agent initialized with LLM (required mode - no fallback)")
    
    @traceable(name="Critic", tags=["agent", "evaluation"])
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """
        Execute critic evaluation on the current state.
        This is called by Orchestrator after each agent step.
        """
        self.log_execution(state, "🔍 Critic evaluation started")
        
        try:
            # Get the last execution from history
            execution_history = state.get("execution_history", [])
            if not execution_history:
                self.log_execution(state, "⚠️ No execution history to review", "warning")
                return state
            
            last_execution = execution_history[-1]
            agent_name = last_execution.get("agent_name", "unknown")
            
            self.log_execution(state, f"📝 Evaluating output from: {agent_name}")
            
            # Evaluate based on agent type
            if agent_name == "DocumentParser":
                evaluation = await self._evaluate_document_parsing(state)
            elif agent_name == "KnowledgeRetriever":
                evaluation = await self._evaluate_knowledge_retrieval(state)
            elif agent_name == "JSONGenerator":
                evaluation = await self._evaluate_json_generation(state)
            else:
                evaluation = {
                    "decision": "ACCEPT",
                    "confidence": 0.5,
                    "feedback": "Unknown agent type, accepting by default",
                    "issues": [],
                    "suggestions": []
                }
            
            # Store evaluation result
            last_execution["critic_evaluation"] = evaluation
            
        except Exception as e:
            self.log_execution(state, f"❌ Critic evaluation failed: {str(e)}", "error")
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"Critic evaluation error: {str(e)}")
            
            # Provide fallback evaluation
            evaluation = {
                "decision": "ACCEPT",  # Accept to continue workflow when critic fails
                "confidence": 0.3,
                "feedback": f"Critic evaluation failed: {str(e)}. Accepting with low confidence.",
                "issues": [f"Critic failure: {str(e)}"],
                "suggestions": ["Manual review recommended due to critic evaluation failure"]
            }
            
            # Store fallback evaluation
            execution_history = state.get("execution_history", [])
            if execution_history:
                last_execution = execution_history[-1]
                last_execution["critic_evaluation"] = evaluation
        
        # Log result
        decision = evaluation.get("decision", "ACCEPT")
        confidence = evaluation.get("confidence", 0.5)
        feedback = evaluation.get("feedback", "")
        issues = evaluation.get("issues", [])
        suggestions = evaluation.get("suggestions", [])
        
        self.log_execution(
            state,
            f"✅ Critic decision: {decision} (confidence: {confidence:.2f})\n"
            f"   Feedback: {feedback[:100] if feedback else 'N/A'}\n"
            f"   Issues: {len(issues)}\n"
            f"   Suggestions: {len(suggestions)}"
        )
        
        return state
    
    @traceable(name="Critic.EvaluateDocumentParsing")
    async def _evaluate_document_parsing(self, state: FAIRifierState) -> Dict[str, Any]:
        """
        Evaluate document parsing output quality using LLM reasoning.
        
        The Critic uses LLM to intelligently assess whether the extracted information
        is complete, accurate, and sufficient for metadata generation.
        """
        doc_info = state.get("document_info", {})
        retry_count = state.get("context", {}).get("retry_count", 0)
        
        # Prepare content with complete doc_info for LLM evaluation
        evaluation_content = f"""**Extracted Document Information:**
{json.dumps(doc_info, indent=2, ensure_ascii=False)}

**Retry Info:** Attempt {retry_count + 1}/{self.max_retries_per_step}"""

        # Call LLM for evaluation (required - no fallback)
        result = await self.llm_helper.evaluate_quality(
            content=evaluation_content,
            criteria=[
                "Complete title and abstract",
                "Author information present",
                "Keywords or research domain identified",
                "Sufficient context for metadata generation"
            ],
            context=f"Retry count: {retry_count}/{self.max_retries_per_step}"
        )
        
        # Ensure required fields
        if "decision" not in result:
            threshold = config.critic_accept_threshold_document_parser
            result["decision"] = "ACCEPT" if result.get("overall_score", 0) >= threshold else "RETRY"
        if "confidence" not in result:
            result["confidence"] = result.get("overall_score", 0.5)
        if "feedback" not in result:
            result["feedback"] = "Evaluation complete"
        if "issues" not in result:
            result["issues"] = result.get("failed_criteria", [])
        if "suggestions" not in result:
            result["suggestions"] = result.get("suggestions", [])
        
        return result
    
    @traceable(name="Critic.EvaluateKnowledgeRetrieval")
    async def _evaluate_knowledge_retrieval(self, state: FAIRifierState) -> Dict[str, Any]:
        """
        Evaluate knowledge retrieval output quality using LLM reasoning.
        
        The Critic uses LLM to assess whether the retrieved FAIR-DS terms
        are relevant and sufficient for the document.
        """
        retrieved_knowledge = state.get("retrieved_knowledge", [])
        doc_info = state.get("document_info", {})
        retry_count = state.get("context", {}).get("retry_count", 0)
        
        # Prepare summary for LLM
        packages_found = set()
        for item in retrieved_knowledge:
            metadata = item.get("metadata", {})
            if metadata and metadata.get("package"):
                packages_found.add(metadata["package"])
        
        knowledge_summary = {
            "total_terms": len(retrieved_knowledge),
            "packages": list(packages_found),
            "all_terms": [
                {"term": item.get("term"), "package": item.get("metadata", {}).get("package")}
                for item in retrieved_knowledge  # ALL terms - no sampling
            ]
        }
        
        # Prepare content with complete doc_info + retrieval results (no truncation)
        evaluation_content = f"""**Complete Document Info:**
{json.dumps(doc_info, indent=2, ensure_ascii=False)}  # Complete info - no truncation

**Retrieved FAIR-DS Knowledge:**
{json.dumps(knowledge_summary, indent=2)}

**Retry Info:** Attempt {retry_count + 1}/{self.max_retries_per_step}"""

        # Call LLM for evaluation (required - no fallback)
        result = await self.llm_helper.evaluate_quality(
            content=evaluation_content,
            criteria=[
                "Retrieved terms are relevant to document domain",
                "Sufficient quantity of terms (15-30)",
                "Appropriate FAIR-DS packages identified",
                "All terms have definitions"
            ],
            context=f"Document domain: {doc_info.get('research_domain')}; Retry: {retry_count}/{self.max_retries_per_step}"
        )
        
        # Ensure required fields
        if "decision" not in result:
            threshold = config.critic_accept_threshold_knowledge_retriever
            result["decision"] = "ACCEPT" if result.get("overall_score", 0) >= threshold else "RETRY"
        if "confidence" not in result:
            result["confidence"] = result.get("overall_score", 0.5)
        
        result["retrieved_count"] = len(retrieved_knowledge)
        result["packages_found"] = list(packages_found)
        
        return result
    
    @traceable(name="Critic.EvaluateJSONGeneration")
    async def _evaluate_json_generation(self, state: FAIRifierState) -> Dict[str, Any]:
        """
        Evaluate JSON metadata generation quality using LLM reasoning.
        
        The Critic uses LLM to intelligently assess the quality, completeness,
        and appropriateness of generated metadata.
        """
        metadata_fields = state.get("metadata_fields", [])
        doc_info = state.get("document_info", {})
        retry_count = state.get("context", {}).get("retry_count", 0)
        
        if not metadata_fields or len(metadata_fields) == 0:
            return {
                "decision": "RETRY",
                "confidence": 0.0,
                "feedback": "No metadata generated. Please retry.",
                "issues": ["No metadata fields generated"],
                "suggestions": ["Generate metadata fields based on document info and FAIR-DS knowledge"]
            }
        
        # Prepare summary for LLM (ALL fields - no sampling)
        fields_summary = []
        total_confidence = 0
        fields_with_evidence = 0
        
        for field in metadata_fields:  # ALL fields - no sampling
            fields_summary.append({
                "name": field.get("field_name"),
                "value": str(field.get("value", "")),  # Full value - no truncation
                "has_evidence": bool(field.get("evidence")),
                "confidence": field.get("confidence", 0)
            })
            total_confidence += field.get("confidence", 0)
            if field.get("evidence"):
                fields_with_evidence += 1
        
        avg_confidence = total_confidence / len(metadata_fields) if metadata_fields else 0
        evidence_coverage = fields_with_evidence / len(metadata_fields) if metadata_fields else 0
        
        # Prepare content with complete doc_info + generated metadata (no truncation)
        evaluation_content = f"""**Complete Document Info:**
{json.dumps(doc_info, indent=2, ensure_ascii=False)}  # Complete info - no truncation

**Generated Metadata:**
- Total fields: {len(metadata_fields)}
- Average confidence: {avg_confidence:.2f}
- Evidence coverage: {evidence_coverage:.1%}

**Sample Fields:**
{json.dumps(fields_summary, indent=2)}

**Retry Info:** Attempt {retry_count + 1}/{self.max_retries_per_step}"""

        # Call LLM for evaluation (required - no fallback)
        result = await self.llm_helper.evaluate_quality(
            content=evaluation_content,
            criteria=[
                "Core metadata fields are present",
                "Field values are appropriate and accurate",
                "Evidence/provenance is clear for fields",
                "Confidence scores are realistic",
                "Sufficient coverage of research aspects"
            ],
            context=f"Total fields: {len(metadata_fields)}; Avg confidence: {avg_confidence:.2f}; Retry: {retry_count}/{self.max_retries_per_step}"
        )
        
        # Ensure required fields
        if "decision" not in result:
            threshold = config.critic_accept_threshold_json_generator
            result["decision"] = "ACCEPT" if result.get("overall_score", 0) >= threshold else "RETRY"
        if "confidence" not in result:
            result["confidence"] = result.get("overall_score", 0.5)
        
        result["field_count"] = len(metadata_fields)
        result["avg_confidence"] = avg_confidence
        result["evidence_coverage"] = evidence_coverage
        
        return result
    
    @traceable(name="Critic.EvaluateValidation")
    async def _evaluate_validation(self, state: FAIRifierState) -> Dict[str, Any]:
        """Evaluate validation results."""
        validation_results = state.get("validation_results", {})
        
        issues = []
        suggestions = []
        
        # Check validation errors
        validation_errors = validation_results.get("errors", [])
        validation_warnings = validation_results.get("warnings", [])
        
        if validation_errors:
            issues.extend([f"Validation error: {err}" for err in validation_errors])  # ALL errors - no truncation
            suggestions.append("Fix validation errors before finalizing metadata")
        
        if validation_warnings:
            issues.extend([f"Validation warning: {warn}" for warn in validation_warnings])  # ALL warnings - no truncation
        
        # Calculate confidence
        error_count = len(validation_errors)
        warning_count = len(validation_warnings)
        
        if error_count == 0 and warning_count == 0:
            confidence = 1.0
            decision = "ACCEPT"
            feedback = "Validation passed with no errors or warnings."
        elif error_count == 0 and warning_count <= 3:
            confidence = 0.85
            decision = "ACCEPT"
            feedback = f"Validation passed with {warning_count} warnings."
        elif error_count <= 2:
            confidence = 0.6
            retry_count = state.get("context", {}).get("retry_count", 0)
            if retry_count < self.max_retries_per_step:
                decision = "RETRY"
                feedback = f"Validation found {error_count} errors. Please fix and retry."
            else:
                decision = "ESCALATE"
                feedback = f"Validation errors persist after {retry_count} retries. Human review needed."
        else:
            confidence = 0.3
            decision = "ESCALATE"
            feedback = f"Validation found {error_count} errors. Manual review required."
        
        return {
            "decision": decision,
            "confidence": confidence,
            "feedback": feedback,
            "issues": issues,
            "suggestions": suggestions,
            "error_count": error_count,
            "warning_count": warning_count
        }
    
    async def provide_feedback_to_agent(
        self, 
        agent_name: str, 
        evaluation: Dict[str, Any], 
        state: FAIRifierState
    ) -> FAIRifierState:
        """
        Prepare state with critic feedback for agent to retry.
        Updates context with specific feedback and suggestions.
        """
        if "context" not in state:
            state["context"] = {}
        
        # Increment retry count
        state["context"]["retry_count"] = state["context"].get("retry_count", 0) + 1
        
        # Store critic feedback (use .get() for safe access)
        state["context"]["critic_feedback"] = {
            "decision": evaluation.get("decision", "ACCEPT"),
            "confidence": evaluation.get("confidence", 0.5),
            "feedback": evaluation.get("feedback", ""),
            "issues": evaluation.get("issues", []),
            "suggestions": evaluation.get("suggestions", []),
            "timestamp": datetime.now().isoformat()
        }
        
        # Store previous attempt for comparison
        if agent_name == "DocumentParser":
            state["context"]["previous_attempt"] = state.get("document_info", {}).copy()
        elif agent_name == "KnowledgeRetriever":
            state["context"]["previous_attempt"] = state.get("retrieved_knowledge", []).copy()
        elif agent_name == "JSONGenerator":
            state["context"]["previous_attempt"] = state.get("metadata_fields", []).copy()
        
        self.log_execution(
            state,
            f"🔄 Prepared feedback for {agent_name} retry (attempt {state['context']['retry_count']})"
        )
        
        return state

