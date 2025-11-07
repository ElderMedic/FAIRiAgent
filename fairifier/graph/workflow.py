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
from typing import Dict, Any
from datetime import datetime
from langsmith import traceable

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from ..models import FAIRifierState, ProcessingStatus
from ..agents.orchestrator import OrchestratorAgent
from ..agents.document_parser import DocumentParserAgent
from ..agents.knowledge_retriever import KnowledgeRetrieverAgent
from ..agents.json_generator import JSONGeneratorAgent

logger = logging.getLogger(__name__)


class FAIRifierWorkflow:
    """Workflow orchestrated by Orchestrator Agent"""
    
    def __init__(self):
        # Create Orchestrator
        self.orchestrator = OrchestratorAgent()
        
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
    
    @traceable(name="ReadFile", tags=["workflow", "io"])
    async def _read_file_node(self, state: FAIRifierState) -> FAIRifierState:
        """Read file content (no LLM) - just extract raw text"""
        logger.info("📄 Reading file content")
        state["status"] = ProcessingStatus.PARSING.value
        
        try:
            document_path = state.get("document_path", "")
            
            # Read based on file type
            if document_path.endswith('.pdf'):
                import fitz  # PyMuPDF
                doc = fitz.open(document_path)
                text = ""
                for page in doc:
                    text += page.get_text()
                doc.close()
                logger.info(f"✅ Extracted {len(text)} characters from PDF")
            else:
                # Plain text file
                with open(document_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                logger.info(f"✅ Read {len(text)} characters from text file")
            
            # Store raw content for Orchestrator
            state["document_content"] = text
            
        except Exception as e:
            logger.error(f"❌ Failed to read file: {e}")
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"File reading error: {str(e)}")
            state["document_content"] = ""
        
        return state
    
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

