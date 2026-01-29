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
from ..utils.llm_helper import get_llm_helper

logger = logging.getLogger(__name__)


def safe_json_parse(raw: str) -> Optional[Dict[str, Any]]:
    """Parse JSON content with support for fenced code blocks and various formats."""
    if not raw:
        return None
    
    snippet = raw.strip()
    
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
            "KnowledgeRetriever": "knowledge_retriever",
            "JSONGenerator": "json_generator",
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
        else:
            context = "No context available."
        
        return await self._judge_with_rubric(node_key, context)
    
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
        state["context"]["critic_feedback"] = {
            "decision": evaluation.get("decision", "ACCEPT"),
            "score": evaluation.get("score", 0.0),
            "critique": evaluation.get("critique", ""),
            "issues": evaluation.get("issues", []),
            "suggestions": evaluation.get("improvement_ops", []),
            "timestamp": datetime.now().isoformat()
        }
        
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

    def _build_parsing_context(self, state: FAIRifierState) -> str:
        doc_info = state.get("document_info", {})
        retry_count = state.get("context", {}).get("retry_count", 0)
        planner_guidance = state.get("agent_guidance", {}).get("DocumentParser")
        return (
            f"**Parsed Document Info (attempt {retry_count + 1}/{self.max_retries_per_step}):**\n"
            f"{json.dumps(doc_info, indent=2, ensure_ascii=False)}\n\n"
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
        # Get domain from either research_domain or scientific_domain
        domain = doc_info.get("research_domain") or doc_info.get("scientific_domain")
        
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
                "limitation_note": limitation_note,
                "evaluation_guidance": (
                    "IMPORTANT: Evaluate the agent's work within the constraints of what the API actually provides. "
                    "If the API only has limited packages available, the agent cannot retrieve packages that don't exist. "
                    "Judge based on whether the agent made optimal use of available resources, not whether it retrieved "
                    "packages that are unavailable in the API."
                ) if len(available_packages) <= 1 else None
            },
            "retrieval_results": {
                "total_terms_retrieved": len(retrieved),
                "packages_selected": packages_found,
                "terms_by_isa_sheet": self._group_terms_by_sheet(retrieved),
                "sample_terms": retrieved[:5] if retrieved else []  # Show first 5 as examples
            },
            "complete_terms_list": retrieved  # Full list for detailed inspection
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
        evidence_coverage = 0
        if metadata_fields:
            evidence_coverage = (
                sum(1 for f in metadata_fields if f.get("evidence")) / len(metadata_fields)
            )
        summary = {
            "document_overview": doc_info,
            "planner_guidance": planner_guidance,
            "field_count": len(metadata_fields),
            "evidence_coverage": evidence_coverage,
            "fields": metadata_fields,
        }
        return json.dumps(summary, indent=2, ensure_ascii=False)

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
            f"**OUTPUT FORMAT - CRITICAL (STANDARD v1.0):**\n"
            f"Wrap your JSON in markdown code blocks:\n\n"
            f"```json\n"
            f"{{\n"
            f'  "score": 0.0-1.0,\n'
            f'  "critique": "brief summary < 200 chars",\n'
            f'  "issues": ["issue1 < 100 chars"],\n'
            f'  "suggestions": ["suggestion1 < 150 chars"]\n'
            f"}}\n"
            f"```\n\n"
            f"REQUIREMENTS:\n"
            f"- Line 1: ```json (alone)\n"
            f"- Lines 2-N: Valid JSON only\n"
            f"- Line N+1: ``` (alone)\n"
            f"- NO text before/after block\n"
            f"- NO comments in JSON"
        )
        
        from langchain_core.messages import HumanMessage
        response = await self.llm_helper._call_llm(
            [HumanMessage(content=prompt)],
            operation_name=f"Critic.{node_key}"
        )
        content = getattr(response, "content", "") if response else ""
        
        # Debug: Log response for troubleshooting
        logger.debug(f"Critic LLM response length: {len(content)} chars")
        logger.debug(f"Critic LLM response preview: {content[:500]}")
        
        parsed = safe_json_parse(content)
        if not parsed:
            logger.error(f"Failed to parse Critic response. Content preview: {content[:1000]}")
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
            "improvement_ops": parsed.get("improvement_ops", []),
            "evidence": parsed.get("evidence", []),
            "critique": parsed.get("critique", "")
        }


