"""Core data models for the FAIRifier framework."""

from typing import Dict, List, Any, Optional, TypedDict
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime


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


class ConfidenceLevel(Enum):
    """Confidence levels for automated decisions."""
    HIGH = "high"      # > 0.8
    MEDIUM = "medium"  # 0.5 - 0.8
    LOW = "low"        # < 0.5


@dataclass
class DocumentInfo:
    """Information extracted from research documents."""
    title: Optional[str] = None
    abstract: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    research_domain: Optional[str] = None
    methodology: Optional[str] = None
    datasets_mentioned: List[str] = field(default_factory=list)
    instruments: List[str] = field(default_factory=list)
    variables: List[str] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class KnowledgeItem:
    """Retrieved knowledge item from external sources."""
    term: str
    definition: str
    source: str
    ontology_uri: Optional[str] = None
    confidence: float = 0.0
    metadata: Optional[Dict[str, Any]] = None  # Additional metadata (level, package, etc.)


@dataclass
class MetadataField:
    """A metadata field in FAIR-DS compatible format."""
    field_name: str
    value: Optional[str] = None
    evidence: Optional[str] = None
    confidence: float = 0.0
    origin: str = "unknown"  # e.g., "document_parser", "knowledge_retriever"
    package_source: Optional[str] = None  # e.g., "miappe", "soil", "default" (from FAIR-DS API)
    status: str = "provisional"  # "provisional" or "confirmed"
    
    # ISA sheet from FAIR-DS API (one of: investigation, study, assay, sample, observationunit)
    isa_sheet: Optional[str] = None

    # Entity grouping for multi-row ISA sheets (sample, assay, observationunit).
    # Fields sharing the same (isa_sheet, entity_id) belong to the same row.
    # None or "" means "no specific entity" — field goes to the default/first row.
    entity_id: Optional[str] = None

    # Additional metadata for internal use
    data_type: Optional[str] = None
    required: bool = False
    description: Optional[str] = None
    ontology_term: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None  # Raw metadata from FAIR-DS


@dataclass
class ValidationResult:
    """Result of SHACL or other validation."""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    score: float = 0.0


@dataclass
class ProcessingArtifacts:
    """Final output artifacts - JSON only for FAIR-DS compatibility."""
    metadata_json: Optional[str] = None    # FAIR-DS compatible JSON
    validation_report: Optional[str] = None  # Validation results
    processing_log: Optional[str] = None   # JSON lines log


@dataclass
class PlannerTask:
    """Structured per-agent guidance produced by the Planner.

    Replaces the free-text ``special_instructions`` dict that downstream agents
    used to regex-parse for package names and search terms (refactor §4).

    Fields:
        agent_name: One of "DocumentParser", "BioMetadataAgent",
            "KnowledgeRetriever", "JSONGenerator", "ISAValueMapper".
        priority_packages: FAIR-DS package names this agent should prioritize
            (e.g. ["Genome", "Nanopore"]).
        search_terms: Domain terms the agent should search for or focus on.
        focus_sheets: ISA sheets to prioritize ("investigation", "study",
            "assay", "sample", "observationunit").
        skip_if: Optional condition string. Reserved for future native LangGraph
            conditional routing (see refactor §7); not consumed yet.
        notes: Human-readable guidance (replaces the per-agent string in
            the legacy ``special_instructions`` dict).
    """

    agent_name: str
    priority_packages: List[str] = field(default_factory=list)
    search_terms: List[str] = field(default_factory=list)
    focus_sheets: List[str] = field(default_factory=list)
    skip_if: Optional[str] = None
    notes: str = ""


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
    
    # Metadata
    status: str
    processing_start: str
    processing_end: Optional[str]
    errors: List[str]


@dataclass 
class FAIRifierProject:
    """Main project container."""
    id: str
    created_at: datetime
    status: ProcessingStatus
    document_info: Optional[DocumentInfo] = None
    knowledge_items: List[KnowledgeItem] = field(default_factory=list)
    metadata_fields: List[MetadataField] = field(default_factory=list)
    validation_results: Optional[ValidationResult] = None
    artifacts: Optional[ProcessingArtifacts] = None
    confidence_scores: Dict[str, float] = field(default_factory=dict)
    needs_human_review: bool = False
    errors: List[str] = field(default_factory=list)
    
    def get_overall_confidence(self) -> float:
        """Calculate overall confidence score."""
        if not self.confidence_scores:
            return 0.0
        return sum(self.confidence_scores.values()) / len(self.confidence_scores)
    
    def requires_review(self) -> bool:
        """Check if human review is needed."""
        return (
            self.needs_human_review or 
            self.get_overall_confidence() < 0.75 or
            len(self.errors) > 0
        )
