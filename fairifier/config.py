"""Configuration management for FAIRifier."""

import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class FAIRifierConfig:
    """Configuration for the FAIRifier system."""
    
    # Paths
    project_root: Path = Path(__file__).parent.parent
    kb_path: Path = project_root / "kb"
    schemas_path: Path = kb_path / "schemas" 
    shapes_path: Path = kb_path / "shapes"
    output_path: Path = project_root / "output"
    
    # LLM Configuration
    llm_provider: str = "ollama"  # "ollama", "openai", or "anthropic"
    llm_model: str = "qwen2.5:7b"  # Model name
    llm_base_url: str = "http://localhost:11434"  # For Ollama
    llm_api_key: Optional[str] = None  # For OpenAI/Anthropic
    embedding_model: str = "nomic-embed-text"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 2000
    
    # Processing limits
    max_document_size_mb: int = 50
    max_processing_time_minutes: int = 10
    
    # Confidence thresholds
    min_confidence_threshold: float = 0.75
    auto_approve_threshold: float = 0.90
    
    # FAIR standards
    default_mixs_package: str = "MIMAG"  # Default MIxS package
    required_fields_coverage: float = 0.8  # Minimum required field coverage
    
    # External services (optional)
    qdrant_url: Optional[str] = None
    grobid_url: Optional[str] = None
    fair_ds_api_url: Optional[str] = None
    
    # LangSmith configuration
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "fairifier"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    enable_langsmith: bool = False
    
    def __post_init__(self):
        """Create necessary directories."""
        self.output_path.mkdir(exist_ok=True)
        self.kb_path.mkdir(exist_ok=True)
        self.schemas_path.mkdir(exist_ok=True)
        self.shapes_path.mkdir(exist_ok=True)


# Global config instance
config = FAIRifierConfig()

# Environment overrides
if os.getenv("FAIRIFIER_LLM_MODEL"):
    config.llm_model = os.getenv("FAIRIFIER_LLM_MODEL")

if os.getenv("FAIRIFIER_LLM_BASE_URL"):
    config.llm_base_url = os.getenv("FAIRIFIER_LLM_BASE_URL")

if os.getenv("QDRANT_URL"):
    config.qdrant_url = os.getenv("QDRANT_URL")

if os.getenv("GROBID_URL"):
    config.grobid_url = os.getenv("GROBID_URL")

if os.getenv("LANGSMITH_API_KEY"):
    config.langsmith_api_key = os.getenv("LANGSMITH_API_KEY")
    config.enable_langsmith = True

if os.getenv("LANGSMITH_PROJECT"):
    config.langsmith_project = os.getenv("LANGSMITH_PROJECT")

if os.getenv("LANGSMITH_ENDPOINT"):
    config.langsmith_endpoint = os.getenv("LANGSMITH_ENDPOINT")

# LLM provider configuration
if os.getenv("LLM_PROVIDER"):
    config.llm_provider = os.getenv("LLM_PROVIDER")

if os.getenv("LLM_API_KEY"):
    config.llm_api_key = os.getenv("LLM_API_KEY")

if os.getenv("LLM_TEMPERATURE"):
    config.llm_temperature = float(os.getenv("LLM_TEMPERATURE"))

if os.getenv("LLM_MAX_TOKENS"):
    config.llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS"))
