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
import re
import csv
import gzip
import shutil
import tarfile
import zipfile
import tempfile
from pathlib import Path
from typing import Dict, Any, Literal, Optional, Tuple, List, Callable
from datetime import datetime
from langsmith import traceable

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import FAIRifierState, ProcessingStatus
from .nodes import ReadFileNode, OrchestrateNode, FinalizeNode
from ..agents.base import BaseAgent
from ..agents.document_parser import DocumentParserAgent
from ..agents.knowledge_retriever import KnowledgeRetrieverAgent
from ..agents.json_generator import JSONGeneratorAgent
from ..agents.isa_value_mapper import ISAValueMapperAgent
from ..agents.critic import CriticAgent
from ..config import config
from ..output_paths import resolve_metadata_output_read_path, METADATA_OUTPUT_FILENAME
from ..utils.llm_helper import get_llm_helper, normalize_llm_response_content
from ..utils.report_generator import WorkflowReportGenerator
from ..utils.run_control import run_stop_requested, reset_run_stop_requested
from ..services.mineru_client import MinerUClient, MinerUConversionError, mineru_client_from_config
from ..services import mineru_cache as mineru_cache_service
from ..services.confidence_aggregator import aggregate_confidence
from ..services.fairds_api_parser import FAIRDSAPIParser
from ..utils.context_observability import log_context_usage
from ..utils.document_text import read_document_text
from ..utils.execution_history import compact_prior_attempts_for_agent
from ..utils.planner_tasks import (
    parse_plan_tasks_from_llm_output,
    planner_task_to_dict,
)
from ..services.source_workspace import SourceRecord, build_source_workspace
from ..tools.mineru_tools import create_mineru_convert_tool

# Mem0 service (optional)
try:
    from ..services.mem0_service import Mem0Service, get_mem0_service
except ImportError:
    Mem0Service = None
    get_mem0_service = None

logger = logging.getLogger(__name__)


def _flatten_field_definition(item: Dict[str, Any]) -> Dict[str, Any]:
    """Extract requirement-bearing keys from a retrieved_knowledge entry.

    ``retrieved_knowledge`` items nest ``requirement`` / ``required`` /
    ``isa_sheet`` inside a ``metadata`` sub-dict.  This helper promotes
    those keys to the top level so that ``_field_definitions`` consumers
    (Excel Help sheet, validators) can read them without understanding
    the internal nesting.
    """
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "term": item.get("term", ""),
        "source": item.get("source", ""),
        "isa_sheet": meta.get("isa_sheet", ""),
        "data_type": meta.get("data_type", ""),
        "requirement": meta.get("requirement", ""),
        "required": bool(meta.get("requirement", "").upper() == "MANDATORY"
                         or meta.get("required")),
        "package": meta.get("package", ""),
    }


def _filesystem_document_path(document_path: str):
    """On-disk path when ``document_path`` uses ``base::source`` multi-file markers."""
    from pathlib import Path

    head = document_path.split("::", 1)[0] if "::" in document_path else document_path
    return Path(head)


class FAIRifierLangGraphApp:
    """LangGraph application for FAIR metadata generation."""
    
    def __init__(self):
        """Initialize the LangGraph app with all agents."""
        # Initialize agents
        from ..agents.bio_metadata_agent import BioMetadataAgent
        self.document_parser = DocumentParserAgent()
        self.bio_metadata_agent = BioMetadataAgent()
        self.knowledge_retriever = KnowledgeRetrieverAgent()
        self.json_generator = JSONGeneratorAgent()
        self.isa_value_mapper = ISAValueMapperAgent()
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
        cm = getattr(self, "_checkpointer_cm", None)
        if cm is not None:
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
            client = mineru_client_from_config(config)
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
                logger.info(
                    "Mem0 not used (optional). Workflow continues without memory layer."
                )
                return None
        except Exception:
            # Only reachable when MEM0_STRICT=1 and mem0 init failed: re-raise
            raise
    
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
    
    def _retrieve_relevant_memories(
        self,
        agent_name: str,
        state: FAIRifierState,
        session_id: str,
        top_k: int = 5,
        prior_issues: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant memories before agent execution (R in R+W).
        
        Query construction: task + doc_type + schema + failure_signals
        Filters: project_id/doc_hash/agent_name with cross-agent support
        
        Args:
            agent_name: Name of the agent about to execute
            state: Current workflow state (for context extraction)
            session_id: Session ID for memory filtering
            top_k: Number of memories to retrieve
            
        Returns:
            List of relevant memories with content and metadata
        """
        if not self.mem0_service:
            return []
            
        try:
            # Extract context for query construction
            doc_info = state.get("document_info", {})
            doc_type = doc_info.get("document_type", "document")
            domain = doc_info.get("research_domain", "")
            
            # Build task-specific query (not "Context for agent X")
            if agent_name == "DocumentParser":
                query = (
                    f"parsing {doc_type} in {domain or 'scientific'} domain: "
                    f"extraction rules validation failures common issues"
                )
            elif agent_name == "KnowledgeRetriever":
                query = (
                    f"FAIR-DS packages ontologies for {domain or doc_type}: "
                    f"package combinations field mappings coverage issues"
                )
            elif agent_name == "JSONGenerator":
                query = (
                    f"FAIR metadata for {domain or doc_type}: "
                    f"field-ontology mappings confidence schema validation"
                )
            elif agent_name == "Critic":
                query = (
                    f"evaluating {domain or doc_type} metadata quality: "
                    f"common issues thresholds improvement patterns"
                )
            elif agent_name == "ISAValueMapper":
                query = (
                    f"metadata entity resolution for {domain or doc_type}: "
                    f"sample grouping experimental design matrix structuring"
                )
            elif agent_name == "Planner":
                query = (
                    f"workflow strategy for {domain or doc_type}: "
                    f"orchestration retry failure handling"
                )
            else:
                query = f"workflow for {domain or doc_type}"

            # On retry: append rejection issues to make the query more targeted
            if prior_issues:
                issue_summary = "; ".join(prior_issues[:3])
                query = f"{query} — previous failures: {issue_summary}"

            # Cold-start diagnostic: first agent on first run has no global memories
            if agent_name == "DocumentParser":
                try:
                    if self.mem0_service.is_cold_start():
                        logger.info("❄️  Cold start: no cross-session memories in global scope — building from scratch")
                    else:
                        logger.info("🌡️  Warm start: cross-session memories available for %s", agent_name)
                except Exception:
                    pass

            # Search both scopes:
            # - session_id/project_id: current run, enabling agent-to-agent handoff
            # - memory_scope_id: cross-run user/global memory
            memories = []
            seen_memory_ids = set()
            seen_memory_texts = set()
            for memory_scope_id in self._memory_scope_ids(state, session_id):
                scope_memories = self.mem0_service.search(
                    query=query,
                    session_id=memory_scope_id,
                    limit=top_k,
                )
                for memory in scope_memories:
                    memory_id = memory.get("id") if isinstance(memory, dict) else None
                    memory_text = memory.get("memory") if isinstance(memory, dict) else str(memory)
                    dedupe_key = memory_id or memory_text
                    if not dedupe_key:
                        continue
                    if memory_id and memory_id in seen_memory_ids:
                        continue
                    if memory_text and memory_text in seen_memory_texts:
                        continue
                    if memory_id:
                        seen_memory_ids.add(memory_id)
                    if memory_text:
                        seen_memory_texts.add(memory_text)
                    memories.append(memory)
                    if len(memories) >= top_k:
                        break
                if len(memories) >= top_k:
                    break
            
            if memories:
                logger.info(
                    f"📚 Retrieved {len(memories)} memories for {agent_name}"
                )
            
            return memories
            
        except Exception as e:
            logger.warning(f"Memory retrieval failed for {agent_name}: {e}")
            return []

    def _memory_scope_ids(
        self,
        state: FAIRifierState,
        session_id: str,
    ) -> List[str]:
        """Return unique memory scopes for current-run and cross-run memory."""
        scope_ids: List[str] = []
        for raw_scope in (session_id, state.get("memory_scope_id")):
            if isinstance(raw_scope, str):
                scope = raw_scope.strip()
                if scope and scope not in scope_ids:
                    scope_ids.append(scope)
        return scope_ids

    def _is_domain_general(self, insight: str) -> bool:
        """Return True if an insight is domain-general enough for the global long-term scope.

        Scope promotion rule (inspired by Claude Code memory discipline):
        - Session scope (run): always write — current-run agent-to-agent context
        - Global scope (long-term): only promote reusable cross-domain knowledge

        Reject from global scope if the insight is clearly run-specific:
        project IDs, file paths, retry counts, per-run timestamps.
        """
        lower = insight.lower()
        # Run-specific signals — keep in session scope only
        run_specific = [
            "project_id", "session_id", "run_id",
            "retry count", "attempt ", "restarted",
            "/home/", "/tmp/", "output/",
            "retry 1", "retry 2", "retry 3",
        ]
        return not any(sig in lower for sig in run_specific)

    def _store_memory_insight(
        self,
        *,
        state: FAIRifierState,
        session_id: str,
        agent_id: str,
        insight: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Store one insight applying scope discipline.

        Read/Write rules (inspired by Claude Code + ADK memory patterns):
        - Session scope  : always write — enables within-run agent-to-agent handoff
        - Global scope   : only promote domain-general facts (see _is_domain_general)
        - Write gate     : caller is responsible for _should_write_memory() check
        """
        if not self.mem0_service:
            return

        for memory_scope_id in self._memory_scope_ids(state, session_id):
            scope_type = "run" if memory_scope_id == session_id else "long_term"

            # Scope promotion gate: skip global scope for run-specific content
            if scope_type == "long_term" and not self._is_domain_general(insight):
                logger.debug(
                    "Skipping global scope promotion for run-specific insight (agent=%s)", agent_id
                )
                continue

            self.mem0_service.add(
                messages=[{
                    "role": "assistant",
                    "content": insight,
                }],
                session_id=memory_scope_id,
                agent_id=agent_id,
                metadata={
                    **metadata,
                    "memory_scope_id": memory_scope_id,
                    "memory_scope_type": scope_type,
                },
            )
    
    def _should_write_memory(
        self,
        agent_name: str,
        state: FAIRifierState,
        critic_eval: Dict[str, Any],
        attempt: int
    ) -> bool:
        """Determine if output should be written to memory (W gating).
        
        Only write: constraints/decisions/repair rules/preferences/failures
        
        Gating criteria:
        - High critic score (>0.75) - lowered threshold
        - First success after failures (repair rule learned)
        - Novel failure patterns (for future avoidance)
        - Workflow decisions (package selection, field mappings)
        """
        score = critic_eval.get("score", 0)
        decision = critic_eval.get("decision", "")
        
        # Rule 1: High-quality outputs (lowered to 0.75 from 0.8)
        if decision == "ACCEPT" and score > 0.75:
            logger.info(
                f"✅ Write gate passed: high-quality (score={score:.2f})"
            )
            return True
        
        # Rule 2: Successful repair (learned correction)
        if decision == "ACCEPT" and attempt > 1:
            logger.info(
                f"✅ Write gate passed: learned repair (attempt={attempt})"
            )
            return True
        
        # Rule 3: Failure patterns (for avoidance) — any attempt with issues
        if decision == "REJECT":
            issues = critic_eval.get("issues", [])
            if issues:
                logger.info(
                    f"✅ Write gate passed: failure pattern (attempt={attempt}, issues={len(issues)})"
                )
                return True
        
        # Rule 4: Workflow decisions (always valuable)
        if decision == "ACCEPT" and agent_name in ["KnowledgeRetriever", "JSONGenerator", "ISAValueMapper"]:
            logger.info(
                f"✅ Write gate passed: workflow decision from {agent_name}"
            )
            return True
        
        logger.info(
            f"❌ Write gate failed: score={score:.2f}, "
            f"decision={decision}, attempt={attempt}"
        )
        return False
    
    def _safe_get_domain(self, doc_info: Dict[str, Any]) -> str:
        """Extract canonical research_domain from doc_info.

        doc_info is canonicalized at the DocumentParser boundary (refactor §1),
        so research_domain is always a string when present (or absent). The
        list-shape handling below is preserved as a defensive fallback for
        legacy state dicts that may bypass canonicalization.
        """
        if not doc_info or not isinstance(doc_info, dict):
            return ""

        domain_raw = doc_info.get("research_domain")
        if not domain_raw:
            return ""
        if isinstance(domain_raw, list):
            for item in domain_raw:
                if isinstance(item, str) and item.strip():
                    return item.strip()
            return ""
        if isinstance(domain_raw, str):
            return domain_raw.strip()
        return ""
    
    def _safe_get_field(self, data: Any, *field_names: str, default: Any = None) -> Any:
        """Safely get a field from nested data, trying multiple field names.
        
        Args:
            data: Dictionary or other data structure to extract from
            *field_names: Multiple field names to try in order
            default: Default value if nothing found
        
        Returns:
            First non-None value found, or default
        """
        if not isinstance(data, dict):
            return default
        
        for field_name in field_names:
            value = data.get(field_name)
            if value is not None:
                return value
        
        return default
    
    def _extract_actionable_insight(
        self,
        agent_name: str,
        state: FAIRifierState,
        critic_eval: Dict[str, Any],
        attempt: int
    ) -> List[str]:
        """Extract actionable insights including workflow decisions.
        
        Returns list of insights (not just one) to capture:
        - Document patterns (for DocumentParser)
        - Package selections (for KnowledgeRetriever)
        - Field mappings (for JSONGenerator)
        - Repair rules
        - Failure causes
        """
        try:
            decision = critic_eval.get("decision", "")
            score = critic_eval.get("score", 0)
            insights = []
            
            # === KnowledgeRetriever: Capture package selection decisions ===
            if agent_name == "KnowledgeRetriever" and decision == "ACCEPT":
                knowledge = state.get("retrieved_knowledge", [])
                doc_info = state.get("document_info", {})
                domain = self._safe_get_domain(doc_info)
                
                logger.info(f"🔍 KR insight extraction: knowledge count={len(knowledge)}, domain='{domain}'")
                
                if knowledge and isinstance(knowledge, list):
                    # Extract selected packages (try multiple possible structures)
                    packages = set()
                    for k in knowledge[:30]:  # Check more items for robustness
                        if not isinstance(k, dict):
                            continue
                        
                        # Try multiple possible field names and structures
                        pkg = (
                            self._safe_get_field(k, "package_source", "package", "fair_ds_package") or
                            self._safe_get_field(k.get("metadata", {}), "package", "package_name") or
                            ""
                        )
                        
                        # Clean and validate package name
                        if isinstance(pkg, str):
                            pkg = pkg.strip()
                            if pkg and pkg.lower() not in ["default", "unknown", "none", ""]:
                                packages.add(pkg)
                    
                    logger.info(f"   Extracted packages: {packages}")
                    
                    if packages:
                        pkg_list = sorted(list(packages))[:5]  # Top 5 packages
                        if domain:
                            insights.append(
                                f"{domain} research requires FAIR-DS packages: {', '.join(pkg_list)}"
                            )
                        else:
                            insights.append(
                                f"FAIR-DS packages selected: {', '.join(pkg_list)}"
                            )
                    
                    # Extract ontology usage (more robust pattern matching)
                    ontologies = set()
                    for k in knowledge[:30]:
                        if not isinstance(k, dict):
                            continue
                        
                        # Try multiple fields for ontology info
                        onto = (
                            self._safe_get_field(k, "ontology_id", "ontology", "ontology_term") or
                            self._safe_get_field(k, "value") or  # Sometimes ontology is in 'value' field
                            ""
                        )
                        
                        # Extract ontology prefix from various formats
                        if isinstance(onto, str) and onto:
                            # Handle formats like "ENVO:00001998" or "http://purl.obolibrary.org/obo/ENVO_00001998"
                            if ":" in onto:
                                prefix = onto.split(":")[0].split("/")[-1].upper()
                            elif "/" in onto and "obo" in onto.lower():
                                # Extract from URL format
                                parts = onto.split("/")
                                for part in parts:
                                    if "_" in part:
                                        prefix = part.split("_")[0].upper()
                                        break
                                else:
                                    continue
                            else:
                                continue
                            
                            # Validate known ontology prefixes
                            if prefix in ["ENVO", "OBI", "EDAM", "NPO", "GO", "ECO", "CHEBI", "UBERON", "PATO", "UO"]:
                                ontologies.add(prefix)
                    
                    logger.info(f"   Extracted ontologies: {ontologies}")
                    
                    if ontologies:
                        onto_str = ", ".join(sorted(ontologies))
                        insights.append(
                            f"FAIR-DS ontologies mapped: {onto_str}"
                        )
                    
                    # Add count insight if significant
                    if len(knowledge) >= 50:
                        if domain:
                            insights.append(
                                f"{domain} studies commonly require 50+ FAIR-DS metadata terms"
                            )
                        else:
                            insights.append(
                                f"Complex experimental studies commonly require 50+ FAIR-DS metadata terms"
                            )
            
            # === JSONGenerator: Capture field mapping patterns ===
            elif agent_name == "JSONGenerator" and decision == "ACCEPT":
                fields = state.get("metadata_fields", [])
                doc_info = state.get("document_info", {})
                domain = self._safe_get_domain(doc_info)
                
                logger.info(f"🔍 JG insight extraction: fields count={len(fields)}, domain='{domain}'")
                
                if fields and isinstance(fields, list):
                    # Sample field-ontology mappings (more robust)
                    mappings = []
                    for f in fields[:25]:
                        if not isinstance(f, dict):
                            continue
                        
                        field_name = self._safe_get_field(f, "field_name", "name", "label") or ""
                        onto_uri = self._safe_get_field(f, "ontology_uri", "ontology", "ontology_id") or ""
                        
                        if isinstance(field_name, str) and isinstance(onto_uri, str):
                            field_name = field_name.strip()
                            onto_uri = onto_uri.strip()
                            
                            if onto_uri and field_name:
                                # Extract ontology prefix from various formats
                                prefix = ""
                                if ":" in onto_uri:
                                    prefix = onto_uri.split(":")[0].split("/")[-1].upper()
                                elif "/" in onto_uri:
                                    parts = onto_uri.split("/")
                                    for part in parts:
                                        if part.isupper() or "_" in part:
                                            prefix = part.split("_")[0].upper() if "_" in part else part
                                            break
                                
                                if prefix and len(prefix) <= 10:  # Reasonable prefix length
                                    mappings.append(f"{field_name}→{prefix}")
                    
                    logger.info(f"   Extracted mappings: {len(mappings)}")
                    
                    if mappings:
                        sample = mappings[:5]
                        insights.append(
                            f"Metadata field mappings: {', '.join(sample)}"
                        )
                    
                    # ISA level distribution
                    isa_levels = {}
                    for f in fields:
                        if isinstance(f, dict):
                            level = self._safe_get_field(f, "isa_level", "level", default="unknown")
                            if isinstance(level, str):
                                level = level.strip().lower()
                                isa_levels[level] = isa_levels.get(level, 0) + 1
                    
                    logger.info(f"   ISA levels: {isa_levels}")
                    
                    # Only report ISA distribution if we have meaningful data
                    if (
                        (len(isa_levels) > 1 and "unknown" not in isa_levels)
                        or isa_levels.get("unknown", 0) < len(fields) * 0.5
                    ):
                        level_str = ", ".join([f"{k}:{v}" for k, v in sorted(isa_levels.items())[:4] if k != "unknown"])
                        if level_str:
                            insights.append(f"Metadata spans ISA levels: {level_str}")
                    
                    # Total field count with context
                    if len(fields) >= 30:
                        if len(fields) >= 70:
                            complexity = "high-complexity"
                        elif len(fields) >= 50:
                            complexity = "medium-complexity"
                        else:
                            complexity = "standard-complexity"
                        
                        if domain:
                            insights.append(
                                f"{len(fields)} FAIR-DS compliant metadata fields represents a robust baseline for {complexity} {domain} studies"
                            )
                        else:
                            insights.append(
                                f"{len(fields)} FAIR-DS compliant metadata fields represents a robust baseline for {complexity} omics studies"
                            )
            
            # === DocumentParser: Capture document patterns ===
            elif agent_name == "DocumentParser" and decision == "ACCEPT":
                doc_info = state.get("document_info", {})
                
                logger.info(f"🔍 DP insight extraction: doc_info keys={list(doc_info.keys()) if doc_info else []}")
                
                if doc_info and isinstance(doc_info, dict):
                    # Extract domain with robust field name handling
                    domain = self._safe_get_domain(doc_info)
                    
                    # Extract document type
                    doc_type = self._safe_get_field(doc_info, "document_type", "type", "doc_type") or ""
                    if isinstance(doc_type, str):
                        doc_type = doc_type.strip()
                    
                    logger.info(f"   DP extracted: domain='{domain}', doc_type='{doc_type}'")
                    
                    # Pattern 1: Document type by domain
                    if domain and doc_type and len(doc_type) > 3:
                        insights.append(f"{domain} research commonly uses {doc_type} documents")
                    
                    # Pattern 2: Experimental design (try multiple field names)
                    exp_design = self._safe_get_field(
                        doc_info, 
                        "experimental_design", 
                        "study_design", 
                        "design"
                    )
                    
                    if exp_design:
                        # Handle both string and dict formats
                        design_text = ""
                        if isinstance(exp_design, dict):
                            # Extract from nested structure
                            design_type = self._safe_get_field(exp_design, "type", "design_type", "name")
                            if design_type and isinstance(design_type, str):
                                design_text = design_type.strip()
                        elif isinstance(exp_design, str):
                            design_text = exp_design.strip()
                        
                        logger.info(f"   DP design_text: '{design_text[:50]}'")
                        
                        # Look for common design patterns
                        if design_text:
                            design_lower = design_text.lower()
                            if "time" in design_lower and ("series" in design_lower or "course" in design_lower or "resolved" in design_lower):
                                if domain:
                                    insights.append(f"{domain} studies commonly use time-resolved (time-series) experimental designs")
                                else:
                                    insights.append("Time-series experimental design is common for transcriptomics studies")
                            elif "case" in design_lower and "control" in design_lower:
                                insights.append(f"Case-control design pattern used in {domain if domain else 'research'}")
                            elif "longitudinal" in design_lower:
                                insights.append(f"Longitudinal study design pattern observed in {domain if domain else 'research'}")
                            elif len(design_text) > 20:
                                # Generic design insight if long enough description
                                insights.append(f"Study design: {design_text[:80]}...")
                    
                    # Pattern 3: Model organisms (try multiple field names)
                    organisms = self._safe_get_field(
                        doc_info,
                        "study_organism",
                        "organisms",
                        "organism",
                        "model_organism"
                    )
                    
                    if organisms:
                        org_list = []
                        
                        # Handle various formats
                        if isinstance(organisms, list):
                            for org in organisms[:3]:  # Top 3 organisms
                                if isinstance(org, str) and org.strip():
                                    org_list.append(org.strip())
                                elif isinstance(org, dict):
                                    # Try to extract organism name from dict
                                    org_name = self._safe_get_field(org, "name", "organism", "species")
                                    if org_name and isinstance(org_name, str):
                                        org_list.append(org_name.strip())
                        elif isinstance(organisms, str) and organisms.strip():
                            org_list.append(organisms.strip())
                        elif isinstance(organisms, dict):
                            org_name = self._safe_get_field(organisms, "name", "organism", "species")
                            if org_name and isinstance(org_name, str):
                                org_list.append(org_name.strip())
                        
                        logger.info(f"   DP organisms: {org_list}")
                        
                        if org_list:
                            # Extract common names (earthworms, mice, etc.)
                            for org in org_list:
                                org_lower = org.lower()
                                if domain:
                                    insights.append(f"{org} is commonly used in {domain} research")
                                else:
                                    insights.append(f"{org} is a standard model organism")
                                break  # Only add one organism insight to avoid clutter
                    
                    # Pattern 4: Research strategy/approach (if available)
                    strategy = self._safe_get_field(doc_info, "research_strategy", "approach", "methodology")
                    if strategy and isinstance(strategy, str) and len(strategy) > 20:
                        insights.append(f"Research approach: {strategy[:80]}...")
            
            # === Repairs: what was fixed ===
            if decision == "ACCEPT" and attempt > 1:
                improvements = critic_eval.get("improvements", [])
                if improvements:
                    fix = improvements[0][:120]
                    insights.append(f"Repair learned: {fix}")
            
            # === High-quality patterns ===
            if decision == "ACCEPT" and score > 0.75:
                strengths = critic_eval.get("strengths", [])
                if strengths and not insights:  # Only if no workflow insights yet
                    strength = strengths[0][:120]
                    insights.append(f"Quality pattern: {strength}")
            
            # === Failures: root causes ===
            if decision == "REJECT":
                issues = critic_eval.get("issues", [])
                if issues:
                    issue = issues[0][:120]
                    insights.append(f"Failure cause: {issue}")
            
            return insights if insights else []
            
        except Exception as e:
            logger.warning(f"Failed to extract insights for {agent_name}: {e}")
            return []

    def _normalize_metadata_text(self, value: Any) -> str:
        """Normalize metadata labels/concepts for fuzzy matching."""
        return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip().split())

    def _field_covers_concept(self, field_name: str, concept: str) -> bool:
        """Best-effort concept coverage check between generated field names and required concepts."""
        normalized_field = self._normalize_metadata_text(field_name)
        normalized_concept = self._normalize_metadata_text(concept)
        if not normalized_field or not normalized_concept:
            return False
        if normalized_concept in normalized_field or normalized_field in normalized_concept:
            return True
        concept_aliases = {
            "license": ["license", "licence", "access rights", "usage rights"],
            "data usage license": ["license", "usage rights", "access rights"],
            "diversity": ["diversity", "richness", "shannon", "bray curtis"],
            "alpha diversity": ["alpha diversity", "richness", "shannon"],
            "beta diversity": ["beta diversity", "bray curtis", "distance matrix"],
            "gamma diversity": ["gamma diversity", "regional diversity"],
            "dataset type": ["dataset type", "library strategy", "target gene", "sequencing method"],
            "shotgun metagenome": ["shotgun metagenome", "metagenome", "library strategy"],
            "16s rrna": ["16s", "rrna", "target gene", "amplicon"],
            "18s rrna": ["18s", "rrna", "target gene", "amplicon"],
            "amplicon sequencing": ["amplicon", "target gene", "library strategy"],
        }
        aliases = concept_aliases.get(normalized_concept, [normalized_concept])
        return any(alias in normalized_field for alias in aliases)
    
    def get_graph_without_checkpointer(self):
        """Get a compiled graph without checkpointer for LangGraph Studio."""
        workflow = self._build_graph_structure()
        return workflow.compile()
    
    def _build_graph_structure(self) -> StateGraph:
        """Build LangGraph workflow with Orchestrator-style coordination."""
        workflow = StateGraph(FAIRifierState)
        workflow.add_node("read_file", ReadFileNode(self))
        workflow.add_node("orchestrate", OrchestrateNode(self))
        workflow.add_node("finalize", FinalizeNode(self))
        workflow.set_entry_point("read_file")
        workflow.add_edge("read_file", "orchestrate")
        workflow.add_edge("orchestrate", "finalize")
        workflow.add_edge("finalize", END)
        return workflow

    async def _read_file_node(self, state: FAIRifierState) -> FAIRifierState:
        return await ReadFileNode(self)(state)

    async def _orchestrate_all_agents_node(self, state: FAIRifierState) -> FAIRifierState:
        return await OrchestrateNode(self)(state)

    async def _finalize_node(self, state: FAIRifierState) -> FAIRifierState:
        return await FinalizeNode(self)(state)

    async def _execute_agent_with_retry(
        self,
        state: FAIRifierState,
        agent: BaseAgent,
        agent_name: str,
        check_output_fn
    ) -> FAIRifierState:
        return await OrchestrateNode(self)._execute_agent_with_retry(state, agent, agent_name, check_output_fn)

    def _evaluate_json_hard_gate(self, state: FAIRifierState) -> Dict[str, Any]:
        return OrchestrateNode(self)._evaluate_json_hard_gate(state)

    async def _plan_workflow_node(self, state: FAIRifierState) -> FAIRifierState:
        return await OrchestrateNode(self)._plan_workflow_node(state)

    def _critic_is_disabled(self) -> bool:
        return OrchestrateNode(self)._critic_is_disabled()

    def _hard_gate_is_disabled(self) -> bool:
        return OrchestrateNode(self)._hard_gate_is_disabled()

    def _cross_layer_rollback_is_disabled(self) -> bool:
        return OrchestrateNode(self)._cross_layer_rollback_is_disabled()

    def _find_existing_mineru_result(
        self,
        document_path: str,
        output_dir: Optional[str] = None,
    ) -> Optional[Tuple[str, str]]:
        return ReadFileNode(self)._find_existing_mineru_result(document_path, output_dir)

    def _read_single_document_content(
        self,
        document_path: str,
        output_dir: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        return ReadFileNode(self)._read_single_document_content(document_path, output_dir)

    def _read_tabular_content(self, document_path: str) -> str:
        return ReadFileNode(self)._read_tabular_content(document_path)

    def _read_multi_file_bundle(
        self,
        root_dir: "Path",
        output_dir: Optional[str] = None,
        source_method: str = "bundle",
    ) -> Tuple[str, Dict[str, Any]]:
        return ReadFileNode(self)._read_multi_file_bundle(root_dir, output_dir, source_method)

    def _read_document_content(
        self, 
        document_path: str,
        output_dir: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        return ReadFileNode(self)._read_document_content(document_path, output_dir)

    def _prepare_single_input_source_state(
        self,
        *,
        state: FAIRifierState,
        source_path: str,
        source_content: str,
        source_index: int,
        source_total: int,
        base_document_path: str,
    ) -> None:
        return OrchestrateNode(self)._prepare_single_input_source_state(
            state=state,
            source_path=source_path,
            source_content=source_content,
            source_index=source_index,
            source_total=source_total,
            base_document_path=base_document_path,
        )

    def _merge_document_info_entries(
        self,
        per_source_entries: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], Dict[str, List[str]]]:
        return OrchestrateNode(self)._merge_document_info_entries(per_source_entries)

    async def _parse_single_input_source(
        self,
        *,
        state: FAIRifierState,
        source_path: str,
        source_content: str,
        source_index: int,
        source_total: int,
        base_document_path: str,
    ) -> FAIRifierState:
        return await OrchestrateNode(self)._parse_single_input_source(
            state=state,
            source_path=source_path,
            source_content=source_content,
            source_index=source_index,
            source_total=source_total,
            base_document_path=base_document_path,
        )
    
    async def run(
        self,
        document_path: str,
        project_id: str = None,
        output_dir: str = None,
        resume: bool = False,
        user_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the LangGraph workflow. If resume=True, continue from last checkpoint."""
        if not project_id:
            project_id = f"fairifier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        if resume and self._checkpointer_factory is None and self.checkpointer is None:
            raise ValueError(
                "Resume requires a persistent checkpointer (CHECKPOINTER_BACKEND=sqlite)."
            )

        from pathlib import Path
        doc_name = Path(document_path or "").stem or project_id

        # Build config (thread_id is required for checkpointing and resume)
        mineru_status = "MinerU" if config.mineru_enabled else "PyMuPDF"
        run_name = (
            f"Resume: {project_id}"
            if resume
            else f"{doc_name} | {config.llm_provider}:{config.llm_model} | {mineru_status}"
        )
        langsmith_metadata = {
            "document": doc_name,
            "document_path": document_path or "",
            "project_id": project_id,
            "workflow_type": "langgraph",
            "resume": resume,
            "llm_provider": config.llm_provider,
            "llm_model": config.llm_model,
            "timestamp": datetime.now().isoformat(),
        }
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
            "recursion_limit": 50,
        }

        if config.enable_langsmith and getattr(config, "langsmith_use_fair_naming", True):
            from fairifier.utils.langsmith_helper import generate_fair_langsmith_project_name
            fair_project = generate_fair_langsmith_project_name(
                environment=None,
                model_provider=config.llm_provider,
                model_name=config.llm_model,
                project_id=project_id,
            )
            os.environ["LANGCHAIN_PROJECT"] = fair_project
            logger.info(f"📊 LangSmith: {fair_project}")

        if resume:
            logger.info(f"🔄 Resuming from checkpoint (project: {project_id})")
        else:
            logger.info(f"🚀 Starting LangGraph Workflow (project: {project_id})")
        reset_run_stop_requested()
        if not run_stop_requested(project_id):
            reset_run_stop_requested(project_id)

        # Initial state only for non-resume; resume uses checkpoint state
        initial_state = None
        if not resume:
            initial_state = {
                "document_path": document_path,
                "document_content": "",
                "document_text_path": None,
                "document_conversion": {},
                "input_documents": [],
                "source_workspace": {},
                "bio_file_paths": [],
                "output_dir": output_dir,
                "document_info": {},
                "document_info_by_source": [],
                "evidence_packets": [],
                "retrieved_knowledge": [],
                "metadata_fields": [],
                "retrieval_cache": {},
                "validation_results": {},
                "confidence_scores": {},
                "needs_human_review": False,
                "artifacts": {},
                "human_interventions": {},
                "execution_history": [],
                "retry_trajectory": {},
                "reasoning_chain": [],
                "execution_plan": {},
                "execution_summary": {},
                "status": ProcessingStatus.PENDING.value,
                "processing_start": datetime.now().isoformat(),
                "processing_end": None,
                "errors": [],
                "agent_guidance": {},
                "plan_tasks": [],
                "selected_packages": [],
                "metadata_gap_hints": [],
                "inferred_metadata_extensions": [],
                "api_capabilities": {},
                "react_scratchpad": None,
                "agent_messages": [],
                "context": {
                    "parse_retry_count": 0,
                    "retrieve_retry_count": 0,
                    "generate_retry_count": 0,
                },
                "session_id": project_id,
                # memory_scope_id drives cross-run learning:
                # - WebUI: user_session_id is the browser's persistent UUID → isolates by user
                # - CLI with explicit override: config.memory_scope_id
                # - CLI without override: "fairifier-global" so all CLI runs share a pool
                "memory_scope_id": (
                    user_session_id
                    or config.memory_scope_id
                    or "fairifier-global"
                ),
            }

        try:
            # Invoke with None on resume so the graph loads from checkpoint
            input_state = initial_state if not resume else None
            result = initial_state if initial_state is not None else {}

            if self._checkpointer_factory is not None:
                logger.debug("Using AsyncSqliteSaver with async context management")
                async with self._checkpointer_factory() as checkpointer:
                    graph_structure = self._build_graph_structure()
                    workflow_with_cp = graph_structure.compile(checkpointer=checkpointer)
                    async for state in workflow_with_cp.astream(
                        input_state, config=config_dict, stream_mode="values"
                    ):
                        result = state
                        if run_stop_requested(project_id):
                            logger.warning(
                                f"⏹ Run stopped by user (project: {project_id})"
                            )
                            result["status"] = ProcessingStatus.INTERRUPTED.value
                            result.setdefault("errors", []).append(
                                "Run stopped by user"
                            )
                            break
                    if resume and not result and input_state is None:
                        snap = workflow_with_cp.get_state(config_dict)
                        if snap and getattr(snap, "values", None):
                            result = dict(snap.values)
            else:
                async for state in self.workflow.astream(
                    input_state, config=config_dict, stream_mode="values"
                ):
                    result = state
                    if run_stop_requested(project_id):
                        logger.warning(
                            f"⏹ Run stopped by user (project: {project_id})"
                        )
                        result["status"] = ProcessingStatus.INTERRUPTED.value
                        result.setdefault("errors", []).append(
                            "Run stopped by user"
                        )
                        break
                if resume and not result and input_state is None:
                    snap = self.workflow.get_state(config_dict)
                    if snap and getattr(snap, "values", None):
                        result = dict(snap.values)

            if run_stop_requested(project_id):
                logger.info(
                    f"⏹ LangGraph workflow stopped by user (project: {project_id})"
                )
            else:
                logger.info(
                    f"✅ LangGraph workflow completed (project: {project_id})"
                )

            return result

        except Exception as e:
            logger.error(
                f"❌ LangGraph workflow failed (project: {project_id}): {str(e)}"
            )
            fallback = initial_state or {
                "status": ProcessingStatus.FAILED.value,
                "errors": [],
            }
            fallback["status"] = ProcessingStatus.FAILED.value
            fallback.setdefault("errors", []).append(str(e))
            return fallback

    def _critic_is_disabled(self) -> bool:
        return bool(getattr(config, "disable_critic", False))

    def _hard_gate_is_disabled(self) -> bool:
        return bool(getattr(config, "disable_hard_gate", False))

    def _cross_layer_rollback_is_disabled(self) -> bool:
        return bool(getattr(config, "disable_cross_layer_rollback", False))
