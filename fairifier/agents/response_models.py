"""Structured response models for deepagents-backed inner loops."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DocumentInfoResponse(BaseModel):
    """Canonical schema for DocumentParser output.

    Locked schema: unknown fields are rejected (``extra="forbid"``) so OpenAI
    Responses API structured outputs emit ``additionalProperties: false``.
    Field aliases (``investigation_title``, ``summary``, etc.) are normalized
    by ``fairifier.utils.doc_info_canonical.canonicalize_doc_info`` before
    Pydantic validation. Downstream consumers (KnowledgeRetriever,
    JSONGenerator, ISAValueMapper) rely on this fixed contract — do NOT
    re-introduce ``extra="allow"`` without updating the canonicalization
    layer first.

    See ARCHITECTURE_REFACTOR_PLAN.md §1.
    """

    model_config = ConfigDict(extra="forbid")

    document_type: Optional[str] = None
    title: Optional[str] = None
    abstract: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    research_domain: Optional[str] = None
    methodology: Optional[str] = None
    location: Optional[str] = None
    coordinates: Optional[str] = None
    doi: Optional[str] = None
    journal: Optional[str] = None
    publication_date: Optional[str] = None
    datasets_mentioned: List[str] = Field(default_factory=list)
    instruments: List[str] = Field(default_factory=list)
    variables: List[str] = Field(default_factory=list)
    key_findings: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class KnowledgeItemDraft(BaseModel):
    """Closed item schema for OpenAI Responses structured output."""

    model_config = ConfigDict(extra="forbid")

    field_name: Optional[str] = None
    value: Optional[str] = None
    package_source: Optional[str] = None
    notes: Optional[str] = None


class KnowledgeResponse(BaseModel):
    """Structured planning payload for KnowledgeRetriever inner loops."""

    # ``forbid`` required for OpenAI Responses ``text.format.schema``.
    model_config = ConfigDict(extra="forbid")

    selected_packages: List[str] = Field(default_factory=list)
    selected_optional_fields: Dict[str, List[str]] = Field(default_factory=dict)
    terms_to_search: List[str] = Field(default_factory=list)
    metadata_gap_hints: List[str] = Field(default_factory=list)
    # Reserved for future explainability/export only. FAIRifier still constructs the
    # final KnowledgeItem objects from real FAIR-DS field definitions downstream.
    knowledge_items: List[KnowledgeItemDraft] = Field(default_factory=list)
    notes: Optional[str] = None
    coverage_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ISAWorksheetResponse(BaseModel):
    """Structured worksheet payload for a single ISA level."""

    model_config = ConfigDict(extra="forbid")

    columns: List[str] = Field(default_factory=list)
    # OpenAI strict schemas reject open Dict[str, Any]; keep cell values as strings.
    rows: List[Dict[str, str]] = Field(default_factory=list)


class ISAValueMappingResponse(BaseModel):
    """Structured response payload for ISAValueMapper inner loops."""

    model_config = ConfigDict(extra="forbid")

    investigation: ISAWorksheetResponse = Field(default_factory=ISAWorksheetResponse)
    study: ISAWorksheetResponse = Field(default_factory=ISAWorksheetResponse)
    observationunit: ISAWorksheetResponse = Field(default_factory=ISAWorksheetResponse)
    sample: ISAWorksheetResponse = Field(default_factory=ISAWorksheetResponse)
    assay: ISAWorksheetResponse = Field(default_factory=ISAWorksheetResponse)
    evidence_summary: List[str] = Field(default_factory=list)
    quality_issues: List[str] = Field(default_factory=list)
    mapping_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
