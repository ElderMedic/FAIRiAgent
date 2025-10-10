"""Main LangGraph workflow for the FAIRifier system."""

import logging
from typing import Dict, Any
from datetime import datetime

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from ..models import FAIRifierState, ProcessingStatus
from ..agents.document_parser import DocumentParserAgent
from ..agents.knowledge_retriever import KnowledgeRetrieverAgent
from ..agents.template_generator import TemplateGeneratorAgent
from ..agents.rdf_builder import RDFBuilderAgent
from ..agents.validator import ValidationAgent
from ..config import config

logger = logging.getLogger(__name__)


class FAIRifierWorkflow:
    """Main workflow orchestrator using LangGraph."""
    
    def __init__(self):
        self.agents = {
            "parser": DocumentParserAgent(),
            "retriever": KnowledgeRetrieverAgent(),
            "generator": TemplateGeneratorAgent(),
            "builder": RDFBuilderAgent(),
            "validator": ValidationAgent()
        }
        
        self.checkpointer = MemorySaver()
        self.workflow = self._create_workflow()
    
    def _create_workflow(self) -> StateGraph:
        """Create the LangGraph workflow."""
        workflow = StateGraph(FAIRifierState)
        
        # Add nodes
        workflow.add_node("parse_document", self._parse_document_node)
        workflow.add_node("retrieve_knowledge", self._retrieve_knowledge_node)
        workflow.add_node("generate_template", self._generate_template_node)
        workflow.add_node("build_rdf", self._build_rdf_node)
        workflow.add_node("validate", self._validate_node)
        workflow.add_node("human_review", self._human_review_node)
        workflow.add_node("finalize", self._finalize_node)
        
        # Define the flow
        workflow.set_entry_point("parse_document")
        
        # Linear flow with conditional human review
        workflow.add_edge("parse_document", "retrieve_knowledge")
        workflow.add_edge("retrieve_knowledge", "generate_template")
        workflow.add_edge("generate_template", "build_rdf")
        workflow.add_edge("build_rdf", "validate")
        
        # Conditional edge after validation
        workflow.add_conditional_edges(
            "validate",
            self._should_review,
            {
                "review": "human_review",
                "finalize": "finalize"
            }
        )
        
        workflow.add_edge("human_review", "finalize")
        workflow.add_edge("finalize", END)
        
        return workflow.compile(checkpointer=self.checkpointer)
    
    async def run(self, document_path: str, project_id: str = None) -> Dict[str, Any]:
        """Run the complete FAIRifier workflow."""
        if not project_id:
            project_id = f"fairifier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Initialize state
        initial_state = FAIRifierState(
            document_path=document_path,
            document_content="",
            document_info={},
            retrieved_knowledge=[],
            metadata_fields=[],
            rdf_graph="",
            validation_results={},
            confidence_scores={},
            needs_human_review=False,
            artifacts={},
            status=ProcessingStatus.PENDING.value,
            processing_start=datetime.now().isoformat(),
            processing_end=None,
            errors=[]
        )
        
        logger.info(f"Starting FAIRifier workflow for project {project_id}")
        
        try:
            # Run the workflow
            config_dict = {"configurable": {"thread_id": project_id}}
            result = await self.workflow.ainvoke(initial_state, config=config_dict)
            
            logger.info(f"Workflow completed for project {project_id}")
            return result
            
        except Exception as e:
            logger.error(f"Workflow failed for project {project_id}: {str(e)}")
            initial_state["status"] = ProcessingStatus.FAILED.value
            initial_state["errors"].append(str(e))
            return initial_state
    
    async def _parse_document_node(self, state: FAIRifierState) -> FAIRifierState:
        """Document parsing node."""
        state["status"] = ProcessingStatus.PARSING.value
        logger.info("Executing document parsing node")
        return await self.agents["parser"].execute(state)
    
    async def _retrieve_knowledge_node(self, state: FAIRifierState) -> FAIRifierState:
        """Knowledge retrieval node."""
        state["status"] = ProcessingStatus.RETRIEVING.value
        logger.info("Executing knowledge retrieval node")
        return await self.agents["retriever"].execute(state)
    
    async def _generate_template_node(self, state: FAIRifierState) -> FAIRifierState:
        """Template generation node."""
        state["status"] = ProcessingStatus.GENERATING.value
        logger.info("Executing template generation node")
        return await self.agents["generator"].execute(state)
    
    async def _build_rdf_node(self, state: FAIRifierState) -> FAIRifierState:
        """RDF building node."""
        state["status"] = ProcessingStatus.GENERATING.value
        logger.info("Executing RDF building node")
        return await self.agents["builder"].execute(state)
    
    async def _validate_node(self, state: FAIRifierState) -> FAIRifierState:
        """Validation node."""
        state["status"] = ProcessingStatus.VALIDATING.value
        logger.info("Executing validation node")
        return await self.agents["validator"].execute(state)
    
    async def _human_review_node(self, state: FAIRifierState) -> FAIRifierState:
        """Human review node (placeholder for now)."""
        state["status"] = ProcessingStatus.REVIEWING.value
        logger.info("Human review required - workflow paused")
        
        # For now, just log the review requirement
        # In a full implementation, this would integrate with a UI
        review_items = []
        
        # Check what needs review
        if state.get("confidence_scores"):
            low_confidence = {k: v for k, v in state["confidence_scores"].items() if v < config.min_confidence_threshold}
            if low_confidence:
                review_items.append(f"Low confidence components: {list(low_confidence.keys())}")
        
        if state.get("errors"):
            review_items.append(f"Errors to address: {len(state['errors'])}")
        
        validation_results = state.get("validation_results", {})
        if not validation_results.get("is_valid", True):
            review_items.append("Validation failures detected")
        
        logger.warning(f"Human review needed for: {'; '.join(review_items)}")
        
        # For MVP, we'll just flag it and continue
        # In production, this would wait for human input
        state["needs_human_review"] = True
        
        return state
    
    async def _finalize_node(self, state: FAIRifierState) -> FAIRifierState:
        """Finalization node."""
        state["status"] = ProcessingStatus.COMPLETED.value
        state["processing_end"] = datetime.now().isoformat()
        
        logger.info("Finalizing workflow results")
        
        # Calculate overall success metrics
        confidence_scores = state.get("confidence_scores", {})
        if confidence_scores:
            overall_confidence = sum(confidence_scores.values()) / len(confidence_scores)
            state["confidence_scores"]["overall"] = overall_confidence
        
        # Log summary
        artifacts = state.get("artifacts", {})
        logger.info(
            f"Workflow finalized. Artifacts: {list(artifacts.keys())}, "
            f"Overall confidence: {state.get('confidence_scores', {}).get('overall', 0):.2f}"
        )
        
        return state
    
    def _should_review(self, state: FAIRifierState) -> str:
        """Determine if human review is needed."""
        # Check if human review is explicitly flagged
        if state.get("needs_human_review", False):
            return "review"
        
        # Check overall confidence
        confidence_scores = state.get("confidence_scores", {})
        if confidence_scores:
            overall_confidence = sum(confidence_scores.values()) / len(confidence_scores)
            if overall_confidence < config.min_confidence_threshold:
                return "review"
        
        # Check validation results
        validation_results = state.get("validation_results", {})
        if not validation_results.get("is_valid", True):
            return "review"
        
        # Check for errors
        if state.get("errors"):
            return "review"
        
        return "finalize"
    
    async def get_workflow_status(self, project_id: str) -> Dict[str, Any]:
        """Get current workflow status for a project."""
        try:
            config_dict = {"configurable": {"thread_id": project_id}}
            # Get latest state from checkpointer
            checkpoint = self.checkpointer.get(config_dict)
            if checkpoint:
                return {
                    "project_id": project_id,
                    "status": checkpoint.get("status", "unknown"),
                    "confidence_scores": checkpoint.get("confidence_scores", {}),
                    "needs_review": checkpoint.get("needs_human_review", False),
                    "errors": checkpoint.get("errors", []),
                    "artifacts": list(checkpoint.get("artifacts", {}).keys())
                }
            else:
                return {"project_id": project_id, "status": "not_found"}
        except Exception as e:
            logger.error(f"Failed to get workflow status: {str(e)}")
            return {"project_id": project_id, "status": "error", "error": str(e)}
