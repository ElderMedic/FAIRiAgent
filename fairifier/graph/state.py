from typing import Dict, List, Any, Optional, TypedDict
from enum import Enum

class ProcessingStatus(Enum):
    """Status of the FAIRifier processing pipeline."""
    PENDING = "pending"
    PARSING = "parsing"
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    VALIDATING = "validating"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class FAIRifierState(TypedDict):
    """State object for LangGraph workflow - FAIR-DS compatible."""
    # Input
    document_path: str
    # Deprecated as a long-lived field (refactor §5). The pipeline reads
    # document text by reference via ``document_text_path``. ``document_content``
    # is only set as a transient fallback when no on-disk path is available
    # (in-memory tests) or briefly during multi-file parsing iteration.
    # Do NOT treat it as the source of truth — use ``read_document_text(state)``.
    document_content: Optional[str]
    document_text_path: Optional[str]  # On-disk pointer to the document text/markdown
    document_conversion: Dict[str, Any]
    output_dir: Optional[str]  # Output directory for artifacts (including MinerU)
    input_documents: List[Dict[str, Any]]  # Normalized input units for per-file parsing
    source_workspace: Dict[str, Any]  # Paths for source manifest, source files, and table indexes
    bio_file_paths: List[str]  # Absolute host paths for BIO_BINARY files (BAM, VCF, FASTQ, h5ad)
    
    # Processing stages
    document_info: Dict[str, Any]
    document_info_by_source: List[Dict[str, Any]]
    evidence_packets: List[Dict[str, Any]]
    retrieved_knowledge: List[Dict[str, Any]]
    metadata_fields: List[Dict[str, Any]]  # FAIR-DS format fields
    selected_packages: List[str]
    metadata_gap_hints: List[Dict[str, Any]]
    inferred_metadata_extensions: List[Dict[str, Any]]
    api_capabilities: Dict[str, Any]
    retrieval_cache: Dict[str, Any]
    
    # Validation and quality
    validation_results: Dict[str, Any]
    confidence_scores: Dict[str, float]
    needs_human_review: bool
    
    # Output (JSON only)
    artifacts: Dict[str, str]  # Only contains metadata_json and validation_report
    
    # Human-in-the-loop and execution tracking
    human_interventions: Dict[str, Dict[str, Any]]  # {step_id: {feedback, context_updates}}
    execution_history: List[Dict[str, Any]]  # Full execution history with critic reviews
    retry_trajectory: Dict[str, List[Dict[str, Any]]]  # {agent_name: [{attempt, decision, score, issues_count, timestamp}]}
    reasoning_chain: List[str]  # Workflow planner's reasoning steps
    execution_plan: Dict[str, Any]  # Current execution plan
    execution_summary: Dict[str, Any]  # Summary of execution (completed, failed, etc.)
    plan_tasks: List[Dict[str, Any]]  # Structured per-agent tasks (refactor §4)
    
    # Context for retry and memory (contains critic_feedback, retrieved_memories, etc.)
    context: Dict[str, Any]
    
    # Agent guidance from planner
    agent_guidance: Dict[str, str]
    
    # Memory integration (optional, for mem0)
    session_id: Optional[str]  # For mem0 session scoping, bound to thread_id
    memory_scope_id: Optional[str]  # Mem0 scope; defaults to session_id but can be shared across runs
    react_scratchpad: Optional[Dict[str, Any]]  # Inner-loop telemetry for deepagents-backed agents
    
    # Agent-to-agent structured handoff (in-process A2A)
    agent_messages: List[Dict[str, Any]]  # append-only log of AgentMessage.to_dict()

    # Metadata
    status: str
    processing_start: str
    processing_end: Optional[str]
    errors: List[str]
