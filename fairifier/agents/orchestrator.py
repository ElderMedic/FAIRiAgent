"""
Orchestrator Agent - Controls the overall workflow and coordinates all agents.

The Orchestrator uses LLM for intelligent planning and adaptation (ReAct pattern).
It manages execution flow, calls Critic after each step, and makes decisions
based on feedback.
"""

import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from langsmith import traceable

from .base import BaseAgent
from .critic import CriticAgent
from ..models import FAIRifierState, ProcessingStatus
from ..config import config

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """
    Orchestrator Agent coordinates the entire FAIR metadata generation workflow.
    
    Responsibilities:
    - Plan and execute the workflow
    - Call agents in proper sequence
    - Invoke Critic after each step for quality evaluation
    - Handle retry logic based on Critic feedback
    - Escalate to human review when needed
    - Maintain execution history and reasoning chain
    """
    
    def __init__(self):
        super().__init__("Orchestrator")
        self.critic = CriticAgent()
        self.registered_agents = {}
        # Get retry limits from config (can be overridden by env vars)
        self.max_global_retries = config.max_global_retries
        self.max_step_retries = config.max_step_retries
        self.global_retry_count = 0
        
        # LLM is required for intelligent planning (no fallback)
        from ..utils.llm_helper import get_llm_helper
        self.llm_helper = get_llm_helper()
        
        logger.info("✅ Orchestrator Agent initialized with LLM for intelligent planning (required mode)")
    
    def register_agent(self, name: str, agent: BaseAgent):
        """Register an agent that can be called by the orchestrator."""
        self.registered_agents[name] = agent
        self.logger.info(f"Registered agent: {name}")
    
    @traceable(name="Orchestrator", tags=["agent", "orchestration"])
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """
        Execute the complete workflow with critic-in-the-loop.
        
        Workflow:
        1. Execute DocumentParser first to extract full document info
        2. Use LLM to plan workflow based on extracted information
        3. Execute remaining steps with Critic evaluation
        4. Adapt plan based on feedback
        5. Finalize and return results
        """
        self.log_execution(state, "🎯 Orchestrator starting workflow execution")
        
        # Initialize state
        if "execution_history" not in state:
            state["execution_history"] = []
        if "reasoning_chain" not in state:
            state["reasoning_chain"] = []
        if "context" not in state:
            state["context"] = {}
        
        # Reset global retry counter
        self.global_retry_count = 0
        
        # Step 1: Execute DocumentParser FIRST to get complete document info
        self.log_execution(state, "\n" + "="*70)
        self.log_execution(state, "📋 Step 1: DocumentParser (Pre-Planning)")
        self.log_execution(state, "   Extract complete information before planning")
        self.log_execution(state, "="*70)
        
        success = await self._execute_step_with_retry(state, "DocumentParser")
        if not success:
            self.log_execution(state, "❌ DocumentParser failed, cannot continue", "error")
            state["status"] = ProcessingStatus.FAILED.value
            return state
        
        # Step 2: Now use LLM to plan workflow based on COMPLETE document info
        self.log_execution(state, "\n" + "="*70)
        self.log_execution(state, "🧠 Orchestrator Planning Phase (Post-Parsing)")
        self.log_execution(state, "="*70)
        
        doc_info = state.get("document_info", {})
        execution_plan = await self._plan_workflow_with_llm(doc_info, state)
        
        self.log_execution(state, f"📋 LLM Execution Plan (based on extracted info):")
        self.log_execution(state, f"   Document type: {execution_plan.get('document_type', 'N/A')}")
        self.log_execution(state, f"   Research domain: {execution_plan.get('research_domain', 'N/A')}")
        self.log_execution(state, f"   Strategy: {execution_plan.get('strategy', 'standard')}")
        self.log_execution(state, f"   Reasoning: {execution_plan.get('reasoning', 'N/A')}")  # Full reasoning - no truncation
        
        state["execution_plan"] = execution_plan
        state["reasoning_chain"].append(f"Plan based on parsing: {execution_plan.get('reasoning', '')}")
        
        # Define remaining workflow steps
        remaining_steps = [
            ("KnowledgeRetriever", "Retrieve FAIR-DS knowledge and ontology terms"),
            ("JSONGenerator", "Generate FAIR-DS compatible metadata")
        ]
        
        # Execute remaining steps with critic review
        for step_name, step_description in remaining_steps:
            self.log_execution(state, f"\n{'='*70}")
            self.log_execution(state, f"📋 Step: {step_name}")
            self.log_execution(state, f"   {step_description}")
            self.log_execution(state, f"{'='*70}")
            
            # Execute step with retry logic
            success = await self._execute_step_with_retry(state, step_name)
            
            if not success:
                # Step failed after retries
                self.log_execution(
                    state,
                    f"❌ Step {step_name} failed after retries. Workflow cannot continue.",
                    "error"
                )
                state["status"] = ProcessingStatus.FAILED.value
                state["needs_human_review"] = True
                return state
        
        # All steps completed successfully
        self.log_execution(state, f"\n{'='*70}")
        self.log_execution(state, "✅ Workflow completed successfully!")
        self.log_execution(state, f"{'='*70}")
        
        state["status"] = ProcessingStatus.COMPLETED.value
        
        # Generate execution summary
        state["execution_summary"] = self._generate_execution_summary(state)
        
        return state
    
    async def _execute_step_with_retry(
        self, 
        state: FAIRifierState, 
        step_name: str
    ) -> bool:
        """
        Execute a single step with critic evaluation and retry logic.
        
        Returns:
            bool: True if step succeeded, False if failed after retries
        """
        agent = self.registered_agents.get(step_name)
        if not agent:
            self.log_execution(state, f"❌ Agent {step_name} not registered", "error")
            return False
        
        # Reset retry count for this step
        if "context" not in state:
            state["context"] = {}
        state["context"]["retry_count"] = 0
        
        # Use configurable max_step_retries
        max_step_retries = self.max_step_retries
        attempt = 0
        
        while attempt <= max_step_retries:
            attempt += 1
            self.global_retry_count += 1
            
            # Check global retry limit
            if self.global_retry_count > self.max_global_retries:
                self.log_execution(
                    state,
                    f"⚠️ Global retry limit ({self.max_global_retries}) exceeded. Escalating to human review.",
                    "warning"
                )
                state["needs_human_review"] = True
                
                # Check if step has already produced output
                # If output exists, accept it with low confidence instead of failing
                has_output = False
                if step_name == "JSONGenerator":
                    has_output = bool(state.get("artifacts", {}).get("metadata_json"))
                elif step_name == "DocumentParser":
                    has_output = bool(state.get("document_info"))
                elif step_name == "KnowledgeRetriever":
                    has_output = bool(state.get("knowledge_items"))
                
                if has_output:
                    self.log_execution(
                        state,
                        f"✅ {step_name} has produced output despite retry limit. Accepting with low confidence.",
                        "warning"
                    )
                    # Get last critic evaluation if available from history
                    execution_history = state.get("execution_history", [])
                    if execution_history:
                        last_eval = execution_history[-1].get("critic_evaluation", {})
                        confidence = last_eval.get("confidence", 0.3)
                    else:
                        confidence = 0.3
                    self.update_confidence(state, step_name.lower(), confidence)
                    return True
                else:
                    # No output produced, fail the step
                    return False
            
            # Log attempt
            if attempt == 1:
                self.log_execution(state, f"▶️  Executing {step_name}...")
            else:
                self.log_execution(state, f"🔄 Retry {attempt-1}/{max_step_retries} for {step_name}...")
            
            # Record execution start
            execution_record = {
                "agent_name": step_name,
                "attempt": attempt,
                "start_time": datetime.now().isoformat(),
                "end_time": None,
                "success": False,
                "critic_evaluation": None,
                "retry_reason": None
            }
            
            try:
                # Execute the agent
                state = await agent.execute(state)
                execution_record["success"] = True
                execution_record["end_time"] = datetime.now().isoformat()
                
            except Exception as e:
                self.log_execution(state, f"❌ Error in {step_name}: {str(e)}", "error")
                execution_record["success"] = False
                execution_record["end_time"] = datetime.now().isoformat()
                execution_record["error"] = str(e)
                state["execution_history"].append(execution_record)
                
                # Decide whether to retry on error
                if attempt < max_step_retries:
                    self.log_execution(state, f"🔄 Retrying due to error...", "warning")
                    state["context"]["retry_count"] = attempt
                    continue
                else:
                    self.log_execution(state, f"❌ Max retries reached after error", "error")
                    return False
            
            # Add execution record to history
            state["execution_history"].append(execution_record)
            
            # Call Critic to evaluate
            self.log_execution(state, f"🔍 Calling Critic to evaluate {step_name} output...")
            state = await self.critic.execute(state)
            
            # Get critic's decision - ALWAYS retrieve from history after Critic execution
            # Critic updates state["execution_history"][-1], so we must get it from there
            execution_history = state.get("execution_history", [])
            if execution_history:
                last_execution = execution_history[-1]
                critic_evaluation = last_execution.get("critic_evaluation", {})
            else:
                # Fallback if history is empty (shouldn't happen)
                critic_evaluation = execution_record.get("critic_evaluation", {})
            
            decision = critic_evaluation.get("decision", "ACCEPT")
            confidence = critic_evaluation.get("confidence", 0.0)
            feedback = critic_evaluation.get("feedback", "No feedback")
            issues = critic_evaluation.get("issues", [])
            suggestions = critic_evaluation.get("suggestions", [])
            
            self.log_execution(
                state,
                f"📊 Critic Decision: {decision} (confidence: {confidence:.2f})\n"
                f"   Feedback: {feedback if feedback else 'N/A'}\n"  # Full feedback - no truncation
                f"   Current attempt: {attempt}/{max_step_retries}"
            )
            
            if issues:
                self.log_execution(state, f"   Issues identified: {len(issues)}")
                for i, issue in enumerate(issues, 1):  # ALL issues - no truncation
                    self.log_execution(state, f"      {i}. {issue}")
            
            # Decide next action based on critic's decision
            if decision == "ACCEPT":
                # Step succeeded, move to next
                self.log_execution(state, f"✅ {step_name} completed successfully")
                
                # Update overall confidence
                self.update_confidence(state, step_name.lower(), confidence)
                
                # Clear context for next step
                state["context"]["retry_count"] = 0
                state["context"]["critic_feedback"] = None
                
                return True
                
            elif decision == "RETRY":
                self.log_execution(
                    state,
                    f"🔄 RETRY decision received for {step_name} (attempt {attempt}/{max_step_retries})",
                    "warning"
                )
                
                if attempt < max_step_retries:
                    # Prepare feedback for retry
                    self.log_execution(
                        state,
                        f"🔄 {step_name} needs improvement. Preparing retry with feedback...",
                        "warning"
                    )
                    
                    # Update retry count in context
                    state["context"]["retry_count"] = attempt
                    
                    # Store retry reason in the execution record (which is in history)
                    if execution_history:
                        last_execution = execution_history[-1]
                        last_execution["retry_reason"] = str(feedback) if feedback else "Retry requested by Critic"
                    
                    # Prepare state with critic feedback
                    state = await self.critic.provide_feedback_to_agent(
                        step_name,
                        critic_evaluation,
                        state
                    )
                    
                    # Log suggestions
                    suggestions = critic_evaluation.get("suggestions", [])
                    if suggestions:
                        self.log_execution(state, "💡 Critic suggestions:")
                        for i, suggestion in enumerate(suggestions, 1):
                            self.log_execution(state, f"      {i}. {suggestion}")
                    
                    # Continue to next retry attempt - this will loop back to execute the agent again
                    self.log_execution(
                        state,
                        f"🔄 Continuing to retry loop (will execute {step_name} again)...",
                        "warning"
                    )
                    continue
                else:
                    # Max retries reached
                    self.log_execution(
                        state,
                        f"⚠️ {step_name} reached maximum retries ({max_step_retries}). Escalating...",
                        "warning"
                    )
                    state["needs_human_review"] = True
                    
                    # Accept with low confidence
                    self.update_confidence(state, step_name.lower(), confidence)
                    return True
                    
            elif decision == "ESCALATE":
                # Critical issues, need human review
                self.log_execution(
                    state,
                    f"🚨 {step_name} requires human review. Escalating...",
                    "warning"
                )
                state["needs_human_review"] = True
                
                # Update confidence with escalation score
                self.update_confidence(state, step_name.lower(), confidence)
                
                # Continue workflow but flag for review
                return True
            
            else:
                # Unknown decision, accept by default
                self.log_execution(
                    state,
                    f"⚠️ Unknown critic decision: {decision}. Accepting by default.",
                    "warning"
                )
                return True
        
        # Should not reach here
        return False
    
    @traceable(name="Orchestrator.PlanWorkflow")
    async def _plan_workflow_with_llm(self, doc_info: Dict[str, Any], state: FAIRifierState) -> Dict[str, Any]:
        """
        Use LLM to analyze extracted document info and plan the execution strategy.
        
        This implements the ReAct pattern where the Orchestrator "thinks" before acting.
        Now receives COMPLETE document info instead of just preview.
        """
        planning_prompt = f"""You are an intelligent workflow orchestrator for FAIR metadata generation.

**Extracted Document Information (complete):**
{json.dumps(doc_info, indent=2, ensure_ascii=False)}  # Complete info - no truncation

**Your task:** Analyze this document and plan the optimal execution strategy.

**Think step by step:**
1. What type of document is this? (research paper, dataset description, protocol, etc.)
2. What research domain does it belong to? (genomics, ecology, chemistry, etc.)
3. What kind of metadata extraction will be needed?
4. What FAIR-DS packages are likely relevant?
5. What potential challenges might arise?

**Available workflow steps:**
1. DocumentParser: Extract structured information
2. KnowledgeRetriever: Get relevant FAIR-DS terms and packages
3. JSONGenerator: Generate FAIR-DS compatible metadata

**Plan the strategy:**
- What should each step focus on?
- What information is critical to extract?
- Which FAIR-DS packages are likely needed?
- Any special considerations?

Return JSON as in following example format:
{{
  "document_type": "research_paper|dataset|protocol|other",
  "research_domain": "genomics|metagenomics|ecology|chemistry|...",
  "strategy": "standard|specialized|...",
  "key_focus_areas": ["area1", "area2", ...],
  "potential_challenges": ["challenge1", ...],
  "reasoning": "your step-by-step analysis",
  "special_instructions": {{
    "DocumentParser": "focus on...",
    "KnowledgeRetriever": "prioritize...",
    "JSONGenerator": "ensure..."
  }}
}}"""

        from langchain_core.messages import HumanMessage, SystemMessage
        
        messages = [
            SystemMessage(content="You are an intelligent workflow planning agent. Analyze documents and create optimal execution plans."),
            HumanMessage(content=planning_prompt)
        ]
        
        # LLM planning is required - no fallback
        response = await self.llm_helper._call_llm(messages, operation_name="Orchestrator Plan Workflow")
        content = response.content
        
        # Parse JSON response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        plan = json.loads(content)
        
        logger.info(f"✅ Orchestrator LLM created execution plan: {plan.get('strategy', 'standard')}")
        logger.info(f"   Document type: {plan.get('document_type')}")
        logger.info(f"   Research domain: {plan.get('research_domain')}")
        
        return plan
    
    def _generate_execution_summary(self, state: FAIRifierState) -> Dict[str, Any]:
        """Generate a summary of the execution."""
        execution_history = state.get("execution_history", [])
        
        summary = {
            "total_steps": len(execution_history),
            "successful_steps": sum(1 for e in execution_history if e.get("success")),
            "failed_steps": sum(1 for e in execution_history if not e.get("success")),
            "total_retries": self.global_retry_count,
            "steps_requiring_retry": sum(1 for e in execution_history if e.get("attempt", 1) > 1),
            "critic_evaluations": {},
            "overall_confidence": state.get("confidence_scores", {}).get("overall", 0.0),
            "needs_human_review": state.get("needs_human_review", False)
        }
        
        # Summarize critic evaluations
        for execution in execution_history:
            agent_name = execution.get("agent_name")
            critic_eval = execution.get("critic_evaluation", {})
            
            if agent_name and critic_eval:
                if agent_name not in summary["critic_evaluations"]:
                    summary["critic_evaluations"][agent_name] = []
                
                summary["critic_evaluations"][agent_name].append({
                    "attempt": execution.get("attempt", 1),
                    "decision": critic_eval.get("decision"),
                    "confidence": critic_eval.get("confidence"),
                    "issues_count": len(critic_eval.get("issues", []))
                })
        
        # Calculate average confidence
        confidence_scores = state.get("confidence_scores", {})
        if confidence_scores:
            avg_confidence = sum(confidence_scores.values()) / len(confidence_scores)
            summary["average_confidence"] = avg_confidence
            state["confidence_scores"]["overall"] = avg_confidence
        
        return summary
    
    async def handle_human_feedback(
        self, 
        state: FAIRifierState, 
        step_name: str, 
        feedback: Dict[str, Any]
    ) -> FAIRifierState:
        """
        Handle human feedback for a specific step.
        This can be used for human-in-the-loop scenarios.
        
        Args:
            state: Current state
            step_name: Name of the step receiving feedback
            feedback: Human feedback with corrections/improvements
        
        Returns:
            Updated state
        """
        if "human_interventions" not in state:
            state["human_interventions"] = {}
        
        state["human_interventions"][step_name] = {
            "timestamp": datetime.now().isoformat(),
            "feedback": feedback,
            "applied": False
        }
        
        self.log_execution(
            state,
            f"👤 Human feedback received for {step_name}"
        )
        
        # Apply feedback to state
        if "corrections" in feedback:
            self._apply_human_corrections(state, step_name, feedback["corrections"])
            state["human_interventions"][step_name]["applied"] = True
        
        return state
    
    def _apply_human_corrections(
        self, 
        state: FAIRifierState, 
        step_name: str, 
        corrections: Dict[str, Any]
    ):
        """Apply human corrections to the state."""
        if step_name == "DocumentParser":
            doc_info = state.get("document_info", {})
            doc_info.update(corrections)
            state["document_info"] = doc_info
            
        elif step_name == "JSONGenerator":
            # Update specific metadata fields
            metadata_fields = state.get("metadata_fields", [])
            for correction_field, correction_value in corrections.items():
                for field in metadata_fields:
                    if field.get("field_name") == correction_field:
                        field["value"] = correction_value
                        field["origin"] = "human_correction"
                        field["confidence"] = 1.0
                        break
            state["metadata_fields"] = metadata_fields
        
        self.log_execution(
            state,
            f"✅ Applied {len(corrections)} human corrections to {step_name}"
        )

