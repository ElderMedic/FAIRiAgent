"""
Critic Agent - Evaluates the quality of each step's output and provides feedback.

The Critic Agent reviews outputs from other agents and decides whether they meet
quality standards, need improvement, or should be accepted.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import yaml
from langsmith import traceable

from .base import BaseAgent
from ..models import FAIRifierState
from ..config import config
from ..utils.llm_helper import get_llm_helper, normalize_llm_response_content
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class CriticEvaluation(BaseModel):
    """Schema for the Critic LLM evaluation output."""
    score: float = Field(description="Confidence score between 0.0 and 1.0")
    critique: str = Field(description="A short narrative explanation of the decision (< 200 chars)")
    issues: List[str] = Field(default_factory=list, description="List of identified issues (< 100 chars each)")
    suggestions: List[str] = Field(default_factory=list, description="Actionable steps to fix issues (< 150 chars each)")

def safe_json_parse(raw: Any) -> Optional[Dict[str, Any]]:
    """Parse JSON content with support for fenced code blocks and various formats."""
    if not raw:
        return None
    
    snippet = normalize_llm_response_content(raw).strip()
    
    # Strategy 1: Remove markdown code fences
    if "```json" in snippet:
        snippet = snippet.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in snippet:
        # Handle generic code blocks
        parts = snippet.split("```")
        if len(parts) >= 3:
            snippet = parts[1].strip()
        elif snippet.startswith("```") and snippet.endswith("```"):
            snippet = snippet[3:-3].strip()
    
    # Strategy 2: Direct parse
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        pass
    
    # Strategy 3: Extract first complete JSON object
    start = snippet.find("{")
    if start != -1:
        brace_count = 0
        in_string = False
        escape_next = False
        
        for i in range(start, len(snippet)):
            char = snippet[i]
            
            if escape_next:
                escape_next = False
                continue
            
            if char == '\\':
                escape_next = True
                continue
            
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            
            if not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        try:
                            return json.loads(snippet[start:i+1])
                        except json.JSONDecodeError:
                            pass
                        break
    
    return None


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
        elif node_key == "json_generator":
            context = self._build_generation_context(state)
        elif node_key == "isa_value_mapper":
            context = self._build_isa_mapper_context(state)
        else:
            context = "No context available."
        
        evaluation = await self._judge_with_rubric(node_key, context)
        evaluation = self._postprocess_api_constrained_evaluation(node_key, evaluation, state)
        return self._stabilize_invalid_critic_output(node_key, evaluation, state)
    
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
        
        Note: Retry count is managed by the evaluate nodes, not here.
        """
        if "context" not in state:
            state["context"] = {}
        
        # Don't increment retry_count here - it's managed by evaluate nodes
        
        # Store critic feedback (use .get() for safe access)
        feedback_payload = {
            "decision": evaluation.get("decision", "ACCEPT"),
            "score": evaluation.get("score", 0.0),
            "critique": evaluation.get("critique", ""),
            "issues": evaluation.get("issues", []),
            "suggestions": evaluation.get("improvement_ops", []),
            "timestamp": datetime.now().isoformat(),
            "target_agent": agent_name,
        }
        state["context"]["critic_feedback"] = feedback_payload
        state["context"].setdefault("critic_feedback_by_agent", {})[agent_name] = feedback_payload
        
        # Manage historical guidance with size limits to prevent token waste
        history = state["context"].setdefault("critic_guidance_history", {})
        history.setdefault(agent_name, [])
        
        # Add new improvement ops (deduplicated)
        for op in evaluation.get("improvement_ops", []):
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

        return evaluation

    def _build_parsing_context(self, state: FAIRifierState) -> str:
        doc_info = state.get("document_info", {})
        retry_count = state.get("context", {}).get("retry_count", 0)
        planner_guidance = state.get("agent_guidance", {}).get("DocumentParser")
        return (
            f"**Parsed Document Info (attempt {retry_count + 1}/{self.max_retries_per_step}):**\n"
            f"{json.dumps(self._compact_document_info(doc_info), indent=2, ensure_ascii=False)}\n\n"
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
                "available_packages_in_api": available_packages[:15],
                "total_packages_available": len(available_packages),
                "candidate_packages_considered": api_capabilities.get("candidate_packages_considered", [])[:15],
                "selected_packages": api_capabilities.get("selected_packages", [])[:10],
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
        planner_guidance = state.get("agent_guidance", {}).get("JSONGenerator")
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
                "ISA-structured metadata JSON artifact with provenance-rich fields. "
                "Planner guidance may request richer JSON-LD or linked-data embellishments, "
                "but those are stretch goals, not minimum acceptance criteria."
            ),
            "document_overview": self._compact_document_info(doc_info),
            "planner_guidance": planner_guidance,
            "field_count": len(metadata_fields),
            "evidence_coverage": evidence_coverage,
            "field_summary": self._summarize_metadata_fields(metadata_fields),
            "metadata_json_summary": metadata_json_summary,
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
                        sheet_summaries[sheet_name] = {
                            "columns": cols[:10] if isinstance(cols, list) else [],
                            "row_count": n_rows,
                            "sample_row": rows[0] if n_rows > 0 else [],
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
                "Every sheet (investigation, study, assay, dataFile) should have at least "
                "the mandatory columns populated."
            ),
            "sheets_populated": sheets_populated,
            "total_rows": row_count,
            "sheet_summaries": sheet_summaries,
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
            f"**CRITICAL CONSTRAINTS:**\n"
            f"1. Maximum response size: 3,000 characters\n"
            f"2. Critique: < 200 characters\n"
            f"3. Each issue: < 100 characters\n"
            f"4. Each suggestion: < 150 characters\n\n"
            f"# Node: {node_key}\n"
            f"Goal: {node_rules.get('description', '')}\n\n"
            f"## Evaluation Context\n{evaluation_content}\n\n"
            f"## Rubric\n{rubric_block}\n\n"
            f"**OUTPUT FORMAT:**\n"
            f"Please provide your evaluation according to the expected schema."
        )
        
        from langchain_core.messages import HumanMessage
        
        try:
            llm = self.llm_helper.get_llm()
            structured_llm = llm.with_structured_output(CriticEvaluation)
            result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
            parsed = result.model_dump()
        except Exception as e:
            logger.warning(f"Structured output parsing failed: {e}. Falling back to standard LLM call.")
            # Prompt adjustment for standard fallback
            fallback_prompt = prompt + (
                "\n\n**CRITICAL (STANDARD v1.0):**\n"
                "Wrap your JSON in markdown code blocks:\n"
                "```json\n"
                "{\n"
                '  "score": 0.0-1.0,\n'
                '  "critique": "brief summary < 200 chars",\n'
                '  "issues": ["issue1 < 100 chars"],\n'
                '  "suggestions": ["suggestion1 < 150 chars"]\n'
                "}\n"
                "```"
            )
            response = await self.llm_helper._call_llm(
                [HumanMessage(content=fallback_prompt)],
                operation_name=f"Critic.{node_key}"
            )
            content = getattr(response, "content", "") if response else ""
            parsed = safe_json_parse(content)
        
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
        from ..config import config
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

        selected_packages = state.get("selected_packages", []) or []
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
