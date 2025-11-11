"""
FAIRifier Workflow - Orchestrator-driven architecture with Critic feedback

Flow:
1. Read file content → raw text
2. Orchestrator plans and executes with Critic review:
   - DocumentParser (LLM): Extract key info adaptively
   - Critic: Evaluate quality → Accept/Retry/Escalate
   - KnowledgeRetriever: Get FAIR-DS packages & terms from API
   - Critic: Evaluate quality → Accept/Retry/Escalate
   - JSONGenerator: Generate FAIR-DS compatible metadata
   - Critic: Evaluate quality → Accept/Retry/Escalate
   
Output: FAIR-DS compatible JSON metadata with full traceability
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from langsmith import traceable

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from ..models import FAIRifierState, ProcessingStatus
from ..agents.orchestrator import OrchestratorAgent
from ..agents.document_parser import DocumentParserAgent
from ..agents.knowledge_retriever import KnowledgeRetrieverAgent
from ..agents.json_generator import JSONGeneratorAgent
from ..config import config
from ..services.mineru_client import MinerUClient, MinerUConversionError

logger = logging.getLogger(__name__)


class FAIRifierWorkflow:
    """Workflow orchestrated by Orchestrator Agent"""
    
    def __init__(self):
        # Create Orchestrator
        self.orchestrator = OrchestratorAgent()
        self.mineru_client = self._initialize_mineru_client()
        
        # Register all agents for Orchestrator to schedule
        self.orchestrator.register_agent("DocumentParser", DocumentParserAgent(use_llm=True))
        self.orchestrator.register_agent("KnowledgeRetriever", KnowledgeRetrieverAgent())
        self.orchestrator.register_agent("JSONGenerator", JSONGeneratorAgent())
        
        self.checkpointer = MemorySaver()
        self.workflow = self._create_workflow()
    
    def _create_workflow(self) -> StateGraph:
        """Create workflow: Read file, then Orchestrator controls everything"""
        
        # Use FAIRifierState as the state schema
        from langgraph.graph import StateGraph
        workflow = StateGraph(FAIRifierState)
        
        # Step 1: Read file content (no LLM)
        workflow.add_node("read_file", self._read_file_node)
        
        # Step 2: Orchestrator controls all agents
        workflow.add_node("orchestrate", self._orchestrate_node)
        
        # Set entry point - start with reading file
        workflow.set_entry_point("read_file")
        
        # Flow: read_file -> orchestrate -> end
        workflow.add_edge("read_file", "orchestrate")
        workflow.add_edge("orchestrate", END)
        
        return workflow.compile(checkpointer=self.checkpointer)
    
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
                logger.info("MinerU client enabled for workflow document loading.")
                return client
            logger.warning("MinerU CLI not available; workflow will fall back to PyMuPDF.")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to initialize MinerU client: %s", exc)
        return None
    
    @traceable(name="ReadFile", tags=["workflow", "io"])
    async def _read_file_node(self, state: FAIRifierState) -> FAIRifierState:
        """Read file content (no LLM) - just extract raw text"""
        logger.info("📄 Reading file content")
        state["status"] = ProcessingStatus.PARSING.value
        
        try:
            document_path = state.get("document_path", "")
            text, conversion_info = self._read_document_content(document_path)
            logger.info(f"✅ Loaded {len(text)} characters from document")
            
            # Store raw content for Orchestrator
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
        """Read document content using MinerU when available."""
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
    
    async def _orchestrate_node(self, state: FAIRifierState) -> FAIRifierState:
        """Orchestrator node"""
        state["status"] = ProcessingStatus.PARSING.value
        logger.info("🎯 Orchestrator starting execution")
        
        result = await self.orchestrator.execute(state)
        
        # Set status based on execution results
        execution_summary = result.get("execution_summary", {})
        if execution_summary.get("failed_steps", 0) > 0:
            result["status"] = ProcessingStatus.REVIEWING.value
            result["needs_human_review"] = True
        else:
            result["status"] = ProcessingStatus.COMPLETED.value
        
        result["processing_end"] = datetime.now().isoformat()
        
        return result
    
    async def run(self, document_path: str, project_id: str = None) -> Dict[str, Any]:
        """Run the workflow"""
        if not project_id:
            project_id = f"fairifier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Initialize state - use dict literal for TypedDict
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
            "human_interventions": {},  # For human-in-the-loop
            "execution_history": [],  # Execution history with critic reviews
            "reasoning_chain": [],  # Orchestrator reasoning
            "execution_plan": {},  # Execution plan
            "execution_summary": {},  # Execution summary
            "status": ProcessingStatus.PENDING.value,
            "processing_start": datetime.now().isoformat(),
            "processing_end": None,
            "errors": []
        }
        
        logger.info(f"🚀 Starting FAIRifier Workflow (project: {project_id})")
        logger.info("📋 Using Orchestrator Agent for intelligent scheduling")
        
        try:
            # Run workflow
            config_dict = {"configurable": {"thread_id": project_id}}
            result = await self.workflow.ainvoke(initial_state, config=config_dict)
            
            logger.info(f"✅ Workflow completed (project: {project_id})")
            
            # Add workflow version info
            result["workflow_version"] = "orchestrator"
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Workflow failed (project: {project_id}): {str(e)}")
            initial_state["status"] = ProcessingStatus.FAILED.value
            initial_state["errors"].append(str(e))
            return initial_state

