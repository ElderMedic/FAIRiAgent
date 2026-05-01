"""Configuration management for FAIRifier."""

import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple
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
    skills_dir: Path = project_root / "fairifier" / "skills"
    # Extra SKILL.md roots merged into the same /skills/ virtual tree (later wins on collision).
    # Populated from FAIRIFIER_SKILLS_EXTRA_DIRS and CLAUDE_SKILLS_PATH (see apply_env_overrides).
    skills_extra_dirs: Tuple[Path, ...] = ()
    # When true, also load ~/.claude/skills and <project>/.claude/skills if present (Claude Code layout).
    import_claude_skills: bool = False
    
    # LLM Configuration
    # Providers: "ollama", "openai", "qwen", "gemini", or "anthropic" (claude)
    llm_provider: str = "ollama"
    llm_model: str = "qwen3:30b"  # Model name
    # For Ollama/Qwen (OpenAI-compatible APIs). Gemini/Anthropic use provider defaults.
    llm_base_url: str = "http://localhost:11434"
    llm_api_key: Optional[str] = None  # For OpenAI/Qwen/Gemini/Anthropic
    embedding_model: str = "nomic-embed-text"
    llm_temperature: float = 0.3  # Recommended for structured extraction; keep consistent across configs (control variable)
    llm_max_tokens: int = 8192  # Conservative default for test/dev cost control
    llm_enable_thinking: bool = False  # Enable thinking mode (requires streaming for some models)
    enable_deep_agents: bool = True  # Use deepagents inner loops when dependency is available
    
    # Document parsing context limits (characters)
    # Modern LLMs support 200K+ tokens (~800K chars), these limits are conservative
    max_doc_context_markdown: int = 200000  # Conservative default to cap input-token cost in test/dev
    max_doc_context_text: int = 120000      # Conservative default to cap input-token cost in test/dev
    multi_file_max_inputs: int = 8  # Cap number of files aggregated from directory/zip input
    table_preview_max_rows: int = 120  # Cap tabular rows rendered into text context
    table_preview_max_cols: int = 24  # Cap tabular columns rendered into text context

    # Source workspace + agentic search budgets. These limit what is exposed to
    # prompts per tool call, not what is preserved on disk.
    source_workspace_enabled: bool = True
    source_workspace_dir_name: str = "source_workspace"
    source_max_selected_inputs: int = 8
    source_inventory_max_chars_per_source: int = 4000
    source_read_max_chars: int = 8000
    source_grep_context_chars: int = 600
    source_max_search_results: int = 20
    source_role_detection_enabled: bool = True
    source_min_relevance_score: float = 0.35
    source_outlier_policy: str = "downweight"
    source_main_role_bonus: float = 0.25
    source_supplement_role_bonus: float = 0.10
    source_require_study_identity_match: bool = False
    metadata_context_mode: str = "agentic_search"
    metadata_field_search_enabled: bool = True
    metadata_max_evidence_snippets_per_field: int = 5
    metadata_max_context_chars_per_field: int = 12000
    metadata_allow_direct_document_fallback: bool = True
    metadata_source_ref_min_confidence: float = 0.75
    metadata_source_ref_downgrade_confidence: float = 0.6
    table_full_scan_enabled: bool = True
    table_search_max_rows: int = 5000
    table_search_max_matches: int = 50
    
    # Processing limits
    max_document_size_mb: int = 50
    max_processing_time_minutes: int = 10
    
    # Retry configuration
    max_step_retries: int = 2  # Default budget favors robustness over minimum token spend
    max_global_retries: int = 5  # Allow planner/critic loops to recover from upstream misses
    
    # Confidence thresholds
    min_confidence_threshold: float = 0.75
    auto_approve_threshold: float = 0.90
    
    # Critic rubric + decision thresholds
    critic_rubric_path: Path = project_root / "docs" / "en" / "development" / "critic_rubric.yaml"
    critic_accept_threshold_document_parser: float = 0.75  # ACCEPT threshold for DocumentParser
    critic_accept_threshold_knowledge_retriever: float = 0.7  # ACCEPT threshold for KnowledgeRetriever
    critic_accept_threshold_json_generator: float = 0.75  # ACCEPT threshold for JSONGenerator
    critic_accept_threshold_general: float = 0.7  # General ACCEPT threshold for LLM evaluation
    critic_retry_min_threshold: float = 0.4  # Minimum score for RETRY (below this is ESCALATE)
    critic_retry_max_threshold: float = 0.69  # Maximum score for RETRY (above this is ACCEPT)
    
    # Confidence aggregation
    confidence_weight_critic: float = 0.5
    confidence_weight_structural: float = 0.3
    confidence_weight_validation: float = 0.2
    structural_coverage_target: float = 0.75
    evidence_coverage_target: float = 0.7
    validation_pass_target: float = 0.8
    
    # FAIR standards
    required_fields_coverage: float = 0.8  # Minimum required field coverage
    default_mixs_package: str = "MIMS"  # Default MIxS package
    
    # External services
    # FAIR Data Station API URL (default: local)
    fair_ds_api_url: Optional[str] = "http://localhost:8083"
    qdrant_url: Optional[str] = None  # Vector database (optional)
    crossref_mailto: Optional[str] = None  # Contact email for polite Crossref API usage
    
    # Document conversion (MinerU)
    mineru_enabled: bool = False
    mineru_cli_path: str = "mineru"
    mineru_backend: str = "vlm-http-client"
    mineru_server_url: Optional[str] = "http://localhost:30000"
    mineru_timeout_seconds: int = 300
    # Reuse MinerU GPU output for identical uploads (SHA-256 of file bytes)
    mineru_cache_enabled: bool = True
    # Shared across runs; keep next to default ``output`` so permissions match project outputs
    mineru_cache_dir: Path = project_root / "output" / ".mineru_cache"

    # Deep agent inner-loop contracts
    react_loop_max_iterations: int = 6
    react_loop_max_tool_calls: int = 18
    cross_layer_max_restarts: int = 1  # Max rollback cycles from JSON -> retrieval
    react_loop_document_parser_target_fields: int = 6
    react_loop_document_parser_target_packets: int = 8
    react_loop_knowledge_retriever_target_packages: int = 4
    react_loop_knowledge_retriever_target_optional_fields: int = 12
    
    # Langfuse configuration (optional observability, parallel to LangSmith)
    enable_langfuse: bool = False
    langfuse_host: Optional[str] = None  # None = SDK default (cloud.langfuse.com)
    langfuse_secret_key: Optional[str] = None
    langfuse_public_key: Optional[str] = None
    
    # LangSmith configuration
    langsmith_api_key: Optional[str] = None
    # Default project name (will be enhanced with FAIR naming scheme)
    # FAIR naming: fairifier-{environment}-{provider}-{model}-{timestamp}
    langsmith_project: str = "fairifier"  # Base name, enhanced at runtime
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    enable_langsmith: bool = False  # Off by default; set True when LANGSMITH_API_KEY is set
    langsmith_use_fair_naming: bool = True  # Use FAIR-compliant naming scheme
    
    # Checkpointer configuration
    # Options: "none" (stateless), "memory" (dev/test only), "sqlite" (production)
    checkpointer_backend: str = "sqlite"
    checkpoint_db_path: Path = project_root / "output" / ".checkpoints.db"

    # Post-output static checks (CLI, after metadata.json is written)
    validate_output_json: bool = True  # JSON syntax (json.load)
    validate_output_json_fair_format: bool = True  # FAIR/ISA rules (same as SchemaValidator)
    
    # Mem0 Memory Layer Configuration (Optional)
    # Provides persistent semantic memory for context compression and retrieval
    # Mem0 uses its own LLM source (provider/model/base_url) independent of the main workflow LLM
    mem0_enabled: bool = True  # On by default; auto health-check + graceful fallback
    mem0_strict: bool = False  # If True and mem0_enabled, raise when mem0 init fails
    mem0_auto_setup: bool = True  # Detect dependencies and auto-adjust mem0 runtime profile
    mem0_auto_start_qdrant: bool = True  # Auto-start local Qdrant via Docker when unreachable
    mem0_qdrant_container_name: str = "fairiagent-qdrant"
    mem0_healthcheck_timeout_seconds: int = 2
    mem0_llm_provider: str = "ollama"  # mem0 LLM provider: ollama, openai, anthropic (mem0-supported only)
    mem0_llm_model: Optional[str] = None  # mem0 LLM model (defaults to llm_model if not set)
    mem0_ollama_base_url: Optional[str] = None  # Base URL for mem0 when provider=ollama
    mem0_llm_base_url: Optional[str] = None  # Base URL for mem0 when provider=openai (e.g. OpenAI-compatible API)
    mem0_llm_api_key: Optional[str] = None  # API key for mem0 when provider=openai or anthropic
    mem0_embedding_provider: str = "ollama"  # Embedder provider: ollama or openai-compatible API
    mem0_embedding_model: str = "nomic-embed-text"  # Ollama embedding model
    mem0_embedding_base_url: Optional[str] = None  # Base URL for openai-compatible embedding APIs
    mem0_embedding_api_key: Optional[str] = None  # API key for openai-compatible embedding APIs
    mem0_embedding_dims: int = 768  # Vector dimension (nomic-embed-text=768; OpenAI ada-002=1536)
    mem0_qdrant_host: str = "localhost"  # Qdrant server host
    mem0_qdrant_port: int = 6333  # Qdrant server port
    mem0_collection_name: str = "fairifier_memories"  # Qdrant collection name
    memory_scope_id: Optional[str] = None  # Override mem0 scope independently from project_id/thread_id
    
    @property
    def skill_roots(self) -> List[Path]:
        """Ordered filesystem roots for Anthropic-style skills (SKILL.md discovery)."""
        from .skills import normalize_existing_skill_roots

        candidates: List[Path] = [self.skills_dir]
        candidates.extend(self.skills_extra_dirs)
        if self.import_claude_skills:
            candidates.append(Path.home() / ".claude" / "skills")
            candidates.append(self.project_root / ".claude" / "skills")
        return normalize_existing_skill_roots(candidates)

    def __post_init__(self):
        """Create necessary directories."""
        self.output_path.mkdir(exist_ok=True)
        self.kb_path.mkdir(exist_ok=True)
        self.schemas_path.mkdir(exist_ok=True)
        self.shapes_path.mkdir(exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        
        # Ensure checkpoint DB parent directory exists if using sqlite
        if self.checkpointer_backend == "sqlite":
            self.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.mineru_cache_enabled:
            try:
                self.mineru_cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logging.getLogger(__name__).warning(
                    "MinerU cache directory not usable (%s): %s — caching disabled at startup",
                    self.mineru_cache_dir,
                    exc,
                )


def _parse_path_list_from_env(key: str) -> List[Path]:
    """Split an env var by ``os.pathsep`` into non-empty expanded paths."""
    raw = os.getenv(key)
    if not raw:
        return []
    out: List[Path] = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            out.append(Path(part).expanduser())
    return out


def apply_env_overrides(config_instance: FAIRifierConfig):
    """Apply environment variable overrides to a config instance."""
    def _normalize_provider(raw: Optional[str]) -> str:
        value = (raw or "").strip().lower()
        if value == "google":
            return "gemini"
        if value == "claude":
            return "anthropic"
        return value

    # Ensure correct model name is used
    if os.getenv("FAIRIFIER_LLM_MODEL"):
        config_instance.llm_model = os.getenv("FAIRIFIER_LLM_MODEL")
    else:
        requested_provider = _normalize_provider(
            os.getenv("LLM_PROVIDER") or config_instance.llm_provider
        )
        if requested_provider == "qwen":
            config_instance.llm_model = "qwen-flash"
        elif requested_provider == "gemini":
            config_instance.llm_model = "gemini-3.1-pro-preview"
        else:
            config_instance.llm_model = "qwen3:30b"

    if os.getenv("FAIRIFIER_LLM_BASE_URL"):
        config_instance.llm_base_url = os.getenv("FAIRIFIER_LLM_BASE_URL")
    if os.getenv("FAIRIFIER_SKILLS_DIR"):
        config_instance.skills_dir = Path(os.getenv("FAIRIFIER_SKILLS_DIR"))

    extra_skill_roots = _parse_path_list_from_env("FAIRIFIER_SKILLS_EXTRA_DIRS")
    extra_skill_roots.extend(_parse_path_list_from_env("CLAUDE_SKILLS_PATH"))
    config_instance.skills_extra_dirs = tuple(extra_skill_roots)

    if os.getenv("FAIRIFIER_IMPORT_CLAUDE_SKILLS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        config_instance.import_claude_skills = True
    if os.getenv("FAIRIFIER_ENABLE_DEEP_AGENTS"):
        value = os.getenv("FAIRIFIER_ENABLE_DEEP_AGENTS").strip().lower()
        config_instance.enable_deep_agents = value in ("1", "true", "yes", "on")
    if os.getenv("REACT_LOOP_MAX_ITERATIONS"):
        config_instance.react_loop_max_iterations = int(os.getenv("REACT_LOOP_MAX_ITERATIONS"))
    if os.getenv("REACT_LOOP_MAX_TOOL_CALLS"):
        config_instance.react_loop_max_tool_calls = int(os.getenv("REACT_LOOP_MAX_TOOL_CALLS"))
    if os.getenv("FAIRIFIER_MULTI_FILE_MAX_INPUTS"):
        config_instance.multi_file_max_inputs = int(os.getenv("FAIRIFIER_MULTI_FILE_MAX_INPUTS"))
    if os.getenv("FAIRIFIER_TABLE_PREVIEW_MAX_ROWS"):
        config_instance.table_preview_max_rows = int(os.getenv("FAIRIFIER_TABLE_PREVIEW_MAX_ROWS"))
    if os.getenv("FAIRIFIER_TABLE_PREVIEW_MAX_COLS"):
        config_instance.table_preview_max_cols = int(os.getenv("FAIRIFIER_TABLE_PREVIEW_MAX_COLS"))
    if os.getenv("FAIRIFIER_SOURCE_WORKSPACE_ENABLED"):
        v = os.getenv("FAIRIFIER_SOURCE_WORKSPACE_ENABLED", "").strip().lower()
        config_instance.source_workspace_enabled = v in ("1", "true", "yes", "on")
    if os.getenv("FAIRIFIER_SOURCE_WORKSPACE_DIR_NAME"):
        config_instance.source_workspace_dir_name = os.getenv("FAIRIFIER_SOURCE_WORKSPACE_DIR_NAME")
    if os.getenv("FAIRIFIER_SOURCE_MAX_SELECTED_INPUTS"):
        config_instance.source_max_selected_inputs = int(os.getenv("FAIRIFIER_SOURCE_MAX_SELECTED_INPUTS"))
    if os.getenv("FAIRIFIER_SOURCE_INVENTORY_MAX_CHARS_PER_SOURCE"):
        config_instance.source_inventory_max_chars_per_source = int(
            os.getenv("FAIRIFIER_SOURCE_INVENTORY_MAX_CHARS_PER_SOURCE")
        )
    if os.getenv("FAIRIFIER_SOURCE_READ_MAX_CHARS"):
        config_instance.source_read_max_chars = int(os.getenv("FAIRIFIER_SOURCE_READ_MAX_CHARS"))
    if os.getenv("FAIRIFIER_SOURCE_GREP_CONTEXT_CHARS"):
        config_instance.source_grep_context_chars = int(os.getenv("FAIRIFIER_SOURCE_GREP_CONTEXT_CHARS"))
    if os.getenv("FAIRIFIER_SOURCE_MAX_SEARCH_RESULTS"):
        config_instance.source_max_search_results = int(os.getenv("FAIRIFIER_SOURCE_MAX_SEARCH_RESULTS"))
    if os.getenv("FAIRIFIER_SOURCE_ROLE_DETECTION_ENABLED"):
        v = os.getenv("FAIRIFIER_SOURCE_ROLE_DETECTION_ENABLED", "").strip().lower()
        config_instance.source_role_detection_enabled = v in ("1", "true", "yes", "on")
    if os.getenv("FAIRIFIER_SOURCE_MIN_RELEVANCE_SCORE"):
        config_instance.source_min_relevance_score = float(os.getenv("FAIRIFIER_SOURCE_MIN_RELEVANCE_SCORE"))
    if os.getenv("FAIRIFIER_SOURCE_OUTLIER_POLICY"):
        config_instance.source_outlier_policy = os.getenv("FAIRIFIER_SOURCE_OUTLIER_POLICY")
    if os.getenv("FAIRIFIER_SOURCE_MAIN_ROLE_BONUS"):
        config_instance.source_main_role_bonus = float(os.getenv("FAIRIFIER_SOURCE_MAIN_ROLE_BONUS"))
    if os.getenv("FAIRIFIER_SOURCE_SUPPLEMENT_ROLE_BONUS"):
        config_instance.source_supplement_role_bonus = float(os.getenv("FAIRIFIER_SOURCE_SUPPLEMENT_ROLE_BONUS"))
    if os.getenv("FAIRIFIER_SOURCE_REQUIRE_STUDY_IDENTITY_MATCH"):
        v = os.getenv("FAIRIFIER_SOURCE_REQUIRE_STUDY_IDENTITY_MATCH", "").strip().lower()
        config_instance.source_require_study_identity_match = v in ("1", "true", "yes", "on")
    if os.getenv("FAIRIFIER_METADATA_CONTEXT_MODE"):
        config_instance.metadata_context_mode = os.getenv("FAIRIFIER_METADATA_CONTEXT_MODE")
    if os.getenv("FAIRIFIER_METADATA_FIELD_SEARCH_ENABLED"):
        v = os.getenv("FAIRIFIER_METADATA_FIELD_SEARCH_ENABLED", "").strip().lower()
        config_instance.metadata_field_search_enabled = v in ("1", "true", "yes", "on")
    if os.getenv("FAIRIFIER_METADATA_MAX_EVIDENCE_SNIPPETS_PER_FIELD"):
        config_instance.metadata_max_evidence_snippets_per_field = int(
            os.getenv("FAIRIFIER_METADATA_MAX_EVIDENCE_SNIPPETS_PER_FIELD")
        )
    if os.getenv("FAIRIFIER_METADATA_MAX_CONTEXT_CHARS_PER_FIELD"):
        config_instance.metadata_max_context_chars_per_field = int(
            os.getenv("FAIRIFIER_METADATA_MAX_CONTEXT_CHARS_PER_FIELD")
        )
    if os.getenv("FAIRIFIER_METADATA_SOURCE_REF_MIN_CONFIDENCE"):
        config_instance.metadata_source_ref_min_confidence = float(
            os.getenv("FAIRIFIER_METADATA_SOURCE_REF_MIN_CONFIDENCE")
        )
    if os.getenv("FAIRIFIER_METADATA_SOURCE_REF_DOWNGRADE_CONFIDENCE"):
        config_instance.metadata_source_ref_downgrade_confidence = float(
            os.getenv("FAIRIFIER_METADATA_SOURCE_REF_DOWNGRADE_CONFIDENCE")
        )
    if os.getenv("FAIRIFIER_METADATA_ALLOW_DIRECT_DOCUMENT_FALLBACK"):
        v = os.getenv("FAIRIFIER_METADATA_ALLOW_DIRECT_DOCUMENT_FALLBACK", "").strip().lower()
        config_instance.metadata_allow_direct_document_fallback = v in ("1", "true", "yes", "on")
    if os.getenv("FAIRIFIER_TABLE_FULL_SCAN_ENABLED"):
        v = os.getenv("FAIRIFIER_TABLE_FULL_SCAN_ENABLED", "").strip().lower()
        config_instance.table_full_scan_enabled = v in ("1", "true", "yes", "on")
    if os.getenv("FAIRIFIER_TABLE_SEARCH_MAX_ROWS"):
        config_instance.table_search_max_rows = int(os.getenv("FAIRIFIER_TABLE_SEARCH_MAX_ROWS"))
    if os.getenv("FAIRIFIER_TABLE_SEARCH_MAX_MATCHES"):
        config_instance.table_search_max_matches = int(os.getenv("FAIRIFIER_TABLE_SEARCH_MAX_MATCHES"))
    if os.getenv("FAIRIFIER_CROSS_LAYER_MAX_RESTARTS"):
        config_instance.cross_layer_max_restarts = int(
            os.getenv("FAIRIFIER_CROSS_LAYER_MAX_RESTARTS")
        )

    if os.getenv("QDRANT_URL"):
        config_instance.qdrant_url = os.getenv("QDRANT_URL")
    if os.getenv("CROSSREF_MAILTO"):
        config_instance.crossref_mailto = os.getenv("CROSSREF_MAILTO")

    if os.getenv("LANGSMITH_API_KEY"):
        config_instance.langsmith_api_key = os.getenv("LANGSMITH_API_KEY")
        config_instance.enable_langsmith = True

    # LANGSMITH_DISABLE=1 or LANGCHAIN_TRACING_V2=false: disable tracing (default for production)
    if os.getenv("LANGSMITH_DISABLE", "").strip() in ("1", "true", "yes"):
        config_instance.enable_langsmith = False
    if os.getenv("LANGCHAIN_TRACING_V2", "").strip().lower() == "false":
        config_instance.enable_langsmith = False

    # Single source of truth: set env so LangChain/LangSmith SDK no-ops when disabled
    if config_instance.langsmith_api_key and config_instance.enable_langsmith:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = config_instance.langsmith_project
    else:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"

    if os.getenv("LANGSMITH_PROJECT"):
        config_instance.langsmith_project = os.getenv("LANGSMITH_PROJECT")
    
    # FAIR naming configuration
    if os.getenv("LANGSMITH_USE_FAIR_NAMING"):
        config_instance.langsmith_use_fair_naming = os.getenv("LANGSMITH_USE_FAIR_NAMING").lower() in ("true", "1", "yes")

    if os.getenv("LANGSMITH_ENDPOINT"):
        config_instance.langsmith_endpoint = os.getenv("LANGSMITH_ENDPOINT")

    # Langfuse observability (optional, parallel to LangSmith)
    if os.getenv("LANGFUSE_SECRET_KEY"):
        config_instance.langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if os.getenv("LANGFUSE_PUBLIC_KEY"):
        config_instance.langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    if os.getenv("LANGFUSE_HOST"):
        config_instance.langfuse_host = os.getenv("LANGFUSE_HOST")
    if os.getenv("LANGFUSE_ENABLE", "").strip().lower() in ("1", "true", "yes"):
        config_instance.enable_langfuse = True
    if config_instance.langfuse_secret_key and config_instance.langfuse_public_key:
        config_instance.enable_langfuse = True
    if os.getenv("LANGFUSE_DISABLE", "").strip().lower() in ("1", "true", "yes"):
        config_instance.enable_langfuse = False

    # LLM provider configuration
    if os.getenv("LLM_PROVIDER"):
        config_instance.llm_provider = _normalize_provider(os.getenv("LLM_PROVIDER"))
    else:
        config_instance.llm_provider = _normalize_provider(config_instance.llm_provider)

    if os.getenv("LLM_API_KEY"):
        config_instance.llm_api_key = os.getenv("LLM_API_KEY")
    # Qwen/DashScope: fallback to DASHSCOPE_API_KEY if LLM_API_KEY not set
    if config_instance.llm_provider == "qwen" and not config_instance.llm_api_key:
        config_instance.llm_api_key = os.getenv("DASHSCOPE_API_KEY")
    # Gemini: prefer GOOGLE_API_KEY, then GEMINI_API_KEY
    if config_instance.llm_provider == "gemini" and not config_instance.llm_api_key:
        config_instance.llm_api_key = (
            os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        )
    if config_instance.llm_provider == "gemini" and config_instance.llm_model == "gemini-3.1-pro":
        config_instance.llm_model = "gemini-3.1-pro-preview"

    # Provider-specific base URL configuration
    # IMPORTANT: Each provider block should only set base_url for its own provider
    
    # Qwen API base URL (default: Alibaba Cloud DashScope)
    if config_instance.llm_provider == "qwen":
        if os.getenv("QWEN_API_BASE_URL"):
            config_instance.llm_base_url = os.getenv("QWEN_API_BASE_URL")
        elif config_instance.llm_base_url == "http://localhost:11434":
            # Default Qwen API endpoint (DashScope OpenAI-compatible)
            config_instance.llm_base_url = (
                "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            )
    
    # Ollama base URL (default: localhost:11434)
    elif config_instance.llm_provider == "ollama":
        if os.getenv("FAIRIFIER_LLM_BASE_URL"):
            # Use explicitly set base URL
            config_instance.llm_base_url = os.getenv("FAIRIFIER_LLM_BASE_URL")
        else:
            # Default Ollama endpoint
            config_instance.llm_base_url = "http://localhost:11434"

    # OpenAI API base URL (default: official OpenAI API)
    elif config_instance.llm_provider == "openai":
        if os.getenv("OPENAI_API_BASE_URL"):
            config_instance.llm_base_url = os.getenv("OPENAI_API_BASE_URL")
        else:
            # Default OpenAI API endpoint
            config_instance.llm_base_url = "https://api.openai.com/v1"

    # Google Gemini - official SDK/API endpoint, custom base_url not used here
    elif config_instance.llm_provider == "gemini":
        config_instance.llm_base_url = None
    
    # Anthropic Claude - uses official API, no custom base_url needed
    elif config_instance.llm_provider == "anthropic":
        # Anthropic SDK uses its own endpoint, base_url not applicable
        config_instance.llm_base_url = None

    if os.getenv("LLM_TEMPERATURE"):
        config_instance.llm_temperature = float(os.getenv("LLM_TEMPERATURE"))

    if os.getenv("LLM_MAX_TOKENS"):
        config_instance.llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS"))
    
    # Thinking mode configuration
    if os.getenv("LLM_ENABLE_THINKING"):
        config_instance.llm_enable_thinking = os.getenv("LLM_ENABLE_THINKING").lower() in ("true", "1", "yes")
    
    # Document parsing context limits
    if os.getenv("MAX_DOC_CONTEXT_MARKDOWN"):
        config_instance.max_doc_context_markdown = int(os.getenv("MAX_DOC_CONTEXT_MARKDOWN"))
    
    if os.getenv("MAX_DOC_CONTEXT_TEXT"):
        config_instance.max_doc_context_text = int(os.getenv("MAX_DOC_CONTEXT_TEXT"))

    if os.getenv("FAIR_DS_API_URL"):
        config_instance.fair_ds_api_url = os.getenv("FAIR_DS_API_URL")
    
    # Processing limits
    if os.getenv("FAIRIFIER_MAX_DOCUMENT_SIZE_MB"):
        config_instance.max_document_size_mb = int(os.getenv("FAIRIFIER_MAX_DOCUMENT_SIZE_MB"))
    if os.getenv("FAIRIFIER_MAX_PROCESSING_TIME_MINUTES"):
        config_instance.max_processing_time_minutes = int(os.getenv("FAIRIFIER_MAX_PROCESSING_TIME_MINUTES"))
    if os.getenv("FAIRIFIER_MIN_CONFIDENCE_THRESHOLD"):
        config_instance.min_confidence_threshold = float(os.getenv("FAIRIFIER_MIN_CONFIDENCE_THRESHOLD"))
    
    # Retry configuration
    if os.getenv("FAIRIFIER_MAX_STEP_RETRIES"):
        config_instance.max_step_retries = int(os.getenv("FAIRIFIER_MAX_STEP_RETRIES"))
    
    if os.getenv("FAIRIFIER_MAX_GLOBAL_RETRIES"):
        config_instance.max_global_retries = int(os.getenv("FAIRIFIER_MAX_GLOBAL_RETRIES"))
    
    # Critic rubric path
    if os.getenv("FAIRIFIER_CRITIC_RUBRIC_PATH"):
        config_instance.critic_rubric_path = Path(os.getenv("FAIRIFIER_CRITIC_RUBRIC_PATH"))
    
    # Critic decision thresholds
    if os.getenv("FAIRIFIER_CRITIC_ACCEPT_THRESHOLD_DOCUMENT_PARSER"):
        config_instance.critic_accept_threshold_document_parser = float(
            os.getenv("FAIRIFIER_CRITIC_ACCEPT_THRESHOLD_DOCUMENT_PARSER")
        )
    
    if os.getenv("FAIRIFIER_CRITIC_ACCEPT_THRESHOLD_KNOWLEDGE_RETRIEVER"):
        config_instance.critic_accept_threshold_knowledge_retriever = float(
            os.getenv("FAIRIFIER_CRITIC_ACCEPT_THRESHOLD_KNOWLEDGE_RETRIEVER")
        )
    
    if os.getenv("FAIRIFIER_CRITIC_ACCEPT_THRESHOLD_JSON_GENERATOR"):
        config_instance.critic_accept_threshold_json_generator = float(
            os.getenv("FAIRIFIER_CRITIC_ACCEPT_THRESHOLD_JSON_GENERATOR")
        )
    
    if os.getenv("FAIRIFIER_CRITIC_ACCEPT_THRESHOLD_GENERAL"):
        config_instance.critic_accept_threshold_general = float(
            os.getenv("FAIRIFIER_CRITIC_ACCEPT_THRESHOLD_GENERAL")
        )
    
    if os.getenv("FAIRIFIER_CRITIC_RETRY_MIN_THRESHOLD"):
        config_instance.critic_retry_min_threshold = float(
            os.getenv("FAIRIFIER_CRITIC_RETRY_MIN_THRESHOLD")
        )
    
    if os.getenv("FAIRIFIER_CRITIC_RETRY_MAX_THRESHOLD"):
        config_instance.critic_retry_max_threshold = float(
            os.getenv("FAIRIFIER_CRITIC_RETRY_MAX_THRESHOLD")
        )
    
    # Confidence aggregation weights
    if os.getenv("FAIRIFIER_CONF_WEIGHT_CRITIC"):
        config_instance.confidence_weight_critic = float(os.getenv("FAIRIFIER_CONF_WEIGHT_CRITIC"))
    if os.getenv("FAIRIFIER_CONF_WEIGHT_STRUCTURAL"):
        config_instance.confidence_weight_structural = float(os.getenv("FAIRIFIER_CONF_WEIGHT_STRUCTURAL"))
    if os.getenv("FAIRIFIER_CONF_WEIGHT_VALIDATION"):
        config_instance.confidence_weight_validation = float(os.getenv("FAIRIFIER_CONF_WEIGHT_VALIDATION"))
    if os.getenv("FAIRIFIER_STRUCTURAL_COVERAGE_TARGET"):
        config_instance.structural_coverage_target = float(os.getenv("FAIRIFIER_STRUCTURAL_COVERAGE_TARGET"))
    if os.getenv("FAIRIFIER_EVIDENCE_COVERAGE_TARGET"):
        config_instance.evidence_coverage_target = float(os.getenv("FAIRIFIER_EVIDENCE_COVERAGE_TARGET"))
    if os.getenv("FAIRIFIER_VALIDATION_PASS_TARGET"):
        config_instance.validation_pass_target = float(os.getenv("FAIRIFIER_VALIDATION_PASS_TARGET"))
    
    # MinerU document conversion
    if os.getenv("MINERU_ENABLED"):
        enabled_value = os.getenv("MINERU_ENABLED").lower()
        config_instance.mineru_enabled = enabled_value in ("true", "1", "yes")
    if os.getenv("MINERU_CLI_PATH"):
        config_instance.mineru_cli_path = os.getenv("MINERU_CLI_PATH")
    if os.getenv("MINERU_BACKEND"):
        config_instance.mineru_backend = os.getenv("MINERU_BACKEND")
    if os.getenv("MINERU_SERVER_URL"):
        config_instance.mineru_server_url = os.getenv("MINERU_SERVER_URL")
    if os.getenv("MINERU_TIMEOUT_SECONDS"):
        timeout_value = os.getenv("MINERU_TIMEOUT_SECONDS")
        config_instance.mineru_timeout_seconds = int(timeout_value)
    if os.getenv("MINERU_CACHE_ENABLED"):
        v = os.getenv("MINERU_CACHE_ENABLED", "").strip().lower()
        config_instance.mineru_cache_enabled = v not in ("0", "false", "no", "off")
    if os.getenv("MINERU_CACHE_DIR"):
        config_instance.mineru_cache_dir = Path(os.getenv("MINERU_CACHE_DIR"))
    
    # Checkpointer configuration
    if os.getenv("CHECKPOINTER_BACKEND"):
        backend = os.getenv("CHECKPOINTER_BACKEND").lower()
        if backend in ("none", "memory", "sqlite"):
            config_instance.checkpointer_backend = backend
        else:
            raise ValueError(f"Invalid CHECKPOINTER_BACKEND: {backend}. Must be 'none', 'memory', or 'sqlite'")
    
    if os.getenv("CHECKPOINT_DB_PATH"):
        config_instance.checkpoint_db_path = Path(os.getenv("CHECKPOINT_DB_PATH"))

    # Post-output JSON / FAIR format checks (CLI)
    if os.getenv("FAIRIFIER_VALIDATE_OUTPUT_JSON"):
        v = os.getenv("FAIRIFIER_VALIDATE_OUTPUT_JSON").strip().lower()
        config_instance.validate_output_json = v not in ("0", "false", "no", "off")
    if os.getenv("FAIRIFIER_VALIDATE_OUTPUT_JSON_FAIR_FORMAT"):
        v = os.getenv("FAIRIFIER_VALIDATE_OUTPUT_JSON_FAIR_FORMAT").strip().lower()
        config_instance.validate_output_json_fair_format = v not in (
            "0",
            "false",
            "no",
            "off",
        )
    
    # Mem0 Memory Layer configuration
    if os.getenv("MEM0_ENABLED"):
        enabled_value = os.getenv("MEM0_ENABLED").lower()
        config_instance.mem0_enabled = enabled_value in ("true", "1", "yes")
    if os.getenv("MEM0_STRICT"):
        strict_value = os.getenv("MEM0_STRICT").lower()
        config_instance.mem0_strict = strict_value in ("true", "1", "yes")
    if os.getenv("MEM0_AUTO_SETUP"):
        auto_setup_value = os.getenv("MEM0_AUTO_SETUP").lower()
        config_instance.mem0_auto_setup = auto_setup_value in ("true", "1", "yes")
    if os.getenv("MEM0_AUTO_START_QDRANT"):
        auto_qdrant_value = os.getenv("MEM0_AUTO_START_QDRANT").lower()
        config_instance.mem0_auto_start_qdrant = auto_qdrant_value in ("true", "1", "yes")
    if os.getenv("MEM0_QDRANT_CONTAINER_NAME"):
        config_instance.mem0_qdrant_container_name = os.getenv("MEM0_QDRANT_CONTAINER_NAME")
    if os.getenv("MEM0_HEALTHCHECK_TIMEOUT_SECONDS"):
        try:
            config_instance.mem0_healthcheck_timeout_seconds = int(
                os.getenv("MEM0_HEALTHCHECK_TIMEOUT_SECONDS")
            )
        except ValueError:
            pass
    
    if os.getenv("MEM0_LLM_PROVIDER"):
        config_instance.mem0_llm_provider = os.getenv("MEM0_LLM_PROVIDER").lower()
    if os.getenv("MEM0_LLM_BASE_URL"):
        config_instance.mem0_llm_base_url = os.getenv("MEM0_LLM_BASE_URL")
    if os.getenv("MEM0_LLM_API_KEY"):
        config_instance.mem0_llm_api_key = os.getenv("MEM0_LLM_API_KEY")
    if os.getenv("MEM0_OLLAMA_BASE_URL"):
        config_instance.mem0_ollama_base_url = os.getenv("MEM0_OLLAMA_BASE_URL")
    if os.getenv("MEM0_EMBEDDING_PROVIDER"):
        config_instance.mem0_embedding_provider = os.getenv("MEM0_EMBEDDING_PROVIDER").lower()
    if os.getenv("MEM0_EMBEDDING_BASE_URL"):
        config_instance.mem0_embedding_base_url = os.getenv("MEM0_EMBEDDING_BASE_URL")
    if os.getenv("MEM0_EMBEDDING_API_KEY"):
        config_instance.mem0_embedding_api_key = os.getenv("MEM0_EMBEDDING_API_KEY")
    
    if os.getenv("MEM0_EMBEDDING_MODEL"):
        config_instance.mem0_embedding_model = os.getenv("MEM0_EMBEDDING_MODEL")
    if os.getenv("MEM0_EMBEDDING_DIMS"):
        try:
            config_instance.mem0_embedding_dims = int(os.getenv("MEM0_EMBEDDING_DIMS"))
        except ValueError:
            pass
    
    if os.getenv("MEM0_LLM_MODEL"):
        config_instance.mem0_llm_model = os.getenv("MEM0_LLM_MODEL")
    
    if os.getenv("MEM0_QDRANT_HOST"):
        config_instance.mem0_qdrant_host = os.getenv("MEM0_QDRANT_HOST")
    
    if os.getenv("MEM0_QDRANT_PORT"):
        config_instance.mem0_qdrant_port = int(os.getenv("MEM0_QDRANT_PORT"))
    
    # Also support MEM0_QDRANT_URL as "host:port" format
    if os.getenv("MEM0_QDRANT_URL"):
        qdrant_url = os.getenv("MEM0_QDRANT_URL")
        # Parse URL like "http://localhost:6333" or "localhost:6333"
        if "://" in qdrant_url:
            qdrant_url = qdrant_url.split("://", 1)[1]
        if ":" in qdrant_url:
            host, port = qdrant_url.rsplit(":", 1)
            config_instance.mem0_qdrant_host = host
            try:
                config_instance.mem0_qdrant_port = int(port)
            except ValueError:
                pass
        else:
            config_instance.mem0_qdrant_host = qdrant_url
    
    if os.getenv("MEM0_COLLECTION_NAME"):
        config_instance.mem0_collection_name = os.getenv("MEM0_COLLECTION_NAME")
    if os.getenv("FAIRIFIER_MEMORY_SCOPE_ID"):
        config_instance.memory_scope_id = os.getenv("FAIRIFIER_MEMORY_SCOPE_ID")


def apply_budget_guardrails(config_instance: FAIRifierConfig):
    """Apply conservative token/cost guardrails unless explicitly disabled.

    This protects local testing from stale high-budget .env settings.
    Set FAIRIFIER_ALLOW_EXPENSIVE_RUNS=true to opt out.
    """
    allow_expensive = os.getenv("FAIRIFIER_ALLOW_EXPENSIVE_RUNS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if allow_expensive:
        return

    config_instance.llm_max_tokens = min(config_instance.llm_max_tokens, 8192)
    config_instance.max_doc_context_markdown = min(
        config_instance.max_doc_context_markdown, 200000
    )
    config_instance.max_doc_context_text = min(
        config_instance.max_doc_context_text, 120000
    )
    config_instance.max_step_retries = min(config_instance.max_step_retries, 2)
    config_instance.max_global_retries = min(config_instance.max_global_retries, 5)
    config_instance.react_loop_max_iterations = min(
        config_instance.react_loop_max_iterations, 6
    )
    config_instance.react_loop_max_tool_calls = min(
        config_instance.react_loop_max_tool_calls, 18
    )
    config_instance.cross_layer_max_restarts = min(
        config_instance.cross_layer_max_restarts, 2
    )


# Global config instance
config = FAIRifierConfig()

# Apply environment overrides
apply_env_overrides(config)
apply_budget_guardrails(config)
