"""Core data models for the FAIRifier framework."""

from typing import Dict, List, Any, Optional, TypedDict
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime


from .graph.state import ProcessingStatus


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
    status_reason: Optional[str] = None
    
    # ISA sheet from FAIR-DS API (one of: investigation, study, observationunit, sample, assay)
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


class AgentMessageType(Enum):
    """Types of structured inter-agent messages."""
    EVIDENCE_BUNDLE = "evidence_bundle"
    FIELD_GAP_REPORT = "field_gap_report"
    MAPPING_QUESTION = "mapping_question"
    ACK = "ack"


@dataclass
class AgentMessage:
    """Typed envelope for structured agent-to-agent communication.

    All messages are appended to ``FAIRifierState["agent_messages"]`` (append-only
    log). Agents read via ``AgentMailbox.inbox()`` and optionally acknowledge.
    """
    id: str
    from_agent: str
    to_agent: str  # target agent name, or "*" for broadcast
    message_type: str  # one of AgentMessageType values
    payload: Dict[str, Any] = field(default_factory=dict)
    refs: Dict[str, str] = field(default_factory=dict)
    priority: int = 0  # higher = more important
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    acked_by: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "message_type": self.message_type,
            "payload": self.payload,
            "refs": self.refs,
            "priority": self.priority,
            "created_at": self.created_at,
            "acked_by": self.acked_by,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentMessage":
        return cls(
            id=data["id"],
            from_agent=data["from_agent"],
            to_agent=data["to_agent"],
            message_type=data["message_type"],
            payload=data.get("payload", {}),
            refs=data.get("refs", {}),
            priority=data.get("priority", 0),
            created_at=data.get("created_at", ""),
            acked_by=data.get("acked_by", []),
        )


from .graph.state import FAIRifierState


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
