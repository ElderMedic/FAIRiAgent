"""
Critic Agent - Evaluates the quality of each step's output and provides feedback.

The Critic Agent reviews outputs from other agents and decides whether they meet
quality standards, need improvement, or should be accepted.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import yaml
from langsmith import traceable

from .base import BaseAgent
from ..models import FAIRifierState
from ..config import config
from ..utils.json_parse import safe_json_parse
from ..utils.llm_helper import get_llm_helper
from ..utils.structured_output import invoke_structured_output
from ..utils.retry_progress import build_retry_contract
from ..services.fairds_api_parser import FAIRDSAPIParser
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class CriticEvaluation(BaseModel):
    """Schema for the Critic LLM evaluation output."""
    score: float = Field(description="Confidence score between 0.0 and 1.0")
    critique: str = Field(
        default="",
        description="A short narrative explanation of the decision (< 200 chars)",
    )
    issues: List[str] = Field(default_factory=list, description="List of identified issues (< 100 chars each)")
    suggestions: List[str] = Field(default_factory=list, description="Actionable steps to fix issues (< 150 chars each)")


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
        self.max_retries_per_step = config.max_step_retries
        self.rubric = self._load_rubric(config.critic_rubric_path)
        self.node_key_map = {
            "DocumentParser": "document_parser",
            "BioMetadataAgent": "bio_metadata_agent",
            "KnowledgeRetriever": "knowledge_retriever",
            "JSONGenerator": "json_generator",
            "ISAValueMapper": "isa_value_mapper",
        }
        logger.info("✅ Critic Agent initialized with LLM-as-Judge rubric")
    
    @traceable(name="Critic", tags=["agent", "evaluation"])
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """
        Execute critic evaluation on the current state.
        This is called by the workflow after each agent step.
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
            
            evaluation = await self._evaluate_agent_output(agent_name, state)
            
            # Store evaluation result
            last_execution["critic_evaluation"] = evaluation
            
        except Exception as e:
            self.log_execution(state, f"❌ Critic evaluation failed: {str(e)}", "error")
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"Critic evaluation error: {str(e)}")
            
            # Provide fallback evaluation (escalate to human review)
            evaluation = self._fallback_evaluation(str(e))
            
            # Store fallback evaluation
            execution_history = state.get("execution_history", [])
            if execution_history:
                last_execution = execution_history[-1]
                last_execution["critic_evaluation"] = evaluation
        
        # Log result
        decision = evaluation.get("decision", "ESCALATE")
        score = evaluation.get("score", 0.0)
        critique = evaluation.get("critique", "")
        issues = evaluation.get("issues", [])
        improvement_ops = evaluation.get("improvement_ops", [])
        
        self.log_execution(
            state,
            f"✅ Critic decision: {decision} (score: {score:.2f})\n"
            f"   Critique: {critique[:160] if critique else 'N/A'}\n"
            f"   Issues: {len(issues)} | Improvements: {len(improvement_ops)}"
        )
        
        return state
    
    async def _evaluate_agent_output(self, agent_name: str, state: FAIRifierState) -> Dict[str, Any]:
        """Route agent evaluation using rubric-driven judging."""
        node_key = self.node_key_map.get(agent_name)
        if not node_key:
            return self._fallback_evaluation(f"Unknown agent {agent_name}")
        
        if node_key == "document_parser":
            context = self._build_parsing_context(state)
        elif node_key == "knowledge_retriever":
            context = self._build_retrieval_context(state)
        elif node_key == "bio_metadata_agent":
            context = self._build_bio_metadata_context(state)
        elif node_key == "json_generator":
            context = self._build_generation_context(state)
        elif node_key == "isa_value_mapper":
            context = self._build_isa_mapper_context(state)
        else:
            context = "No context available."
        
        evaluation = await self._judge_with_rubric(node_key, context)
        if node_key == "document_parser":
            evaluation = self._postprocess_document_parser_evaluation(
                evaluation, state
            )
        if not config.disable_api_grounding:
            evaluation = self._postprocess_api_constrained_evaluation(node_key, evaluation, state)
        if node_key == "json_generator":
            evaluation = self._postprocess_generation_plan_evaluation(
                evaluation, state
            )
        if node_key == "isa_value_mapper":
            evaluation = self._postprocess_entity_plan_evaluation(evaluation, state)
        return self._stabilize_invalid_critic_output(node_key, evaluation, state)

    @staticmethod
    def _postprocess_document_parser_evaluation(
        evaluation: Dict[str, Any], state: FAIRifierState
    ) -> Dict[str, Any]:
        """Remove missing-field claims contradicted by parsed state.

        This guard does not decide whether a populated value is scientifically
        correct. It only prevents the judge from claiming that a visibly
        non-empty field was not captured. Composite claims are narrowed to the
        fields that really are absent.
        """
        document_info = state.get("document_info") or {}
        fields = [
            (
                "authors",
                ("author", "authors", "contributor", "contributors"),
                bool(document_info.get("authors")),
            ),
            (
                "publication date/year",
                ("publication date", "publication year", "year"),
                bool(
                    document_info.get("publication_date")
                    or document_info.get("publication_year")
                    or document_info.get("year")
                ),
            ),
            ("journal", ("journal",), bool(document_info.get("journal"))),
            ("DOI", ("doi",), bool(document_info.get("doi"))),
            ("title", ("title",), bool(document_info.get("title"))),
            ("abstract", ("abstract",), bool(document_info.get("abstract"))),
            ("keywords", ("keyword", "keywords"), bool(document_info.get("keywords"))),
            ("document type", ("document type",), bool(document_info.get("document_type"))),
            ("methodology", ("methodology", "methods"), bool(document_info.get("methodology"))),
            ("PMID", ("pmid",), bool(document_info.get("pmid"))),
        ]
        absence_markers = (
            "missing",
            "not captured",
            "not extracted",
            "not provided",
            "absent",
            "omitted",
            "empty",
            "no ",
            "add ",
            "extract ",
            "populate ",
            "include ",
        )
        source_context = state.get("context") or {}
        source_role = str(source_context.get("current_source_role") or "unknown")
        source_total = int(source_context.get("current_source_total") or 1)
        scoped_bundle_source = source_total > 1 and source_role != "main_manuscript"
        bibliography_words = {
            "a",
            "add",
            "abstract",
            "and",
            "author",
            "authors",
            "bibliographic",
            "block",
            "captured",
            "date",
            "doi",
            "extract",
            "field",
            "fields",
            "for",
            "full",
            "include",
            "journal",
            "missing",
            "no",
            "not",
            "omitted",
            "paper",
            "parsed",
            "pmid",
            "publication",
            "research",
            "the",
            "title",
            "year",
        }

        def is_out_of_scope_bibliography_claim(item: Any) -> bool:
            if not scoped_bundle_source:
                return False
            lowered = str(item or "").strip().lower()
            if not any(marker in lowered for marker in absence_markers):
                return False
            tokens = set(re.findall(r"[a-z]+", lowered))
            return bool(tokens) and tokens.issubset(bibliography_words)

        def narrow(item: Any, *, improvement: bool) -> str | None:
            text = str(item or "").strip()
            lowered = text.lower()
            if not text or not any(marker in lowered for marker in absence_markers):
                return text or None
            mentioned = [
                (label, present)
                for label, aliases, present in fields
                if any(alias in lowered for alias in aliases)
            ]
            if not mentioned or not any(present for _, present in mentioned):
                return text
            absent = [label for label, present in mentioned if not present]
            if not absent:
                return None
            prefix = (
                "Extract missing parsed field(s)"
                if improvement
                else "Missing parsed field(s)"
            )
            return f"{prefix}: {', '.join(absent)}."

        def clean(items: Any, *, improvement: bool) -> List[str]:
            cleaned: List[str] = []
            for item in items or []:
                if is_out_of_scope_bibliography_claim(item):
                    continue
                candidate = narrow(item, improvement=improvement)
                if candidate and candidate not in cleaned:
                    cleaned.append(candidate)
            return cleaned

        adjusted = dict(evaluation)
        adjusted["issues"] = clean(
            evaluation.get("issues"), improvement=False
        )
        adjusted["improvement_ops"] = clean(
            evaluation.get("improvement_ops"), improvement=True
        )
        if adjusted["issues"] != list(evaluation.get("issues") or []):
            adjusted["critique"] = (
                "Deterministic consistency check removed missing-field claims "
                "contradicted by the current parsed output. Remaining issues: "
                + ("; ".join(adjusted["issues"]) or "none")
            )
        if (
            scoped_bundle_source
            and evaluation.get("issues")
            and not adjusted["issues"]
        ):
            adjusted["decision"] = "ACCEPT"
            adjusted["score"] = max(
                float(adjusted.get("score") or 0.0),
                float(config.critic_accept_threshold_document_parser),
            )
            adjusted["critique"] = (
                "Accepted within per-source scope: bundle tables and supplements "
                "are not responsible for paper-level bibliographic fields."
            )
        return adjusted

    @staticmethod
    def _postprocess_generation_plan_evaluation(
        evaluation: Dict[str, Any], state: FAIRifierState
    ) -> Dict[str, Any]:
        """Keep value-generation feedback inside its architectural boundary.

        JSONGenerator emits normalized field/value records.  Repeated field
        names and identifiers are therefore expected across entity rows, and a
        source-faithful empty value has confidence zero by design.  Cardinality
        is owned by the already validated entity plan and is checked again
        after matrix projection.  The LLM critic may still reject invalid JSON,
        missing schema coverage, unsupported non-empty values, contradictory
        values, or package/field mismatches.
        """
        if (state.get("entity_plan_validation") or {}).get("passed") is not True:
            return evaluation

        metadata_fields = state.get("metadata_fields") or []
        metadata_json = (state.get("artifacts") or {}).get("metadata_json")
        if not metadata_fields or not metadata_json:
            return evaluation
        try:
            payload = json.loads(metadata_json)
        except Exception:
            return evaluation
        if not isinstance(payload, dict) or not isinstance(
            payload.get("isa_structure"), dict
        ):
            return evaluation

        field_coverage = CriticAgent._generation_field_coverage(state)
        coverage_complete = bool(field_coverage["expected_count"]) and not field_coverage[
            "missing"
        ]

        ambiguity_texts = [
            str(item).lower()
            for item in (
                (state.get("entity_plan") or {}).get(
                    "unresolved_ambiguities", []
                )
                or []
            )
            if item
        ]

        def matches_declared_ambiguity(value: Any) -> bool:
            def ambiguity_words(text: Any) -> set[str]:
                normalized: set[str] = set()
                for word in re.findall(r"[a-z0-9]+", str(text or "").lower()):
                    singular = word[:-1] if word.endswith("s") else word
                    if (
                        len(singular) < 3
                        or singular
                        in {
                            "with",
                            "from",
                            "that",
                            "this",
                            "should",
                            "specific",
                            "source",
                        }
                    ):
                        continue
                    normalized.add(singular)
                return normalized

            words = ambiguity_words(value)
            if not words:
                return False
            return any(
                len(words & ambiguity_words(ambiguity)) >= 2
                for ambiguity in ambiguity_texts
            )

        def non_actionable(value: Any) -> bool:
            lowered = str(value or "").lower()
            if not lowered:
                return False
            # Internal ISA identifiers and parent links are synthetic plan
            # outputs, never source values for JSONGenerator to invent.  Their
            # presence and referential integrity are enforced after matrix
            # projection.  This architectural boundary takes precedence over
            # generic phrases such as "missing mandatory field".
            synthetic_linkage_request = (
                any(term in lowered for term in ("identifier", " id", "ids"))
                and any(
                    term in lowered
                    for term in (
                        "isa",
                        "investigation",
                        "study",
                        "observationunit",
                        "observation unit",
                        "sample",
                        "assay",
                        "parent",
                        "cross-reference",
                        "cross reference",
                        "linkage",
                    )
                )
            )
            if synthetic_linkage_request:
                return True
            substantive_markers = (
                "hallucinat",
                "unsupported non-empty",
                "contradict",
                "inconsistent",
                "invalid json",
                "unparseable",
                "missing field",
                "missing schema",
                "package mismatch",
                "wrong package",
                "wrong field",
                "not in fair-ds",
            )
            if any(marker in lowered for marker in substantive_markers):
                return False

            missing_source_markers = (
                "provisional",
                "overall_confidence",
                "overall confidence",
                "needs_review",
                "needs review",
                "0.0-confidence",
                "zero-confidence",
                "low confidence",
                "unconfirmed in output",
                "blank value",
                "empty value",
                "unfilled",
                "not downstream-ready",
                "not downstream ready",
                "check paper for",
                "check source for",
                "if present",
            )
            normalized_record_markers = (
                "duplicate identifier",
                "duplicated identifier",
                "deduplicate investigation",
                "one authoritative id",
            )
            structure_change_markers = (
                "merge duplicate",
                "collapse",
                "separate observationunit",
                "separate observation unit",
                "observationunit blocks",
                "observation unit blocks",
                "map dilution-series rows",
                "map dilution series rows",
                "observationunit count",
                "observation unit count",
                "entity count",
                "row count",
                "diverge from planner",
                "differs from planner",
                "linkage clarity",
                "ou-to-sample",
                "sample-assay links",
                "cross-reference",
                "cross reference",
                "parent identifier",
                "linking sample",
                "mapping logic",
                "cover all",
                "per planner",
            )
            return (
                any(marker in lowered for marker in missing_source_markers)
                or any(
                    marker in lowered for marker in normalized_record_markers
                )
                or any(
                    marker in lowered for marker in structure_change_markers
                )
                or matches_declared_ambiguity(value)
            )

        def invalid_record_count_comparison(value: Any) -> bool:
            """Detect claims that confuse schema fields with entity records."""
            if not coverage_complete:
                return False
            lowered = str(value or "").lower()
            if "field" not in lowered:
                return False
            return any(
                marker in lowered
                for marker in (
                    "coverage gap",
                    "coverage is",
                    "field record",
                    "planned field",
                    "all field",
                    "all the field",
                    "emit all",
                    "only ",
                    " of ",
                    "appear in the json",
                )
            )

        issues = [
            item
            for item in (evaluation.get("issues") or [])
            if not non_actionable(item) and not invalid_record_count_comparison(item)
        ]
        improvements = [
            item
            for item in (evaluation.get("improvement_ops") or [])
            if not non_actionable(item) and not invalid_record_count_comparison(item)
        ]
        adjusted = dict(evaluation)
        adjusted["issues"] = issues
        adjusted["improvement_ops"] = improvements
        if not issues:
            adjusted["decision"] = "ACCEPT"
            adjusted["score"] = max(
                float(adjusted.get("score", 0.0) or 0.0),
                config.critic_accept_threshold_json_generator,
            )
            adjusted["critique"] = (
                "The normalized FAIR-DS JSON is structurally present. Empty, "
                "zero-confidence fields preserve source uncertainty; repeated "
                "field records follow the locked entity plan. Matrix semantics "
                "remain subject to deterministic downstream validation."
            )
        return adjusted

    @staticmethod
    def _generation_field_coverage(state: FAIRifierState) -> Dict[str, Any]:
        """Compare unique FAIR-DS schema fields, never raw entity records."""

        def key(level: Any, field_name: Any) -> tuple[str, str] | None:
            normalized_level = FAIRDSAPIParser.normalize_isa_sheet(level)
            normalized_name = " ".join(
                str(field_name or "").strip().lower().split()
            )
            if not normalized_level or not normalized_name:
                return None
            return normalized_level, normalized_name

        expected: set[tuple[str, str]] = set()
        for item in state.get("retrieved_knowledge") or []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") or {}
            candidate = key(
                metadata.get("isa_sheet") or metadata.get("sheet"),
                item.get("term")
                or item.get("field_name")
                or item.get("name")
                or metadata.get("label"),
            )
            if candidate:
                expected.add(candidate)

        actual: set[tuple[str, str]] = set()
        for field in state.get("metadata_fields") or []:
            if not isinstance(field, dict):
                continue
            candidate = key(
                field.get("isa_level") or field.get("isa_sheet"),
                field.get("field_name") or field.get("name"),
            )
            if candidate:
                actual.add(candidate)

        missing = sorted(expected - actual)
        return {
            "expected_count": len(expected),
            "actual_count": len(actual),
            "missing": [f"{level}.{name}" for level, name in missing],
            "raw_entity_field_records": len(state.get("metadata_fields") or []),
        }

    @staticmethod
    def _postprocess_entity_plan_evaluation(
        evaluation: Dict[str, Any], state: FAIRifierState
    ) -> Dict[str, Any]:
        """Prevent Critic retries from contradicting a validated entity plan.

        Source-declared replicates can legitimately share all measured metadata
        when FAIR-DS has no dedicated replicate-number term. Likewise, an
        explicitly recorded source ambiguity cannot be repaired by rerunning the
        mapper. Deterministic plan/matrix validation remains authoritative for
        cardinality, factor values, and linkage.
        """
        plan_validation = state.get("entity_plan_validation") or {}
        matrix_validation = state.get("entity_matrix_validation") or {}
        if not (
            plan_validation.get("passed") is True
            and matrix_validation.get("passed") is True
        ):
            return evaluation

        plan = state.get("entity_plan") or {}
        ambiguities = [
            str(item).strip().lower()
            for item in plan.get("unresolved_ambiguities") or []
            if str(item).strip()
        ]
        contract_rejection_fields = {
            match.group(1).strip().lower()
            for issue in (state.get("isa_value_quality") or {}).get("issues", [])
            for match in [
                re.search(
                    r"fair-ds value contract rejected [^.]+\.([^=]+)=",
                    str(issue or ""),
                    re.IGNORECASE,
                )
            ]
            if match
        }

        def tokens(value: Any) -> set[str]:
            return {
                token
                for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
                if len(token) > 2
            }

        def matches_ambiguity(value: Any) -> bool:
            candidate = tokens(value)
            if not candidate:
                return False
            return any(
                len(candidate & tokens(ambiguity))
                / max(len(candidate | tokens(ambiguity)), 1)
                >= 0.35
                for ambiguity in ambiguities
            )

        has_unmapped_dimensions = any(
            not attribute.get("field_name")
            for level in plan.get("levels") or []
            if isinstance(level, dict)
            for entity in level.get("entities") or []
            if isinstance(entity, dict)
            for attribute in entity.get("attributes") or []
            if isinstance(attribute, dict)
        )

        def non_actionable(value: Any) -> bool:
            lowered = str(value or "").lower()
            contradicts_cardinality = any(
                phrase in lowered
                for phrase in (
                    "merge row",
                    "merge duplicate",
                    "collapse row",
                    "deduplicate row",
                    "reduce duplicate",
                )
            )
            declared_replicate_similarity = has_unmapped_dimensions and any(
                term in lowered
                for term in ("duplicate", "identity-stripped", "identical row")
            )
            contradicts_value_contract = bool(contract_rejection_fields) and any(
                field in lowered for field in contract_rejection_fields
            ) and any(
                marker in lowered
                for marker in (
                    "restore",
                    "retain",
                    "add back",
                    "free-text",
                    "free text",
                    "exclude",
                    "vocabulary enforcement",
                    "cleared",
                )
            )
            # These properties are exhaustively checked by
            # validate_entity_matrix_against_plan.  Once that gate passed, a
            # free-form reviewer claim to the contrary is a hallucination, not
            # a reason to regenerate the matrix.
            contradicts_passed_matrix_gate = bool(matrix_validation.get("passed")) and (
                any(
                    phrase in lowered
                    for phrase in (
                        "non-unique identifier",
                        "nonunique identifier",
                        "identifiers unique",
                        "duplicate identifier",
                        "list-like identifier",
                        "list like identifier",
                        "row count",
                        "cardinality",
                        "label mismatch",
                        "label mismatches",
                        "name mismatch",
                        "name mismatches",
                        "missing parent",
                        "parent link",
                        "missing link",
                        "missing assay-sample link",
                        "unknown parent",
                        "person sheet",
                        "person worksheet",
                        "contact row",
                    )
                )
            )
            return (
                contradicts_cardinality
                or declared_replicate_similarity
                or contradicts_value_contract
                or contradicts_passed_matrix_gate
                or matches_ambiguity(value)
            )

        adjusted = dict(evaluation)
        issues = [
            issue
            for issue in evaluation.get("issues", []) or []
            if not non_actionable(issue)
        ]
        improvements = [
            item
            for item in evaluation.get("improvement_ops", []) or []
            if not non_actionable(item)
        ]
        adjusted["issues"] = issues
        adjusted["improvement_ops"] = improvements
        if not issues:
            adjusted["decision"] = "ACCEPT"
            adjusted["score"] = max(
                float(adjusted.get("score", 0.0) or 0.0),
                config.critic_accept_threshold_general,
            )
            adjusted["critique"] = (
                "Deterministic entity-plan validation passed. Declared source "
                "ambiguities remain review notes, and planned replicate rows "
                "must not be merged merely because their non-identity metadata match."
            )
        return adjusted
    
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
        state: FAIRifierState,
        observation: Optional[Dict[str, Any]] = None,
    ) -> FAIRifierState:
        """
        Prepare state with critic feedback for agent to retry.
        Updates context with specific feedback and suggestions.
        
        Note: Retry count is managed by the evaluate nodes, not here.
        """
        if "context" not in state:
            state["context"] = {}
        
        # Don't increment retry_count here - it's managed by evaluate nodes
        
        # Store critic feedback (use .get() for safe access)
        if observation is None:
            observation = state.get("context", {}).get("retry_observation")
        improvement_ops = evaluation.get("improvement_ops") or evaluation.get("suggestions") or []
        feedback_payload = {
            "decision": evaluation.get("decision", "ACCEPT"),
            "score": evaluation.get("score", 0.0),
            "critique": evaluation.get("critique", ""),
            "issues": evaluation.get("issues", []),
            "suggestions": improvement_ops,
            "timestamp": datetime.now().isoformat(),
            "target_agent": agent_name,
            "retry_contract": build_retry_contract(evaluation, observation),
        }
        state["context"]["critic_feedback"] = feedback_payload
        state["context"].setdefault("critic_feedback_by_agent", {})[agent_name] = feedback_payload
        
        # Manage historical guidance with size limits to prevent token waste
        history = state["context"].setdefault("critic_guidance_history", {})
        history.setdefault(agent_name, [])
        
        # Add new improvement ops (deduplicated)
        for op in improvement_ops:
            # Simple deduplication: avoid exact duplicates
            if op not in history[agent_name]:
                history[agent_name].append(op)
        
        # LIMIT: Keep only the last 10 suggestions per agent to prevent token explosion
        MAX_GUIDANCE_PER_AGENT = 10
        if len(history[agent_name]) > MAX_GUIDANCE_PER_AGENT:
            # Keep the most recent suggestions
            history[agent_name] = history[agent_name][-MAX_GUIDANCE_PER_AGENT:]
            logger.info(
                f"Trimmed historical guidance for {agent_name} to {MAX_GUIDANCE_PER_AGENT} items"
            )
        
        # NOTE (refactor §2): we no longer snapshot the previous attempt's full
        # output into state. Exposing the failed output to the retry prompt
        # anchored the LLM to its own mistake (echo-chamber effect). The
        # current values are still in state["document_info"] / state["retrieved_knowledge"]
        # / state["metadata_fields"] — agents simply do not see them in the
        # next-attempt prompt (see fairifier.utils.retry_context).
        
        self.log_execution(
            state,
            f"🔄 Prepared feedback for {agent_name} retry (attempt {state['context']['retry_count']})"
        )
        
        return state

    # ---------- Helper methods ----------

    def _load_rubric(self, rubric_path: Path) -> Dict[str, Any]:
        try:
            with open(rubric_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.error("Critic rubric not found at %s", rubric_path)
        except Exception as exc:
            logger.error("Failed to load critic rubric: %s", exc)
        return {}

    def _fallback_evaluation(self, reason: str) -> Dict[str, Any]:
        return {
            "decision": "ESCALATE",
            "score": 0.0,
            "critique": f"Critic failure: {reason}",
            "issues": [reason],
            "improvement_ops": ["Human review required due to critic failure."]
        }

    def _stabilize_invalid_critic_output(
        self,
        node_key: str,
        evaluation: Dict[str, Any],
        state: FAIRifierState,
    ) -> Dict[str, Any]:
        """Avoid wasting retries when the critic itself returns unusable output."""
        critique = str(evaluation.get("critique", "") or "")
        if not critique.startswith("Critic failure:"):
            return evaluation

        if node_key == "document_parser":
            doc_info = state.get("document_info", {}) or {}
            source_context = state.get("context") or {}
            source_role = str(
                source_context.get("current_source_role") or "unknown"
            )
            source_total = int(
                source_context.get("current_source_total") or 1
            )
            if (
                source_total > 1
                and source_role != "main_manuscript"
                and len(doc_info) >= 3
            ):
                return {
                    "decision": "ACCEPT",
                    "score": config.critic_accept_threshold_document_parser,
                    "critique": (
                        "Critic returned invalid output, but the bundle source produced "
                        "usable source-scoped metadata. Keeping it for authoritative "
                        "multi-file synthesis instead of regenerating without actionable feedback."
                    ),
                    "issues": [],
                    "improvement_ops": [],
                }
            if doc_info.get("title") and len(doc_info) >= 8:
                return {
                    "decision": "ACCEPT",
                    "score": config.critic_accept_threshold_document_parser,
                    "critique": (
                        "Critic returned invalid output, but DocumentParser produced usable "
                        "structured document metadata. Accepting to avoid wasting retries."
                    ),
                    "issues": [],
                    "improvement_ops": [],
                }

        if node_key == "knowledge_retriever":
            retrieved = state.get("retrieved_knowledge", []) or []
            selected_packages = state.get("selected_packages", []) or []
            if retrieved and selected_packages:
                return {
                    "decision": "ACCEPT",
                    "score": config.critic_accept_threshold_knowledge_retriever,
                    "critique": (
                        "Critic returned invalid output, but KnowledgeRetriever produced "
                        "retrieved FAIR-DS fields and selected packages. Accepting current output."
                    ),
                    "issues": [],
                    "improvement_ops": [],
                }

        if node_key == "json_generator":
            metadata_fields = state.get("metadata_fields", []) or []
            metadata_json = state.get("artifacts", {}).get("metadata_json")
            if metadata_fields and metadata_json:
                return {
                    "decision": "ACCEPT",
                    "score": config.critic_accept_threshold_json_generator,
                    "critique": (
                        "Critic returned invalid output, but JSONGenerator produced "
                        "metadata fields and a metadata_json artifact. Accepting current output."
                    ),
                    "issues": [],
                    "improvement_ops": [],
                }

        if node_key == "isa_value_mapper":
            raw_matrix = (state.get("artifacts") or {}).get("isa_values_json")
            try:
                matrix = (
                    json.loads(raw_matrix)
                    if isinstance(raw_matrix, str)
                    else raw_matrix
                )
            except (TypeError, ValueError):
                matrix = None
            expected_levels = {
                "investigation",
                "study",
                "observationunit",
                "sample",
                "assay",
            }
            populated_levels = {
                str(level).lower()
                for level, sheet in (matrix or {}).items()
                if isinstance(sheet, dict) and isinstance(sheet.get("rows"), list)
                and sheet.get("rows")
            }
            matrix_valid = bool(
                (state.get("entity_matrix_validation") or {}).get("passed")
            )
            if matrix_valid and expected_levels.issubset(populated_levels):
                state["needs_human_review"] = True
                return {
                    "decision": "ACCEPT",
                    "score": config.critic_accept_threshold_general,
                    "critique": (
                        "Critic returned invalid output, but ISAValueMapper produced a "
                        "five-level matrix that passed the locked entity-plan validation. "
                        "Keeping it and flagging review instead of regenerating blindly."
                    ),
                    "issues": [],
                    "improvement_ops": [],
                }
            # A reviewer transport/parse failure is not actionable mapper
            # feedback.  If the deterministic entity gate found real defects,
            # make those exact defects the retry contract instead of asking the
            # expensive mapper to react to "human review required".  If no
            # deterministic defect exists, preserve the escalation: there is
            # no evidence that regeneration would improve the candidate.
            structure_errors = list(
                (state.get("entity_matrix_validation") or {}).get("errors") or []
            )
            if matrix and structure_errors:
                return {
                    "decision": "RETRY",
                    "score": config.critic_retry_max_threshold,
                    "critique": (
                        "The Critic response was unavailable; retry is justified only "
                        "by deterministic entity-matrix validation failures."
                    ),
                    "issues": structure_errors[:8],
                    "improvement_ops": [
                        "Repair only the listed deterministic cardinality, identifier, "
                        "or parent-link failures and re-run the entity-matrix validator."
                    ],
                }

        if node_key == "bio_metadata_agent":
            bio_packets = self._bio_metadata_evidence_packets(state)
            conf = float((state.get("confidence_scores") or {}).get("bio_metadata") or 0.0)
            scratch = (state.get("react_scratchpad") or {}).get("BioMetadataAgent") or {}
            tools = scratch.get("tools_called") or []
            if bio_packets and conf >= 0.5 and tools:
                return {
                    "decision": "ACCEPT",
                    "score": config.critic_accept_threshold_general,
                    "critique": (
                        "Critic returned invalid output, but BioMetadataAgent produced "
                        "tool-grounded evidence packets and reported usable confidence."
                    ),
                    "issues": [],
                    "improvement_ops": [],
                }

        return evaluation

    def _build_parsing_context(self, state: FAIRifierState) -> str:
        doc_info = state.get("document_info", {})
        state_context = state.get("context", {})
        retry_count = state_context.get("retry_count", 0)
        planner_guidance = state.get("agent_guidance", {}).get("DocumentParser")
        source_role = str(state_context.get("current_source_role") or "unknown")
        source_total = int(state_context.get("current_source_total") or 1)
        scope_guidance = "N/A"
        if source_total > 1:
            if source_role == "main_manuscript":
                scope_guidance = (
                    "This is the primary manuscript in a multi-file bundle. Evaluate "
                    "paper identity, methods, study scope, and bibliographic coverage."
                )
            else:
                scope_guidance = (
                    f"This is a {source_role} source within a multi-file bundle. Evaluate only "
                    "source-appropriate facts such as identifiers, variables, methods, table "
                    "semantics, and entity evidence. Do not penalize or request retries for "
                    "missing DOI, journal, publication date, abstract, title, or full authors; "
                    "the main manuscript owns those fields. Do not request external searches "
                    "solely to fill paper-level bibliography for this source."
                )
        return (
            f"**Parsed Document Info (attempt {retry_count + 1}/{self.max_retries_per_step}):**\n"
            f"{json.dumps(self._compact_document_info(doc_info), indent=2, ensure_ascii=False)}\n\n"
            f"**Current source role:** {source_role}\n"
            f"**Per-source scope:** {scope_guidance}\n\n"
            f"**Planner guidance:** {planner_guidance or 'N/A'}"
        )

    def _build_retrieval_context(self, state: FAIRifierState) -> str:
        doc_info = state.get("document_info", {})
        retrieved = state.get("retrieved_knowledge", [])
        planner_guidance = state.get("agent_guidance", {}).get("KnowledgeRetriever")
        packages_found = sorted(
            {
                item.get("metadata", {}).get("package")
                for item in retrieved
                if item.get("metadata", {}).get("package")
            }
        )
        # doc_info is canonicalized upstream (refactor §1) — only research_domain.
        domain = doc_info.get("research_domain")
        
        # Get API capabilities from state (set by KnowledgeRetriever)
        api_capabilities = state.get("api_capabilities", {})
        available_packages = api_capabilities.get("available_packages", [])
        limitation_note = api_capabilities.get("limitation_note")
        
        # Build clear summary with agent output prominently displayed
        summary = {
            "agent_output_status": "present" if retrieved else "missing",
            "document_domain": domain,
            "document_type": doc_info.get("document_type"),
            "planner_guidance": planner_guidance,
            # CRITICAL: Include API limitations so Critic understands constraints
            "api_limitations": {
                "available_packages_in_api": available_packages,
                "total_packages_available": len(available_packages),
                "candidate_packages_considered": api_capabilities.get("candidate_packages_considered", [])[:15],
                "selected_packages": api_capabilities.get("selected_packages", [])[:10],
                "package_selection_trace": state.get("package_selection_trace", {}),
                "unavailable_requested_packages": api_capabilities.get("unavailable_requested_packages", [])[:10],
                "metadata_gap_hints": api_capabilities.get("requested_metadata_gaps", [])[:10],
                "limitation_note": limitation_note,
                "evaluation_guidance": (
                    "IMPORTANT: Evaluate the agent's work within the constraints of what the API actually provides. "
                    "If the API only has limited packages available, the agent cannot retrieve packages that don't exist. "
                    "Judge based on whether the agent made optimal use of available resources, not whether it retrieved "
                    "packages that are unavailable in the API. Missing concepts that are not real FAIR-DS packages "
                    "should be recorded as metadata gaps, not treated as package-selection failures."
                ),
            },
            "retrieval_results": {
                "total_terms_retrieved": len(retrieved),
                "packages_selected": packages_found,
                "terms_by_isa_sheet": self._group_terms_by_sheet(retrieved),
                "sample_terms": self._sample_retrieved_terms(retrieved, limit=10),
            },
            "metadata_gap_handling": {
                "gap_hint_count": len(state.get("metadata_gap_hints", []) or []),
                "gap_hints": [
                    {
                        "label": hint.get("label"),
                        "source": hint.get("source"),
                    }
                    for hint in (state.get("metadata_gap_hints", []) or [])[:10]
                    if isinstance(hint, dict)
                ],
            },
        }
        return json.dumps(summary, indent=2, ensure_ascii=False)

    def _bio_metadata_evidence_packets(self, state: FAIRifierState) -> List[Dict[str, Any]]:
        """Evidence packets attributable to BioMetadataAgent (tool output path)."""
        out: List[Dict[str, Any]] = []
        for p in state.get("evidence_packets", []) or []:
            if not isinstance(p, dict):
                continue
            agent = (p.get("provenance") or {}).get("agent")
            if agent == "BioMetadataAgent":
                out.append(p)
        return out

    def _build_bio_metadata_context(self, state: FAIRifierState) -> str:
        """Structured signals for judging tool-first biological data analysis."""
        retry_count = state.get("context", {}).get("retry_count", 0)
        bio_paths = state.get("bio_file_paths", []) or []
        planner_guidance = state.get("agent_guidance", {}).get("BioMetadataAgent")
        scratch = (state.get("react_scratchpad") or {}).get("BioMetadataAgent") or {}
        bio_conf = (state.get("confidence_scores") or {}).get("bio_metadata")
        bio_packets = self._bio_metadata_evidence_packets(state)
        samples: List[Dict[str, Any]] = []
        for p in bio_packets[:10]:
            samples.append(
                {
                    "field_candidate": p.get("field_candidate"),
                    "value_preview": str(p.get("value", ""))[:160],
                    "evidence_preview": str(p.get("evidence_text", ""))[:220],
                    "section": p.get("section"),
                    "source_type": p.get("source_type"),
                }
            )

        sw = state.get("source_workspace") or {}
        bio_workspace_ids: List[str] = []
        if isinstance(sw, dict):
            for sid in (sw.get("source_paths") or {}).keys():
                if str(sid).startswith("bio_"):
                    bio_workspace_ids.append(str(sid))

        summary = {
            "bio_metadata_contract": (
                "Evaluate whether BioMetadataAgent ran appropriate bioinformatics tools "
                "(e.g., samtools, bcftools) and recovered metadata that is grounded in "
                "observable tool output, not filename guessing or hallucinated parameters."
            ),
            "attempt": f"{retry_count + 1}/{self.max_retries_per_step}",
            "planner_guidance": planner_guidance,
            "input_files": [Path(p).name for p in bio_paths],
            "input_file_count": len(bio_paths),
            "reported_bio_metadata_confidence": bio_conf,
            "inner_loop_telemetry": {
                "iterations": scratch.get("iterations"),
                "tools_called": scratch.get("tools_called", [])[:24],
            },
            "bio_evidence_packets": {
                "count": len(bio_packets),
                "samples": samples,
            },
            "bio_source_workspace_entries": bio_workspace_ids[:12],
            "document_context_after_merge": self._compact_document_info(
                state.get("document_info", {}) or {}
            ),
        }
        return json.dumps(summary, indent=2, ensure_ascii=False)
    
    def _group_terms_by_sheet(self, terms):
        """Group terms by ISA sheet for clearer presentation."""
        by_sheet = {}
        for term in terms:
            sheet = term.get("metadata", {}).get("isa_sheet", "unknown")
            if sheet not in by_sheet:
                by_sheet[sheet] = []
            by_sheet[sheet].append(term.get("term"))
        return {k: len(v) for k, v in by_sheet.items()}

    def _build_generation_context(self, state: FAIRifierState) -> str:
        doc_info = state.get("document_info", {})
        metadata_fields = state.get("metadata_fields", [])
        metadata_json = state.get("artifacts", {}).get("metadata_json")
        metadata_json_summary: Dict[str, Any] = {
            "present": False,
            "parseable": False,
        }
        if metadata_json:
            metadata_json_summary["present"] = True
            try:
                metadata_payload = json.loads(metadata_json)
                isa_structure = metadata_payload.get("isa_structure", {}) or {}
                statistics = metadata_payload.get("statistics", {}) or {}
                metadata_json_summary = {
                    "present": True,
                    "parseable": True,
                    "top_level_keys": list(metadata_payload.keys())[:20],
                    "packages_used": metadata_payload.get("packages_used", [])[:10],
                    "overall_confidence": metadata_payload.get("overall_confidence"),
                    "needs_review": metadata_payload.get("needs_review"),
                    "isa_levels_present": [
                        level
                        for level, payload in isa_structure.items()
                        if isinstance(payload, dict) and payload.get("fields")
                    ],
                    "statistics": {
                        "total_fields": statistics.get("total_fields"),
                        "confirmed_fields": statistics.get("confirmed_fields"),
                        "provisional_fields": statistics.get("provisional_fields"),
                        "inferred_extension_fields": statistics.get("inferred_extension_fields"),
                    },
                }
            except Exception as exc:
                metadata_json_summary["parse_error"] = str(exc)
        evidence_coverage = 0
        if metadata_fields:
            evidence_coverage = (
                sum(1 for f in metadata_fields if f.get("evidence")) / len(metadata_fields)
            )
        summary = {
            "generator_contract": (
                "Evaluate against FAIRiAgent's actual contract: produce a FAIR-DS-compatible, "
                "ISA-structured metadata JSON artifact with provenance-rich fields. The "
                "output is a normalized field/value record stream, so repeated field names "
                "and identifiers across planned entities are expected and are not duplicate "
                "rows. A blank value with confidence 0 is the required source-faithful result "
                "when the supplied document does not state a mandatory FAIR-DS value; do not "
                "request guessing merely to raise overall confidence or clear needs_review. "
                "The validated entity plan owns cardinality and linkage and is immutable at "
                "this stage; do not recommend merging, splitting, or moving its entities. "
                "Reject unsupported non-empty values, contradictions, missing selected fields, "
                "invalid JSON, or FAIR-DS/package mismatches. "
                "Planner guidance may request richer JSON-LD or linked-data embellishments, "
                "but those are stretch goals, not minimum acceptance criteria."
            ),
            "document_overview": self._compact_document_info(doc_info),
            "planner_guidance_policy": (
                "Free-form orchestration suggestions are intentionally excluded. "
                "Judge only source evidence, selected FAIR-DS contracts, and the "
                "validated entity plan."
            ),
            "field_count": len(metadata_fields),
            "schema_field_coverage": self._generation_field_coverage(state),
            "field_count_semantics": (
                "schema_field_coverage compares unique (ISA level, FAIR-DS term) keys. "
                "field_count/raw_entity_field_records may be larger because one schema "
                "field is repeated across planned entities; metadata_json statistics.total_fields "
                "is the deduplicated schema-field count. These counts are not expected to match."
            ),
            "evidence_coverage": evidence_coverage,
            "field_summary": self._summarize_metadata_fields(metadata_fields),
            "metadata_json_summary": metadata_json_summary,
            "locked_entity_plan": {
                "validated": (state.get("entity_plan_validation") or {}).get(
                    "passed"
                ),
                "row_counts": (state.get("entity_plan_validation") or {}).get(
                    "row_counts", {}
                ),
                "investigation_contact_count": (
                    state.get("entity_plan_validation") or {}
                ).get("investigation_contact_count", 0),
                "unresolved_source_ambiguities": (
                    state.get("entity_plan") or {}
                ).get("unresolved_ambiguities", [])[:8],
            },
            "inferred_metadata_extensions": (state.get("inferred_metadata_extensions", []) or [])[:10],
        }
        return json.dumps(summary, indent=2, ensure_ascii=False)

    def _build_isa_mapper_context(self, state: FAIRifierState) -> str:
        """Build evaluation context for ISAValueMapper."""
        isa_values = state.get("artifacts", {}).get("isa_values_json")
        metadata_fields = state.get("metadata_fields", [])
        sheets_populated: list = []
        row_count = 0
        sheet_summaries: dict = {}
        if isa_values:
            try:
                isa_data = json.loads(isa_values) if isinstance(isa_values, str) else isa_values
                sheets_populated = list(isa_data.keys())
                for sheet_name, sheet_data in isa_data.items():
                    if isinstance(sheet_data, dict):
                        # {"columns": [...], "rows": [[...], ...]} structure
                        rows = sheet_data.get("rows", [])
                        cols = sheet_data.get("columns", [])
                        n_rows = len(rows) if isinstance(rows, list) else 0
                        row_count += n_rows
                        identifier_fields = {
                            "investigation": "investigation identifier",
                            "study": "study identifier",
                            "observationunit": "observation unit identifier",
                            "sample": "sample identifier",
                            "assay": "assay identifier",
                        }
                        id_field = identifier_fields.get(str(sheet_name).lower())
                        identifiers = []
                        if id_field and isinstance(rows, list):
                            identifiers = [
                                row.get(id_field)
                                for row in rows
                                if isinstance(row, dict) and row.get(id_field)
                            ]
                        sheet_summaries[sheet_name] = {
                            "columns": cols[:10] if isinstance(cols, list) else [],
                            "row_count": n_rows,
                            "identifiers": identifiers[:6] + identifiers[-2:] if len(identifiers) > 8 else identifiers,
                        }
                    elif isinstance(sheet_data, list):
                        row_count += len(sheet_data)
                        sheet_summaries[sheet_name] = {"row_count": len(sheet_data)}
            except Exception:
                pass
        mapped_count = sum(
            1 for f in metadata_fields
            if f.get("status") == "confirmed" and f.get("value")
        )
        summary = {
            "isa_mapper_contract": (
                "Evaluate whether ISAValueMapper produced a complete, well-structured "
                "columns×rows matrix for each ISA-Tab sheet using controlled vocabulary. "
                "Every sheet (investigation, study, observationunit, sample, assay) should "
                "preserve entity rows, parent linkage fields, and tool-backed evidence gathered from source workspace inspection. "
                "A validated entity plan is a hard cardinality contract: never recommend merging or collapsing its rows. "
                "Declared replicates may share non-identity metadata when no FAIR-DS replicate term exists; their plan labels and links still distinguish them. "
                "Explicit unresolved source ambiguities are review notes, not retryable mapper defects."
                " FAIR-DS regex enforcement is a hard boundary: never recommend restoring a value "
                "that the deterministic contract rejected. The value may belong in another selected "
                "field, while the rejected controlled column stays blank."
            ),
            "sheets_populated": sheets_populated,
            "total_rows": row_count,
            "sheet_summaries": sheet_summaries,
            "isa_value_quality": state.get("isa_value_quality", {}),
            "entity_plan": {
                "levels": [
                    {
                        "level": item.get("level"),
                        "cardinality": item.get("cardinality"),
                        "materialized_rows": len(item.get("entities") or []),
                        "evidence": (item.get("evidence") or [])[:3],
                        "unresolved_ambiguities": item.get("unresolved_ambiguities") or [],
                    }
                    for item in ((state.get("entity_plan") or {}).get("levels") or [])
                    if isinstance(item, dict)
                ],
                "investigation_contacts": (
                    (state.get("entity_plan") or {}).get("investigation_contacts") or []
                ),
                "unresolved_ambiguities": (state.get("entity_plan") or {}).get(
                    "unresolved_ambiguities", []
                ),
            },
            "entity_plan_validation": state.get("entity_plan_validation", {}),
            "entity_matrix_validation": state.get("entity_matrix_validation", {}),
            "source_authors": (state.get("document_info") or {}).get("authors", []),
            "inner_loop_telemetry": (state.get("react_scratchpad") or {}).get("ISAValueMapper", {}),
            "confirmed_metadata_fields_available": mapped_count,
            "retrieved_knowledge_terms": len(state.get("retrieved_knowledge", [])),
        }
        return json.dumps(summary, indent=2, ensure_ascii=False)

    def _compact_document_info(self, doc_info: Dict[str, Any]) -> Dict[str, Any]:
        """Keep only the highest-signal document parser outputs for critic prompts."""
        if not isinstance(doc_info, dict):
            return {}
        # doc_info is canonicalized upstream (refactor §1) — no scientific_domain alias.
        keys = [
            "document_type",
            "title",
            "research_domain",
            "methodology",
            "location",
            "keywords",
            "datasets_mentioned",
            "variables",
            "key_findings",
        ]
        compact = {}
        for key in keys:
            value = doc_info.get(key)
            if value:
                if isinstance(value, list):
                    compact[key] = value[:8]
                else:
                    compact[key] = value
        return compact

    def _sample_retrieved_terms(self, retrieved: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
        """Return a compact, representative sample of retrieved terms."""
        sampled = []
        for item in retrieved[:limit]:
            metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
            sampled.append(
                {
                    "term": item.get("term"),
                    "package": metadata.get("package"),
                    "isa_sheet": metadata.get("isa_sheet"),
                    "required": metadata.get("required"),
                }
            )
        return sampled

    def _summarize_metadata_fields(self, metadata_fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Return a compact field-level summary for critic evaluation."""
        by_level: Dict[str, int] = {}
        with_evidence = 0
        provisional = 0
        sampled_fields = []
        for field in metadata_fields:
            if not isinstance(field, dict):
                continue
            level = (field.get("isa_level") or "unknown").lower()
            by_level[level] = by_level.get(level, 0) + 1
            if field.get("evidence"):
                with_evidence += 1
            if float(field.get("confidence", 0.0) or 0.0) < 0.85:
                provisional += 1
            if len(sampled_fields) < 12:
                sampled_fields.append(
                    {
                        "field_name": field.get("field_name") or field.get("name"),
                        "isa_level": level,
                        "confidence": field.get("confidence"),
                        "has_evidence": bool(field.get("evidence")),
                    }
                )
        return {
            "counts_by_isa_level": by_level,
            "fields_with_evidence": with_evidence,
            "provisional_fields": provisional,
            "sample_fields": sampled_fields,
        }

    async def _judge_with_rubric(self, node_key: str, evaluation_content: str) -> Dict[str, Any]:
        node_rules = (self.rubric.get("nodes") or {}).get(node_key)
        if not node_rules:
            return self._fallback_evaluation(f"No rubric defined for {node_key}")
        
        system_prompt = self.rubric.get(
            "default_prompt",
            "You are an impartial reviewer who returns JSON verdicts."
        )
        criteria = node_rules.get("criteria", {})
        criteria_text = []
        for dim, detail in criteria.items():
            checks = detail.get("checks", [])
            bullet = "\n".join([f"    - {chk}" for chk in checks]) if checks else "    - (no checks provided)"
            criteria_text.append(f"- {dim.title()}:\n{bullet}")
        rubric_block = "\n".join(criteria_text) if criteria_text else "N/A"
        
        accept_threshold = node_rules.get("accept_threshold", 0.8)
        revise_min = node_rules.get("revise_min", 0.5)
        
        prompt = (
            f"{system_prompt}\n\n"
            f"─── OUTPUT CONTRACT (HARD LIMITS — EXCEEDING ANY WILL CAUSE REJECTION) ───\n"
            f"- Respond with a SINGLE JSON object matching the schema below.\n"
            f"- The ENTIRE response MUST be under 1,500 characters.\n"
            f"- critique: ≤ 180 characters — one sentence, no bullet points.\n"
            f"- issues: ≤ 3 items, each ≤ 80 characters.  Omit if none.\n"
            f"- suggestions: ≤ 3 items, each ≤ 120 characters.  Omit if none.\n"
            f"- DO NOT re-state the evaluation context or rubric back.\n"
            f"- DO NOT write paragraphs, explanations, or markdown outside the JSON.\n"
            f"- If the output meets the rubric → score ≥ threshold, issues=[], suggestions=[].\n"
            f"- If the output fails → score < threshold, list ONLY the top 2-3 concrete gaps.\n"
            f"─── END CONTRACT ───\n\n"
            f"# Node: {node_key}\n"
            f"Goal: {node_rules.get('description', '')}\n\n"
            f"## Evaluation Context\n{evaluation_content}\n\n"
            f"## Rubric\n{rubric_block}\n\n"
            f"Return the JSON evaluation now.  No preamble."
        )
        
        from langchain_core.messages import HumanMessage

        # Use one provider-agnostic budget policy.  Critic reasoning and the
        # structured JSON share the completion budget on many providers, so a
        # 1k default is unsafe even when the visible JSON is short.  Provider
        # adapters may translate the parameter name, but no model gets a
        # smaller budget based on its model name.
        critic_max_tokens = min(
            max(int(config.llm_max_tokens or 16384), 16384),
            32768,
        )
        parsed = await invoke_structured_output(
            self.llm_helper,
            [HumanMessage(content=prompt)],
            CriticEvaluation,
            operation_name=f"Critic.{node_key}",
            max_tokens=critic_max_tokens,
        )
        
        if not parsed:
            logger.error(f"Failed to parse Critic response.")
            return self._fallback_evaluation("Unable to parse critic JSON response")
        
        score = float(parsed.get("score", 0.0) or 0.0)
        
        # ALWAYS use score-based decision (ignore LLM's decision field)
        # This ensures consistent behavior based on rubric thresholds
        # Decision thresholds (from critic_rubric.yaml):
        # - ACCEPT: score >= accept_threshold
        # - RETRY (revise): revise_min <= score < accept_threshold
        # - ESCALATE: score < revise_min
        if score >= accept_threshold:
            decision = "accept"
        elif score >= revise_min:
            decision = "revise"
        else:
            decision = "escalate"
        
        mapped_decision = {
            "accept": "ACCEPT",
            "revise": "RETRY",
            "escalate": "ESCALATE"
        }[decision]
        
        # Log decision with clear threshold information
        # (use module-level config — a local import here shadows it and breaks
        # earlier references in this function under UnboundLocalError)
        rubric_file = str(config.critic_rubric_path)
        logger.info(
            f"Critic decision for {node_key}: {mapped_decision}\n"
            f"  Score: {score:.2f}\n"
            f"  Thresholds (from {rubric_file}):\n"
            f"    - ACCEPT if score >= {accept_threshold:.2f}\n"
            f"    - RETRY if {revise_min:.2f} <= score < {accept_threshold:.2f}\n"
            f"    - ESCALATE if score < {revise_min:.2f}\n"
            f"  → Decision: {mapped_decision} (score {score:.2f} is in range for {decision})"
        )
        
        return {
            "decision": mapped_decision,
            "score": score,
            "issues": parsed.get("issues", []),
            "improvement_ops": parsed.get("improvement_ops", parsed.get("suggestions", [])),
            "evidence": parsed.get("evidence", []),
            "critique": parsed.get("critique", "")
        }

    def _postprocess_api_constrained_evaluation(
        self,
        node_key: str,
        evaluation: Dict[str, Any],
        state: FAIRifierState,
    ) -> Dict[str, Any]:
        """Reduce false-negative critic results when FAIR-DS API coverage is the limiting factor."""
        if node_key not in {"knowledge_retriever", "json_generator"}:
            return evaluation

        unavailable = {
            str(item).lower()
            for item in (state.get("api_capabilities", {}).get("unavailable_requested_packages", []) or [])
            if item
        }
        gap_labels = {
            str(item.get("label")).lower()
            for item in (state.get("metadata_gap_hints", []) or [])
            if isinstance(item, dict) and item.get("label")
        }
        constraint_terms = unavailable | gap_labels

        def is_constraint_issue(text: Any) -> bool:
            lowered = str(text or "").lower()
            if not lowered:
                return False
            if not any(term in lowered for term in constraint_terms):
                return False
            return any(
                marker in lowered
                for marker in [
                    "package",
                    "fair-ds",
                    "fair ds",
                    "missing",
                    "unavailable",
                    "not found",
                    "should use",
                    "add",
                ]
            )

        def is_json_contract_mismatch_issue(text: Any) -> bool:
            if node_key != "json_generator":
                return False
            lowered = str(text or "").lower()
            if not lowered:
                return False
            markers = [
                "json-ld",
                "no actual json",
                "only field summaries",
                "only field summary",
                "researchproject",
                "dcat",
                "bioschemas",
                "schema.org",
                "top-level researchproject",
                "@context",
                "linked-data",
                "linked data",
            ]
            return any(marker in lowered for marker in markers)

        issues = [
            issue for issue in evaluation.get("issues", [])
            if not is_constraint_issue(issue) and not is_json_contract_mismatch_issue(issue)
        ]
        suggestions = [
            suggestion
            for suggestion in evaluation.get("improvement_ops", [])
            if not is_constraint_issue(suggestion) and not is_json_contract_mismatch_issue(suggestion)
        ]
        critique = str(evaluation.get("critique", "") or "")
        critique_mentions_only_constraints = (
            is_constraint_issue(critique) or is_json_contract_mismatch_issue(critique)
        ) and not issues
        selected_packages = state.get("selected_packages", []) or []

        if node_key == "knowledge_retriever":
            package_trace = state.get("package_selection_trace") or {}
            if package_trace and not package_trace.get("stable", False):
                adjusted = dict(evaluation)
                adjusted_issues = list(issues)
                uncovered_levels = package_trace.get("uncovered_schema_levels") or []
                if uncovered_levels:
                    adjusted_issues.append(
                        "Package selection left strong source-schema matches uncovered "
                        f"for ISA levels: {', '.join(uncovered_levels)}."
                    )
                else:
                    adjusted_issues.append(
                        "Package selection did not stabilize after bounded field-contract audits."
                    )
                adjusted["issues"] = list(dict.fromkeys(adjusted_issues))
                adjusted["improvement_ops"] = list(
                    dict.fromkeys(
                        suggestions
                        + [
                            "Re-evaluate selected packages against source-matched controlled values, real fields, and unsupported mandatory burden."
                        ]
                    )
                )
                adjusted["score"] = min(
                    float(adjusted.get("score", 0.0) or 0.0),
                    max(config.critic_retry_min_threshold, config.critic_accept_threshold_knowledge_retriever - 0.01),
                )
                adjusted["decision"] = "RETRY"
                adjusted["critique"] = (
                    "Package selection is unresolved because a strong current-source schema "
                    "match remains uncovered."
                    if uncovered_levels
                    else "Package selection is structurally unresolved: successive contract "
                    "audits still disagree on the applicable FAIR-DS packages."
                )
                return adjusted

            # Once bounded audits over real FAIR-DS field contracts converge
            # and all strong source-schema levels are covered, free-form model
            # preference for another package name is not a retryable defect.
            # The Critic may still report concrete field/level coverage errors;
            # those are governed by the deterministic trace above.
            available_packages = {
                str(item).lower()
                for item in (
                    state.get("api_capabilities", {}).get(
                        "available_packages", []
                    )
                    or []
                )
            }
            selected_are_real = bool(selected_packages) and all(
                str(package).lower() in available_packages
                for package in selected_packages
            )
            trace_is_authoritative = bool(package_trace) and (
                package_trace.get("stable") is True
                and package_trace.get("coverage_resolved", True) is not False
                and not (package_trace.get("uncovered_schema_levels") or [])
                and selected_are_real
            )

            def is_package_preference(value: Any) -> bool:
                lowered = str(value or "").lower()
                if not lowered:
                    return False
                preference_markers = (
                    "add ",
                    "remove ",
                    "prefer ",
                    "instead of",
                    "not selected",
                    "omitted",
                    "missing package",
                    "selected set",
                    "consider adding",
                    "package per planner",
                )
                package_context = (
                    "package" in lowered
                    or any(
                        str(package).lower() in lowered
                        for package in available_packages
                    )
                )
                gap_reclassification = "gap_hint" in lowered or "gap hint" in lowered
                return (package_context and any(
                    marker in lowered for marker in preference_markers
                )) or gap_reclassification

            if trace_is_authoritative:
                trace_suggestions = [
                    item for item in suggestions if not is_package_preference(item)
                ]
                adjusted = dict(evaluation)
                adjusted["decision"] = "ACCEPT"
                adjusted["score"] = max(
                    float(adjusted.get("score", 0.0) or 0.0),
                    config.critic_accept_threshold_knowledge_retriever,
                )
                adjusted["issues"] = []
                adjusted["improvement_ops"] = trace_suggestions
                adjusted["critique"] = (
                    "Real FAIR-DS field-contract audits converged, mandatory "
                    "burden was arbitrated, and every source-matched ISA level "
                    "is covered. Free-form package or cross-level preferences "
                    "cannot override that deterministic trace."
                )
                return adjusted

        if (
            not constraint_terms
            and node_key != "json_generator"
        ):
            return evaluation

        if issues == evaluation.get("issues", []) and suggestions == evaluation.get("improvement_ops", []) and not critique_mentions_only_constraints:
            return evaluation

        adjusted = dict(evaluation)
        adjusted["issues"] = issues
        adjusted["improvement_ops"] = suggestions

        has_substantive_output = bool(state.get("retrieved_knowledge") if node_key == "knowledge_retriever" else state.get("metadata_fields"))
        if node_key == "knowledge_retriever":
            available_packages = {
                str(item).lower() for item in (state.get("api_capabilities", {}).get("available_packages", []) or [])
            }
            gap_hints = state.get("metadata_gap_hints", []) or []
            all_packages_real = bool(selected_packages) and all(
                str(pkg).lower() in available_packages for pkg in selected_packages
            )
            if has_substantive_output and all_packages_real and gap_hints:
                adjusted["score"] = max(
                    float(adjusted.get("score", 0.0) or 0.0),
                    config.critic_accept_threshold_knowledge_retriever,
                )
                adjusted["decision"] = "ACCEPT"
                adjusted["critique"] = (
                    "Adjusted for FAIR-DS/API coverage limits; real FAIR-DS packages were selected and "
                    "uncovered concepts were captured as metadata gaps."
                )
                adjusted["issues"] = []
                adjusted["improvement_ops"] = []
                return adjusted

        if node_key == "json_generator":
            metadata_json = state.get("artifacts", {}).get("metadata_json")
            if has_substantive_output and metadata_json:
                try:
                    metadata_payload = json.loads(metadata_json)
                except Exception:
                    metadata_payload = {}
                statistics = metadata_payload.get("statistics", {}) if isinstance(metadata_payload, dict) else {}
                total_fields = int(statistics.get("total_fields") or len(state.get("metadata_fields", []) or []))
                packages_used = metadata_payload.get("packages_used", []) if isinstance(metadata_payload, dict) else []
                if total_fields > 0 and not issues:
                    adjusted["score"] = max(
                        float(adjusted.get("score", 0.0) or 0.0),
                        config.critic_accept_threshold_json_generator,
                    )
                    adjusted["decision"] = "ACCEPT"
                    adjusted["critique"] = (
                        "Adjusted to FAIRiAgent's current output contract: ISA-structured metadata JSON "
                        f"was generated successfully with {total_fields} fields and "
                        f"{len(packages_used)} package(s)."
                    )
                    adjusted["issues"] = []
                    adjusted["improvement_ops"] = suggestions
                    return adjusted

        if has_substantive_output and selected_packages and not issues:
            if node_key == "knowledge_retriever":
                threshold = config.critic_accept_threshold_knowledge_retriever
            else:
                threshold = config.critic_accept_threshold_json_generator
            adjusted["score"] = max(float(adjusted.get("score", 0.0) or 0.0), threshold)
            adjusted["decision"] = "ACCEPT"
            adjusted["critique"] = (
                (critique + " " if critique and not critique_mentions_only_constraints else "")
                + "Adjusted for FAIR-DS/API coverage limits; unmet concepts were captured as metadata gaps."
            ).strip()
        return adjusted
