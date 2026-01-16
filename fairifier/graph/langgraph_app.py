"""
LangGraph App for FAIRifier - Explicit node-based workflow.

This implements a proper LangGraph application where:
- Each agent is an explicit node
- Critic evaluates outputs and routes via conditional edges
- Retry logic is handled through state management
- Planning is a separate node that uses LLM for workflow strategy
"""

import logging
import json
from typing import Dict, Any, Literal, Optional, Tuple
from datetime import datetime
from langsmith import traceable

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from ..models import FAIRifierState, ProcessingStatus
from ..agents.base import BaseAgent
from ..agents.document_parser import DocumentParserAgent
from ..agents.knowledge_retriever import KnowledgeRetrieverAgent
from ..agents.json_generator import JSONGeneratorAgent
from ..agents.critic import CriticAgent
from ..config import config
from ..utils.llm_helper import get_llm_helper
from ..utils.report_generator import WorkflowReportGenerator
from ..services.mineru_client import MinerUClient, MinerUConversionError
from ..services.confidence_aggregator import aggregate_confidence

logger = logging.getLogger(__name__)


class FAIRifierLangGraphApp:
    """LangGraph application for FAIR metadata generation."""
    
    def __init__(self):
        """Initialize the LangGraph app with all agents."""
        # Initialize agents
        self.document_parser = DocumentParserAgent()
        self.knowledge_retriever = KnowledgeRetrieverAgent()
        self.json_generator = JSONGeneratorAgent()
        self.critic = CriticAgent()
        self.llm_helper = get_llm_helper()
        self.mineru_client = self._initialize_mineru_client()
        
        # Initialize retry counters (like old Orchestrator)
        self.global_retry_count = 0
        self.max_global_retries = config.max_global_retries
        self.max_step_retries = config.max_step_retries
        
        # Multi-turn reflection configuration
        # Each retry attempt can have multiple reflection iterations
        self.max_reflection_iters = getattr(config, 'max_reflection_iters', 3)
        
        # Initialize checkpointer
        self.checkpointer = MemorySaver()
        
        # Build the graph
        graph_structure = self._build_graph_structure()
        self.workflow = graph_structure.compile(checkpointer=self.checkpointer)
        
        logger.info("✅ LangGraph app initialized")
    
    def _initialize_mineru_client(self) -> Optional[MinerUClient]:
        """Instantiate MinerU client if configuration is enabled."""
        if not (config.mineru_enabled and config.mineru_server_url):
            return None
        try:
            client = MinerUClient(
                cli_path=config.mineru_cli_path,
                server_url=config.mineru_server_url,
                backend=config.mineru_backend,
                timeout_seconds=config.mineru_timeout_seconds,
            )
            if client.is_available():
                logger.info("MinerU client enabled for LangGraph document loading.")
                return client
            logger.warning("MinerU CLI not available; LangGraph will fall back to PyMuPDF.")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to initialize MinerU client: %s", exc)
        return None
    
    async def _execute_agent_with_retry(
        self,
        state: FAIRifierState,
        agent: BaseAgent,
        agent_name: str,
        check_output_fn
    ) -> FAIRifierState:
        """
        Execute an agent with multi-turn self-reflection and retry logic.
        
        Architecture:
        - Outer loop: retry attempts (full re-execution)
        - Inner loop: reflection iterations (iterative refinement within same attempt)
        
        Flow per attempt:
        1. Agent executes (or revises if reflection_iter > 0)
        2. Critic evaluates
        3. If ACCEPT: done
        4. If not ACCEPT and reflection_iters left: provide feedback, loop back to step 1
        5. If not ACCEPT and no reflection_iters left: increment retry, start new attempt
        
        Args:
            state: Current workflow state
            agent: Agent instance to execute
            agent_name: Name for logging
            check_output_fn: Function to check if agent produced usable output
            
        Returns:
            Updated state after execution (with or without retries)
        """
        if "execution_history" not in state:
            state["execution_history"] = []
        if "context" not in state:
            state["context"] = {}
        
        # Initialize reflection tracking
        if "reflection_trajectory" not in state:
            state["reflection_trajectory"] = {}
        state["reflection_trajectory"][agent_name] = []
        
        # Outer retry loop (full re-execution attempts)
        for attempt in range(1, self.max_step_retries + 2):  # +2 = initial + max_retries
            # Check global retry limit
            if self.global_retry_count >= self.max_global_retries:
                logger.warning(f"⚠️ Global retry limit ({self.max_global_retries}) reached")
                if check_output_fn(state):
                    logger.warning(f"   But {agent_name} has usable output - accepting")
                    state["needs_human_review"] = True
                    break
                else:
                    logger.error(f"   And {agent_name} has no usable output - failing")
                    state["errors"] = state.get("errors", []) + [f"{agent_name} failed: global retry limit reached"]
                    break
            
            # Log attempt
            if attempt == 1:
                logger.info(f"▶️  Executing {agent_name}")
            else:
                logger.info(f"🔄 Retry {attempt-1}/{self.max_step_retries} for {agent_name}")
                self.global_retry_count += 1
            
            # Set retry context for agent
            state["context"]["retry_count"] = attempt - 1
            
            # Track final decision for this attempt
            final_decision = "ACCEPT"
            final_score = 0.0
            
            # Inner reflection loop (iterative refinement within same attempt)
            for reflection_iter in range(self.max_reflection_iters):
                state["context"]["reflection_iter"] = reflection_iter
                state["context"]["is_revision"] = reflection_iter > 0
                
                # Create execution record
                execution_record = {
                    "agent_name": agent_name,
                    "attempt": attempt,
                    "reflection_iter": reflection_iter,
                    "start_time": datetime.now().isoformat(),
                    "end_time": None,
                    "success": False,
                    "critic_evaluation": None,
                    "is_revision": reflection_iter > 0
                }
                
                try:
                    # Log reflection iteration
                    if reflection_iter > 0:
                        logger.info(f"   🔄 Reflection {reflection_iter}/{self.max_reflection_iters-1}: {agent_name} refining output...")
                    
                    # Execute agent (initial or revision)
                    state = await agent.execute(state)
                    execution_record["success"] = True
                    execution_record["end_time"] = datetime.now().isoformat()
                    
                except Exception as e:
                    logger.error(f"❌ {agent_name} error (reflection {reflection_iter}): {str(e)}")
                    execution_record["success"] = False
                    execution_record["end_time"] = datetime.now().isoformat()
                    execution_record["error"] = str(e)
                    state["execution_history"].append(execution_record)
                    
                    # On error, break reflection loop and try next attempt
                    final_decision = "ERROR"
                    break
                
                # Add execution record
                state["execution_history"].append(execution_record)
                
                # Call Critic
                if reflection_iter == 0:
                    logger.info(f"🔍 Critic evaluating {agent_name}...")
                else:
                    logger.info(f"   🔍 Critic re-evaluating after reflection {reflection_iter}...")
                state = await self.critic.execute(state)
                
                # Get Critic decision
                last_execution = state["execution_history"][-1]
                critic_eval = last_execution.get("critic_evaluation", {})
                final_decision = critic_eval.get("decision", "ACCEPT")
                final_score = critic_eval.get("score", 0.0)
                
                # Record reflection trajectory
                state["reflection_trajectory"][agent_name].append({
                    "attempt": attempt,
                    "reflection_iter": reflection_iter,
                    "decision": final_decision,
                    "score": final_score,
                    "issues_count": len(critic_eval.get("issues", [])),
                    "timestamp": datetime.now().isoformat()
                })
                
                logger.info(
                    f"   📊 Critic: {final_decision} (score: {final_score:.2f}, "
                    f"attempt: {attempt}/{self.max_step_retries + 1}, "
                    f"reflection: {reflection_iter}/{self.max_reflection_iters-1})"
                )
                
                if final_decision == "ACCEPT":
                    logger.info(f"✅ {agent_name} completed successfully (score {final_score:.2f} >= accept threshold)")
                    break  # Exit reflection loop
                
                # Check if more reflections are allowed
                if reflection_iter < self.max_reflection_iters - 1:
                    # Provide feedback for next reflection iteration
                    logger.info(
                        f"   🔄 {agent_name} needs improvement (score: {final_score:.2f}), "
                        f"starting reflection {reflection_iter + 1}..."
                    )
                    state = await self.critic.provide_feedback_to_agent(agent_name, critic_eval, state)
                else:
                    # Max reflections reached for this attempt
                    logger.info(
                        f"   ⚠️ Max reflections ({self.max_reflection_iters}) reached for attempt {attempt}, "
                        f"final score: {final_score:.2f}"
                    )
            
            # Clear reflection context
            state["context"]["reflection_iter"] = 0
            state["context"]["is_revision"] = False
            
            # Check if we should exit retry loop
            if final_decision == "ACCEPT":
                break  # Success, exit retry loop
            
            if final_decision == "ERROR":
                if attempt <= self.max_step_retries:
                    continue  # Try next attempt on error
                else:
                    break  # Max retries reached
            
            # Handle non-ACCEPT after all reflections
            if attempt > self.max_step_retries:
                # Max retries reached - check if we have usable output
                if check_output_fn(state):
                    logger.warning(
                        f"⚠️ Max retries reached ({attempt-1}/{self.max_step_retries}) "
                        f"but {agent_name} has usable output - accepting with review flag\n"
                        f"  Final Critic decision: {final_decision} (score: {final_score:.2f})\n"
                        f"  Total reflections: {len(state['reflection_trajectory'][agent_name])}\n"
                        f"  Note: Workflow continues because output is usable, but needs human review"
                    )
                    state["needs_human_review"] = True
                    break
                else:
                    logger.error(
                        f"❌ Max retries reached ({attempt-1}/{self.max_step_retries}) "
                        f"with no usable output from {agent_name}\n"
                        f"  Final Critic decision: {final_decision} (score: {final_score:.2f})\n"
                        f"  Total reflections: {len(state['reflection_trajectory'][agent_name])}\n"
                        f"  Workflow will continue but may fail at finalization"
                    )
                    break
            else:
                # More retries available - prepare for next attempt
                logger.info(
                    f"🔄 {agent_name} did not reach ACCEPT after {self.max_reflection_iters} reflections "
                    f"(score: {final_score:.2f}), starting retry {attempt}/{self.max_step_retries}..."
                )
                state = await self.critic.provide_feedback_to_agent(agent_name, critic_eval, state)
        
        return state
    
    def get_graph_without_checkpointer(self):
        """Get a compiled graph without checkpointer for LangGraph Studio."""
        # Build graph structure without checkpointer
        workflow = self._build_graph_structure()
        # Compile without checkpointer (LangGraph API handles persistence)
        return workflow.compile()
    
    def _build_graph_structure(self) -> StateGraph:
        """Build LangGraph workflow with Orchestrator-style coordination."""
        workflow = StateGraph(FAIRifierState)
        
        # Simplified workflow: Read file, then Orchestrator handles everything
        workflow.add_node("read_file", self._read_file_node)
        workflow.add_node("orchestrate", self._orchestrate_all_agents_node)
        workflow.add_node("finalize", self._finalize_node)
        
        # Set entry point
        workflow.set_entry_point("read_file")
        
        # Simple linear flow
        workflow.add_edge("read_file", "orchestrate")
        workflow.add_edge("orchestrate", "finalize")
        workflow.add_edge("finalize", END)
        
        return workflow  # Return uncompiled StateGraph
    
    @traceable(name="Orchestrate", tags=["workflow", "orchestration"])
    async def _orchestrate_all_agents_node(self, state: FAIRifierState) -> FAIRifierState:
        """
        Orchestrate all agents with Critic-in-the-loop (like old OrchestratorAgent).
        
        This node coordinates:
        1. DocumentParser → Critic → (retry if needed)
        2. Planner (based on parsed info)
        3. KnowledgeRetriever → Critic → (retry if needed)
        4. JSONGenerator → Critic → (retry if needed)
        
        Benefits:
        - Global coordination and visibility
        - Unified retry management
        - Can adapt strategy based on intermediate results
        """
        logger.info("🎯 Orchestrator coordinating all agents")
        
        # Reset global retry counter for this run
        self.global_retry_count = 0
        
        # Step 1: Parse Document
        logger.info("\n" + "="*70)
        logger.info("📋 Step 1: DocumentParser")
        logger.info("="*70)
        state = await self._execute_agent_with_retry(
            state, self.document_parser, "DocumentParser",
            lambda s: s.get("document_info", {}) and len(s["document_info"]) > 3
        )
        
        # Step 2: Plan workflow based on parsed info
        logger.info("\n" + "="*70)
        logger.info("🧠 Step 2: Planning workflow strategy")
        logger.info("="*70)
        state = await self._plan_workflow_internal(state)
        
        # Step 3: Retrieve Knowledge
        logger.info("\n" + "="*70)
        logger.info("🔍 Step 3: KnowledgeRetriever")
        logger.info("="*70)
        state = await self._execute_agent_with_retry(
            state, self.knowledge_retriever, "KnowledgeRetriever",
            lambda s: s.get("retrieved_knowledge", []) and len(s["retrieved_knowledge"]) > 0
        )
        
        # Step 4: Generate JSON
        logger.info("\n" + "="*70)
        logger.info("📝 Step 4: JSONGenerator")
        logger.info("="*70)
        state = await self._execute_agent_with_retry(
            state, self.json_generator, "JSONGenerator",
            lambda s: s.get("metadata_fields", []) and len(s["metadata_fields"]) > 0
        )
        
        logger.info("\n" + "="*70)
        logger.info(f"✅ Orchestration complete (global retries used: {self.global_retry_count}/{self.max_global_retries})")
        logger.info("="*70)
        
        return state
    
    async def _plan_workflow_internal(self, state: FAIRifierState) -> FAIRifierState:
        """Internal planning (part of orchestration)."""
        # This is the same as the old _plan_workflow_node logic
        return await self._plan_workflow_node(state)
    
    @traceable(name="ReadFile", tags=["workflow", "io"])
    async def _read_file_node(self, state: FAIRifierState) -> FAIRifierState:
        """Read file content from disk."""
        logger.info("📄 Reading file content")
        state["status"] = ProcessingStatus.PARSING.value
        
        try:
            document_path = state.get("document_path", "")
            output_dir = state.get("output_dir")  # Get output dir from state
            
            text, conversion_info = self._read_document_content(document_path, output_dir)
            logger.info(f"✅ Loaded {len(text)} characters from document")
            
            state["document_content"] = text
            state["document_conversion"] = conversion_info
            
        except Exception as e:
            logger.error(f"❌ Failed to read file: {e}")
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"File reading error: {str(e)}")
            state["document_content"] = ""
        
        return state
    
    def _read_document_content(
        self, 
        document_path: str,
        output_dir: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Read content using MinerU when available."""
        conversion_info: Dict[str, Any] = {}
        if document_path.endswith(".pdf"):
            if self.mineru_client:
                try:
                    # Use output_dir for MinerU artifacts if provided
                    mineru_output = None
                    if output_dir:
                        from pathlib import Path
                        doc_name = Path(document_path).stem
                        mineru_output = Path(output_dir) / f"mineru_{doc_name}"
                        logger.info(f"MinerU will save artifacts to: {mineru_output}")
                    
                    conversion = self.mineru_client.convert_document(
                        document_path,
                        output_dir=mineru_output
                    )
                    conversion_info = conversion.to_dict()
                    logger.info("MinerU conversion successful: %s", conversion.markdown_path)
                    logger.info(f"MinerU artifacts: {conversion.output_dir}")
                    if conversion.images_dir:
                        logger.info(f"MinerU images: {conversion.images_dir}")
                    return conversion.markdown_text, conversion_info
                except MinerUConversionError as exc:
                    logger.warning("MinerU conversion failed (%s). Falling back to PyMuPDF.", exc)
            import fitz  # PyMuPDF
            doc = fitz.open(document_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text, conversion_info
        
        with open(document_path, "r", encoding="utf-8") as file:
            text = file.read()
        return text, conversion_info
    
    @traceable(name="PlanWorkflow", tags=["workflow", "planning"])
    async def _plan_workflow_node(self, state: FAIRifierState) -> FAIRifierState:
        """Plan workflow strategy using LLM based on document content."""
        logger.info("🧠 Planning workflow strategy")
        
        # Initialize state fields if needed
        if "execution_history" not in state:
            state["execution_history"] = []
        if "reasoning_chain" not in state:
            state["reasoning_chain"] = []
        
        try:
            # Get parsed document info (if available)
            doc_info = state.get("document_info", {})
            document_content = state.get("document_content", "")
            
            # Use LLM to analyze document and plan strategy based on parsed content
            planning_prompt = f"""You are an intelligent workflow orchestrator for FAIR metadata generation.

**Parsed Document Information:**
{json.dumps(doc_info, indent=2) if doc_info else "Document parsing in progress..."}

**Document Content Preview:**
{document_content[:2000]}...

**Your task:** Analyze the parsed document information and plan the optimal execution strategy.

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

Return JSON in the following format:
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
            
            response = await self.llm_helper._call_llm(messages, operation_name="Plan Workflow")
            content = response.content
            
            # Parse JSON response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            plan = json.loads(content)
            state["execution_plan"] = plan
            state["reasoning_chain"].append(f"Plan: {plan.get('reasoning', '')}")
            state["agent_guidance"] = plan.get("special_instructions", {})
            if state.get("agent_guidance"):
                logger.info(f"🧭 Planner guidance: {state['agent_guidance']}")
            
            logger.info(f"✅ Workflow plan created: {plan.get('strategy', 'standard')}")
            logger.info(f"   Document type: {plan.get('document_type')}")
            logger.info(f"   Research domain: {plan.get('research_domain')}")
            
        except Exception as e:
            logger.error(f"❌ Planning failed: {e}")
            # Use default plan
            state["execution_plan"] = {
                "document_type": "unknown",
                "research_domain": "unknown",
                "strategy": "standard",
                "reasoning": f"Planning failed: {str(e)}"
            }
            state["agent_guidance"] = {}
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"Planning error: {str(e)}")
        
        return state
    
    @traceable(name="ParseDocument", tags=["agent", "parsing"])
    async def _parse_document_with_retry_node(self, state: FAIRifierState) -> FAIRifierState:
        """Parse document with internal retry logic."""
        logger.info("📋 Parsing document (with retry)")
        
        def check_output(s):
            doc_info = s.get("document_info", {})
            return doc_info and len(doc_info) > 3
        
        return await self._execute_agent_with_retry(
            state, self.document_parser, "DocumentParser", check_output
        )
    
    @traceable(name="ParseDocument_OLD", tags=["agent", "parsing"])
    async def _parse_document_node(self, state: FAIRifierState) -> FAIRifierState:
        """Parse document and extract structured information. [OLD - kept for reference]"""
        logger.info("📋 Parsing document")
        
        # Initialize execution history if needed
        if "execution_history" not in state:
            state["execution_history"] = []
        
        # Record execution start
        execution_record = {
            "agent_name": "DocumentParser",
            "attempt": state.get("context", {}).get("parse_retry_count", 0) + 1,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "success": False,
            "critic_evaluation": None
        }
        
        try:
            # Initialize context and get current retry count
            if "context" not in state:
                state["context"] = {}
            
            # Don't increment here - let the evaluate node handle retry logic
            # Just track the current attempt number
            retry_count = state["context"].get("parse_retry_count", 0)
            state["context"]["retry_count"] = retry_count  # Set for agent feedback
            
            # Execute document parser
            state = await self.document_parser.execute(state)
            
            execution_record["success"] = True
            execution_record["end_time"] = datetime.now().isoformat()
            
        except Exception as e:
            logger.error(f"❌ Document parsing failed: {e}")
            execution_record["end_time"] = datetime.now().isoformat()
            execution_record["error"] = str(e)
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"Document parsing error: {str(e)}")
        
        # Add to execution history
        state["execution_history"].append(execution_record)
        
        return state
    
    @traceable(name="EvaluateParsing", tags=["critic", "evaluation"])
    async def _evaluate_parsing_node(self, state: FAIRifierState) -> FAIRifierState:
        """Evaluate document parsing output using Critic."""
        logger.info("🔍 Evaluating document parsing")
        
        # Execute critic evaluation
        state = await self.critic.execute(state)
        
        # Prepare feedback if retry is needed
        execution_history = state.get("execution_history", [])
        if execution_history:
            last_execution = execution_history[-1]
            critic_eval = last_execution.get("critic_evaluation", {})
            decision = critic_eval.get("decision", "ACCEPT")
            
            # Initialize context if needed
            if "context" not in state:
                state["context"] = {}
            retry_count = state["context"].get("parse_retry_count", 0)
            
            # Handle retry logic: RETRY or ESCALATE both trigger retry if under limit
            if decision in ["RETRY", "ESCALATE"] and retry_count < config.max_step_retries:
                # Increment retry count for this step
                state["context"]["parse_retry_count"] = retry_count + 1
                state["context"]["retry_count"] = retry_count + 1
                
                logger.info(f"🔄 Preparing retry {retry_count + 1}/{config.max_step_retries} for DocumentParser")
                
                # Prepare feedback for retry
                state = await self.critic.provide_feedback_to_agent(
                    "DocumentParser",
                    critic_eval,
                    state
                )
            elif retry_count >= config.max_step_retries:
                # Max retries reached, mark for review but continue
                logger.warning(f"⚠️ Max retries ({config.max_step_retries}) reached for DocumentParser")
                state["needs_human_review"] = True
        
        return state
    
    def _route_after_parsing(self, state: FAIRifierState) -> Literal["accept", "retry", "escalate"]:
        """Route after parsing evaluation based on Critic decision.
        
        Priority order:
        1. User-configured max_step_retries (HIGHEST PRIORITY)
        2. Critic decision (ACCEPT > RETRY > ESCALATE)
        3. Output quality check (if max retries exhausted)
        
        Strategy:
        - If retries available (retry_count < max_step_retries): Use retry for RETRY/ESCALATE
        - If max retries reached: Respect Critic decision, but check for usable output
        """
        execution_history = state.get("execution_history", [])
        if not execution_history:
            return "accept"
        
        last_execution = execution_history[-1]
        critic_eval = last_execution.get("critic_evaluation", {})
        decision = critic_eval.get("decision", "ACCEPT")
        score = critic_eval.get("score", 0.0)
        
        # Initialize context if needed
        if "context" not in state:
            state["context"] = {}
        
        # Get current retry count (this is the count AFTER the current attempt)
        retry_count = state["context"].get("parse_retry_count", 0)
        
        logger.info(
            f"📊 Routing decision: {decision} (score: {score:.2f}, "
            f"retry_count: {retry_count}/{config.max_step_retries})"
        )
        
        if decision == "ACCEPT":
            logger.info(f"✅ Critic decision ACCEPT - proceeding to next step")
            return "accept"
        
        # PRIORITY 1: Check if retries are still available (user-configured limit)
        if retry_count < config.max_step_retries:
            # We have retries left - use them regardless of RETRY/ESCALATE
            if decision in ["RETRY", "ESCALATE"]:
                logger.info(
                    f"🔄 Retries available ({retry_count + 1}/{config.max_step_retries}) - "
                    f"retrying despite Critic decision {decision} (score: {score:.2f}). "
                    f"Note: User-configured max_step_retries takes priority."
                )
                return "retry"
            else:
                # Unknown decision but have retries - default to retry
                logger.warning(
                    f"⚠️ Unknown decision '{decision}' but retries available - retrying"
                )
                return "retry"
        
        # PRIORITY 2: Max retries reached - now respect Critic decision
        if decision == "RETRY":
            # Critic said RETRY but max retries reached
            doc_info = state.get("document_info", {})
            if doc_info and len(doc_info) > 3:
                logger.warning(
                    f"⚠️ Max retries reached ({config.max_step_retries}) but Critic decision was RETRY "
                    f"(score: {score:.2f}). Have {len(doc_info)} fields - continuing with human review flag."
                )
                state["needs_human_review"] = True
                return "accept"
            else:
                logger.error(
                    f"❌ Max retries reached, Critic decision RETRY (score: {score:.2f}), "
                    f"but no usable document info - escalating"
                )
                return "escalate"
        elif decision == "ESCALATE":
            # Critic said ESCALATE and max retries reached
            doc_info = state.get("document_info", {})
            if doc_info and len(doc_info) > 3:
                logger.warning(
                    f"⚠️ Max retries reached ({config.max_step_retries}) and Critic decision ESCALATE "
                    f"(score: {score:.2f}). Have {len(doc_info)} fields - continuing with human review flag. "
                    f"Note: Overriding ESCALATE because we have usable output."
                )
                state["needs_human_review"] = True
                return "accept"
            else:
                logger.error(
                    f"❌ Max retries reached and Critic decision ESCALATE (score: {score:.2f}) "
                    f"with no usable document info - escalating"
                )
                return "escalate"
        else:
            # Unknown decision, default to accept if we have output
            doc_info = state.get("document_info", {})
            if doc_info and len(doc_info) > 3:
                logger.warning(f"⚠️ Unknown decision '{decision}' but have {len(doc_info)} fields - continuing")
                state["needs_human_review"] = True
                return "accept"
            else:
                logger.error(f"❌ Unknown decision '{decision}' and no usable document info - escalating")
                return "escalate"
    
    @traceable(name="RetrieveKnowledge", tags=["agent", "knowledge"])
    async def _retrieve_knowledge_with_retry_node(self, state: FAIRifierState) -> FAIRifierState:
        """Retrieve knowledge with internal retry logic."""
        logger.info("🔍 Retrieving knowledge (with retry)")
        
        def check_output(s):
            knowledge = s.get("retrieved_knowledge", [])
            return knowledge and len(knowledge) > 0
        
        return await self._execute_agent_with_retry(
            state, self.knowledge_retriever, "KnowledgeRetriever", check_output
        )
    
    @traceable(name="RetrieveKnowledge_OLD", tags=["agent", "knowledge"])
    async def _retrieve_knowledge_node(self, state: FAIRifierState) -> FAIRifierState:
        """Retrieve knowledge from FAIR-DS API. [OLD - kept for reference]"""
        logger.info("🔍 Retrieving knowledge")
        
        if "execution_history" not in state:
            state["execution_history"] = []
        
        execution_record = {
            "agent_name": "KnowledgeRetriever",
            "attempt": state.get("context", {}).get("retrieve_retry_count", 0) + 1,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "success": False,
            "critic_evaluation": None
        }
        
        try:
            # Update retry count
            if "context" not in state:
                state["context"] = {}
            retry_count = state["context"].get("retrieve_retry_count", 0)
            state["context"]["retrieve_retry_count"] = retry_count + 1
            # Also set generic retry_count for agents that expect it
            state["context"]["retry_count"] = state["context"]["retrieve_retry_count"]
            
            # Execute knowledge retriever
            state = await self.knowledge_retriever.execute(state)
            
            execution_record["success"] = True
            execution_record["end_time"] = datetime.now().isoformat()
            
        except Exception as e:
            logger.error(f"❌ Knowledge retrieval failed: {e}")
            execution_record["end_time"] = datetime.now().isoformat()
            execution_record["error"] = str(e)
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"Knowledge retrieval error: {str(e)}")
        
        state["execution_history"].append(execution_record)
        
        return state
    
    @traceable(name="EvaluateRetrieval", tags=["critic", "evaluation"])
    async def _evaluate_retrieval_node(self, state: FAIRifierState) -> FAIRifierState:
        """Evaluate knowledge retrieval output using Critic."""
        logger.info("🔍 Evaluating knowledge retrieval")
        
        state = await self.critic.execute(state)
        
        # Prepare feedback if retry is needed
        execution_history = state.get("execution_history", [])
        if execution_history:
            last_execution = execution_history[-1]
            critic_eval = last_execution.get("critic_evaluation", {})
            decision = critic_eval.get("decision", "ACCEPT")
            
            # Initialize context if needed
            if "context" not in state:
                state["context"] = {}
            retry_count = state["context"].get("retrieve_retry_count", 0)
            
            # Handle retry logic: RETRY or ESCALATE both trigger retry if under limit
            if decision in ["RETRY", "ESCALATE"] and retry_count < config.max_step_retries:
                # Increment retry count for this step
                state["context"]["retrieve_retry_count"] = retry_count + 1
                state["context"]["retry_count"] = retry_count + 1
                
                logger.info(f"🔄 Preparing retry {retry_count + 1}/{config.max_step_retries} for KnowledgeRetriever")
                
                # Prepare feedback for retry
                state = await self.critic.provide_feedback_to_agent(
                    "KnowledgeRetriever",
                    critic_eval,
                    state
                )
            elif retry_count >= config.max_step_retries:
                # Max retries reached, mark for review but continue
                logger.warning(f"⚠️ Max retries ({config.max_step_retries}) reached for KnowledgeRetriever")
                state["needs_human_review"] = True
        
        return state
    
    def _route_after_retrieval(self, state: FAIRifierState) -> Literal["accept", "retry", "escalate"]:
        """Route after retrieval evaluation based on Critic decision.
        
        Priority order:
        1. User-configured max_step_retries (HIGHEST PRIORITY)
        2. Critic decision (ACCEPT > RETRY > ESCALATE)
        3. Output quality check (if max retries exhausted)
        
        Strategy:
        - If retries available (retry_count < max_step_retries): Use retry for RETRY/ESCALATE
        - If max retries reached: Respect Critic decision, but check for usable output
        """
        execution_history = state.get("execution_history", [])
        if not execution_history:
            return "accept"
        
        last_execution = execution_history[-1]
        critic_eval = last_execution.get("critic_evaluation", {})
        decision = critic_eval.get("decision", "ACCEPT")
        score = critic_eval.get("score", 0.0)
        
        # Initialize context if needed
        if "context" not in state:
            state["context"] = {}
        retry_count = state["context"].get("retrieve_retry_count", 0)
        
        logger.info(
            f"📊 Routing decision: {decision} (score: {score:.2f}, "
            f"retry_count: {retry_count}/{config.max_step_retries})"
        )
        
        if decision == "ACCEPT":
            logger.info(f"✅ Critic decision ACCEPT - proceeding to next step")
            return "accept"
        
        # PRIORITY 1: Check if retries are still available (user-configured limit)
        if retry_count < config.max_step_retries:
            # We have retries left - use them regardless of RETRY/ESCALATE
            if decision in ["RETRY", "ESCALATE"]:
                logger.info(
                    f"🔄 Retries available ({retry_count + 1}/{config.max_step_retries}) - "
                    f"retrying despite Critic decision {decision} (score: {score:.2f}). "
                    f"Note: User-configured max_step_retries takes priority."
                )
                return "retry"
            else:
                # Unknown decision but have retries - default to retry
                logger.warning(
                    f"⚠️ Unknown decision '{decision}' but retries available - retrying"
                )
                return "retry"
        
        # PRIORITY 2: Max retries reached - now respect Critic decision
        if decision == "RETRY":
            # Critic said RETRY but max retries reached
            knowledge = state.get("retrieved_knowledge", [])
            if knowledge and len(knowledge) > 0:
                logger.warning(
                    f"⚠️ Max retries reached ({config.max_step_retries}) but Critic decision was RETRY "
                    f"(score: {score:.2f}). Have {len(knowledge)} knowledge items - continuing with human review flag."
                )
                state["needs_human_review"] = True
                return "accept"
            else:
                logger.error(
                    f"❌ Max retries reached, Critic decision RETRY (score: {score:.2f}), "
                    f"but no knowledge retrieved - escalating"
                )
                return "escalate"
        elif decision == "ESCALATE":
            # Critic said ESCALATE and max retries reached
            knowledge = state.get("retrieved_knowledge", [])
            if knowledge and len(knowledge) > 0:
                logger.warning(
                    f"⚠️ Max retries reached ({config.max_step_retries}) and Critic decision ESCALATE "
                    f"(score: {score:.2f}). Have {len(knowledge)} knowledge items - continuing with human review flag. "
                    f"Note: Overriding ESCALATE because we have usable output."
                )
                state["needs_human_review"] = True
                return "accept"
            else:
                logger.error(
                    f"❌ Max retries reached and Critic decision ESCALATE (score: {score:.2f}) "
                    f"with no knowledge retrieved - escalating"
                )
                return "escalate"
        else:
            # Unknown decision, default to accept if we have output
            knowledge = state.get("retrieved_knowledge", [])
            if knowledge and len(knowledge) > 0:
                logger.warning(f"⚠️ Unknown decision '{decision}' but have {len(knowledge)} knowledge items - continuing")
                state["needs_human_review"] = True
                return "accept"
            else:
                logger.error(f"❌ Unknown decision '{decision}' and no knowledge - escalating")
                return "escalate"
    
    @traceable(name="GenerateJSON", tags=["agent", "generation"])
    async def _generate_json_with_retry_node(self, state: FAIRifierState) -> FAIRifierState:
        """Generate JSON with internal retry logic."""
        logger.info("📝 Generating JSON metadata (with retry)")
        
        def check_output(s):
            metadata_fields = s.get("metadata_fields", [])
            return metadata_fields and len(metadata_fields) > 0
        
        return await self._execute_agent_with_retry(
            state, self.json_generator, "JSONGenerator", check_output
        )
    
    @traceable(name="GenerateJSON_OLD", tags=["agent", "generation"])
    async def _generate_json_node(self, state: FAIRifierState) -> FAIRifierState:
        """Generate FAIR-DS compatible JSON metadata. [OLD - kept for reference]"""
        logger.info("📝 Generating JSON metadata")
        
        if "execution_history" not in state:
            state["execution_history"] = []
        
        execution_record = {
            "agent_name": "JSONGenerator",
            "attempt": state.get("context", {}).get("generate_retry_count", 0) + 1,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "success": False,
            "critic_evaluation": None
        }
        
        try:
            # Update retry count
            if "context" not in state:
                state["context"] = {}
            retry_count = state["context"].get("generate_retry_count", 0)
            state["context"]["generate_retry_count"] = retry_count + 1
            # Also set generic retry_count for agents that expect it
            state["context"]["retry_count"] = state["context"]["generate_retry_count"]
            
            # Execute JSON generator
            state = await self.json_generator.execute(state)
            
            execution_record["success"] = True
            execution_record["end_time"] = datetime.now().isoformat()
            
        except Exception as e:
            logger.error(f"❌ JSON generation failed: {e}")
            execution_record["end_time"] = datetime.now().isoformat()
            execution_record["error"] = str(e)
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"JSON generation error: {str(e)}")
        
        state["execution_history"].append(execution_record)
        
        return state
    
    @traceable(name="EvaluateGeneration", tags=["critic", "evaluation"])
    async def _evaluate_generation_node(self, state: FAIRifierState) -> FAIRifierState:
        """Evaluate JSON generation output using Critic."""
        logger.info("🔍 Evaluating JSON generation")
        
        state = await self.critic.execute(state)
        
        # Prepare feedback if retry is needed
        execution_history = state.get("execution_history", [])
        if execution_history:
            last_execution = execution_history[-1]
            critic_eval = last_execution.get("critic_evaluation", {})
            decision = critic_eval.get("decision", "ACCEPT")
            
            # Initialize context if needed
            if "context" not in state:
                state["context"] = {}
            retry_count = state["context"].get("generate_retry_count", 0)
            
            # Handle retry logic: RETRY or ESCALATE both trigger retry if under limit
            if decision in ["RETRY", "ESCALATE"] and retry_count < config.max_step_retries:
                # Increment retry count for this step
                state["context"]["generate_retry_count"] = retry_count + 1
                state["context"]["retry_count"] = retry_count + 1
                
                logger.info(f"🔄 Preparing retry {retry_count + 1}/{config.max_step_retries} for JSONGenerator")
                
                # Prepare feedback for retry
                state = await self.critic.provide_feedback_to_agent(
                    "JSONGenerator",
                    critic_eval,
                    state
                )
            elif retry_count >= config.max_step_retries:
                # Max retries reached, mark for review but continue
                logger.warning(f"⚠️ Max retries ({config.max_step_retries}) reached for JSONGenerator")
                state["needs_human_review"] = True
        
        return state
    
    def _route_after_generation(self, state: FAIRifierState) -> Literal["accept", "retry", "escalate"]:
        """Route after generation evaluation based on Critic decision.
        
        Priority order:
        1. User-configured max_step_retries (HIGHEST PRIORITY)
        2. Critic decision (ACCEPT > RETRY > ESCALATE)
        3. Output quality check (if max retries exhausted)
        
        Strategy:
        - If retries available (retry_count < max_step_retries): Use retry for RETRY/ESCALATE
        - If max retries reached: Respect Critic decision, but check for usable output
        """
        execution_history = state.get("execution_history", [])
        if not execution_history:
            return "accept"
        
        last_execution = execution_history[-1]
        critic_eval = last_execution.get("critic_evaluation", {})
        decision = critic_eval.get("decision", "ACCEPT")
        score = critic_eval.get("score", 0.0)
        
        # Initialize context if needed
        if "context" not in state:
            state["context"] = {}
        retry_count = state["context"].get("generate_retry_count", 0)
        
        logger.info(
            f"📊 Routing decision: {decision} (score: {score:.2f}, "
            f"retry_count: {retry_count}/{config.max_step_retries})"
        )
        
        if decision == "ACCEPT":
            logger.info(f"✅ Critic decision ACCEPT - proceeding to finalize")
            return "accept"
        
        # PRIORITY 1: Check if retries are still available (user-configured limit)
        if retry_count < config.max_step_retries:
            # We have retries left - use them regardless of RETRY/ESCALATE
            if decision in ["RETRY", "ESCALATE"]:
                logger.info(
                    f"🔄 Retries available ({retry_count + 1}/{config.max_step_retries}) - "
                    f"retrying despite Critic decision {decision} (score: {score:.2f}). "
                    f"Note: User-configured max_step_retries takes priority."
                )
                return "retry"
            else:
                # Unknown decision but have retries - default to retry
                logger.warning(
                    f"⚠️ Unknown decision '{decision}' but retries available - retrying"
                )
                return "retry"
        
        # PRIORITY 2: Max retries reached - now respect Critic decision
        if decision == "RETRY":
            # Critic said RETRY but max retries reached
            metadata_fields = state.get("metadata_fields", [])
            if metadata_fields and len(metadata_fields) > 0:
                logger.warning(
                    f"⚠️ Max retries reached ({config.max_step_retries}) but Critic decision was RETRY "
                    f"(score: {score:.2f}). Have {len(metadata_fields)} metadata fields - "
                    f"finalizing with human review flag."
                )
                state["needs_human_review"] = True
                return "accept"
            else:
                logger.error(
                    f"❌ Max retries reached, Critic decision RETRY (score: {score:.2f}), "
                    f"but no metadata fields generated - escalating"
                )
                return "escalate"
        elif decision == "ESCALATE":
            # Critic said ESCALATE and max retries reached
            metadata_fields = state.get("metadata_fields", [])
            if metadata_fields and len(metadata_fields) > 0:
                logger.warning(
                    f"⚠️ Max retries reached ({config.max_step_retries}) and Critic decision ESCALATE "
                    f"(score: {score:.2f}). Have {len(metadata_fields)} metadata fields - "
                    f"finalizing with human review flag. "
                    f"Note: Overriding ESCALATE because we have usable output."
                )
                state["needs_human_review"] = True
                return "accept"
            else:
                logger.error(
                    f"❌ Max retries reached and Critic decision ESCALATE (score: {score:.2f}) "
                    f"with no metadata fields generated - escalating"
                )
                return "escalate"
        else:
            # Unknown decision, default to accept if we have output
            metadata_fields = state.get("metadata_fields", [])
            if metadata_fields and len(metadata_fields) > 0:
                logger.warning(f"⚠️ Unknown decision '{decision}' but have {len(metadata_fields)} metadata fields - finalizing")
                state["needs_human_review"] = True
                return "accept"
            else:
                logger.error(f"❌ Unknown decision '{decision}' and no metadata fields - escalating")
                return "escalate"
    
    @traceable(name="Finalize", tags=["workflow", "finalization"])
    async def _finalize_node(self, state: FAIRifierState) -> FAIRifierState:
        """Finalize workflow and generate summary."""
        logger.info("✅ Finalizing workflow")
        
        # Generate execution summary
        execution_history = state.get("execution_history", [])
        
        # Count reflection iterations
        reflection_trajectory = state.get("reflection_trajectory", {})
        total_reflections = sum(len(traj) for traj in reflection_trajectory.values())
        reflections_by_agent = {
            agent: len(traj) for agent, traj in reflection_trajectory.items()
        }
        
        summary = {
            "total_steps": len(execution_history),
            "successful_steps": sum(1 for e in execution_history if e.get("success")),
            "failed_steps": sum(1 for e in execution_history if not e.get("success")),
            "steps_requiring_retry": sum(1 for e in execution_history if e.get("attempt", 1) > 1),
            "needs_human_review": state.get("needs_human_review", False),
            # Multi-turn reflection stats
            "total_reflections": total_reflections,
            "reflections_by_agent": reflections_by_agent,
            "reflection_trajectory": reflection_trajectory,
        }
        
        confidence_snapshot = aggregate_confidence(state, config)
        state["confidence_scores"] = {
            "critic": confidence_snapshot.critic,
            "structural": confidence_snapshot.structural,
            "validation": confidence_snapshot.validation,
            "overall": confidence_snapshot.overall,
        }
        state["quality_metrics"] = confidence_snapshot.details
        summary["overall_confidence"] = confidence_snapshot.overall
        summary["average_confidence"] = confidence_snapshot.overall
        if confidence_snapshot.overall < config.min_confidence_threshold:
            state["needs_human_review"] = True
            summary["needs_human_review"] = True
        
        state["execution_summary"] = summary
        
        # Set final status based on whether we have the critical output
        metadata_json = state.get("artifacts", {}).get("metadata_json")
        metadata_fields = state.get("metadata_fields", [])
        
        if not metadata_json or not metadata_fields:
            # Critical output missing - this is a failure
            state["status"] = ProcessingStatus.FAILED.value
            logger.error("❌ Workflow FAILED: No metadata_json.json generated")
            state["errors"] = state.get("errors", []) + ["Critical output missing: metadata_json.json not generated"]
        elif summary["failed_steps"] > 0:
            state["status"] = ProcessingStatus.REVIEWING.value
            logger.warning("⚠️ Workflow completed with failures - needs review")
        else:
            state["status"] = ProcessingStatus.COMPLETED.value
            logger.info("✅ Workflow completed successfully")
        
        state["processing_end"] = datetime.now().isoformat()
        state["workflow_version"] = "langgraph"
        
        logger.info(f"📊 Final summary: {summary}")
        
        # Store global retry info in state for report
        state["global_retries_used"] = self.global_retry_count
        state["max_global_retries"] = self.max_global_retries
        
        # Generate comprehensive report
        try:
            output_dir = state.get("output_dir")
            report_generator = WorkflowReportGenerator(output_dir=output_dir)
            
            # Find metadata_json.json path if available
            metadata_json_path = None
            if output_dir:
                from pathlib import Path
                output_path = Path(output_dir)
                metadata_json_file = output_path / "metadata_json.json"
                if metadata_json_file.exists():
                    metadata_json_path = str(metadata_json_file)
            
            # Generate report
            report = report_generator.generate_report(state, metadata_json_path)
            
            # Save reports
            json_path = report_generator.save_report(report, "workflow_report.json")
            txt_path = report_generator.save_text_report(report, "workflow_report.txt")
            
            if json_path:
                logger.info(f"📄 Workflow report saved: {json_path}")
            if txt_path:
                logger.info(f"📄 Text report saved: {txt_path}")
            
            # Log report summary
            text_report = report_generator.generate_text_report(report)
            logger.info("\n" + text_report)
            
            # Store report in state
            state["workflow_report"] = report
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to generate workflow report: {e}")
            # Don't fail the workflow if report generation fails
        
        return state
    
    async def run(
        self, 
        document_path: str, 
        project_id: str = None,
        output_dir: str = None
    ) -> Dict[str, Any]:
        """Run the LangGraph workflow."""
        if not project_id:
            project_id = f"fairifier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Initialize state
        initial_state = {
            "document_path": document_path,
            "document_content": "",
            "document_conversion": {},
            "output_dir": output_dir,  # Pass output directory for MinerU artifacts
            "document_info": {},
            "retrieved_knowledge": [],
            "metadata_fields": [],
            "validation_results": {},
            "confidence_scores": {},
            "needs_human_review": False,
            "artifacts": {},
            "human_interventions": {},
            "execution_history": [],
            "reasoning_chain": [],
            "execution_plan": {},
            "execution_summary": {},
            "status": ProcessingStatus.PENDING.value,
            "processing_start": datetime.now().isoformat(),
            "processing_end": None,
            "errors": [],
            "agent_guidance": {},
            "context": {
                "parse_retry_count": 0,
                "retrieve_retry_count": 0,
                "generate_retry_count": 0
            }
        }
        
        logger.info(f"🚀 Starting LangGraph Workflow (project: {project_id})")
        
        try:
            # Prepare LangSmith metadata for better tracing
            from pathlib import Path
            doc_name = Path(document_path).stem
            
            # Build descriptive run name with key configs
            mineru_status = "MinerU" if config.mineru_enabled else "PyMuPDF"
            run_name = f"{doc_name} | {config.llm_provider}:{config.llm_model} | {mineru_status}"
            
            # Collect important configuration metadata
            langsmith_metadata = {
                "document": doc_name,
                "document_path": document_path,
                "workflow_type": "langgraph",
                "llm_provider": config.llm_provider,
                "llm_model": config.llm_model,
                "llm_temperature": config.llm_temperature,
                "llm_max_tokens": config.llm_max_tokens,
                "mineru_enabled": config.mineru_enabled,
                "mineru_backend": config.mineru_backend if config.mineru_enabled else None,
                "fair_ds_api": config.fair_ds_api_url,
                "max_step_retries": config.max_step_retries,
                "max_global_retries": config.max_global_retries,
                "critic_accept_threshold_parser": config.critic_accept_threshold_document_parser,
                "critic_accept_threshold_retriever": config.critic_accept_threshold_knowledge_retriever,
                "critic_accept_threshold_generator": config.critic_accept_threshold_json_generator,
                "timestamp": datetime.now().isoformat(),
            }
            
            # Run workflow with enhanced LangSmith metadata
            config_dict = {
                "configurable": {"thread_id": project_id},
                "run_name": run_name,
                "metadata": langsmith_metadata,
                "tags": [
                    "langgraph-workflow",
                    config.llm_provider,
                    mineru_status.lower(),
                    f"model:{config.llm_model}",
                ],
                # Set higher recursion limit to allow multiple retries across all agents
                # Default is 25, we increase to 50 to support up to ~8 retries per agent
                "recursion_limit": 50
            }
            result = await self.workflow.ainvoke(initial_state, config=config_dict)
            
            logger.info(f"✅ LangGraph workflow completed (project: {project_id})")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ LangGraph workflow failed (project: {project_id}): {str(e)}")
            initial_state["status"] = ProcessingStatus.FAILED.value
            initial_state["errors"].append(str(e))
            return initial_state

