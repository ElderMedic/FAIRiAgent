"""Utility to save runtime configuration to output directory."""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from ..config import config


def collect_runtime_config(
    document_path: str,
    project_id: str,
    output_path: Optional[Path] = None
) -> Dict[str, Any]:
    """Collect all runtime configuration information.
    
    Args:
        document_path: Path to the input document
        project_id: Project ID for this run
        output_path: Output directory path (optional)
        
    Returns:
        Dictionary containing all configuration information
    """
    # Collect environment variables (filter sensitive data)
    env_vars = {}
    sensitive_keys = ['api_key', 'password', 'secret', 'token']
    
    for key, value in os.environ.items():
        # Skip sensitive keys or mask them
        if any(sensitive in key.lower() for sensitive in sensitive_keys):
            env_vars[key] = "***MASKED***" if value else None
        else:
            env_vars[key] = value
    
    # Collect .env file content if exists
    env_file_content = None
    env_file_path = None
    project_root = config.project_root
    env_file = project_root / ".env"
    if env_file.exists():
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # Mask sensitive information
                lines = content.split('\n')
                masked_lines = []
                for line in lines:
                    if any(sensitive in line.lower() for sensitive in sensitive_keys):
                        # Mask the value part
                        if '=' in line:
                            key_part, value_part = line.split('=', 1)
                            masked_lines.append(f"{key_part}=***MASKED***")
                        else:
                            masked_lines.append(line)
                    else:
                        masked_lines.append(line)
                env_file_content = '\n'.join(masked_lines)
                env_file_path = str(env_file)
        except Exception as e:
            env_file_content = f"Error reading .env file: {str(e)}"
    
    # Collect config object (filter sensitive data)
    config_dict = {
        "llm_provider": config.llm_provider,
        "llm_model": config.llm_model,
        "llm_base_url": config.llm_base_url,
        "llm_temperature": config.llm_temperature,
        "llm_max_tokens": config.llm_max_tokens,
        "llm_enable_thinking": config.llm_enable_thinking,
        "llm_api_key": "***MASKED***" if config.llm_api_key else None,
        "fair_ds_api_url": config.fair_ds_api_url,
        "langsmith_api_key": "***MASKED***" if config.langsmith_api_key else None,
        "langsmith_project": config.langsmith_project,
        "langsmith_endpoint": config.langsmith_endpoint,
        "enable_langsmith": config.enable_langsmith,
        "max_step_retries": config.max_step_retries,
        "max_global_retries": config.max_global_retries,
        "min_confidence_threshold": config.min_confidence_threshold,
        "auto_approve_threshold": config.auto_approve_threshold,
    }
    
    # Collect runtime information
    runtime_info = {
        "project_id": project_id,
        "document_path": document_path,
        "document_name": Path(document_path).name if document_path else None,
        "output_path": str(output_path) if output_path else None,
        "timestamp": datetime.now().isoformat(),
        "workflow_version": "langgraph",
    }
    
    # Compile all configuration
    all_config = {
        "runtime_info": runtime_info,
        "config": config_dict,
        "environment_variables": env_vars,
        "env_file": {
            "path": env_file_path,
            "content": env_file_content,
            "exists": env_file.exists() if env_file else False
        }
    }
    
    return all_config


def save_runtime_config(
    document_path: str,
    project_id: str,
    output_path: Path
) -> Path:
    """Save runtime configuration to output directory.
    
    Args:
        document_path: Path to the input document
        project_id: Project ID for this run
        output_path: Output directory path
        
    Returns:
        Path to the saved configuration file
    """
    # Ensure output directory exists
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Collect configuration
    all_config = collect_runtime_config(document_path, project_id, output_path)
    
    # Save to JSON file
    config_file = output_path / "runtime_config.json"
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(all_config, f, indent=2, ensure_ascii=False)
    
    return config_file

