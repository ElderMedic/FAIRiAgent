"""Structured response models for deepagents-backed inner loops."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


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


class RootEntityResponse(BaseModel):
    """Investigation or study entity not generated from a factorial design."""

    model_config = ConfigDict(extra="forbid")

    row_id: str
    label: str
    parent_row_id: Optional[str] = None
    external_identifier: Optional[str] = None
    evidence: str


class DesignClaimFieldMappingResponse(BaseModel):
    """One level-specific FAIR-DS mapping for a design dimension."""

    model_config = ConfigDict(extra="forbid")

    level: str = Field(description="One of: observationunit, sample, assay")
    field_name: str


class DesignClaimKnownValueResponse(BaseModel):
    """A source-stated factor value at a known one-based position."""

    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=1)
    value: str


class DesignClaimDimensionResponse(BaseModel):
    """A source design factor before any row materialization."""

    model_config = ConfigDict(extra="forbid")

    name: str
    level_count: Optional[int] = Field(default=None, ge=1)
    explicit_values: List[str] = Field(default_factory=list)
    known_values: List[DesignClaimKnownValueResponse] = Field(
        default_factory=list,
        description=(
            "Source-stated values whose ordinal position is known when the full "
            "factor enumeration is unavailable."
        ),
    )
    origin: str = Field(description="One of: explicit or derived")
    semantic_role: str = Field(
        default="other",
        description=(
            "One of: observation_condition, sample_replicate, material_path, "
            "assay_process, constant_characteristic, other"
        ),
    )
    field_mappings: List[DesignClaimFieldMappingResponse] = Field(
        default_factory=list,
        description=(
            "FAIR-DS term mappings validated separately for each ISA level. "
            "Omit a level when no suitable term exists there."
        ),
    )
    # Backward-compatible input for older model responses.  The planner now
    # requests ``field_mappings`` because one term is not necessarily valid at
    # every level through which a design dimension propagates.
    field_name: Optional[str] = None
    applies_to: List[str] = Field(
        default_factory=list,
        description="Subset of observationunit, sample, assay",
    )


class DesignClaimGroupResponse(BaseModel):
    """One independent experimental branch and its scoped factors."""

    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(validation_alias=AliasChoices("group_id", "group"))
    label: str = Field(
        default="",
        description="Concise scientific label for this independent design branch",
    )
    study_row_id: str
    evidence: str
    dimensions: List[DesignClaimDimensionResponse] = Field(default_factory=list)
    reuse_same_sample_for_multiple_assays: bool = False
    sample_reuse_evidence: Optional[str] = None
    unresolved_ambiguities: List[str] = Field(default_factory=list)


class RecordTableFilterResponse(BaseModel):
    """One exact equality selector for a source metadata table."""

    model_config = ConfigDict(extra="forbid")

    column: str
    value: str


class RecordTableColumnMappingResponse(BaseModel):
    """Map one source table column to one selected FAIR-DS field."""

    model_config = ConfigDict(extra="forbid")

    column: str
    level: str = Field(description="One of: observationunit, sample, assay")
    field_name: str


class RecordTableSourceExtensionResponse(BaseModel):
    """Expose one source-table column when FAIR-DS has no equivalent term."""

    model_config = ConfigDict(extra="forbid")

    column: str
    level: str = Field(description="One of: observationunit, sample, assay")
    data_type: str = Field(
        default="string",
        description="One of: string, number, integer, identifier, text",
    )
    definition: str = ""


class RecordTableExcludedColumnResponse(BaseModel):
    """Document why a source column is not an ISOSA metadata field."""

    model_config = ConfigDict(extra="forbid")

    column: str
    classification: str = Field(
        description=(
            "One of: filter, identity, result_payload, redundant, or "
            "out_of_scope"
        )
    )
    reason: str


class RecordTableDerivationRuleResponse(BaseModel):
    """One auditable rule for deriving a row value from a source column."""

    model_config = ConfigDict(extra="forbid")

    match_type: str = Field(
        description="One of: exact, prefix, suffix, contains, or regex"
    )
    pattern: str
    value: str


class RecordTableDerivedMappingResponse(BaseModel):
    """Derive a FAIR-DS value from a source-table convention stated by the paper."""

    model_config = ConfigDict(extra="forbid")

    source_column: str
    level: str = Field(description="One of: observationunit, sample, assay")
    field_name: str
    source_extension: bool = False
    data_type: str = "string"
    definition: str = ""
    use_for_observation_unit_grouping: bool = False
    filters: List[RecordTableFilterResponse] = Field(default_factory=list)
    rules: List[RecordTableDerivationRuleResponse] = Field(default_factory=list)
    expected_nonblank_count: Optional[int] = Field(default=None, ge=1)
    evidence: str


class MetadataTableEntityPlanResponse(BaseModel):
    """Agent decision for exact row materialization from a metadata table."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    table_name: str
    study_row_id: str
    study_identifier_value: Optional[str] = None
    covers_complete_focal_study: bool = False
    filters: List[RecordTableFilterResponse] = Field(default_factory=list)
    sample_identifier_column: str
    assay_identifier_column: str
    observation_unit_columns: List[str] = Field(default_factory=list)
    expected_observation_unit_count: Optional[int] = Field(default=None, ge=1)
    expected_sample_count: Optional[int] = Field(default=None, ge=1)
    expected_assay_count: Optional[int] = Field(default=None, ge=1)
    group_column: Optional[str] = None
    description_columns: List[str] = Field(default_factory=list)
    assay_description_columns: List[str] = Field(default_factory=list)
    column_mappings: List[RecordTableColumnMappingResponse] = Field(
        default_factory=list
    )
    source_extension_mappings: List[RecordTableSourceExtensionResponse] = Field(
        default_factory=list
    )
    derived_mappings: List[RecordTableDerivedMappingResponse] = Field(
        default_factory=list
    )
    excluded_columns: List[RecordTableExcludedColumnResponse] = Field(
        default_factory=list
    )
    evidence: str = ""


class EntityDesignClaimsResponse(BaseModel):
    """Minimal source claims from which all entity rows are expanded."""

    model_config = ConfigDict(extra="forbid")

    investigations: List[RootEntityResponse] = Field(default_factory=list)
    studies: List[RootEntityResponse] = Field(default_factory=list)
    design_groups: List[DesignClaimGroupResponse] = Field(default_factory=list)
    record_table_plans: List[MetadataTableEntityPlanResponse] = Field(
        default_factory=list
    )
    design_summary: List[str] = Field(default_factory=list)
    unresolved_ambiguities: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class EntityPlanScopeFindingResponse(BaseModel):
    """One exact source condition omitted from a design group's dimensions."""

    # Findings are advisory. Providers sometimes attach an explanatory
    # ``rationale`` or a suggested target to an otherwise valid finding. Do
    # not let those harmless extras discard the required, independently
    # audited mapping/scope decisions that share this response envelope.
    model_config = ConfigDict(extra="ignore")

    # Optional findings are filtered item-by-item by the planner. Keep absent
    # keys as empty sentinels so one incomplete suggestion cannot discard the
    # audit's required mapping and scope decisions.
    group_id: str = ""
    dimension_name: str = Field(
        default="",
        validation_alias=AliasChoices("dimension_name", "dimension")
    )
    source_value: str = ""
    level: str = Field(
        default="", description="One of: observationunit, sample, assay"
    )
    field_name: str = ""
    evidence: str = ""


class EntityPlanFieldMappingFindingResponse(BaseModel):
    """One more specific FAIR-DS field mapping for an existing dimension."""

    model_config = ConfigDict(extra="forbid")

    group_id: str = ""
    dimension_name: str = Field(
        default="",
        validation_alias=AliasChoices("dimension_name", "dimension")
    )
    level: str = Field(
        default="", description="One of: observationunit, sample, assay"
    )
    field_name: str = ""


class EntityPlanFieldTargetResponse(BaseModel):
    """One FAIR-DS target inside a dimension-level mapping decision."""

    model_config = ConfigDict(extra="forbid")

    level: str = Field(description="One of: observationunit, sample, assay")
    field_name: str


class EntityPlanFieldMappingDecisionResponse(BaseModel):
    """Complete independent mapping decision for one design dimension."""

    # Some providers echo harmless scope/correction context into this bounded
    # decision object. Ignore those redundant keys while keeping mapping
    # targets themselves strict.
    model_config = ConfigDict(extra="ignore")

    group_id: str = Field(validation_alias=AliasChoices("group_id", "group"))
    dimension_name: str = Field(
        validation_alias=AliasChoices("dimension_name", "dimension")
    )
    mappings: List[EntityPlanFieldTargetResponse] = Field(default_factory=list)
    rationale: str = ""


class EntityPlanReuseValidationResponse(BaseModel):
    """Independent decision on a proposed many-assays-per-sample relation."""

    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(validation_alias=AliasChoices("group_id", "group"))
    approved: bool = False
    evidence_quote: Optional[str] = None
    rationale: str = Field(
        default="",
        validation_alias=AliasChoices("rationale", "reasoning", "reason"),
    )


class EntityPlanDimensionScopeResponse(BaseModel):
    """Independent ISA-level scope assignment for one design dimension."""

    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(validation_alias=AliasChoices("group_id", "group"))
    dimension_name: str = Field(
        validation_alias=AliasChoices("dimension_name", "dimension")
    )
    semantic_role: str = Field(
        default="other",
        description=(
            "Independent classification: observation_condition, "
            "sample_replicate, material_path, assay_process, "
            "constant_characteristic, or other"
        ),
    )
    applies_to: List[str] = Field(
        description="One of the ordered suffixes observationunit/sample/assay, sample/assay, or assay"
    )


class EntityPlanRecordColumnDecisionResponse(BaseModel):
    """Independent semantic disposition for one metadata-table column."""

    model_config = ConfigDict(extra="forbid")

    # A provider may omit repeated table coordinates when the column name
    # resolves to exactly one source-table profile. The planner fills that
    # context only when it is unambiguous; otherwise its completeness gate
    # still fails closed.
    source_id: str = ""
    table_name: str = ""
    column: str
    disposition: str = Field(
        validation_alias=AliasChoices("disposition", "decision", "classification"),
        description=(
            "One of: structural_only, fairds_mapping, source_extension, or excluded"
        )
    )
    level: Optional[str] = Field(
        default=None,
        description="For fairds_mapping/source_extension: observationunit, sample, or assay",
    )
    field_name: Optional[str] = None
    data_type: str = "string"
    rationale: str = ""


class EntityPlanScopeAuditResponse(BaseModel):
    """Bounded semantic audit of entity scope and FAIR-DS field mappings."""

    model_config = ConfigDict(extra="forbid")

    missing_conditions: List[EntityPlanScopeFindingResponse] = Field(
        default_factory=list
    )
    mapping_corrections: List[EntityPlanFieldMappingFindingResponse] = Field(
        default_factory=list
    )
    mapping_decisions: List[EntityPlanFieldMappingDecisionResponse] = Field(
        default_factory=list
    )
    reuse_validations: List[EntityPlanReuseValidationResponse] = Field(
        default_factory=list
    )
    dimension_scopes: List[EntityPlanDimensionScopeResponse] = Field(
        default_factory=list
    )
    record_column_decisions: List[EntityPlanRecordColumnDecisionResponse] = Field(
        default_factory=list
    )
