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
import os
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
from ..tools.mineru_tools import create_mineru_convert_tool

# Mem0 service (optional)
try:
    from ..services.mem0_service import Mem0Service, get_mem0_service
except ImportError:
    Mem0Service = None
    get_mem0_service = None

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
        
        # Create MinerU tool for LangChain integration
        self.mineru_tool = None
        if self.mineru_client:
            self.mineru_tool = create_mineru_convert_tool(client=self.mineru_client)
            logger.info("MinerU tool enabled for LangGraph workflow.")
        
        # Initialize mem0 service for persistent memory (optional)
        self.mem0_service = self._initialize_mem0_service()
        
        # Initialize retry counters (like old Orchestrator)
        self.global_retry_count = 0
        self.max_global_retries = config.max_global_retries
        self.max_step_retries = config.max_step_retries
        
        # Initialize checkpointer based on configuration
        self._checkpointer_cm = None  # Store context manager for cleanup
        self._checkpointer_factory = None  # For AsyncSqliteSaver
        self.checkpointer = self._initialize_checkpointer()
        
        # Build the graph
        graph_structure = self._build_graph_structure()
        # For AsyncSqliteSaver, compile without checkpointer initially
        # We'll handle it at invocation time
        if self._checkpointer_factory is not None:
            # Async checkpointer - compile without it, handle at invocation
            self.workflow = graph_structure.compile()
            logger.info("Workflow compiled (async checkpointer will be managed at invocation time)")
        else:
            # Sync checkpointer or none - compile normally
            self.workflow = graph_structure.compile(checkpointer=self.checkpointer)
        
        logger.info("✅ LangGraph app initialized")
    
    def close(self):
        """Explicitly close checkpointer and cleanup resources.
        
        Call this method to properly cleanup SQLite connections when done.
        Recommended for long-running applications (API, UI).
        
        Note: For AsyncSqliteSaver, LangGraph manages the lifecycle automatically.
        This is mainly for SqliteSaver (sync) context managers.
        """
        if self._checkpointer_cm is not None:
            try:
                # Only try to close if it's a synchronous context manager
                # AsyncSqliteSaver is managed by LangGraph
                if hasattr(self._checkpointer_cm, '__exit__'):
                    self._checkpointer_cm.__exit__(None, None, None)
                    logger.info("Checkpointer resources cleaned up")
                self._checkpointer_cm = None
            except Exception as e:
                logger.warning(f"Error during checkpointer cleanup: {e}")
    
    def __del__(self):
        """Cleanup checkpointer context manager on instance deletion.
        
        Ensures proper cleanup of SQLite connections when using SqliteSaver.
        For AsyncSqliteSaver, LangGraph manages the lifecycle.
        """
        if self._checkpointer_cm is not None:
            try:
                # Only try to close if it's a synchronous context manager
                if hasattr(self._checkpointer_cm, '__exit__'):
                    self._checkpointer_cm.__exit__(None, None, None)
                    logger.debug("Checkpointer context manager cleaned up in __del__")
            except Exception as e:
                # Suppress exceptions during cleanup to avoid issues in destructor
                logger.debug(f"Error during checkpointer cleanup in __del__: {e}")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources."""
        self.close()
        return False
    
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
    
    def _initialize_mem0_service(self) -> Optional["Mem0Service"]:
        """Initialize mem0 service if enabled and available.
        
        Returns:
            Mem0Service instance or None if disabled/unavailable.
        """
        if not config.mem0_enabled:
            logger.debug("Mem0 disabled by configuration")
            return None
        
        if get_mem0_service is None:
            logger.warning("mem0ai package not installed, memory features disabled")
            return None
        
        try:
            service = get_mem0_service()
            if service and service.is_available():
                logger.info("✅ Mem0 service enabled for persistent memory")
                return service
            else:
                logger.warning("Mem0 service not available (check Qdrant connection)")
                return None
        except Exception as e:
            logger.warning(f"Failed to initialize mem0 service: {e}")
            return None
    
    def _initialize_checkpointer(self):
        """Initialize checkpointer based on configuration.
        
        Returns:
            Checkpointer instance or None based on config.checkpointer_backend
        """
        backend = config.checkpointer_backend.lower()
        
        if backend == "none":
            logger.info("Checkpointer: None (stateless mode)")
            return None
        
        elif backend == "memory":
            logger.warning(
                "Checkpointer: MemorySaver (in-memory, dev/test only). "
                "NOT for production - state will be lost on process exit."
            )
            return MemorySaver()
        
        elif backend == "sqlite":
            try:
                # Try AsyncSqliteSaver for async workflow support
                try:
                    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
                    
                    db_path = str(config.checkpoint_db_path)
                    config.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Store the factory function, not the context manager
                    # We'll use it at invocation time in async context
                    self._checkpointer_factory = lambda: AsyncSqliteSaver.from_conn_string(db_path)
                    
                    logger.info(f"Checkpointer: AsyncSqliteSaver (persistent) at {db_path}")
                    logger.info("Note: Async checkpointer will be managed at workflow invocation time")
                    return None  # Will be created at invocation time
                    
                except ImportError:
                    logger.warning("aiosqlite not available, falling back to sync SqliteSaver")
                    # Fallback to sync SqliteSaver
                    from langgraph.checkpoint.sqlite import SqliteSaver
                    
                    db_path = str(config.checkpoint_db_path)
                    config.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    checkpointer_cm = SqliteSaver.from_conn_string(db_path)
                    checkpointer = checkpointer_cm.__enter__()
                    self._checkpointer_cm = checkpointer_cm
                    
                    logger.info(f"Checkpointer: SqliteSaver (persistent, sync fallback) at {db_path}")
                    return checkpointer
                    
            except ImportError as exc:
                logger.error(
                    "Failed to import SQLite checkpointer. "
                    "Install: pip install langgraph-checkpoint-sqlite aiosqlite"
                )
                raise ImportError(
                    "langgraph-checkpoint-sqlite and aiosqlite required for sqlite checkpointer. "
                    "Install with: pip install langgraph-checkpoint-sqlite aiosqlite"
                ) from exc
            except Exception as exc:
                logger.error(f"Failed to initialize SQLite checkpointer: {exc}")
                raise
        
        else:
            raise ValueError(
                f"Invalid checkpointer_backend: {backend}. "
                f"Must be 'none', 'memory', or 'sqlite'"
            )
    
    async def _execute_agent_with_retry(
        self,
        state: FAIRifierState,
        agent: BaseAgent,
        agent_name: str,
        check_output_fn
    ) -> FAIRifierState:
        """
        Execute an agent with Critic evaluation and retry logic.
        
        Flow:
        1. Agent executes
        2. Critic evaluates
        3. If ACCEPT: done
        4. If not ACCEPT and retries left: provide feedback, retry
        5. If not ACCEPT and no retries left: accept with review flag or fail
        
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
        
        # Initialize retry tracking
        if "retry_trajectory" not in state:
            state["retry_trajectory"] = {}
        state["retry_trajectory"][agent_name] = []
        
        # Track previous scores for no-progress detection
        previous_scores = []
        NO_PROGRESS_THRESHOLD = 2  # Exit if score unchanged for this many consecutive attempts
        
        # Retrieve relevant memories before execution (if mem0 is enabled)
        session_id = state.get("session_id")
        if self.mem0_service and session_id:
            try:
                # Use agent's custom query hint if available, otherwise use default
                query_hint = None
                if hasattr(agent, 'get_memory_query_hint'):
                    query_hint = agent.get_memory_query_hint(state)
                
                # Default query based on document info and agent name
                if not query_hint:
                    doc_title = state.get("document_info", {}).get("title", "")
                    doc_domain = state.get("document_info", {}).get("research_domain", "")
                    query_hint = f"Context for {agent_name}: {doc_title} {doc_domain}".strip()
                
                relevant_memories = self.mem0_service.search(
                    query=query_hint,
                    session_id=session_id,
                    agent_id=agent_name,
                    limit=5
                )
                
                if relevant_memories:
                    state["context"]["retrieved_memories"] = relevant_memories
                    logger.debug(f"📚 Retrieved {len(relevant_memories)} memories for {agent_name}")
                else:
                    state["context"]["retrieved_memories"] = []
                    
            except Exception as e:
                logger.warning(f"Memory retrieval failed for {agent_name}: {e}")
                state["context"]["retrieved_memories"] = []
        
        # Retry loop
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
            
            # Create execution record
            execution_record = {
                "agent_name": agent_name,
                "attempt": attempt,
                "start_time": datetime.now().isoformat(),
                "end_time": None,
                "success": False,
                "critic_evaluation": None
            }
            
            try:
                # Execute agent
                state = await agent.execute(state)
                execution_record["success"] = True
                execution_record["end_time"] = datetime.now().isoformat()
                
            except Exception as e:
                logger.error(f"❌ {agent_name} error (attempt {attempt}): {str(e)}")
                execution_record["success"] = False
                execution_record["end_time"] = datetime.now().isoformat()
                execution_record["error"] = str(e)
                state["execution_history"].append(execution_record)
                
                # On error, try next attempt if available
                if attempt <= self.max_step_retries:
                    continue
                else:
                    break
            
            # Add execution record
            state["execution_history"].append(execution_record)
            
            # Call Critic
            logger.info(f"🔍 Critic evaluating {agent_name}...")
            state = await self.critic.execute(state)
            
            # Get Critic decision
            last_execution = state["execution_history"][-1]
            critic_eval = last_execution.get("critic_evaluation", {})
            decision = critic_eval.get("decision", "ACCEPT")
            score = critic_eval.get("score", 0.0)
            
            # Record retry trajectory
            state["retry_trajectory"][agent_name].append({
                "attempt": attempt,
                "decision": decision,
                "score": score,
                "issues_count": len(critic_eval.get("issues", [])),
                "timestamp": datetime.now().isoformat()
            })
            
            logger.info(
                f"   📊 Critic: {decision} (score: {score:.2f}, "
                f"attempt: {attempt}/{self.max_step_retries + 1})"
            )
            
            # Handle decision
            if decision == "ACCEPT":
                logger.info(f"✅ {agent_name} completed successfully (score {score:.2f} >= accept threshold)")
                
                # Store key insights as memories (if mem0 is enabled)
                if self.mem0_service and session_id:
                    try:
                        # Generate a summary of agent output for memory storage
                        agent_output_summary = self._generate_agent_output_summary(
                            agent_name, state, critic_eval
                        )
                        if agent_output_summary:
                            self.mem0_service.add(
                                messages=[{"role": "assistant", "content": agent_output_summary}],
                                session_id=session_id,
                                agent_id=agent_name,
                                metadata={
                                    "workflow_step": agent_name,
                                    "score": score,
                                    "attempt": attempt,
                                    "timestamp": datetime.now().isoformat()
                                }
                            )
                            logger.debug(f"💾 Stored memory for {agent_name}")
                    except Exception as e:
                        logger.warning(f"Memory storage failed for {agent_name}: {e}")
                
                break
            
            # Track score for no-progress detection
            previous_scores.append(round(score, 2))
            
            # Check for no-progress: if score unchanged for N consecutive attempts
            if len(previous_scores) >= NO_PROGRESS_THRESHOLD:
                recent_scores = previous_scores[-NO_PROGRESS_THRESHOLD:]
                if len(set(recent_scores)) == 1:
                    # All recent scores are identical - no progress being made
                    logger.warning(
                        f"⚠️ No progress detected for {agent_name}: "
                        f"score unchanged at {score:.2f} for {NO_PROGRESS_THRESHOLD} consecutive attempts\n"
                        f"  This may indicate API limitations or infeasible requirements.\n"
                        f"  Accepting current output to avoid further token waste."
                    )
                    if check_output_fn(state):
                        state["needs_human_review"] = True
                        state["no_progress_detected"] = True
                        break
                    else:
                        logger.error(f"❌ No progress and no usable output from {agent_name}")
                        state["errors"] = state.get("errors", []) + [
                            f"{agent_name}: No progress after {NO_PROGRESS_THRESHOLD} attempts (score stuck at {score:.2f})"
                        ]
                        break
            
            # Check if more retries available
            if attempt > self.max_step_retries:
                # Max retries reached - check if we have usable output
                if check_output_fn(state):
                    logger.warning(
                        f"⚠️ Max retries reached ({attempt-1}/{self.max_step_retries}) "
                        f"but {agent_name} has usable output - accepting with review flag\n"
                        f"  Final Critic decision: {decision} (score: {score:.2f})\n"
                        f"  Note: Workflow continues because output is usable, but needs human review"
                    )
                    state["needs_human_review"] = True
                    break
                else:
                    logger.error(
                        f"❌ Max retries reached ({attempt-1}/{self.max_step_retries}) "
                        f"with no usable output from {agent_name}\n"
                        f"  Final Critic decision: {decision} (score: {score:.2f})\n"
                        f"  Workflow will continue but may fail at finalization"
                    )
                    break
            else:
                # More retries available - provide feedback and continue
                logger.info(
                    f"   🔄 {agent_name} needs improvement (score: {score:.2f}), "
                    f"preparing retry {attempt}/{self.max_step_retries}..."
                )
                state = await self.critic.provide_feedback_to_agent(agent_name, critic_eval, state)
        
        return state
    
    def _generate_agent_output_summary(
        self, 
        agent_name: str, 
        state: FAIRifierState, 
        critic_eval: Dict[str, Any]
    ) -> Optional[str]:
        """Generate a summary of agent output for memory storage.
        
        Args:
            agent_name: Name of the agent that produced the output
            state: Current workflow state
            critic_eval: Critic evaluation results
            
        Returns:
            Summary string suitable for memory storage, or None if no summary available.
        """
        try:
            summaries = []
            
            if agent_name == "DocumentParser":
                doc_info = state.get("document_info", {})
                if doc_info:
                    title = doc_info.get("title", "Unknown")
                    domain = doc_info.get("research_domain", "")
                    keywords = doc_info.get("keywords", [])[:5]
                    summaries.append(f"Parsed document: '{title}'")
                    if domain:
                        summaries.append(f"Research domain: {domain}")
                    if keywords:
                        summaries.append(f"Key topics: {', '.join(keywords)}")
                        
            elif agent_name == "KnowledgeRetriever":
                knowledge = state.get("retrieved_knowledge", [])
                if knowledge:
                    packages = set()
                    for k in knowledge[:10]:
                        pkg = k.get("package_source") or k.get("metadata", {}).get("package", "")
                        if pkg:
                            packages.add(pkg)
                    if packages:
                        summaries.append(f"Selected FAIR-DS packages: {', '.join(packages)}")
                    summaries.append(f"Retrieved {len(knowledge)} knowledge items")
                    
            elif agent_name == "JSONGenerator":
                fields = state.get("metadata_fields", [])
                if fields:
                    high_conf = [f for f in fields if f.get("confidence", 0) > 0.7]
                    summaries.append(f"Generated {len(fields)} metadata fields")
                    if high_conf:
                        summaries.append(f"{len(high_conf)} fields with high confidence")
            
            # Add critic feedback summary if available
            if critic_eval:
                score = critic_eval.get("score", 0)
                summaries.append(f"Quality score: {score:.2f}")
                
                # Include specific strengths if available
                strengths = critic_eval.get("strengths", [])
                if strengths:
                    summaries.append(f"Strengths: {'; '.join(strengths[:2])}")
            
            if summaries:
                return f"[{agent_name}] " + ". ".join(summaries)
            return None
            
        except Exception as e:
            logger.debug(f"Failed to generate summary for {agent_name}: {e}")
            return None
    
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
    
    def _find_existing_mineru_result(self, document_path: str) -> Optional[Tuple[str, str]]:
        """
        Check if pre-converted MinerU results exist for this document.
        
        Searches in the same directory as the document for:
        1. mineru_{doc_name}/{doc_name}/vlm/{doc_name}.md (standard MinerU output structure)
        2. mineru_{doc_name}/**/*.md (any markdown in the mineru directory)
        
        Args:
            document_path: Path to the original PDF document
            
        Returns:
            Tuple of (markdown_path, images_dir) if found, None otherwise
        """
        from pathlib import Path
        
        doc_path = Path(document_path)
        doc_name = doc_path.stem
        doc_dir = doc_path.parent
        
        # Check for mineru_{doc_name} directory in same location as document
        mineru_dir = doc_dir / f"mineru_{doc_name}"
        
        if not mineru_dir.exists():
            return None
        
        logger.info(f"🔍 Found pre-converted MinerU directory: {mineru_dir}")
        
        # Try standard MinerU output structure: mineru_{doc_name}/{doc_name}/vlm/{doc_name}.md
        standard_md_path = mineru_dir / doc_name / "vlm" / f"{doc_name}.md"
        if standard_md_path.exists():
            images_dir = mineru_dir / doc_name / "vlm" / "images"
            logger.info(f"✅ Found pre-converted markdown: {standard_md_path}")
            return str(standard_md_path), str(images_dir) if images_dir.exists() else None
        
        # Fallback: search for any .md file in the mineru directory
        md_files = list(mineru_dir.rglob("*.md"))
        if md_files:
            # Prefer files named like the document
            for md_file in md_files:
                if doc_name in md_file.stem:
                    images_dir = md_file.parent / "images"
                    logger.info(f"✅ Found pre-converted markdown: {md_file}")
                    return str(md_file), str(images_dir) if images_dir.exists() else None
            
            # Use first found markdown file
            md_file = md_files[0]
            images_dir = md_file.parent / "images"
            logger.info(f"✅ Found pre-converted markdown: {md_file}")
            return str(md_file), str(images_dir) if images_dir.exists() else None
        
        logger.warning(f"⚠️ MinerU directory exists but no markdown found: {mineru_dir}")
        return None
    
    def _read_document_content(
        self, 
        document_path: str,
        output_dir: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Read content using MinerU when available, or use pre-converted results."""
        from pathlib import Path
        
        conversion_info: Dict[str, Any] = {}
        
        if document_path.endswith(".pdf"):
            # First, check if pre-converted MinerU results exist
            existing_result = self._find_existing_mineru_result(document_path)
            if existing_result:
                markdown_path, images_dir = existing_result
                logger.info(f"📄 Using pre-converted MinerU result (skipping conversion)")
                try:
                    with open(markdown_path, "r", encoding="utf-8") as f:
                        markdown_text = f.read()
                    
                    # Build conversion_info similar to MinerU client output
                    conversion_info = {
                        "source": "pre-converted",
                        "markdown_path": markdown_path,
                        "images_dir": images_dir,
                        "output_dir": str(Path(markdown_path).parent.parent),
                        "method": "mineru_preconverted"
                    }
                    logger.info(f"✅ Loaded pre-converted MinerU markdown ({len(markdown_text)} chars)")
                    return markdown_text, conversion_info
                except Exception as e:
                    logger.warning(f"⚠️ Failed to read pre-converted result: {e}")
                    # Fall through to normal conversion
            
            # No pre-converted results, use MinerU tool if available
            if self.mineru_tool:
                # Use output_dir for MinerU artifacts if provided
                mineru_output = None
                if output_dir:
                    doc_name = Path(document_path).stem
                    mineru_output = str(Path(output_dir) / f"mineru_{doc_name}")
                    logger.info(f"MinerU will save artifacts to: {mineru_output}")
                
                # Invoke MinerU tool
                result = self.mineru_tool.invoke({
                    "input_path": document_path,
                    "output_dir": mineru_output
                })
                
                if result["success"]:
                    # Conversion successful
                    conversion_info = {
                        "markdown_path": result["markdown_path"],
                        "output_dir": result["output_dir"],
                        "images_dir": result["images_dir"],
                        "method": result["method"]
                    }
                    logger.info("MinerU conversion successful: %s", result["markdown_path"])
                    logger.info(f"MinerU artifacts: {result['output_dir']}")
                    if result["images_dir"]:
                        logger.info(f"MinerU images: {result['images_dir']}")
                    return result["markdown_text"], conversion_info
                else:
                    # Conversion failed
                    logger.warning("MinerU conversion failed (%s). Falling back to PyMuPDF.", result["error"])
            
            # Fallback to PyMuPDF
            import fitz  # PyMuPDF
            doc = fitz.open(document_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            conversion_info["method"] = "pymupdf"
            return text, conversion_info
        
        # Non-PDF files: read directly
        with open(document_path, "r", encoding="utf-8") as file:
            text = file.read()
        conversion_info["method"] = "direct_read"
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
        
        # Count retry attempts
        retry_trajectory = state.get("retry_trajectory", {})
        total_retries = sum(len(traj) for traj in retry_trajectory.values())
        retries_by_agent = {
            agent: len(traj) for agent, traj in retry_trajectory.items()
        }
        
        summary = {
            "total_steps": len(execution_history),
            "successful_steps": sum(1 for e in execution_history if e.get("success")),
            "failed_steps": sum(1 for e in execution_history if not e.get("success")),
            "steps_requiring_retry": sum(1 for e in execution_history if e.get("attempt", 1) > 1),
            "needs_human_review": state.get("needs_human_review", False),
            # Retry stats
            "total_retries": total_retries,
            "retries_by_agent": retries_by_agent,
            "retry_trajectory": retry_trajectory,
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
            },
            # Memory integration: session_id bound to thread_id for consistent resume
            "session_id": project_id,
        }
        
        logger.info(f"🚀 Starting LangGraph Workflow (project: {project_id})")
        
        try:
            # Prepare LangSmith metadata for better tracing
            from pathlib import Path
            doc_name = Path(document_path).stem
            
            # FAIR-compliant LangSmith project name
            if config.enable_langsmith and getattr(config, 'langsmith_use_fair_naming', True):
                from fairifier.utils.langsmith_helper import generate_fair_langsmith_project_name
                fair_project = generate_fair_langsmith_project_name(
                    environment=None,
                    model_provider=config.llm_provider,
                    model_name=config.llm_model,
                    project_id=project_id,
                )
                os.environ["LANGCHAIN_PROJECT"] = fair_project
                logger.info(f"📊 LangSmith: {fair_project}")
            
            # Build descriptive run name with key configs
            mineru_status = "MinerU" if config.mineru_enabled else "PyMuPDF"
            run_name = f"{doc_name} | {config.llm_provider}:{config.llm_model} | {mineru_status}"
            
            # Collect important configuration metadata
            langsmith_metadata = {
                "document": doc_name,
                "document_path": document_path,
                "project_id": project_id,
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
            
            # Handle async checkpointer context if needed
            if self._checkpointer_factory is not None:
                # Use AsyncSqliteSaver with async context
                logger.debug("Using AsyncSqliteSaver with async context management")
                async with self._checkpointer_factory() as checkpointer:
                    # Recompile workflow with the checkpointer instance
                    graph_structure = self._build_graph_structure()
                    workflow_with_cp = graph_structure.compile(checkpointer=checkpointer)
                    result = await workflow_with_cp.ainvoke(initial_state, config=config_dict)
            else:
                # Use pre-compiled workflow (sync checkpointer or none)
                result = await self.workflow.ainvoke(initial_state, config=config_dict)
            
            logger.info(f"✅ LangGraph workflow completed (project: {project_id})")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ LangGraph workflow failed (project: {project_id}): {str(e)}")
            initial_state["status"] = ProcessingStatus.FAILED.value
            initial_state["errors"].append(str(e))
            return initial_state

