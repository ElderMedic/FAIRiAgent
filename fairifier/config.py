"""Configuration management for FAIRifier."""

import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

# Load .env file if it exists
def load_env_file(env_file_path: Optional[Path] = None, verbose: bool = False):
    """
    Load environment variables from a .env file.
    
    Args:
        env_file_path: Path to .env file. If None, tries default locations.
        verbose: Whether to print loading messages.
    """
    try:
        from dotenv import load_dotenv
        
        if env_file_path:
            # Load from specified file
            env_path = Path(env_file_path)
            if env_path.exists():
                load_dotenv(env_path, override=True)
                if verbose:
                    print(f"✅ Loaded .env file from {env_path}")
                return True
            else:
                if verbose:
                    print(f"⚠️  .env file not found: {env_path}")
                return False
        else:
            # Load from project root
            project_root = Path(__file__).parent.parent.parent
            env_path = project_root / ".env"
            if env_path.exists():
                load_dotenv(env_path)
                if verbose:
                    print(f"✅ Loaded .env file from {env_path}")
                return True
            else:
                # Also try current directory
                load_dotenv()
                return True
    except ImportError:
        # python-dotenv not installed, skip
        if verbose:
            print("⚠️  python-dotenv not installed, skipping .env file loading")
        return False

# Load default .env file on import (can be overridden by CLI)
load_env_file(verbose=False)


@dataclass
class FAIRifierConfig:
    """Configuration for the FAIRifier system."""
    
    # Paths
    project_root: Path = Path(__file__).parent.parent
    kb_path: Path = project_root / "kb"
    schemas_path: Path = kb_path / "schemas" 
    shapes_path: Path = kb_path / "shapes"
    output_path: Path = project_root / "output"  # Default, will be overridden with timestamp in CLI
    
    # LLM Configuration
    # Providers: "ollama", "openai", "qwen", or "anthropic" (claude)
    llm_provider: str = "ollama"
    llm_model: str = "qwen3:30b"  # Model name
    # For Ollama/Qwen (OpenAI-compatible APIs)
    llm_base_url: str = "http://localhost:11434"
    llm_api_key: Optional[str] = None  # For OpenAI/Qwen/Anthropic
    embedding_model: str = "nomic-embed-text"
    llm_temperature: float = 0.5
    llm_max_tokens: int = 100000
    
    # Processing limits
    max_document_size_mb: int = 50
    max_processing_time_minutes: int = 10
    
    # Confidence thresholds
    min_confidence_threshold: float = 0.75
    auto_approve_threshold: float = 0.90
    
    # FAIR standards
    required_fields_coverage: float = 0.8  # Minimum required field coverage
    default_mixs_package: str = "MIMS"  # Default MIxS package
    
    # External services
    # FAIR Data Station API URL (default: local)
    fair_ds_api_url: Optional[str] = "http://localhost:8083"
    qdrant_url: Optional[str] = None  # Vector database (optional)
    grobid_url: Optional[str] = None  # PDF parsing service (optional)
    
    # LangSmith configuration
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "fairifier"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    enable_langsmith: bool = True  # Enabled by default
    
    def __post_init__(self):
        """Create necessary directories."""
        self.output_path.mkdir(exist_ok=True)
        self.kb_path.mkdir(exist_ok=True)
        self.schemas_path.mkdir(exist_ok=True)
        self.shapes_path.mkdir(exist_ok=True)


def apply_env_overrides(config_instance: FAIRifierConfig):
    """Apply environment variable overrides to a config instance."""
    # Ensure correct model name is used
    if os.getenv("FAIRIFIER_LLM_MODEL"):
        config_instance.llm_model = os.getenv("FAIRIFIER_LLM_MODEL")
    else:
        # Use model from config file
        config_instance.llm_model = "qwen3:30b"

    if os.getenv("FAIRIFIER_LLM_BASE_URL"):
        config_instance.llm_base_url = os.getenv("FAIRIFIER_LLM_BASE_URL")

    if os.getenv("QDRANT_URL"):
        config_instance.qdrant_url = os.getenv("QDRANT_URL")

    if os.getenv("GROBID_URL"):
        config_instance.grobid_url = os.getenv("GROBID_URL")

    if os.getenv("LANGSMITH_API_KEY"):
        config_instance.langsmith_api_key = os.getenv("LANGSMITH_API_KEY")
        config_instance.enable_langsmith = True

    # Auto-enable tracing environment variables if API key is set
    if config_instance.langsmith_api_key and config_instance.enable_langsmith:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = config_instance.langsmith_project

    if os.getenv("LANGSMITH_PROJECT"):
        config_instance.langsmith_project = os.getenv("LANGSMITH_PROJECT")

    if os.getenv("LANGSMITH_ENDPOINT"):
        config_instance.langsmith_endpoint = os.getenv("LANGSMITH_ENDPOINT")

    # LLM provider configuration
    if os.getenv("LLM_PROVIDER"):
        config_instance.llm_provider = os.getenv("LLM_PROVIDER").lower()

    if os.getenv("LLM_API_KEY"):
        config_instance.llm_api_key = os.getenv("LLM_API_KEY")

    # Qwen API base URL (default: Alibaba Cloud DashScope)
    if os.getenv("QWEN_API_BASE_URL"):
        config_instance.llm_base_url = os.getenv("QWEN_API_BASE_URL")
    elif (config_instance.llm_provider == "qwen" and
          config_instance.llm_base_url == "http://localhost:11434"):
        # Default Qwen API endpoint (DashScope OpenAI-compatible)
        config_instance.llm_base_url = (
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
        )

    # OpenAI API base URL (default: official OpenAI API)
    if (os.getenv("OPENAI_API_BASE_URL") and
            config_instance.llm_provider == "openai"):
        config_instance.llm_base_url = os.getenv("OPENAI_API_BASE_URL")
    elif (config_instance.llm_provider == "openai" and
          config_instance.llm_base_url == "http://localhost:11434"):
        # Default OpenAI API endpoint
        config_instance.llm_base_url = "https://api.openai.com/v1"

    if os.getenv("LLM_TEMPERATURE"):
        config_instance.llm_temperature = float(os.getenv("LLM_TEMPERATURE"))

    if os.getenv("LLM_MAX_TOKENS"):
        config_instance.llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS"))

    if os.getenv("FAIR_DS_API_URL"):
        config_instance.fair_ds_api_url = os.getenv("FAIR_DS_API_URL")


# Global config instance
config = FAIRifierConfig()

# Apply environment overrides
apply_env_overrides(config)
