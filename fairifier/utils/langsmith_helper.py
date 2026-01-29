"""
LangSmith naming helper for FAIR-compliant project names.

This module implements a FAIR-compliant naming scheme for LangSmith projects:
- Findable: Includes timestamp, environment, and model info
- Accessible: Clear structure, easy to understand
- Interoperable: Standardized format, programmatically parsable
- Reusable: Contains metadata for reproducibility
"""

import os
import re
from datetime import datetime
from typing import Optional


def generate_fair_langsmith_project_name(
    environment: Optional[str] = None,
    model_provider: Optional[str] = None,
    model_name: Optional[str] = None,
    project_id: Optional[str] = None,
    custom_suffix: Optional[str] = None
) -> str:
    """
    Generate a FAIR-compliant LangSmith project name.
    
    Naming scheme:
        fairifier-{environment}-{model_provider}-{model_name}-{timestamp}
    
    Examples:
        - fairifier-cli-ollama-qwen3_8b-20260128_213830
        - fairifier-api-openai-gpt4-20260128_143025
        - fairifier-eval-anthropic-claude3-20260128_093012
        - fairifier-test-ollama-llama3_70b-20260128_120000
    
    FAIR Principles Applied:
        - Findable: Timestamp and structured naming enable easy searching
        - Accessible: Clear, human-readable components
        - Interoperable: Standardized format, can be parsed programmatically
        - Reusable: Contains metadata (environment, model) for reproducibility
    
    Args:
        environment: Execution environment (cli, api, ui, eval, test, dev)
                    If None, auto-detected from context
        model_provider: LLM provider (ollama, openai, anthropic, qwen)
                       If None, read from env or config
        model_name: Model name (e.g., qwen3:8b, gpt-4o, claude-3-5-sonnet)
                   If None, read from env or config
        project_id: Optional project_id to extract timestamp from
                   Format: fairifier_YYYYMMDD_HHMMSS
        custom_suffix: Optional custom suffix to append
    
    Returns:
        FAIR-compliant LangSmith project name
    
    Examples:
        >>> generate_fair_langsmith_project_name(
        ...     environment="cli",
        ...     model_provider="ollama",
        ...     model_name="qwen3:8b",
        ...     project_id="fairifier_20260128_213830"
        ... )
        'fairifier-cli-ollama-qwen3_8b-20260128_213830'
        
        >>> generate_fair_langsmith_project_name(
        ...     environment="eval",
        ...     model_provider="openai",
        ...     model_name="gpt-4o"
        ... )
        'fairifier-eval-openai-gpt4o-20260128_143025'  # current timestamp
    """
    components = ["fairifier"]
    
    # 1. Environment (auto-detect if not provided)
    if environment is None:
        environment = _detect_environment()
    env_clean = _sanitize_component(environment)
    if env_clean:
        components.append(env_clean)
    
    # 2. Model Provider (from args or env)
    if model_provider is None:
        model_provider = os.getenv("LLM_PROVIDER", "ollama")
    provider_clean = _sanitize_component(model_provider)
    if provider_clean:
        components.append(provider_clean)
    
    # 3. Model Name (from args or env, simplified)
    if model_name is None:
        model_name = os.getenv("FAIRIFIER_LLM_MODEL", "unknown")
    model_clean = _sanitize_model_name(model_name)
    if model_clean:
        components.append(model_clean)
    
    # 4. Timestamp (from project_id or current time)
    timestamp = _extract_or_generate_timestamp(project_id)
    components.append(timestamp)
    
    # 5. Custom suffix (optional)
    if custom_suffix:
        suffix_clean = _sanitize_component(custom_suffix)
        if suffix_clean:
            components.append(suffix_clean)
    
    # Join with hyphens (standard separator)
    project_name = "-".join(components)
    
    # Valid LangSmith name: alphanumeric, hyphens, underscores
    project_name = re.sub(r'[^a-zA-Z0-9\-_]', '_', project_name)
    # LangSmith limit 100 chars
    if len(project_name) > 100:
        # Keep prefix and timestamp, truncate middle
        prefix = "-".join(components[:3])  # fairifier-env-provider
        suffix = components[-1]  # timestamp
        max_middle_len = 100 - len(prefix) - len(suffix) - 2  # 2 hyphens
        if max_middle_len > 0:
            middle = "-".join(components[3:-1])[:max_middle_len]
            project_name = f"{prefix}-{middle}-{suffix}"
        else:
            project_name = f"{prefix}-{suffix}"
    
    return project_name


def _detect_environment() -> str:
    """
    Auto-detect execution environment.
    
    Returns:
        Environment identifier: cli, api, ui, eval, test, dev, or unknown
    """
    # Check for known environment markers
    if os.getenv("FAIRIFIER_ENV"):
        return os.getenv("FAIRIFIER_ENV")
    
    # Check for evaluation mode
    if os.getenv("EVALUATION_MODE") or "evaluation" in os.getcwd().lower():
        return "eval"
    
    # Check for Streamlit (avoid importing heavy libs)
    import importlib.util
    if importlib.util.find_spec("streamlit") is not None:
        return "ui-streamlit"
    
    # Check for FastAPI/API mode
    if os.getenv("API_MODE") or "uvicorn" in os.getenv("_", ""):
        return "api"
    
    # Check for LangGraph Studio
    ls_proj = os.getenv("LANGCHAIN_PROJECT", "")
    if os.getenv("LANGGRAPH_STUDIO") or (ls_proj and ls_proj.endswith("-studio")):
        return "studio"
    
    # Check for test mode
    if os.getenv("PYTEST_CURRENT_TEST") or "pytest" in os.getenv("_", ""):
        return "test"
    
    # Default to CLI
    return "cli"


def _sanitize_component(component: str) -> str:
    """
    Sanitize a component for use in project name.
    
    Args:
        component: Component string to sanitize
    
    Returns:
        Sanitized component (lowercase, alphanumeric + hyphens/underscores)
    """
    if not component:
        return ""
    
    # Lowercase and replace spaces with hyphens
    clean = component.lower().strip()
    clean = re.sub(r'\s+', '-', clean)
    
    # Remove invalid characters
    clean = re.sub(r'[^a-z0-9\-_]', '', clean)
    
    # Remove multiple consecutive hyphens/underscores
    clean = re.sub(r'[-_]+', '-', clean)
    
    # Remove leading/trailing hyphens
    clean = clean.strip('-_')
    
    return clean


def _sanitize_model_name(model_name: str) -> str:
    """
    Sanitize and simplify model name for project naming.
    
    Args:
        model_name: Original model name (e.g., "qwen3:8b", "gpt-4o-2024-05-13")
    
    Returns:
        Simplified model name (e.g., "qwen3_8b", "gpt4o")
    
    Examples:
        >>> _sanitize_model_name("qwen3:8b")
        'qwen3_8b'
        >>> _sanitize_model_name("gpt-4o-2024-05-13")
        'gpt4o'
        >>> _sanitize_model_name("claude-3-5-sonnet-20240620")
        'claude3_5'
    """
    if not model_name:
        return "unknown"
    
    # Replace colons with underscores (e.g., qwen3:8b -> qwen3_8b)
    clean = model_name.replace(":", "_")
    
    # Remove version dates (YYYY-MM-DD or YYYYMMDD)
    clean = re.sub(r'-?\d{4}-?\d{2}-?\d{2}', '', clean)
    
    # Simplify common model names
    clean = re.sub(r'(gpt)-(\d)', r'\1\2', clean)  # gpt-4 -> gpt4
    clean = re.sub(r'(claude)-(\d)', r'\1\2', clean)  # claude-3 -> claude3
    
    # Remove trailing hyphens and extra version info
    clean = re.sub(r'-\d+b$', 'b', clean)  # Keep size suffix (e.g., 8b, 70b)
    
    # Lowercase and sanitize
    clean = _sanitize_component(clean)
    
    # Limit length (keep first 20 chars)
    if len(clean) > 20:
        clean = clean[:20].rstrip('-_')
    
    return clean or "unknown"


def _extract_or_generate_timestamp(project_id: Optional[str] = None) -> str:
    """
    Extract timestamp from project_id or generate current timestamp.
    
    Args:
        project_id: Optional project_id (format: fairifier_YYYYMMDD_HHMMSS)
    
    Returns:
        Timestamp string in format YYYYMMDD_HHMMSS
    
    Examples:
        >>> _extract_or_generate_timestamp("fairifier_20260128_213830")
        '20260128_213830'
        >>> _extract_or_generate_timestamp(None)  # doctest: +SKIP
        '20260128_143025'  # current time
    """
    if project_id:
        # Try to extract timestamp from project_id
        # Expected format: fairifier_YYYYMMDD_HHMMSS or similar
        match = re.search(r'(\d{8}_\d{6})', project_id)
        if match:
            return match.group(1)
    
    # Generate current timestamp
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def parse_fair_project_name(project_name: str) -> dict:
    """
    Parse a FAIR-compliant LangSmith project name into components.
    
    Args:
        project_name: FAIR project name to parse
    
    Returns:
        Dictionary with parsed components:
            - environment: Execution environment
            - model_provider: LLM provider
            - model_name: Model name
            - timestamp: Timestamp (YYYYMMDD_HHMMSS)
            - custom_suffix: Any custom suffix
    
    Examples:
        >>> parse_fair_project_name("fairifier-cli-ollama-qwen3_8b-20260128_213830")
        {'environment': 'cli', 'model_provider': 'ollama', ...}
    """
    parts = project_name.split("-")
    
    result = {
        "environment": None,
        "model_provider": None,
        "model_name": None,
        "timestamp": None,
        "custom_suffix": None
    }
    
    if len(parts) < 2:
        return result
    
    # Skip "fairifier" prefix
    idx = 1
    
    providers = ["ollama", "openai", "anthropic", "qwen"]
    if idx < len(parts) and parts[idx] not in providers:
        result["environment"] = parts[idx]
        idx += 1
    
    # Model provider
    if idx < len(parts):
        result["model_provider"] = parts[idx]
        idx += 1
    
    # Model name (everything before timestamp)
    model_parts = []
    while idx < len(parts):
        # Check if this part looks like a timestamp
        if re.match(r'\d{8}_\d{6}', parts[idx]):
            result["timestamp"] = parts[idx]
            idx += 1
            break
        model_parts.append(parts[idx])
        idx += 1
    
    if model_parts:
        result["model_name"] = "-".join(model_parts)
    
    # Custom suffix (anything after timestamp)
    if idx < len(parts):
        result["custom_suffix"] = "-".join(parts[idx:])
    
    return result


# Backward compatibility: Default project name generator
def get_default_langsmith_project() -> str:
    """
    Get default LangSmith project name using FAIR scheme.
    
    Returns:
        FAIR-compliant default project name.
    """
    return generate_fair_langsmith_project_name()


if __name__ == "__main__":
    # Demo/testing
    print("FAIR LangSmith Project Name Generator")
    print("=" * 60)
    
    # Example 1: CLI with Ollama
    name1 = generate_fair_langsmith_project_name(
        environment="cli",
        model_provider="ollama",
        model_name="qwen3:8b",
        project_id="fairifier_20260128_213830"
    )
    print(f"CLI + Ollama: {name1}")
    print(f"  Parsed: {parse_fair_project_name(name1)}")
    print()
    
    # Example 2: Evaluation with OpenAI
    name2 = generate_fair_langsmith_project_name(
        environment="eval",
        model_provider="openai",
        model_name="gpt-4o-2024-05-13"
    )
    print(f"Eval + OpenAI: {name2}")
    print(f"  Parsed: {parse_fair_project_name(name2)}")
    print()
    
    # Example 3: Auto-detect
    name3 = generate_fair_langsmith_project_name()
    print(f"Auto-detected: {name3}")
    print(f"  Parsed: {parse_fair_project_name(name3)}")
