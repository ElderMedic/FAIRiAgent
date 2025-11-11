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
from ..agents.document_parser import DocumentParserAgent
from ..agents.knowledge_retriever import KnowledgeRetrieverAgent
from ..agents.json_generator import JSONGeneratorAgent
from ..agents.critic import CriticAgent
from ..config import config
from ..utils.llm_helper import get_llm_helper
from ..services.mineru_client import MinerUClient, MinerUConversionError

logger = logging.getLogger(__name__)


class FAIRifierLangGraphApp:
    """LangGraph application for FAIR metadata generation."""
    
    def __init__(self):
        """Initialize the LangGraph app with all agents."""
        # Initialize agents
        self.document_parser = DocumentParserAgent(use_llm=True)
        self.knowledge_retriever = KnowledgeRetrieverAgent(use_llm=True)
        self.json_generator = JSONGeneratorAgent(use_llm=True)
        self.critic = CriticAgent()
        self.llm_helper = get_llm_helper()
        self.mineru_client = self._initialize_mineru_client()
        
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
    
    def get_graph_without_checkpointer(self):
        """Get a compiled graph without checkpointer for LangGraph Studio."""
        # Build graph structure without checkpointer
        workflow = self._build_graph_structure()
        # Compile without checkpointer (LangGraph API handles persistence)
        return workflow.compile()
    
    def _build_graph_structure(self) -> StateGraph:
        """Build the LangGraph workflow structure (uncompiled)."""
        workflow = StateGraph(FAIRifierState)
        
        # Add nodes
        workflow.add_node("read_file", self._read_file_node)
        workflow.add_node("plan_workflow", self._plan_workflow_node)
        workflow.add_node("parse_document", self._parse_document_node)
        workflow.add_node("evaluate_parsing", self._evaluate_parsing_node)
        workflow.add_node("retrieve_knowledge", self._retrieve_knowledge_node)
        workflow.add_node("evaluate_retrieval", self._evaluate_retrieval_node)
        workflow.add_node("generate_json", self._generate_json_node)
        workflow.add_node("evaluate_generation", self._evaluate_generation_node)
        workflow.add_node("finalize", self._finalize_node)
        
        # Set entry point
        workflow.set_entry_point("read_file")
        
        # Define edges
        workflow.add_edge("read_file", "parse_document")
        
        # After parsing, plan workflow based on parsed content
        workflow.add_edge("parse_document", "plan_workflow")
        
        # After planning, evaluate parsing results
        workflow.add_edge("plan_workflow", "evaluate_parsing")
        
        # After evaluation, route based on parsing evaluation decision
        workflow.add_conditional_edges(
            "evaluate_parsing",
            self._route_after_parsing,
            {
                "accept": "retrieve_knowledge",
                "retry": "parse_document",
                "escalate": "finalize"
            }
        )
        
        # After retrieval, always evaluate
        workflow.add_edge("retrieve_knowledge", "evaluate_retrieval")
        
        # Conditional routing after retrieval evaluation
        workflow.add_conditional_edges(
            "evaluate_retrieval",
            self._route_after_retrieval,
            {
                "accept": "generate_json",
                "retry": "retrieve_knowledge",
                "escalate": "finalize"
            }
        )
        
        # After generation, always evaluate
        workflow.add_edge("generate_json", "evaluate_generation")
        
        # Conditional routing after generation evaluation
        workflow.add_conditional_edges(
            "evaluate_generation",
            self._route_after_generation,
            {
                "accept": "finalize",
                "retry": "generate_json",
                "escalate": "finalize"
            }
        )
        
        # Finalize always goes to END
        workflow.add_edge("finalize", END)
        
        return workflow  # Return uncompiled StateGraph
    
    @traceable(name="ReadFile", tags=["workflow", "io"])
    async def _read_file_node(self, state: FAIRifierState) -> FAIRifierState:
        """Read file content from disk."""
        logger.info("📄 Reading file content")
        state["status"] = ProcessingStatus.PARSING.value
        
        try:
            document_path = state.get("document_path", "")
            
            text, conversion_info = self._read_document_content(document_path)
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
    
    def _read_document_content(self, document_path: str) -> Tuple[str, Dict[str, Any]]:
        """Read content using MinerU when available."""
        conversion_info: Dict[str, Any] = {}
        if document_path.endswith(".pdf"):
            if self.mineru_client:
                try:
                    conversion = self.mineru_client.convert_document(document_path)
                    conversion_info = conversion.to_dict()
                    logger.info("MinerU conversion successful: %s", conversion.markdown_path)
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
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"Planning error: {str(e)}")
        
        return state
    
    @traceable(name="ParseDocument", tags=["agent", "parsing"])
    async def _parse_document_node(self, state: FAIRifierState) -> FAIRifierState:
        """Parse document and extract structured information."""
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
            # Update retry count
            if "context" not in state:
                state["context"] = {}
            retry_count = state["context"].get("parse_retry_count", 0)
            state["context"]["parse_retry_count"] = retry_count + 1
            # Also set generic retry_count for agents that expect it
            state["context"]["retry_count"] = state["context"]["parse_retry_count"]
            
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
            
            if decision == "RETRY" and retry_count < config.max_step_retries:
                # Prepare feedback for retry
                # Note: provide_feedback_to_agent increments retry_count, but we're using parse_retry_count
                # So we'll sync them after the call
                state = await self.critic.provide_feedback_to_agent(
                    "DocumentParser",
                    critic_eval,
                    state
                )
                # Sync the retry counts
                state["context"]["parse_retry_count"] = state["context"].get("retry_count", 0)
            elif decision == "ESCALATE" or retry_count >= config.max_step_retries:
                state["needs_human_review"] = True
        
        return state
    
    def _route_after_parsing(self, state: FAIRifierState) -> Literal["accept", "retry", "escalate"]:
        """Route after parsing evaluation based on Critic decision."""
        execution_history = state.get("execution_history", [])
        if not execution_history:
            return "accept"
        
        last_execution = execution_history[-1]
        critic_eval = last_execution.get("critic_evaluation", {})
        decision = critic_eval.get("decision", "ACCEPT")
        
        # Initialize context if needed
        if "context" not in state:
            state["context"] = {}
        retry_count = state["context"].get("parse_retry_count", 0)
        
        logger.info(f"📊 Routing decision: {decision} (retry count: {retry_count})")
        
        if decision == "ACCEPT":
            return "accept"
        elif decision == "RETRY" and retry_count < config.max_step_retries:
            return "retry"
        else:
            # Max retries reached or ESCALATE
            return "escalate"
    
    @traceable(name="RetrieveKnowledge", tags=["agent", "knowledge"])
    async def _retrieve_knowledge_node(self, state: FAIRifierState) -> FAIRifierState:
        """Retrieve knowledge from FAIR-DS API."""
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
            
            if decision == "RETRY" and retry_count < config.max_step_retries:
                # Prepare feedback for retry
                state = await self.critic.provide_feedback_to_agent(
                    "KnowledgeRetriever",
                    critic_eval,
                    state
                )
                # Sync the retry counts
                state["context"]["retrieve_retry_count"] = state["context"].get("retry_count", 0)
            elif decision == "ESCALATE" or retry_count >= config.max_step_retries:
                state["needs_human_review"] = True
        
        return state
    
    def _route_after_retrieval(self, state: FAIRifierState) -> Literal["accept", "retry", "escalate"]:
        """Route after retrieval evaluation based on Critic decision."""
        execution_history = state.get("execution_history", [])
        if not execution_history:
            return "accept"
        
        last_execution = execution_history[-1]
        critic_eval = last_execution.get("critic_evaluation", {})
        decision = critic_eval.get("decision", "ACCEPT")
        
        # Initialize context if needed
        if "context" not in state:
            state["context"] = {}
        retry_count = state["context"].get("retrieve_retry_count", 0)
        
        logger.info(f"📊 Routing decision: {decision} (retry count: {retry_count})")
        
        if decision == "ACCEPT":
            return "accept"
        elif decision == "RETRY" and retry_count < config.max_step_retries:
            return "retry"
        else:
            return "escalate"
    
    @traceable(name="GenerateJSON", tags=["agent", "generation"])
    async def _generate_json_node(self, state: FAIRifierState) -> FAIRifierState:
        """Generate FAIR-DS compatible JSON metadata."""
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
            
            if decision == "RETRY" and retry_count < config.max_step_retries:
                # Prepare feedback for retry
                state = await self.critic.provide_feedback_to_agent(
                    "JSONGenerator",
                    critic_eval,
                    state
                )
                # Sync the retry counts
                state["context"]["generate_retry_count"] = state["context"].get("retry_count", 0)
            elif decision == "ESCALATE" or retry_count >= config.max_step_retries:
                state["needs_human_review"] = True
        
        return state
    
    def _route_after_generation(self, state: FAIRifierState) -> Literal["accept", "retry", "escalate"]:
        """Route after generation evaluation based on Critic decision."""
        execution_history = state.get("execution_history", [])
        if not execution_history:
            return "accept"
        
        last_execution = execution_history[-1]
        critic_eval = last_execution.get("critic_evaluation", {})
        decision = critic_eval.get("decision", "ACCEPT")
        
        # Initialize context if needed
        if "context" not in state:
            state["context"] = {}
        retry_count = state["context"].get("generate_retry_count", 0)
        
        logger.info(f"📊 Routing decision: {decision} (retry count: {retry_count})")
        
        if decision == "ACCEPT":
            return "accept"
        elif decision == "RETRY" and retry_count < config.max_step_retries:
            return "retry"
        else:
            return "escalate"
    
    @traceable(name="Finalize", tags=["workflow", "finalization"])
    async def _finalize_node(self, state: FAIRifierState) -> FAIRifierState:
        """Finalize workflow and generate summary."""
        logger.info("✅ Finalizing workflow")
        
        # Generate execution summary
        execution_history = state.get("execution_history", [])
        
        summary = {
            "total_steps": len(execution_history),
            "successful_steps": sum(1 for e in execution_history if e.get("success")),
            "failed_steps": sum(1 for e in execution_history if not e.get("success")),
            "steps_requiring_retry": sum(1 for e in execution_history if e.get("attempt", 1) > 1),
            "overall_confidence": state.get("confidence_scores", {}).get("overall", 0.0),
            "needs_human_review": state.get("needs_human_review", False)
        }
        
        # Calculate average confidence
        confidence_scores = state.get("confidence_scores", {})
        if confidence_scores:
            avg_confidence = sum(confidence_scores.values()) / len(confidence_scores)
            summary["average_confidence"] = avg_confidence
            state["confidence_scores"]["overall"] = avg_confidence
        
        state["execution_summary"] = summary
        
        # Set final status
        if summary["failed_steps"] > 0:
            state["status"] = ProcessingStatus.REVIEWING.value
        else:
            state["status"] = ProcessingStatus.COMPLETED.value
        
        state["processing_end"] = datetime.now().isoformat()
        state["workflow_version"] = "langgraph"
        
        logger.info(f"✅ Workflow completed: {summary}")
        
        return state
    
    async def run(self, document_path: str, project_id: str = None) -> Dict[str, Any]:
        """Run the LangGraph workflow."""
        if not project_id:
            project_id = f"fairifier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Initialize state
        initial_state = {
            "document_path": document_path,
            "document_content": "",
            "document_conversion": {},
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
            "context": {
                "parse_retry_count": 0,
                "retrieve_retry_count": 0,
                "generate_retry_count": 0
            }
        }
        
        logger.info(f"🚀 Starting LangGraph Workflow (project: {project_id})")
        
        try:
            config_dict = {"configurable": {"thread_id": project_id}}
            result = await self.workflow.ainvoke(initial_state, config=config_dict)
            
            logger.info(f"✅ LangGraph workflow completed (project: {project_id})")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ LangGraph workflow failed (project: {project_id}): {str(e)}")
            initial_state["status"] = ProcessingStatus.FAILED.value
            initial_state["errors"].append(str(e))
            return initial_state

