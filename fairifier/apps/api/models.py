"""Pydantic models for API request / response schemas."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    project_name: Optional[str] = None


class ConfigOverrides(BaseModel):
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    fair_ds_api_url: Optional[str] = None


class ProjectResponse(BaseModel):
    project_id: str
    project_name: Optional[str] = None
    filename: Optional[str] = None
    input_files: Optional[List[str]] = None
    session_id: Optional[str] = None
    session_started_at: Optional[str] = None
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    stop_requested: Optional[bool] = None
    stop_requested_at: Optional[str] = None
    confidence_scores: Optional[Dict[str, float]] = None
    needs_review: Optional[bool] = None
    errors: Optional[List[str]] = None
    artifacts: Optional[List[str]] = None
    execution_summary: Optional[Dict[str, object]] = None
    quality_metrics: Optional[Dict[str, object]] = None
    message: Optional[str] = None


class ProjectListResponse(BaseModel):
    projects: List[ProjectResponse]


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str


class DemoDocumentResponse(BaseModel):
    key: str
    label: str
    filename: str
    description: str
    size_bytes: int


class DemoOptionsResponse(BaseModel):
    default_demo_document_key: str
    default_ollama_provider: str
    default_ollama_model: str
    default_ollama_base_url: str
    ollama_available: bool
    documents: List[DemoDocumentResponse]


class ServiceStatusResponse(BaseModel):
    name: str
    label: str
    enabled: bool
    reachable: bool
    status: str
    message: str
    endpoint: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class OllamaModelResponse(BaseModel):
    name: str
    size: Optional[int] = None
    digest: Optional[str] = None
    modified_at: Optional[str] = None


class OllamaModelsResponse(BaseModel):
    base_url: str
    reachable: bool
    message: str
    models: List[OllamaModelResponse]


class SystemStatusResponse(BaseModel):
    timestamp: str
    active_config: Dict[str, Any]
    services: List[ServiceStatusResponse]


class ResourceLoadResponse(BaseModel):
    cpu_pct: float
    memory_pct: float
    memory_used_gb: float
    memory_total_gb: float
    disk_pct: float
    active_runs: int
    gpu_util_pct: Optional[float] = None
    gpu_memory_used_gb: Optional[float] = None
    gpu_memory_total_gb: Optional[float] = None


class MemoryWordEntry(BaseModel):
    text: str
    value: int
    category: str


class MemoryCloudResponse(BaseModel):
    session_words: List[MemoryWordEntry]
    scope_words: List[MemoryWordEntry]
    session_total: int
    scope_total: int
    memory_enabled: bool


class FAIRDSStatisticsTotals(BaseModel):
    packages: int
    fields: int
    mandatory_fields: int
    recommended_fields: int
    optional_fields: int
    terms: int
    unique_field_labels: int
    packages_with_no_fields: int
    terms_referenced_in_packages: int
    mandatory_ratio: float


class FAIRDSRequirementCount(BaseModel):
    requirement: str
    count: int


class FAIRDSISAStatistics(BaseModel):
    isa_level: str
    fields: int
    mandatory_fields: int
    recommended_fields: int
    optional_fields: int
    packages_count: int


class FAIRDSPackageStatistics(BaseModel):
    package_name: str
    fields: int
    mandatory_fields: int
    recommended_fields: int
    optional_fields: int
    isa_level_count: int
    term_linked_fields: int


class FAIRDSTermStatistics(BaseModel):
    term: str
    field_count: int


class FAIRDSTermQuality(BaseModel):
    with_definition: int
    with_example: int
    with_regex: int
    with_ontology_url: int


class FAIRDSStatisticsResponse(BaseModel):
    available: bool
    api_url: Optional[str] = None
    message: str
    generated_at: str
    totals: FAIRDSStatisticsTotals
    requirement_distribution: List[FAIRDSRequirementCount]
    isa_levels: List[FAIRDSISAStatistics]
    package_leaderboard: List[FAIRDSPackageStatistics]
    top_terms: List[FAIRDSTermStatistics]
    term_quality: FAIRDSTermQuality
