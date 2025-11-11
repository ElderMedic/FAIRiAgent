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


class FAIRifierState(TypedDict):
    """State object for LangGraph workflow - FAIR-DS compatible with self-reflection."""
    # Input
    document_path: str
    document_content: str
    document_conversion: Dict[str, Any]
    output_dir: Optional[str]  # Output directory for artifacts (including MinerU)
    
    # Processing stages
    document_info: Dict[str, Any]
    retrieved_knowledge: List[Dict[str, Any]]
    metadata_fields: List[Dict[str, Any]]  # FAIR-DS format fields
    
    # Validation and quality
    validation_results: Dict[str, Any]
    confidence_scores: Dict[str, float]
    needs_human_review: bool
    
    # Output (JSON only)
    artifacts: Dict[str, str]  # Only contains metadata_json and validation_report
    
    # Self-reflection and human-in-the-loop
    human_interventions: Dict[str, Dict[str, Any]]  # {step_id: {feedback, context_updates}}
    execution_history: List[Dict[str, Any]]  # Full execution history with critic reviews
    reasoning_chain: List[str]  # Orchestrator's reasoning steps
    execution_plan: Dict[str, Any]  # Current execution plan
    execution_summary: Dict[str, Any]  # Summary of execution (completed, failed, etc.)
    
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
